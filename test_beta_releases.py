"""Network and lifecycle boundaries of the GitHub installer, using fictional releases."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from beta_setup.core import Cancelled, Installer, SetupError
from beta_setup import releases


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.payload = b"fictional package"
        self.manifest = {"format": 1, "minimum_installer_protocol": 1, "runtime_protocol": 1,
                         "platform": sys.platform, "architecture": "x64", "release_tag": "v2026.9.23.1",
                         "source_commit": "a" * 40, "files": {"app/main.py": "b" * 64},
                         "archive_sha256": hashlib.sha256(self.payload).hexdigest(), "archive_bytes": len(self.payload)}
        self.release = {"id": 123, "draft": False, "prerelease": False, "tag_name": self.manifest["release_tag"],
                        "html_url": releases.RELEASES_URL + "/tag/" + self.manifest["release_tag"], "body": "Test release"}
        self.refresh_assets()

    def tearDown(self):
        self.temp.cleanup()

    def refresh_assets(self):
        self.manifest_bytes = json.dumps(self.manifest).encode()
        self.release["assets"] = [self.asset("json", self.manifest_bytes, 1), self.asset("zip", self.payload, 2)]

    def asset(self, extension, content, identifier):
        name = f"OpenHoikuICT-windows-x64.{extension}"
        return {"id": identifier, "name": name, "state": "uploaded", "size": len(content),
                "digest": "sha256:" + hashlib.sha256(content).hexdigest(),
                "browser_download_url": releases.RELEASES_URL + "/download/" + self.release["tag_name"] + "/" + name}

    def open(self, url):
        if url == releases.API_URL:
            return io.BytesIO(json.dumps(self.release).encode())
        for item in self.release["assets"]:
            if url == item["browser_download_url"]:
                return io.BytesIO(self.manifest_bytes if item["name"].endswith(".json") else self.payload)
        raise AssertionError("Unexpected network target")

    def latest(self):
        with patch.object(releases, "platform_key", return_value="windows-x64"), patch.object(releases, "open_download", self.open):
            return releases.latest_release()

    def test_release_identity_hash_and_payload_are_pinned(self):
        original = self.latest()
        self.assertEqual(original["version"], self.manifest["release_tag"])
        self.assertNotIn("manifest", releases.public_release(original))
        self.release["assets"][1]["id"] = 5
        self.assertNotEqual(self.latest()["revision"], original["revision"])

    def test_unpublished_and_non_matching_assets_do_not_install(self):
        for mutation in ("draft", "prerelease", "digest", "url", "duplicate", "missing", "oversized"):
            with self.subTest(mutation=mutation):
                saved = copy.deepcopy(self.release)
                if mutation in {"draft", "prerelease"}:
                    self.release[mutation] = True
                if mutation == "digest": self.release["assets"][0]["digest"] = None
                if mutation == "url": self.release["assets"][0]["browser_download_url"] = "https://github.com/other/repo/file"
                if mutation == "duplicate": self.release["assets"].append(copy.deepcopy(self.release["assets"][0]))
                if mutation == "missing": self.release["assets"] = []
                if mutation == "oversized": self.release["assets"][1]["size"] = releases.MAX_PACKAGE + 1
                with self.assertRaises(SetupError): self.latest()
                self.release = saved

    def test_incompatible_installer_and_manifest_tampering_are_rejected(self):
        self.manifest["minimum_installer_protocol"] = releases.INSTALLER_PROTOCOL + 1
        self.refresh_assets()
        with self.assertRaises(SetupError) as error: self.latest()
        self.assertEqual(error.exception.code, "installer_outdated")
        self.manifest["minimum_installer_protocol"] = 1
        self.refresh_assets()
        self.manifest_bytes += b" "
        with self.assertRaises(SetupError): self.latest()

    def test_download_has_exact_size_hash_and_cancellation(self):
        release = self.latest()
        progress = []
        with patch.object(releases, "open_download", self.open):
            releases.download_bundle(release, self.root/"ok", threading.Event(), lambda done,total: progress.append((done,total)))
        self.assertEqual((self.root/"ok/payload.zip").read_bytes(), self.payload)
        self.assertEqual(progress[-1], (len(self.payload), len(self.payload)))
        with patch.object(releases, "open_download", return_value=io.BytesIO(b"corrupt")):
            with self.assertRaises(SetupError):
                releases.download_bundle(release, self.root/"bad", threading.Event(), lambda *args: None)
        self.assertFalse((self.root/"bad/bundle.json").exists())
        cancel = threading.Event(); cancel.set()
        with patch.object(releases, "open_download", self.open):
            with self.assertRaises(Cancelled):
                releases.download_bundle(release, self.root/"cancel", cancel, lambda *args: None)
        self.assertFalse((self.root/"cancel/bundle.json").exists())

    def test_https_and_redirect_hosts_are_checked(self):
        for url in ("http://github.com/a", "https://example.test/a", "https://github.com:444/a",
                    "https://user:password@github.com/a", "file:///tmp/payload", "https://github.com.evil.test/a"):
            with self.subTest(url=url), self.assertRaises(SetupError): releases.checked_url(url)
        self.assertEqual(releases.checked_url("https://release-assets.githubusercontent.com/a?token=example"),
                         "https://release-assets.githubusercontent.com/a?token=example")

    def test_changed_confirmation_creates_no_installation(self):
        manager = Installer(self.root/"not-required", self.root/"new-install", online=True)
        values = dict(path=str(manager.home), port="18085", name="試用管理者", email="trial@example.test",
                      password="random sample test password", confirm="random sample test password", release_revision="stale")
        with patch.object(releases, "latest_release", return_value=self.latest()):
            with self.assertRaises(SetupError) as error: manager.begin(values)
        self.assertEqual(error.exception.code, "release_changed")
        self.assertIsNone(manager.thread)
        self.assertFalse(manager.home.exists())
        manager.close()

    def test_failed_download_cleans_only_owned_staging_and_never_initializes(self):
        manager = Installer(self.root/"not-required", self.root/"new-install", online=True)
        sentinel = self.root/".new-install.setup-keep"; sentinel.mkdir()
        (sentinel/"keep.txt").write_text("keep")
        release = self.latest()
        values = dict(path=str(manager.home), port="18085", name="試用管理者", email="trial@example.test",
                      password="random sample test password", confirm="random sample test password", release_revision=release["revision"])
        def failed_download(release, destination, cancel, progress):
            destination.mkdir()
            (destination/"partial.zip").write_bytes(b"partial")
            raise SetupError("connection interrupted", "download_failed")
        with patch.object(releases, "latest_release", return_value=release), patch.object(releases, "download_bundle", failed_download), patch("beta_setup.core.child") as child:
            manager.begin(values)
            manager.thread.join(10)
            child.assert_not_called()
        self.assertEqual(manager.snapshot()["code"], "download_failed")
        self.assertFalse(manager.home.exists())
        self.assertEqual(list(self.root.glob(".new-install.setup-*")), [sentinel])
        self.assertNotIn("password", json.dumps(manager.snapshot()))
        manager.close()


if __name__ == "__main__": unittest.main()
