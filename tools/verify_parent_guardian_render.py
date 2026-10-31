"""Render real route responses using only fictional data and disposable in-memory databases."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(PYTHON_DOTENV_DISABLED='1', HOIKUICT_ENV='test', HOIKUICT_DATABASE_URL='sqlite://')

from pytest import MonkeyPatch
from routers.parent_auth import templates
from test_guardian_account_sync import pilot as pilot_fixture
from test_parent_enrollment import invite, open_form, profile


def main():
    out = ROOT / '.local-dev/parent-guardian-registration-verification'
    out.mkdir(parents=True, exist_ok=True)
    for kind, order in [('add', 0), ('invite', 1), ('new', None)]:
        with MonkeyPatch.context() as monkeypatch:
            generator = pilot_fixture.__wrapped__(monkeypatch)
            pilot = next(generator)
            try:
                client, _, ids, _ = pilot
                args = dict(child_id=ids['child'], guardian_order=order) if order is not None else {}
                _, account_id, token = invite(pilot, **args)
                response = open_form(client, token, guardian_only=order is not None)
                (out/f'{kind}-empty.html').write_text(response.text, encoding='utf-8')
                values = profile(last_name='検証', first_name='葵') if order is not None else profile()
                context = {**response.context, 'values': values}
                (out/f'{kind}-filled.html').write_text(templates.get_template('parent_auth/enrollment.html').render(**context), encoding='utf-8')
                error = client.post('/parent-portal/register/enrollment', data={**values, 'g1_phone':''})
                assert error.status_code == 400
                (out/f'{kind}-error.html').write_text(error.text, encoding='utf-8')
                assert client.post('/parent-portal/register/enrollment', data=values).status_code == 200
                admin = client.get(f'/parent-accounts/{account_id}/authentication')
                (out/f'{kind}-review.html').write_text(admin.text, encoding='utf-8')
            finally:
                try:
                    next(generator)
                except StopIteration:
                    pass
    (out/'fixture.json').write_text(json.dumps({'fictional_only':True,'database':'sqlite://, disposed after each case','external_mail':False})+'\n')
    print('Rendered actual input, validation-error and review responses for three fictional cases.')


if __name__ == '__main__':
    main()
