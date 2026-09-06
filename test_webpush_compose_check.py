import io
import json

import pytest

from scripts.check_webpush_compose import PRIVATE_KEY_PATH, PUSH_FIELDS, main


@pytest.fixture
def config():
    environment = dict.fromkeys(PUSH_FIELDS, "example")
    environment.update(HOIKUICT_PUSH_TRANSPORT="webpush",
                       HOIKUICT_PUSH_VAPID_PRIVATE_KEY=PRIVATE_KEY_PATH,
                       HOIKUICT_SMTP_PASSWORD="never-print-smtp",
                       HOIKUICT_SECRET_KEY="never-print-auth")
    return {"services": {"app": {
        "environment": environment,
        "volumes": [{"type": "bind", "source": "/example" + target, "target": target,
                     "read_only": target.startswith("/run/secrets/")}
                    for target in ("/data", "/app/storage", "/run/secrets/password-blocklist.txt", PRIVATE_KEY_PATH)],
    }}}


@pytest.mark.parametrize("mutation", [
    lambda app: None,
    lambda app: app["environment"].update(HOIKUICT_PUSH_TRANSPORT="disabled"),
    lambda app: app["environment"].pop("HOIKUICT_PUSH_VAPID_SUBJECT"),
    lambda app: app["volumes"].pop(),
    lambda app: app["volumes"][-1].update(read_only=False),
    lambda app: app["volumes"].pop(0),
    lambda app: app["volumes"].append(app["volumes"][-1]),
])
def test_checks_merged_settings_without_printing_credentials(config, mutation, monkeypatch, capsys):
    original = json.dumps(config)
    mutation(config["services"]["app"])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(config)))
    expected = 0 if json.dumps(config) == original else 2
    assert main() == expected
    output = capsys.readouterr()
    assert "never-print" not in output.out + output.err
    if expected == 0:
        assert '"read_only": true' in output.out
        assert all(key in output.out for key in PUSH_FIELDS)
