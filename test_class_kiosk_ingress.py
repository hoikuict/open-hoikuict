import os
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from class_kiosk import ingress


class PrivateIngressTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        def upstream(request):
            self.requests.append(request)
            return httpx.Response(200, headers=[('set-cookie', 'one=1; Secure'), ('set-cookie', 'two=2; Secure')],
                                  stream=httpx.ByteStream(b'upstream'))
        self.env = patch.dict(os.environ, {'HOIKUICT_CLASS_KIOSK_ORIGIN':'https://private.example:8443',
            'HOIKUICT_CLASS_KIOSK_INGRESS_KEY':'private-marker-'*4})
        self.env.start()
        self.factory = patch.object(ingress, 'make_client', lambda _: httpx.AsyncClient(
            base_url='http://app:8000', transport=httpx.MockTransport(upstream)))
        self.factory.start()
        self.client = TestClient(ingress.app, base_url='https://private.example:8443')
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.factory.stop()
        self.env.stop()

    def test_kiosk_header_is_replaced_and_cookies_are_preserved(self):
        response = self.client.post('/class-kiosk/api/history?scope=all', content=b'example',
            headers={'X-Class-Kiosk-Ingress':'forged', 'X-Forwarded-For':'192.168.0.1',
                     'Forwarded':'host=evil', 'Tailscale-User-Login':'forged', 'X-CSRF-Token':'csrf'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'upstream')
        self.assertEqual(len(response.headers.get_list('set-cookie')), 2)
        sent = self.requests[0]
        self.assertEqual(str(sent.url), 'http://app:8000/class-kiosk/api/history?scope=all')
        self.assertEqual(sent.headers['x-class-kiosk-ingress'], 'private-marker-'*4)
        self.assertEqual(sent.headers['x-csrf-token'], 'csrf')
        for header in ['x-forwarded-for','forwarded','tailscale-user-login']:
            self.assertNotIn(header, sent.headers)
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_only_kiosk_and_staff_login_paths_are_forwarded(self):
        for route in ['/children/', '/settings/backups', '/staff/users', '/parent-portal/', '/class-kiosk-other']:
            self.assertEqual(self.client.get(route).status_code, 404)
        self.assertFalse(self.requests)
        self.assertEqual(self.client.get('/staff/login').status_code, 200)
        self.assertNotIn('x-class-kiosk-ingress', self.requests[-1].headers)
        self.assertEqual(self.client.get('/settings/class-kiosk/').status_code, 200)
        self.assertIn('x-class-kiosk-ingress', self.requests[-1].headers)

    def test_host_static_methods_and_upload_limits(self):
        self.assertEqual(self.client.get('/class-kiosk/', headers={'host':'evil.example'}).status_code, 400)
        self.assertEqual(self.client.post('/static/example.js', content=b'x').status_code, 405)
        with patch.object(ingress, 'MAX_BODY', 4):
            self.assertEqual(self.client.post('/class-kiosk/enroll', content=b'12345').status_code, 413)
        self.assertFalse(self.requests)

    def test_caller_cannot_select_another_upstream(self):
        self.assertEqual(self.client.get('/class-kiosk/http://example.invalid/').status_code, 200)
        self.assertEqual(self.requests[-1].url.host, 'app')
        self.assertEqual(self.client.get('/').url.path, '/class-kiosk/')


if __name__ == '__main__':
    unittest.main()
