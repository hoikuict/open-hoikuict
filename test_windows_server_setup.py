"""Safety and data-preservation checks, with no SCM/firewall/DNS/mail mutation."""
import base64
import copy
from contextlib import closing, nullcontext
import hashlib
import http.client
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from beta_setup.core import Installer, SetupError, make_config
from beta_setup.server import SetupServer
from windows_setup import configuration, migration, model, operations, platform, preflight, storage
from windows_setup.manager import ServerManager

INSTANCE = 'e' * 32


def values():
    return dict(facility='架空園', adapter='8', ip='192.168.50.20', subnet='192.168.50.0/24',
                ipReserved=True, tls='internal', localHostname='hoikuict.home.arpa', dnsReady=True,
                smtpHost='smtp.example.test', smtpPort='587', smtpUser='user', smtpPassword=' secret ',
                mailFrom='office@example.test', testRecipient='admin@example.test',
                backupPath=r'C:\ExampleBackups', backupTime='02:00', retention='30', noSleep=True,
                dnsToken='fictional-dns', tunnelToken='fictional-tunnel')


class ServerSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_validation_rejects_unsafe_paths_networks_and_mail(self):
        for path in ['C:/', r'\\server\share', r'C:\x\..\y', r'C:\x\CON', r'C:\x\a:stream', 'relative']:
            with self.subTest(path=path), self.assertRaises(SetupError):
                model.local_directory(path)
        for field, value in [('ip', '8.8.8.8'), ('subnet', '0.0.0.0/0'), ('adapter', '8;exit'),
                             ('ip', '192.168.50.255'), ('subnet', '192.168.50.1/24'),
                             ('ipReserved', 'true'), ('backupTime', '25:00'), ('retention', '1')]:
            with self.subTest(field=field), self.assertRaises(SetupError):
                model.normalize_lan({**values(), field: value})
        for address in ['a@example.test,b@example.test', 'a@example.test\nBcc:x@y.test', 'a;b@example.test']:
            with self.assertRaises(SetupError):
                model.email(address)
        result = model.normalize_lan(values())
        self.assertEqual(result['smtpPassword'], ' secret ')
        self.assertEqual(result['dnsToken'], '')

    def test_hostname_and_public_constraints(self):
        for name in ['https://garden.example.org', 'garden.example.org:443', '192.168.1.1', 'a..org', 'a.local']:
            with self.assertRaises(SetupError):
                model.hostname(name)
        lan = {**values(), 'tls': 'domain', 'hostname': 'garden.example.org'}
        with self.assertRaises(SetupError):
            model.normalize_public({'publicHostname': 'other.example.org', 'tunnelToken': 'abc'}, lan)
        self.assertEqual(model.hostname('HOIKUICT.HOME.ARPA', internal=True), 'hoikuict.home.arpa')

    def test_every_changed_connection_value_invalidates_its_proof(self):
        original = values()
        for kind, fields in model.CHECK_FIELDS.items():
            for field in fields:
                with self.subTest(kind=kind, field=field):
                    changed = {**original, field: 'changed'}
                    self.assertNotEqual(model.check_revision(kind, original), model.check_revision(kind, changed))

    def test_drafts_contain_no_passwords_or_confirmation_proofs(self):
        store = storage.DraftStore(self.root)
        store.save('lan', 3, {**values(), 'password': 'private', 'confirm': 'private', 'mailReceived': True})
        result = store.load()
        raw = store.path.read_text()
        for key in ['password', 'confirm', 'smtpPassword', 'dnsToken', 'tunnelToken', 'mailReceived']:
            self.assertNotIn(key, result['values'])
        self.assertNotIn('private', raw)
        self.assertEqual(result['values']['backupTime'], '02:00')

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_secret_storage_is_encrypted_and_rejects_tampering(self):
        path = self.root / 'settings.bin'
        storage.save_secrets(path, {'secret': 'fictional secret value'})
        self.assertNotIn(b'fictional secret value', path.read_bytes())
        self.assertEqual(storage.load_secrets(path)['secret'], 'fictional secret value')
        raw = bytearray(path.read_bytes()); raw[-1] ^= 1; path.write_bytes(raw)
        with self.assertRaises(SetupError):
            storage.load_secrets(path)

    def trial(self):
        trial = self.root / 'trial'
        (trial / 'app/data').mkdir(parents=True)
        (trial / 'app/storage/attachments').mkdir(parents=True)
        make_config(trial / 'app/.env.beta.local', 18001)
        for relative in ['app/hoikuict-beta-auth.db', 'app/data/facility.sqlite']:
            with closing(sqlite3.connect(trial / relative)) as db:
                db.execute('CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)')
                db.execute('INSERT INTO sample(value) VALUES (?)', ('unchanged credential/data',))
                db.commit()
        (trial / 'app/storage/attachments/a.txt').write_text('fictional attachment')
        return trial

    def test_migration_preserves_keys_credentials_attachments_and_source(self):
        source = self.trial()
        before = {p.relative_to(source): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
        target = self.root / 'service'; target.mkdir()
        keys = migration.migrate(source, target)
        self.assertEqual(keys, migration.legacy_keys(source))
        with closing(sqlite3.connect(target / 'data/hoikuict.db')) as db:
            self.assertEqual(db.execute('select value from sample').fetchone()[0], 'unchanged credential/data')
        self.assertEqual((target / 'storage/attachments/a.txt').read_text(), 'fictional attachment')
        self.assertEqual(before, {p.relative_to(source): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()})
        with self.assertRaises(FileExistsError):
            migration.migrate(source, target)

    def test_migration_does_not_overwrite_database_or_accept_changed_layout(self):
        source = self.trial()
        destination = self.root / 'existing.db'; destination.write_bytes(b'keep')
        with self.assertRaises(SetupError):
            migration.copy_database(source / 'app/hoikuict-beta-auth.db', destination)
        self.assertEqual(destination.read_bytes(), b'keep')
        settings = source / 'app/.env.beta.local'
        settings.write_text(settings.read_text().replace('sqlite:///./hoikuict-beta-auth.db', 'sqlite:///other.db'))
        with self.assertRaises(SetupError):
            migration.legacy_keys(source)

    def test_production_environment_preserves_authentication_and_enforces_security(self):
        from security_config import validate_runtime_security
        source = self.trial()
        code = self.root / 'code'; (code / 'app/assets').mkdir(parents=True)
        (code / 'app/assets/password-blocklist.txt').write_text('password\n')
        keys = migration.legacy_keys(source)
        env = configuration.production_environment(model.normalize_lan(values()), self.root, code, keys, INSTANCE, 'a'*40)
        with patch.dict(os.environ, env, clear=True):
            validate_runtime_security()
        self.assertEqual(env['HOIKUICT_SECRET_KEY'], keys['HOIKUICT_SECRET_KEY'])
        self.assertEqual(env['HOIKUICT_COOKIE_SECURE'], '1')
        self.assertEqual(env['HOIKUICT_CSRF_ENFORCE'], '1')
        self.assertEqual(env['FORWARDED_ALLOW_IPS'], '127.0.0.1')
        self.assertEqual(env['HOIKUICT_ENABLE_MOCK_AUTH'], '0')
        stopped = configuration.production_environment(model.normalize_lan(values()), self.root, code, keys, INSTANCE, 'a'*40, suspended=True)
        self.assertEqual(stopped['HOIKUICT_ACTION_MAIL_SUSPENDED'], '1')
        self.assertEqual(stopped['HOIKUICT_PARENT_MAIL_TRANSPORT'], 'smtp')

    def test_service_and_https_are_scoped_and_do_not_embed_secrets(self):
        lan = model.normalize_lan(values())
        conf = configuration.caddy_config(lan, self.root, INSTANCE)
        self.assertFalse(conf['apps']['pki']['certificate_authorities']['local']['install_trust'])
        self.assertEqual(conf['apps']['http']['servers']['lan']['listen'], ['192.168.50.20:443'])
        self.assertTrue(conf['apps']['http']['servers']['tunnel']['listen'][0].startswith('127.0.0.1:'))
        self.assertTrue(conf['admin']['disabled'])
        markup = configuration.service_xml(self.root / 'code', self.root / 'data', INSTANCE)
        self.assertIn('Automatic', markup)
        self.assertNotIn('secret', markup)
        self.assertNotIn('powershell', markup)
        self.assertIn('<startarguments>', markup)
        self.assertNotIn('<arguments>', markup)
        with self.assertRaises(ValueError):
            configuration.service_name('../arbitrary')

    def test_acl_replaces_prior_explicit_grants(self):
        with patch.object(platform, 'powershell') as ps:
            platform.restrict_directory(self.root, owner_sid='S-1-5-21-1234')
        script, data = ps.call_args.args
        self.assertIn('RemoveAccessRuleSpecific', script)
        self.assertIn('SetAccessRuleProtection($true,$false)', script)
        self.assertEqual(len(data['entries']), 3)

    def test_package_tampering_is_detected_before_service_commands(self):
        payload = self.root / 'payload.zip'; payload.write_bytes(b'changed')
        with patch.object(platform, 'restrict_directory'), patch.object(platform, 'run') as run:
            with self.assertRaises(SetupError):
                operations.extract_verified_payload(payload, self.root / 'code', {'archive_sha256': '0'*64})
            run.assert_not_called()

    def test_virtual_service_account_uses_no_password_parameter(self):
        with patch.object(platform, 'service_state', return_value={'exists': False}), \
                patch.object(platform, 'restrict_directory'), patch.object(platform, 'run') as run:
            platform.install_service(self.root / 'code', self.root / 'data', INSTANCE)
        config = next(call.args[0] for call in run.call_args_list if 'config' in call.args[0])
        self.assertEqual(config[config.index('obj=') + 1], 'NT SERVICE\\' + configuration.service_name(INSTANCE))
        self.assertNotIn('password=', config)

    def test_stop_pending_waits_before_returning_without_second_stop(self):
        code = self.root / 'code'
        state = dict(exists=True, state='Stop Pending', path=str(code / 'service.exe'))
        with patch.object(platform, 'service_state', return_value=state), \
                patch.object(platform, 'powershell') as ps, patch.object(platform, 'run') as run:
            platform.change_service(code, INSTANCE, 'stop')
        run.assert_not_called()
        self.assertEqual(ps.call_args.args[1]['status'], 'Stopped')

    def test_request_hash_and_expiration_precede_mutations(self):
        request_file = self.root / '.server-setup/jobs' / ('f'*32) / 'request.bin'
        request_file.parent.mkdir(parents=True); request_file.write_bytes(b'opaque')
        with patch.object(platform, 'is_admin', return_value=True), patch.object(platform, 'run') as run:
            with self.assertRaises(SetupError) as caught:
                operations.execute_job(request_file, '0'*64)
            self.assertEqual(caught.exception.code, 'request_changed')
            with patch.object(operations, 'load_secrets', return_value={'source': str(self.root), 'operation': 'lan', 'created_at': 0}):
                with self.assertRaises(SetupError) as caught:
                    operations.execute_job(request_file, hashlib.sha256(b'opaque').hexdigest())
            self.assertEqual(caught.exception.code, 'request_expired')
            run.assert_not_called()

    def test_precommit_failure_restores_trial_but_retains_copied_data(self):
        source = self.trial(); data = self.root / 'service'; data.mkdir()
        storage.atomic_json(source / 'installation.json', {'server': {'instance': INSTANCE}})
        (source / 'app/.env.beta.local').rename(source / 'app/.env.beta.migrated')
        (data / 'keep.db').write_bytes(b'preserve')
        with patch.object(platform, 'instance_paths', return_value=(self.root / 'code', data)):
            operation = operations.Operation({'instance': INSTANCE, 'source': str(source), 'operation': 'lan'}, self.root / 'job')
        operation.journal['steps'] = ['retired_trial']
        self.assertTrue(operation.rollback())
        self.assertTrue((source / 'app/.env.beta.local').is_file())
        self.assertNotIn('server', storage.read_json(source / 'installation.json'))
        self.assertEqual((data / 'keep.db').read_bytes(), b'preserve')

    def test_rollback_failure_is_reported_as_blocked(self):
        data = self.root / 'service'; data.mkdir()
        with patch.object(platform, 'instance_paths', return_value=(self.root / 'code', data)):
            operation = operations.Operation({'instance': INSTANCE, 'source': str(self.root), 'operation': 'lan'}, self.root / 'job')
        operation.journal['steps'] = ['installing_service']
        with patch.object(platform, 'change_service', side_effect=RuntimeError('failure')):
            self.assertFalse(operation.rollback())
        self.assertEqual(operation.journal['state'], 'blocked')

    def test_resume_interrupted_operation_prevents_duplicate_setup(self):
        installer = Installer(self.root / 'bundle', self.root / 'trial')
        job = installer.home / '.server-setup/jobs' / ('f'*32)
        storage.atomic_json(job / 'status.json', {'state': 'running'})
        storage.atomic_json(job.parent.parent / 'active-job.json', {'id': job.name, 'operation': 'lan', 'created_at': 0})
        manager = ServerManager(installer)
        with patch.object(manager, 'state', return_value=None):
            self.assertEqual(manager.status()['job']['state'], 'blocked')
            with self.assertRaises(SetupError) as caught:
                manager.begin('lan', values())
        self.assertEqual(caught.exception.code, 'recovery_required')
        installer.close()

    def test_changed_check_cannot_apply_or_elevate(self):
        installer = Installer(self.root / 'bundle', self.root / 'trial', launcher=self.root / 'installer.exe')
        manager = ServerManager(installer)
        with patch.object(manager, 'status', return_value={}), patch.object(platform, 'elevate') as elevate:
            with self.assertRaises(SetupError) as caught:
                manager.begin('lan', {**values(), 'mailReceived': True})
            self.assertEqual(caught.exception.code, 'check_expired')
            elevate.assert_not_called()
        installer.close()

    def test_new_http_routes_require_token_host_origin_and_bounded_body(self):
        installer = Installer(self.root / 'bundle', self.root / 'new')
        server = SetupServer(installer)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def call(path, body=b'{}', headers=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
            connection.request('POST', path, body, headers=headers or {})
            response = connection.getresponse(); response.read(); status = response.status; connection.close(); return status
        headers = {'Authorization': 'Bearer '+server.token, 'Origin': server.origin, 'Content-Type': 'application/json'}
        try:
            for route in ('check','draft','apply','cancel','drill','confirm'):
                self.assertEqual(call('/api/server/'+route), 403)
                self.assertEqual(call('/api/server/'+route, headers={**headers, 'Origin':'https://foreign.example'}), 403)
            self.assertEqual(call('/api/server/apply', b'x'*20000, headers), 400)
            self.assertEqual(call('/api/server/apply', headers={**headers, 'Host':'foreign.example'}), 403)
        finally:
            server.shutdown(); server.server_close(); thread.join(); installer.close()

    def test_restart_ignores_healthy_heartbeats_from_previous_process(self):
        from windows_setup.worker import Service
        service = Service(self.root, {'instance': INSTANCE})
        child = MagicMock(); child.poll.return_value = None
        service.children = {'gateway': child}
        with patch('restore_control.service_state', return_value={'online': True, 'healthy': True, 'seen': service.started-1}):
            status = service.status()
            self.assertFalse(status['gateway'] or status['backup'] or status['restore'])

    def test_pending_links_follow_public_origin_and_roll_back_without_touching_sent_mail(self):
        from windows_setup.mail_links import update_pending_links
        (self.root / 'data').mkdir()
        path = self.root / 'data/hoikuict.db'
        with closing(sqlite3.connect(path)) as db, db:
            for table in ('parent_mail_deliveries', 'staff_mail_deliveries'):
                db.execute(f'CREATE TABLE {table} (id INTEGER, body TEXT, status TEXT, message_type TEXT)')
                db.executemany(f'INSERT INTO {table} VALUES (?,?,?,?)', [
                    (1, 'https://hoikuict.home.arpa/activate#code', 'pending', 'parent_activate'),
                    (2, 'https://hoikuict.home.arpa/old', 'sent', 'parent_activate'),
                    (3, 'https://hoikuict.home.arpa.evil.test/a', 'pending', 'parent_activate')])
            db.execute("INSERT INTO parent_mail_deliveries VALUES (4, ?, 'pending','attendance_confirmation')", ('https://hoikuict.home.arpa/attendance',))
        settings = {'root': str(self.root), 'mail_origins': ['https://hoikuict.home.arpa','https://garden.example.org'],
                    'environment': {'HOIKUICT_PARENT_REGISTRATION_BASE_URL': 'https://garden.example.org'}}
        self.assertEqual(update_pending_links(settings), 2)
        with closing(sqlite3.connect(path)) as db:
            records = dict(db.execute('select id,body from parent_mail_deliveries'))
        self.assertEqual(records[1], 'https://garden.example.org/activate#code')
        self.assertEqual(records[2], 'https://hoikuict.home.arpa/old')
        self.assertEqual(records[3], 'https://hoikuict.home.arpa.evil.test/a')
        self.assertEqual(records[4], 'https://hoikuict.home.arpa/attendance')
        settings['environment']['HOIKUICT_PARENT_REGISTRATION_BASE_URL'] = 'https://hoikuict.home.arpa'
        self.assertEqual(update_pending_links(settings), 2)

    def test_retention_preserves_latest_two_foreign_and_incomplete_sets(self):
        from windows_setup.retention import prune_backups
        root = self.root / ('open-hoikuict-'+INSTANCE); root.mkdir()
        names = ['open-hoikuict_2026010'+str(i)+'T000000Z_'+('a'*12) for i in range(1,5)]
        for index,name in enumerate(names):
            storage.atomic_json(root/name/'manifest.json', {'facility_ref': 'other' if index==0 else INSTANCE})
            (root/name/'keep').write_text('fictional backup')
        (root/'.incomplete.partial').mkdir()
        settings = {'instance': INSTANCE, 'lan': {'backupPath': str(root), 'retention': '30'}}
        with patch('restore_control.exclusive_lock', return_value=nullcontext()), patch('restore_control.active_job', return_value=None), patch('restore_control.maintenance', return_value=None), patch('scripts.backup_runtime.verify_backup_set'):
            removed = prune_backups(settings, now=1780000000)
        self.assertEqual(removed, [names[1]])
        self.assertTrue((root/names[0]).exists())
        self.assertTrue((root/names[2]).exists() and (root/names[3]).exists())
        self.assertTrue((root/'.incomplete.partial').exists())


class GuidedSetupTests(unittest.TestCase):
    def gmail(self):
        return {**values(), 'mailProvider': 'gmail', 'smtpHost': 'smtp.gmail.com',
                'smtpUser': 'office@example.test', 'smtpPassword': 'abcd efgh ijkl mnop'}

    def test_gmail_presets_and_password_normalization(self):
        result = model.normalize_mail(self.gmail())
        self.assertEqual(result['smtpPassword'], 'abcdefghijklmnop')
        self.assertEqual(result['mailProvider'], 'gmail')
        self.assertEqual(model.normalize_mail(values())['smtpPassword'], ' secret ')
        for key, value in [('smtpHost', 'smtp.other.test'), ('smtpPort', '465'),
                           ('smtpUser', 'different@example.test'), ('smtpPassword', 'short'),
                           ('mailProvider', 'unknown')]:
            with self.subTest(key=key), self.assertRaises(SetupError):
                model.normalize_mail({**self.gmail(), key: value})

    def test_mail_sends_only_one_explicit_recipient_over_starttls(self):
        with patch.object(preflight.smtplib, 'SMTP') as factory:
            smtp = factory.return_value.__enter__.return_value
            preflight.check_mail(self.gmail())
            factory.assert_called_once_with('smtp.gmail.com', 587, timeout=20)
            smtp.starttls.assert_called_once()
            smtp.login.assert_called_once_with('office@example.test', 'abcdefghijklmnop')
            smtp.send_message.assert_called_once()
            message = smtp.send_message.call_args.args[0]
            self.assertEqual(message['To'], 'admin@example.test')
            self.assertIsNone(message['Cc'])
            self.assertIsNone(message['Bcc'])
            self.assertEqual([c[0] for c in smtp.method_calls], ['starttls', 'login', 'send_message'])

    def test_mail_errors_distinguish_auth_connection_and_recipient_without_leaking(self):
        cases = [(preflight.smtplib.SMTPAuthenticationError(535, b'private server response'), 'smtp_auth_failed'),
                 (OSError('private connection detail'), 'smtp_connection_failed'),
                 (preflight.smtplib.SMTPDataError(452, b'private quota response'), 'smtp_failed'),
                 (preflight.smtplib.SMTPRecipientsRefused({'secret@example.test': (550, b'private')}), 'smtp_recipient_failed')]
        for error, code in cases:
            with self.subTest(code=code), patch.object(preflight.smtplib, 'SMTP', side_effect=error):
                with self.assertRaises(SetupError) as caught:
                    preflight.check_mail(self.gmail())
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn('private', str(caught.exception))
                self.assertNotIn('secret@example.test', str(caught.exception))

    def test_connection_reports_independent_results_and_retains_no_false_proof(self):
        adapter = {'id': '8', 'ip': '192.168.50.20', 'private': True}
        fixture = {**values(), 'trustPlan': True}
        manager = ServerManager(MagicMock())
        with patch.object(platform, 'network_adapters', return_value=[adapter]), patch.object(preflight.socket, 'getaddrinfo', return_value=[(None, None, None, None, ('192.168.50.20', 443))]):
            self.assertTrue(manager.check('connection', fixture)['complete'])
            self.assertIn('dns', manager.checks)
            with patch.object(preflight.socket, 'getaddrinfo', side_effect=OSError):
                report = manager.check('connection', fixture)
            self.assertFalse(report['complete'])
            self.assertTrue(report['results']['ip']['passed'])
            self.assertTrue(report['results']['tls']['passed'])
            self.assertEqual(report['results']['dns']['code'], 'dns_unresolved')
            self.assertNotIn('dns', manager.checks)

    def test_domain_check_only_verifies_token_and_zone_without_writing_dns(self):
        fixture = {**values(), 'tls': 'domain', 'hostname': 'hoikuict.garden.org'}
        replies = [{'result': {'status': 'active'}}, {'result': []}, {'result': [{'name': 'garden.org'}]}]
        with patch.object(preflight, 'cloudflare', side_effect=replies) as api:
            preflight.check_certificate_preparation(fixture)
            paths = [call.args[0] for call in api.call_args_list]
            self.assertEqual(paths[0], 'user/tokens/verify')
            self.assertTrue(all(path.startswith('zones?') for path in paths[1:]))

    def test_failed_retest_invalidates_previous_mail_acceptance(self):
        manager = ServerManager(MagicMock())
        with patch.object(preflight, 'check_mail', return_value={'message': 'accepted'}):
            manager.check('mail', self.gmail())
        self.assertIn('mail', manager.checks)
        with patch.object(preflight, 'check_mail', side_effect=SetupError('failed', 'smtp_failed')):
            with self.assertRaises(SetupError):
                manager.check('mail', self.gmail())
        self.assertNotIn('mail', manager.checks)

    def test_guide_draft_resumes_substeps_without_secrets_or_connection_proofs(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = storage.DraftStore(Path(temporary))
            draft = {**self.gmail(), 'mailReceived': True, 'checks': {'mail': True},
                     'mailDrafts': {'gmail': {'smtpPassword': 'never-persist'}},
                     'password': 'never-persist', 'googleReady': True}
            position = {'netStep': 7, 'tokenStep': 2, 'mailStep': 3}
            store.save('lan', 2, draft, {**position, 'secret': 'never-persist'})
            loaded = store.load()
            self.assertEqual(loaded['guide'], position)
            self.assertTrue(loaded['values']['googleReady'])
            for name in ('smtpPassword', 'dnsToken', 'tunnelToken', 'mailReceived', 'mailDrafts', 'checks', 'password'):
                self.assertNotIn(name, loaded['values'])
            self.assertNotIn('never-persist', store.path.read_text())
            for guide in ({'netStep': 8}, {'mailStep': -1}, {'tokenStep': True}, 'invalid'):
                with self.assertRaises(SetupError):
                    store.save('lan', 2, draft, guide)
            storage.atomic_json(store.path, {'format': 1, 'flow': 'lan', 'step': 1, 'values': {'hostname': 'garden.org'}})
            self.assertEqual(store.load()['guide'], {'netStep': 0, 'tokenStep': 0, 'mailStep': 0})

    def test_installer_serves_guided_assets_with_script_restrictions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installer = Installer(root / 'bundle', root / 'new')
            server = SetupServer(installer)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                for asset in ('/', '/guided.js', '/guide-actions.js', '/guide.css'):
                    connection = http.client.HTTPConnection('127.0.0.1', server.server_port)
                    connection.request('GET', asset)
                    response = connection.getresponse(); body = response.read().decode(); connection.close()
                    self.assertEqual(response.status, 200)
                    self.assertIn("script-src 'self'", response.getheader('Content-Security-Policy'))
                    self.assertNotIn('DEMO-NOT-A-REAL', body)
                    if asset == '/':
                        self.assertIn('guide-actions.js', body)
                        self.assertIn('id="help-dialog"', body)
            finally:
                server.shutdown(); server.server_close(); thread.join(); installer.close()


if __name__ == '__main__':
    unittest.main()
