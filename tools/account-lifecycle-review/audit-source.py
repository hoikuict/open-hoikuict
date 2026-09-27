"""Reproduce CSV lifecycle drift in an in-memory fixture; never open a production DB."""
import csv
import io
import json
from pathlib import Path
import sys

source = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source))
from test_local_parent_auth import LocalParentAuthenticationTests
from data_transfer_service import DATASETS, commit_import
from models import AuthSession, ParentAccount, ParentPushSubscription, PasswordCredential
from parent_auth import authenticate_parent, resolve_parent_session, token_hash
from sqlmodel import Session, select

assert Path(sys.modules['data_transfer_service'].__file__).resolve().is_relative_to(source)
case = LocalParentAuthenticationTests()
case.setUp()
try:
    case._complete_initial_registration()
    with Session(case.engine) as session:
        login = authenticate_parent(session, login_id='parent@example.com', password=case.PASSWORD)
        old_token = login.session_token
        session.add(ParentPushSubscription(parent_account_id=case.account_id,
            endpoint='https://push.example.test/synthetic', endpoint_hash='s' * 64,
            p256dh_key='synthetic-key', auth_key='synthetic-key', environment='test'))
        session.commit()

    def update_from_csv(status):
        buf = io.StringIO(newline='')
        writer = csv.DictWriter(buf, fieldnames=DATASETS['parent_accounts'].headers)
        writer.writeheader()
        writer.writerow({'ID': str(case.account_id), '状態': status})
        with Session(case.engine) as session:
            result = commit_import(session, 'parent_accounts', 'synthetic.csv',
                buf.getvalue().encode('utf-8-sig'), actor_name='Synthetic investigation')
            assert not result.errors, result.errors

    update_from_csv('inactive')
    with Session(case.engine) as session:
        stopped = {
            'account_status': session.get(ParentAccount, case.account_id).status.value,
            'credential_disabled': session.exec(select(PasswordCredential)).one().disabled_at is not None,
            'old_session_revoked': session.get(AuthSession, token_hash(old_token)).revoked_at is not None,
            'push_status': session.exec(select(ParentPushSubscription)).one().status.value,
        }
    update_from_csv('active')
    with Session(case.engine) as session:
        restored_old_session = resolve_parent_session(session, old_token) is not None
    assert stopped == {'account_status':'inactive','credential_disabled':False,'old_session_revoked':False,'push_status':'active'}
    assert restored_old_session
    print(json.dumps({'source':str(source),'synthetic_only':True,'after_csv_stop':stopped,
        'old_session_usable_after_csv_reenable_without_intervening_request':restored_old_session}))
finally:
    case.tearDown()
