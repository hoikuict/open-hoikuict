"""Render family recognition without writing real family, child, or fee records."""
import hashlib
import json
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import inspect
from sqlmodel import Session, select
from starlette.requests import Request
from auth import Role, StaffUser
from database import engine
from models import Family
from family_care_service import TABLES
from routers.family_care import page, router


def verify():
    schema=inspect(engine)
    assert all(model.__tablename__ in schema.get_table_names() for model in TABLES)
    assert {('/families/{family_id}/care-certifications','GET'),
            ('/families/{family_id}/care-certifications/{action}','POST')} <= {(r.path,m) for r in router.routes for m in r.methods}
    with Session(engine) as session:
        session.connection().exec_driver_sql('PRAGMA query_only=ON')
        session.connection().exec_driver_sql('BEGIN')
        family=session.exec(select(Family).order_by(Family.id)).first()
        rendered=0
        if family:
            request=Request(dict(type='http',method='GET',path=f'/families/{family.id}/care-certifications',headers=[]))
            for role,permission in ((Role.ADMIN,True),(Role.CAN_EDIT,True),(Role.VIEW_ONLY,False)):
                actor=StaffUser(role=role,name='Verification',can_manage_child_records=permission)
                if not permission:
                    try:page(family.id,request,session,actor)
                    except HTTPException as exc: assert exc.status_code==403
                    else:raise AssertionError('Viewer was allowed')
                    continue
                response=page(family.id,request,session,actor)
                assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
                assert '家族共通の保育認定' in response.body.decode()
                for asset in ('css/family-care.css','js/family-care.js'):
                    assert '/static/'+asset+'?v=' in response.body.decode()
                rendered+=1
        assert not session.new and not session.dirty and not session.deleted
        session.rollback()
    return dict(verified=True,read_only=True,records_written=0,rendered_roles=rendered,
                asset_sha256={n:hashlib.sha256(Path('static',n).read_bytes()).hexdigest() for n in ('css/family-care.css','js/family-care.js')})


if __name__=='__main__': print('FAMILY_CARE_LIVE='+json.dumps(verify()))
