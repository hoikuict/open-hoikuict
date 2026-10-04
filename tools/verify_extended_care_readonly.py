"""Render actual settings under all staff roles; never write a setting or a charge."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import inspect
from sqlmodel import Session, select
from starlette.requests import Request

from auth import Role, StaffUser
from database import engine
from models import ExtendedCareFeeRule
from routers.extended_care_fees import extended_care_fee_settings, router


def verify():
    schema=inspect(engine)
    assert 'fee_bands_json' in {c['name'] for c in schema.get_columns('extended_care_fee_rules')}
    assert 'fee_breakdown_json' in {c['name'] for c in schema.get_columns('extended_care_charges')}
    required={('/extended-care-fees/settings/bands/{category}','POST'),('/extended-care-fees/settings/bands/preview','POST')}
    assert required <= {(r.path,m) for r in router.routes for m in r.methods}
    with Session(engine) as session:
        session.connection().exec_driver_sql('PRAGMA query_only=ON')
        session.connection().exec_driver_sql('BEGIN')
        rules=session.exec(select(ExtendedCareFeeRule)).all()
        before=[r.model_dump_json() for r in rules]
        for role in (Role.ADMIN,Role.CAN_EDIT,Role.VIEW_ONLY):
            request=Request({'type':'http','method':'GET','path':'/extended-care-fees/settings','headers':[]})
            actor=StaffUser(role=role,name='Verification')
            response=extended_care_fee_settings(request,message=None,session=session,current_user=actor)
            assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
            state=response.context['settings_state']
            assert state['canEdit']==actor.can_edit and state['isAdmin']==actor.is_admin
            assert sum(len(v) for v in state['rules'].values())==sum(r.care_time_category is not None for r in rules)
            for category,plans in state['rules'].items():
                for p in plans:
                    original=next(r for r in rules if r.id==p['id'])
                    assert original.care_time_category.value==category
                    assert p['name']==original.name and p['from']==original.effective_from.isoformat()
                    assert p['existingCalculation']==(original.fee_bands_json is None)
            markup=response.body.decode('utf-8')
            for asset in ('css/extended-care-settings.css','js/extended-care-settings.js','js/extended-care-calculator.js'):
                assert '/static/'+asset+'?v=' in markup
        assert before==[r.model_dump_json() for r in rules]
        assert not session.new and not session.dirty and not session.deleted
        session.rollback()
    return dict(verified=True,read_only=True,records_written=0,roles_verified=3,rules=len(rules),
                asset_sha256={n:hashlib.sha256(Path('static',n).read_bytes()).hexdigest()
                    for n in ('css/extended-care-settings.css','js/extended-care-settings.js','js/extended-care-calculator.js')})


if __name__=='__main__':
    print('EXTENDED_CARE_LIVE='+json.dumps(verify()))
