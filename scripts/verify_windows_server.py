"""Opt-in Windows integration with fictional data and loopback-only listeners.

Does not install services, alter firewall/DNS/power, trust a certificate, or send mail.
"""
from __future__ import annotations
import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from beta_setup.core import clean_environment, make_config
from scripts.build_beta_bundle import selected
from windows_setup.configuration import caddy_config, ports, production_environment
from windows_setup.migration import migrate
from windows_setup.operations import control, wait_healthy
from windows_setup.storage import atomic_json, save_secrets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--components', type=Path, required=True)
    args = parser.parse_args()
    identifier = secrets.token_hex(16)
    workspace = args.workspace.resolve() / identifier[:8]
    workspace.mkdir(parents=True, exist_ok=False)
    code = workspace / 'code'; app = code / 'app'
    source = workspace / 'trial'; trial = source / 'app'
    data = workspace / 'data'
    files = subprocess.check_output(['git', '-c', 'safe.directory='+str(ROOT.as_posix()), 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
    for name in files:
        if name and selected(name):
            destination = app / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
    shutil.copytree(app, trial)
    shutil.copyfile(ROOT / 'beta_setup/runtime.py', trial / '_beta_runtime.py')
    make_config(trial / '.env.beta.local', 18743)
    password = secrets.token_urlsafe(24)
    values = dict(name='架空の検証管理者', email='qa@example.test', login='qa@example.test',
                  password=password, confirm=password, actor='検証', approver='検証', reason='隔離された動作確認')
    initialized = subprocess.run([sys.executable, '-I', '-B', str(trial / '_beta_runtime.py'), 'initialize'],
                    input=(json.dumps(values)+'\n').encode(), capture_output=True, cwd=trial, env=clean_environment(), timeout=120)
    assert initialized.returncode == 0 and json.loads(initialized.stdout.splitlines()[-1])['ok'], 'Fictional initialization failed'
    print('Fictional trial initialized', flush=True)
    data.mkdir(); keys = migrate(source, data)
    for name in ('config', 'logs', 'restore-control', 'restore-staging', 'restore-drills', 'tls'):
        (data / name).mkdir()
    component_dir = app / 'windows_setup/components'; component_dir.mkdir()
    for name in ('caddy.exe', 'cloudflared.exe'):
        shutil.copyfile(args.components / name, component_dir / name)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); tls_port = probe.getsockname()[1]
    lan = dict(facility='架空園', ip='127.0.0.1', tls='internal', localHostname='localhost',
               smtpHost='127.0.0.1', smtpPort='1', smtpUser='', smtpPassword='', mailFrom='qa@example.test',
               dnsToken='', backupPath=str(workspace / ('open-hoikuict-'+identifier)), retention='30')
    environment = production_environment(lan, data, code, keys, identifier, 'a'*40)
    url = 'https://localhost:'+str(tls_port)
    environment.update(HOIKUICT_ALLOWED_ORIGINS=url, HOIKUICT_PARENT_REGISTRATION_BASE_URL=url,
                       HOIKUICT_STAFF_RECOVERY_BASE_URL=url)
    settings = dict(instance=identifier, root=str(data), code=str(code), lan=lan, public=None,
                    control_token=secrets.token_urlsafe(32), ports=ports(identifier), environment=environment)
    (data / 'config/restore-signing-key').write_bytes(secrets.token_bytes(32))
    save_secrets(data / 'config/settings.bin', settings)
    atomic_json(data / 'state.json', dict(instance=identifier, lan=lan, lan_confirmed=False))
    conf = caddy_config(lan, data, identifier)
    conf['apps']['http']['servers']['lan']['listen'] = ['127.0.0.1:'+str(tls_port)]
    atomic_json(data / 'config/caddy.json', conf)
    token = settings['control_token']
    log = (workspace / 'worker.log').open('wb')
    process = None
    def start():
        return subprocess.Popen([sys.executable, '-I', '-B', str(app / 'windows_setup/worker_entry.py'), str(data)],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=clean_environment(),
                                 creationflags=subprocess.CREATE_NO_WINDOW)
    def stop():
        (data / 'stop-requested').touch()
        try:
            process.wait(timeout=65)
        except subprocess.TimeoutExpired:
            process.terminate(); process.wait(10)
            raise AssertionError('Owned service did not stop gracefully')
        assert process.returncode == 0, 'Service failed; inspect isolated worker.log'
    try:
        process = start(); wait_healthy(data, token)
        cert = data / 'tls/pki/authorities/local/root.crt'
        deadline = time.monotonic()+30
        while not cert.exists() and time.monotonic()<deadline: time.sleep(.2)
        context = ssl.create_default_context(cafile=str(cert))
        jar = CookieJar()
        http = build_opener(ProxyHandler({}), HTTPSHandler(context=context), HTTPCookieProcessor(jar))
        try:
            http.open(url+'/staff/login', timeout=10)
        except HTTPError as error:
            assert error.code == 503, 'Pre-activation request was not gated'
        else:
            raise AssertionError('Setup exposed the application before commit')
        (data / 'ready').touch()
        with http.open(url+'/staff/login', timeout=15) as response:
            page = response.read().decode()
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page)[1]
        fields = dict(login_id='qa@example.test', password=password, csrf_token=csrf, redirect_to='/classrooms/')
        with http.open(Request(url+'/staff/login', data=urlencode(fields).encode(), headers={'Origin':url}), timeout=20) as response:
            assert response.url.endswith('/classrooms/'), 'Migrated administrator login failed'
            assert response.headers['X-HoikuICT-Instance'] == identifier
        assert any(cookie.secure for cookie in jar), 'Secure session cookie missing'
        print('Production HTTPS, activation gate and migrated-password login passed', flush=True)
        control(data, token, '/drill', {})
        deadline = time.monotonic()+120
        while time.monotonic()<deadline:
            drill = control(data, token, '/status')['drill']
            if drill['state'] != 'running': break
            time.sleep(.3)
        assert drill['state'] == 'complete', drill
        print('Backup and isolated restore verification passed', flush=True)
        stop(); process = start(); wait_healthy(data, token)
        with http.open(url+'/classrooms/', timeout=15) as response:
            assert response.url.endswith('/classrooms/')
        assert control(data, token, '/status')['drill']['state'] == 'complete'
        print('Restart, session keys and completed verification persisted', flush=True)
        result = dict(passed=True, workspace=str(workspace), checks=['production HTTPS', 'activation gate',
                    'migrated password', 'secure cookie', 'backup', 'isolated restore', 'restart', 'persistent session keys'])
        atomic_json(workspace / 'verification.json', result)
        print(json.dumps(result), flush=True)
    finally:
        if process and process.poll() is None:
            stop()
        log.close()


if __name__ == '__main__':
    main()
