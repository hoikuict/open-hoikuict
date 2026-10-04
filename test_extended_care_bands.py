from datetime import date, datetime
import html
import json
import re

import pytest
from sqlmodel import Session, select

from auth import Role
from extended_care_bands import evaluate_plan, normalize_plan
from extended_care_fee_service import recalculate_attendance_charge, recalculate_period
from models import (AttendanceRecord, CareTimeCategory, ChildCareCertification,
                    ExtendedCareCalculationSetting, ExtendedCareCharge, ExtendedCareChargeStatus, ExtendedCareFeeRule)
import test_extended_care_fees as fee_tests


def plan():
    return dict(name="標準時間の延長", **{"from": "2026-04-01", "to": ""}, active=True,
                normalStart="07:30", normalEnd="18:00", morningEnabled=False, eveningEnabled=True,
                morningGrace="0", eveningGrace="0", morningBands=[], cap="",
                eveningBands=[dict(start="18:00", end="19:00", mode="unit", unit="10", price="100"),
                              dict(start="19:00", end="20:00", mode="unit", unit="10", price="200")])


@pytest.fixture
def nursery():
    case = fee_tests.ExtendedCareFeeTests()
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()


@pytest.mark.parametrize("leave,amount", [("18:00", 0), ("18:01", 100), ("18:59", 600), ("19:00", 600), ("19:01", 800), ("19:20", 1000), ("20:00", 1800), ("20:01", None)])
def test_band_boundaries(leave, amount):
    result = evaluate_plan(plan(), "2026-10-15", "08:30", leave)
    assert result["total"] == amount


def test_flat_grace_cap_and_short_time():
    p = plan()
    p["eveningGrace"] = "10"
    assert evaluate_plan(p, "2026-10-15", "08:30", "19:01")["total"] == 700
    p["eveningBands"][1]["mode"] = "flat"
    p["cap"] = "650"
    result = evaluate_plan(p, "2026-10-15", "08:30", "19:20")
    assert result["subtotal"] == 700 and result["total"] == 650 and result["capped"]
    p.update(normalStart="09:00", morningEnabled=True, morningBands=[dict(start="07:30", end="09:00", mode="unit", unit="15", price="100")], cap="")
    assert evaluate_plan(p, "2026-10-15", "08:30", "19:20")["total"] == 900


@pytest.mark.parametrize("change", [
    {"morningEnabled": None}, {"active": "false"}, {"from": "2026-02-30"}, {"to": "2026-03-31"},
    {"normalEnd": "06:00"}, {"cap": "-1"}, {"eveningGrace": "121"}, {"eveningBands": []},
])
def test_invalid_settings_rejected(change):
    p = plan(); p.update(change)
    with pytest.raises(ValueError): normalize_plan(p)


@pytest.mark.parametrize("key,value", [("start", "18:45"), ("start", "19:01"), ("end", "19:00"), ("mode", "other"), ("unit", "0"), ("price", "-1"), ("price", "")])
def test_invalid_bands_rejected(key, value):
    p = plan(); p["eveningBands"][1][key] = value
    with pytest.raises(ValueError): normalize_plan(p)


def test_disabled_is_distinct_from_unset():
    p = plan(); p["eveningEnabled"] = False; p["eveningGrace"] = ""
    assert normalize_plan(p)["eveningGrace"] == "0"
    assert evaluate_plan(p, "2026-10-15", "08:30", "18:00")["total"] == 0
    assert evaluate_plan(p, "2026-10-15", "08:30", "19:00")["total"] is None


def test_save_reload_preview_and_no_charge_recalculation(nursery):
    client = nursery.client
    body = plan()
    response = client.post('/extended-care-fees/settings/bands/standard', json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['id'] and saved['revision'] and not saved['existingCalculation']
    page = client.get('/extended-care-fees/settings')
    assert page.status_code == 200, page.text
    assert page.headers['cache-control'] == 'private, no-store'
    data = json.loads(html.unescape(re.search(r'data-state="([^"]+)"', page.text).group(1)))
    assert data['rules']['standard'][0] == saved
    preview = client.post('/extended-care-fees/settings/bands/preview', json=dict(plan=saved, date='2026-10-15', arrival='08:30', departure='19:01'))
    assert preview.json()['total'] == 800
    with Session(nursery.engine) as session:
        assert session.exec(select(ExtendedCareCharge)).all() == []
        assert session.get(ExtendedCareFeeRule, nursery.rule_id).fee_bands_json is None


def test_overlap_and_stale_save_keep_database(nursery):
    path = '/extended-care-fees/settings/bands/standard'
    saved = nursery.client.post(path, json=plan()).json()
    assert nursery.client.post(path, json=plan()).status_code == 400
    changed = {**saved, 'name': '変更後'}
    assert nursery.client.post(path, json=changed).status_code == 200
    assert nursery.client.post(path, json=saved).status_code == 409
    assert nursery.client.post('/extended-care-fees/settings/bands/short', json=changed).status_code == 404
    with Session(nursery.engine) as session:
        assert session.get(ExtendedCareFeeRule, saved['id']).name == '変更後'


@pytest.mark.parametrize('role,status', [(Role.ADMIN,200), (Role.CAN_EDIT,200), (Role.VIEW_ONLY,403)])
def test_save_permissions(nursery, role, status):
    nursery.current_user.role = role
    response = nursery.client.post('/extended-care-fees/settings/bands/standard', json=plan())
    assert response.status_code == status
    assert nursery.client.get('/extended-care-fees/settings').status_code == 200


def seed_record(nursery):
    saved = nursery.client.post('/extended-care-fees/settings/bands/standard', json=plan()).json()
    with Session(nursery.engine) as session:
        session.add(ExtendedCareCalculationSetting(mode='category_aware', category_aware_from=date(2026,4,1)))
        session.add(ChildCareCertification(child_id=nursery.child_id, care_time_category=CareTimeCategory.standard,
                                          effective_from=date(2026,4,1), is_active=True))
        record = AttendanceRecord(child_id=nursery.child_id, attendance_date=date(2026,10,15),
                                  check_in_at=datetime(2026,10,15,8,30), check_out_at=datetime(2026,10,15,19,20))
        session.add(record);session.commit()
        charge = recalculate_attendance_charge(session,record);session.commit()
        assert charge.final_amount == 1000 and charge.calculation_version == 'bands_v1'
        assert json.loads(charge.fee_breakdown_json)['total'] == 1000
        return record.id, saved


def test_outside_bands_invalidates_only_unconfirmed_calculation(nursery):
    record_id, _ = seed_record(nursery)
    with Session(nursery.engine) as session:
        record = session.get(AttendanceRecord,record_id)
        record.check_out_at=datetime(2026,10,15,20,10);session.add(record)
        assert recalculate_period(session,date(2026,10,1),date(2026,10,31)) == 1
        session.commit()
        assert session.exec(select(ExtendedCareCharge)).all() == []
        assert session.get(AttendanceRecord,record_id).check_out_at.hour == 20
    assert '時間帯設定' in nursery.client.get('/extended-care-fees/?month=2026-10').text


@pytest.mark.parametrize('status', [ExtendedCareChargeStatus.confirmed, ExtendedCareChargeStatus.manual_adjusted, ExtendedCareChargeStatus.excluded])
def test_locked_amounts_retained(nursery,status):
    record_id, _ = seed_record(nursery)
    with Session(nursery.engine) as session:
        charge=session.exec(select(ExtendedCareCharge)).one();charge.status=status;session.add(charge)
        record=session.get(AttendanceRecord,record_id);record.check_out_at=datetime(2026,10,15,20,10);session.add(record);session.commit()
        assert recalculate_period(session,date(2026,10,1),date(2026,10,31)) == 0
        assert session.exec(select(ExtendedCareCharge)).one().final_amount == 1000


def test_old_api_cannot_overwrite_band_rule(nursery):
    saved=nursery.client.post('/extended-care-fees/settings/bands/standard',json=plan()).json()
    response=nursery.client.post(f"/extended-care-fees/settings/{saved['id']}",data=dict(name='old',effective_from='2026-04-01',start_time='18:00',grace_minutes='0',rounding_minutes='10',unit_price='100'))
    assert response.status_code == 409


def test_migration_is_nullable_and_idempotent(monkeypatch):
    from sqlmodel import create_engine
    import database
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE extended_care_fee_rules (id INTEGER PRIMARY KEY)')
        conn.exec_driver_sql('CREATE TABLE extended_care_charges (id INTEGER PRIMARY KEY)')
        conn.exec_driver_sql('INSERT INTO extended_care_fee_rules (id) VALUES (1)')
    monkeypatch.setattr(database,'engine',engine)
    database._migrate_care_certification_and_extended_care_columns()
    database._migrate_care_certification_and_extended_care_columns()
    with engine.connect() as conn:
        assert conn.exec_driver_sql('SELECT fee_bands_json FROM extended_care_fee_rules WHERE id=1').scalar() is None
        assert 'fee_breakdown_json' in {r[1] for r in conn.exec_driver_sql('PRAGMA table_info(extended_care_charges)')}
    engine.dispose()


def test_csrf_required_for_band_save_and_preview(nursery, monkeypatch):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from csrf import CsrfTokenMiddleware, verify_csrf
    from routers.extended_care_fees import router
    monkeypatch.setenv('HOIKUICT_CSRF_ENFORCE','1')
    monkeypatch.setenv('HOIKUICT_COOKIE_SECURE','0')
    app=FastAPI(dependencies=[Depends(verify_csrf)])
    app.add_middleware(CsrfTokenMiddleware)
    app.include_router(router)
    app.dependency_overrides=nursery.app.dependency_overrides.copy()
    with TestClient(app) as client:
        page=client.get('/extended-care-fees/settings')
        token=re.search(r'name="csrf-token" content="([^"]+)"',page.text).group(1)
        for path in ('standard','preview'):
            assert client.post('/extended-care-fees/settings/bands/'+path,json=plan()).status_code==403
        response=client.post('/extended-care-fees/settings/bands/standard',json=plan(),headers={'X-CSRF-Token':token})
        assert response.status_code==200,response.text
