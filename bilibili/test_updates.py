"""Real HTTP update checks, validation, cancellation and settings preservation."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from app_version import REPOSITORY
from runtime_paths import read_settings, save_output, save_settings
from update_core import UpdateCancelled, UpdateClient, UpdateError, parse_manifest, permitted_url, version_parts

INSTALLER = b"MZ" + bytes(range(251)) * 3000


class Handler(BaseHTTPRequestHandler):
    manifest = {}
    payload = INSTALLER
    truncate = False

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if urlparse(self.path).path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://example.invalid/insecure")
            self.end_headers()
            return
        payload = json.dumps(self.manifest).encode() if urlparse(self.path).path == "/manifest" else self.payload
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload[:100] if self.truncate and urlparse(self.path).path != "/manifest" else payload)


class UpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        Handler.payload = INSTALLER
        Handler.truncate = False
        Handler.manifest = {"schema": 1, "product": "LocalVideoDownloader", "notes": "新版说明", "platforms": {
            "windows": {"version": "1.0.3", "url": self.base + "/installer", "size": len(INSTALLER),
                        "sha256": hashlib.sha256(INSTALLER).hexdigest()}}}
        self.client = UpdateClient(manifest_url=self.base + "/manifest", allow_loopback=True)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_new_version_detected_and_install_download_byte_verified(self):
        info = self.client.check(current_version="1.0.2")
        self.assertTrue(info.available)
        self.assertEqual(info.notes, "新版说明")
        progress = []
        path = self.client.download(info, self.root, lambda done, total: progress.append((done, total)))
        self.assertEqual(path.read_bytes(), INSTALLER)
        self.assertEqual(progress[-1], (len(INSTALLER), len(INSTALLER)))
        self.assertEqual(path.name, "VideoDownloader-Update.exe")
        self.assertFalse(list(self.root.glob("*.part")))

    def test_current_and_older_versions_do_not_offer_downgrade(self):
        for current in ("1.0.3", "1.1.0", "2.0.0"):
            info = self.client.check(current_version=current)
            self.assertFalse(info.available)
            with self.assertRaises(UpdateError):
                self.client.download(info, self.root)

    def test_corrupted_update_never_replaces_a_verified_cached_installer(self):
        target = self.root / "VideoDownloader-Update.exe"
        target.write_bytes(b"previous verified package")
        info = self.client.check(current_version="1.0.2")
        Handler.payload = b"X" * len(INSTALLER)
        with self.assertRaises(UpdateError):
            self.client.download(info, self.root)
        self.assertEqual(target.read_bytes(), b"previous verified package")
        self.assertFalse(list(self.root.glob("*.part")))

    def test_truncated_update_is_rejected_and_partial_removed(self):
        info = self.client.check(current_version="1.0.2")
        Handler.truncate = True
        with self.assertRaises(UpdateError):
            self.client.download(info, self.root)
        self.assertFalse(list(self.root.iterdir()))

    def test_cancelled_download_does_not_leave_an_executable(self):
        info = self.client.check(current_version="1.0.2")
        with self.assertRaises(UpdateCancelled):
            self.client.download(info, self.root, lambda *_: self.client.cancelled.set())
        self.assertFalse(list(self.root.iterdir()))

    def test_insecure_redirect_is_blocked_before_contacting_other_host(self):
        self.client.manifest_url = self.base + "/redirect"
        with self.assertRaisesRegex(UpdateError, "HTTPS"):
            self.client.check()

    def test_manifest_product_hash_size_and_version_are_required(self):
        for field, invalid in (("sha256", "missing"), ("size", -1), ("size", True), ("version", "latest")):
            data = json.loads(json.dumps(Handler.manifest))
            data["platforms"]["windows"][field] = invalid
            with self.subTest(field=field), self.assertRaises(UpdateError):
                parse_manifest(data, allow_loopback=True)
        Handler.manifest["product"] = "another product"
        with self.assertRaises(UpdateError):
            self.client.check()

    def test_only_configured_github_release_urls_are_accepted(self):
        self.assertTrue(permitted_url(f"https://github.com/{REPOSITORY}/releases/download/v1.0.3/update.exe"))
        for url in ("http://github.com/" + REPOSITORY + "/releases/x", "https://github.com/other/repo/releases/x",
                    "https://github.com.evil.org/" + REPOSITORY + "/releases/x", "file:///C:/setup.exe",
                    "https://user:password@github.com/" + REPOSITORY + "/releases/x"):
            with self.subTest(url=url):
                self.assertFalse(permitted_url(url))

    def test_numeric_versions_sort_correctly_and_reject_non_versions(self):
        self.assertGreater(version_parts("1.10.0"), version_parts("1.9.9"))
        self.assertEqual(version_parts("v1.0.2"), (1, 0, 2))
        for value in (None, "latest", "1.2", "1.0.2-beta", "1.0.2;run"):
            with self.assertRaises(UpdateError):
                version_parts(value)

    def test_output_and_update_preferences_preserve_each_other(self):
        with patch("runtime_paths.SETTINGS", self.root / "settings.json"):
            save_settings(auto_update=False)
            save_output(self.root / "video")
            self.assertFalse(read_settings()["auto_update"])
            save_settings(auto_update=True)
            self.assertEqual(read_settings()["output"], str((self.root / "video").resolve()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
