"""Controlled HTTP acceptance for GitHub metadata, ranges and failure recovery."""
from dataclasses import replace
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.parse import urlparse

from update_core import UpdateCancelled, UpdateClient, UpdateError, UpdateInfo, parse_release

PAYLOAD = b"MZ" + bytes(range(251)) * 42000
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


class ReleaseHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    mode = "range"
    version = "2.1.0"
    payload = PAYLOAD
    delay = 0
    fail_after = None
    fail_all = False
    requests_seen = []
    active = peak = 0
    lock = threading.Lock()

    def log_message(self, *_):
        pass

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError):
            pass

    def do_GET(self):
        cls = type(self)
        path = urlparse(self.path).path
        base = f"http://127.0.0.1:{self.server.server_port}"
        start, end = 0, len(cls.payload) - 1
        range_header = self.headers.get("Range")
        if range_header:
            start, end = map(int, range_header[6:].split("-"))
        with cls.lock:
            cls.requests_seen.append((path, range_header))
        if cls.fail_all or (path == "/installer" and cls.fail_after is not None and start >= cls.fail_after):
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path in {"/api", "/manifest"}:
            if path == "/api":
                data = {"tag_name": "v" + cls.version, "body": "## 新增功能\n真实 Release Notes\n\n## 问题修复\n范围下载恢复。",
                        "assets": [{"name": "VideoDownloader-Windows-Setup.exe", "browser_download_url": base + "/installer",
                                    "digest": "sha256:" + DIGEST, "size": len(PAYLOAD)}]}
            else:
                data = {"schema": 1, "product": "LocalVideoDownloader", "notes": "备用说明", "platforms": {"windows": {
                    "version": cls.version, "url": base + "/installer", "sha256": DIGEST, "size": len(PAYLOAD)}}}
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        is_range = bool(range_header and cls.mode in {"range", "bad-range"})
        body = cls.payload[start:end + 1] if is_range else cls.payload
        self.send_response(206 if is_range else 200)
        if is_range:
            declared_start = start + 1 if cls.mode == "bad-range" and end > 0 else start
            self.send_header("Content-Range", f"bytes {declared_start}-{end}/{len(cls.payload)}")
        self.send_header("ETag", '"immutable-v2-fixture"')
        if cls.mode != "unknown":
            self.send_header("Content-Length", str(len(body)))
        else:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        with cls.lock:
            cls.active += 1
            cls.peak = max(cls.peak, cls.active)
        try:
            for offset in range(0, len(body), 65536):
                self.wfile.write(body[offset:offset + 65536])
                self.wfile.flush()
                if cls.delay:
                    time.sleep(cls.delay)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            with cls.lock:
                cls.active -= 1


class TransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ReleaseHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        ReleaseHandler.mode = "range"
        ReleaseHandler.payload = PAYLOAD
        ReleaseHandler.version = "2.1.0"
        ReleaseHandler.delay = 0
        ReleaseHandler.fail_after = None
        ReleaseHandler.fail_all = False
        ReleaseHandler.requests_seen = []
        ReleaseHandler.active = ReleaseHandler.peak = 0
        self.client = UpdateClient(manifest_url=self.base + "/manifest", api_url=self.base + "/api", allow_loopback=True)
        self.info = UpdateInfo("2.1.0", self.base + "/installer", DIGEST, len(PAYLOAD), "说明", True)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_actual_release_notes_and_digest_take_priority_over_manifest(self):
        info = self.client.check(current_version="2.0.0")
        self.assertTrue(info.available)
        self.assertIn("真实 Release Notes", info.notes)
        self.assertEqual(info.sha256, DIGEST)
        self.assertNotIn("/manifest", [path for path, _ in ReleaseHandler.requests_seen])

    def test_api_failure_uses_compatible_configured_manifest(self):
        self.client.api_url = self.base + "/invalid-api"
        info = self.client.check()
        self.assertEqual(info.notes, "备用说明")

    def test_four_connections_write_exact_payload_and_real_progress(self):
        ReleaseHandler.delay = .002
        progress = []
        target = self.client.download(self.info, self.folder, lambda *values: progress.append(values))
        self.assertEqual(target.read_bytes(), PAYLOAD)
        self.assertGreaterEqual(ReleaseHandler.peak, 2)
        self.assertTrue(any(0 < done < total for done, total in progress))
        self.assertEqual(progress[-1], (len(PAYLOAD), len(PAYLOAD)))
        self.assertFalse(list(self.folder.glob("*.part")))

    def test_interrupted_ranges_keep_safe_prefix_and_retry_resumes(self):
        ReleaseHandler.fail_after = 8 * 1024 * 1024
        with self.assertRaises(UpdateError):
            self.client.download(self.info, self.folder)
        prefix = self.folder / "VideoDownloader-Update.exe.part"
        self.assertEqual(prefix.stat().st_size, 8 * 1024 * 1024)
        ReleaseHandler.fail_after = None
        ReleaseHandler.requests_seen.clear()
        target = self.client.download(self.info, self.folder)
        self.assertEqual(target.read_bytes(), PAYLOAD)
        ranges = [header for _, header in ReleaseHandler.requests_seen]
        self.assertIn("bytes=8388608-10485759", ranges)
        self.assertIn("bytes=10485760-" + str(len(PAYLOAD) - 1), ranges)
        self.assertNotIn("bytes=0-2097151", ranges)

    def test_changed_resume_prefix_is_redownloaded_not_trusted(self):
        ReleaseHandler.fail_after = 8 * 1024 * 1024
        with self.assertRaises(UpdateError):
            self.client.download(self.info, self.folder)
        prefix = self.folder / "VideoDownloader-Update.exe.part"
        with prefix.open("r+b") as file:
            file.write(b"broken")
        ReleaseHandler.fail_after = None
        target = self.client.download(self.info, self.folder)
        self.assertEqual(target.read_bytes(), PAYLOAD)

    def test_ignored_ranges_fall_back_to_single_stream(self):
        ReleaseHandler.mode = "stream"
        target = self.client.download(self.info, self.folder)
        self.assertEqual(target.read_bytes(), PAYLOAD)
        self.assertIn(("/installer", None), ReleaseHandler.requests_seen)

    def test_wrong_content_range_falls_back_without_appending(self):
        ReleaseHandler.mode = "bad-range"
        target = self.client.download(self.info, self.folder)
        self.assertEqual(target.read_bytes(), PAYLOAD)

    def test_unknown_length_reports_indeterminate_until_eof(self):
        ReleaseHandler.mode = "unknown"
        progress = []
        target = self.client.download(replace(self.info, size=0), self.folder, lambda *values: progress.append(values))
        self.assertEqual(target.read_bytes(), PAYLOAD)
        self.assertTrue(any(done > 0 and total == 0 for done, total in progress))
        self.assertEqual(progress[-1], (len(PAYLOAD), len(PAYLOAD)))

    def test_cancellation_cleans_parts_without_replacing_previous_package(self):
        ReleaseHandler.delay = .002
        existing = self.folder / "VideoDownloader-Update.exe"
        existing.write_bytes(b"old verified installer")
        def progress(done, total):
            if done > 100000:
                self.client.cancelled.set()
        with self.assertRaises(UpdateCancelled):
            self.client.download(self.info, self.folder, progress)
        self.assertEqual(existing.read_bytes(), b"old verified installer")
        self.assertFalse(list(self.folder.glob("*.part")))

    def test_hash_error_cannot_replace_previous_package(self):
        existing = self.folder / "VideoDownloader-Update.exe"
        existing.write_bytes(b"previous")
        ReleaseHandler.payload = b"MZ" + b"x" * (len(PAYLOAD) - 2)
        with self.assertRaisesRegex(UpdateError, "SHA-256"):
            self.client.download(self.info, self.folder)
        self.assertEqual(existing.read_bytes(), b"previous")

    def test_verified_cache_is_reused_without_network(self):
        target = self.folder / "VideoDownloader-Update.exe"
        target.write_bytes(PAYLOAD)
        ReleaseHandler.fail_all = True
        self.assertEqual(self.client.download(self.info, self.folder), target)
        self.assertFalse(ReleaseHandler.requests_seen)

    def test_release_rejects_boolean_size_and_foreign_asset(self):
        asset = {"name": "VideoDownloader-Windows-Setup.exe", "size": True,
                 "browser_download_url": self.info.url}
        with self.assertRaises(UpdateError):
            parse_release({"tag_name": "v2.1.0", "assets": [asset]}, allow_loopback=True)
        asset.update(size=5, browser_download_url="https://github.com/other/repo/releases/download/v2.1.0/setup.exe")
        with self.assertRaises(UpdateError):
            parse_release({"tag_name": "v2.1.0", "assets": [asset]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
