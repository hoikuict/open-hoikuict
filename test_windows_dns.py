"""Regression: a local hosts entry must never prove other devices can resolve."""
import unittest
import socket
from unittest.mock import patch

from beta_setup.core import SetupError
from test_windows_server_setup import values
from windows_setup import platform, preflight


class DNSChecks(unittest.TestCase):
    def test_no_hosts_fallback_and_no_false_success(self):
        cases = [([], 'dns_unresolved'),
                 ([{'A': [], 'AAAA': [], 'errors': ['A']}], 'dns_unresolved'),
                 ([{'A': ['192.168.50.20'], 'AAAA': [], 'errors': ['AAAA']}], 'dns_unresolved'),
                 ([{'A': ['192.168.50.99'], 'AAAA': [], 'errors': []}], 'dns_mismatch'),
                 ([{'A': ['192.168.50.20'], 'AAAA': ['2001:db8::1'], 'errors': []}], 'dns_mismatch'),
                 ([{'A': ['192.168.50.20'], 'AAAA': [], 'errors': []},
                   {'A': ['192.168.50.99'], 'AAAA': [], 'errors': []}], 'dns_mismatch')]
        with patch.object(socket, 'getaddrinfo', side_effect=AssertionError('must ignore hosts')):
            for answers, code in cases:
                with self.subTest(answers=answers), patch.object(platform, 'dns_answers', return_value=answers):
                    with self.assertRaises(SetupError) as caught:
                        preflight.check_name_resolution(values())
                    self.assertEqual(caught.exception.code, code)
                    self.assertIn('リバインディング', str(caught.exception))

    def test_all_selected_resolvers_must_agree(self):
        answer = {'A': ['192.168.50.20'], 'AAAA': [], 'errors': []}
        with patch.object(platform, 'dns_answers', return_value=[answer, answer]) as query:
            preflight.check_name_resolution(values())
        query.assert_called_once_with('8', 'hoikuict.home.arpa')

    def test_fixed_powershell_queries_selected_adapter_and_both_families(self):
        with patch.object(platform, 'powershell', return_value=[]) as command:
            platform.dns_answers('8', 'hoikuict.home.arpa')
        script, inputs = command.call_args.args
        self.assertEqual(inputs, {'adapter': '8', 'host': 'hoikuict.home.arpa'})
        for required in ['Get-DnsClientServerAddress -InterfaceIndex', '-Server $server',
                         '-NoHostsFile -DnsOnly', "@('A','AAAA')"]:
            self.assertIn(required, script)

    def test_inactive_cloudflare_token_fails_before_zone_read(self):
        with patch.object(preflight, 'cloudflare', return_value={'result': {'status': 'disabled'}}) as api:
            with self.assertRaises(SetupError):
                preflight.check_certificate_preparation({**values(), 'tls': 'domain', 'hostname': 'lan.garden.org'})
            self.assertEqual(api.call_count, 1)


if __name__ == '__main__':
    unittest.main()
