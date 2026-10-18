"""Exercise range acceleration, resume and fallback against an actual HTTP server."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from parallel_http import AcceleratedYoutubeDL, RangeUnavailable, content_range
from bilibili_adapter import BiliBiliIE

BODY = bytes(range(251)) * 9000


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    requests = []
    active = peak = 0
    guard = threading.Lock()

    def log_message(self, *_args):
        pass

    def do_GET(self):
        requested = self.headers.get("Range")
        mode = self.path.strip("/")
        match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested or "")
        start, end = (int(match[1]), int(match[2] or len(BODY) - 1)) if match else (0, len(BODY) - 1)
        ranged = bool(match) and mode != "ignore"
        if not ranged:
            start, end = 0, len(BODY) - 1
        if start >= len(BODY):
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{len(BODY)}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        is_piece = ranged and end > start
        with self.guard:
            self.requests.append((mode, requested))
            if is_piece:
                type(self).active += 1
                type(self).peak = max(type(self).peak, self.active)
        try:
            if is_piece:
                time.sleep(0.025)
            self.send_response(206 if ranged else 200)
            if ranged:
                reported_start = start + 1 if mode == "bad-offset" and is_piece else start
                self.send_header("Content-Range", f"bytes {reported_start}-{end}/{len(BODY)}")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("ETag", '"stable-resource"')
            self.end_headers()
            data = BODY[start:end + 1]
            if mode == "truncated" and is_piece:
                data = data[:len(data) // 2]
                self.close_connection = True
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            if is_piece:
                with self.guard:
                    type(self).active -= 1


class ParallelHttpTests(unittest.TestCase):
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
        self.target = Path(self.temp.name) / "download.mp4"
        with Handler.guard:
            Handler.requests = []
            Handler.peak = 0
        self.events = []

    def tearDown(self):
        self.temp.cleanup()

    def download(self, mode="normal", *, backup=False):
        options = {"proxy": "", "quiet": True, "noprogress": True, "continuedl": True,
                   "retries": 0, "socket_timeout": 2, "progress_hooks": [self.events.append]}
        url = f"http://127.0.0.1:{self.server.server_port}/{mode}"
        info = {"url": url, "ext": "mp4"}
        if backup:
            info["_backup_urls"] = [f"http://127.0.0.1:{self.server.server_port}/normal"]
        with patch("parallel_http.CHUNK", 256 * 1024), patch("parallel_http.MIN_SIZE", 1024):
            with AcceleratedYoutubeDL(options) as client:
                success, _ = client.dl(str(self.target), info)
        self.assertTrue(success)
        self.assertEqual(hashlib.sha256(self.target.read_bytes()).digest(), hashlib.sha256(BODY).digest())
        self.assertFalse(self.target.with_suffix(".mp4.part").exists())
        self.assertEqual(self.events[-1]["status"], "finished")

    def test_parallel_ranges_produce_identical_file_and_live_progress(self):
        self.download()
        self.assertGreater(Handler.peak, 1)
        self.assertTrue(any(event["status"] == "downloading" and event["total_bytes"] == len(BODY)
                            for event in self.events))

    def test_resume_keeps_existing_contiguous_bytes(self):
        prefix = 543210
        self.target.with_suffix(".mp4.part").write_bytes(BODY[:prefix])
        self.download()
        ranges = [requested for _, requested in Handler.requests if requested
                  and int(requested.split("-")[1]) >= prefix]
        self.assertTrue(ranges)
        self.assertTrue(all(int(requested.split("=")[1].split("-")[0]) >= prefix for requested in ranges))

    def test_corrupted_resume_prefix_is_replaced(self):
        self.target.with_suffix(".mp4.part").write_bytes(b"wrong" * 100000)
        self.download()

    def test_broken_primary_switches_to_identical_format_backup(self):
        self.download("truncated", backup=True)
        self.assertNotIn(("truncated", None), Handler.requests)
        self.assertTrue(any(mode == "normal" for mode, _ in Handler.requests))

    def test_ignored_ranges_fall_back_to_complete_native_download(self):
        self.download("ignore")
        self.assertIn(("ignore", None), Handler.requests)

    def test_mismatched_range_never_becomes_a_finished_corrupt_file(self):
        self.download("bad-offset")
        self.assertIn(("bad-offset", None), Handler.requests)

    def test_truncated_piece_falls_back_without_holes_or_duplicate_data(self):
        self.download("truncated")
        self.assertIn(("truncated", None), Handler.requests)

    def test_invalid_resume_size_restarts_safely(self):
        self.target.with_suffix(".mp4.part").write_bytes(BODY + b"wrong-extra-data")
        self.download()

    def test_range_parser_rejects_unknown_and_invalid_boundaries(self):
        self.assertEqual(content_range("bytes 0-0/123"), (0, 0, 123))
        for value in (None, "bytes 0-0/*", "bytes 10-5/100", "bytes 0-100/100", "garbage"):
            with self.subTest(value=value), self.assertRaises(RangeUnavailable):
                content_range(value)


class BilibiliSourceTests(unittest.TestCase):
    def test_backups_stay_with_the_exact_source_format(self):
        play_info = {"dash": {"audio": [{"baseUrl": "https://primary/audio", "backupUrl":
                                        ["https://backup/audio", "https://backup/audio"]}],
                              "video": [{"base_url": "https://primary/video", "backup_url": ["https://backup/video"]}]}}
        formats = [{"url": "https://primary/audio", "format_id": "30280"},
                   {"url": "https://primary/video", "format_id": "100026"}]
        with patch("bilibili_adapter.UpstreamBiliBiliIE.extract_formats", return_value=formats):
            actual = BiliBiliIE().extract_formats(play_info)
        self.assertEqual(actual[0]["_backup_urls"], ["https://backup/audio"])
        self.assertEqual(actual[1]["_backup_urls"], ["https://backup/video"])
        self.assertEqual([fmt["format_id"] for fmt in actual], ["30280", "100026"])

    def test_missing_or_invalid_backups_do_not_invent_another_source(self):
        play_info = {"dash": {"audio": [{"baseUrl": "https://primary/audio", "backupUrl": [None, "file:///local"]}]}}
        with patch("bilibili_adapter.UpstreamBiliBiliIE.extract_formats", return_value=[{"url": "https://primary/audio"}]):
            self.assertNotIn("_backup_urls", BiliBiliIE().extract_formats(play_info)[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
