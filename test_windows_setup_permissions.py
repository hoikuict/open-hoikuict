"""Opt-in, real Windows DACL checks on temporary folders, without UAC or SCM."""
import os
from pathlib import Path
import tempfile
import unittest

from windows_setup import platform
from windows_setup.storage import DraftStore


@unittest.skipUnless(os.name == 'nt' and os.environ.get('HOIKUICT_TEST_WINDOWS_ACL') == '1',
                     'Set HOIKUICT_TEST_WINDOWS_ACL=1 in a normal Windows session.')
class WindowsFolderPermissionsTests(unittest.TestCase):
    def test_unelevated_repeated_draft_save_preserves_owner_and_limits_access(self):
        self.assertFalse(platform.is_admin(), 'Run this regression check without administrator elevation.')
        sid = platform.current_sid()
        with tempfile.TemporaryDirectory(prefix='open-hoikuict-acl-') as location:
            home = Path(location)
            folder = home / '.server-setup'
            folder.mkdir()
            before = platform.powershell("""
              $directory=[IO.DirectoryInfo]::new($v.path)
              $acl=$directory.GetAccessControl()
              $owner=$acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
              $rule=[Security.AccessControl.FileSystemAccessRule]::new(
                [Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'),
                'ReadAndExecute','ContainerInherit,ObjectInherit','None','Allow')
              $acl.AddAccessRule($rule)
              $directory.SetAccessControl($acl)
              $owner | ConvertTo-Json -Compress
            """, {'path': str(folder)})
            for step in (1, 2):
                platform.restrict_directory(folder, owner_sid=sid)
                DraftStore(home).save('lan', step, {'facility': 'ACL test nursery'})
                self.assertEqual(DraftStore(home).load()['step'], step)
                observed = platform.powershell("""
                  $acl=([IO.DirectoryInfo]::new($v.path)).GetAccessControl()
                  @{owner=$acl.GetOwner([Security.Principal.SecurityIdentifier]).Value;
                    protected=$acl.AreAccessRulesProtected;
                    rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]) |
                      ForEach-Object { @{sid=$_.IdentityReference.Value; rights=[string]$_.FileSystemRights;
                        inherited=$_.IsInherited; type=[string]$_.AccessControlType} })} |
                    ConvertTo-Json -Depth 4 -Compress
                """, {'path': str(folder)})
                self.assertEqual(observed['owner'], before)
                self.assertTrue(observed['protected'])
                self.assertCountEqual([rule['sid'] for rule in observed['rules']],
                                      ['S-1-5-18', 'S-1-5-32-544', sid])
                for rule in observed['rules']:
                    self.assertEqual(rule['rights'], 'FullControl')
                    self.assertEqual(rule['type'], 'Allow')
                    self.assertFalse(rule['inherited'])


if __name__ == '__main__':
    unittest.main()
