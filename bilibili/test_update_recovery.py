"""Regression checks for cached release redirects and resumable throttling."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from update_core import UpdateClient, UpdateInfo, UpdateNetworkError, UpdateRateLimitError, retry_after_seconds
from test_v2_updates import PAYLOAD, DIGEST


class RecoveryHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    mode = 'redirect'
    counts = Counter()
    ranges = []
    throttled = False
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
        parsed = urlparse(self.path)
        with cls.lock:
            cls.counts[parsed.path] += 1
            count = cls.counts[parsed.path]
        if parsed.path == '/origin':
            self.send_response(302)
            self.send_header('Location', '/asset?token=' + str(count))
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        start, end = map(int, self.headers['Range'][6:].split('-'))
        with cls.lock:
            cls.ranges.append((start, end))
            throttle = cls.mode == 'throttle' and start >= 8 * 1024 * 1024 and not cls.throttled
            if throttle:
                cls.throttled = True
        if cls.mode == 'probe-throttle' or throttle:
            self.send_response(429)
            self.send_header('Retry-After', '0')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        expired = cls.mode == 'expired' and parse_qs(parsed.query).get('token') == ['1'] and count > 1
        if cls.mode == 'forbidden' or expired:
            self.send_response(403)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        body = PAYLOAD[start:end + 1]
        self.send_response(206)
        self.send_header('Content-Range', f'bytes {start}-{end}/{len(PAYLOAD)}')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('ETag', '"fixed"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), RecoveryHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        RecoveryHandler.mode = 'redirect'
        RecoveryHandler.counts = Counter()
        RecoveryHandler.ranges = []
        RecoveryHandler.throttled = False
        self.client = UpdateClient(manifest_url=self.base+'/manifest', allow_loopback=True)
        self.info = UpdateInfo('2.1.5',self.base+'/origin',DIGEST,len(PAYLOAD),'',True)

    def tearDown(self):
        self.client.close();self.temp.cleanup()

    def test_ranges_reuse_the_probed_asset_redirect(self):
        result = self.client.download(self.info,self.folder)
        self.assertEqual(result.read_bytes(),PAYLOAD)
        self.assertEqual(RecoveryHandler.counts['/origin'],1)
        self.assertGreater(RecoveryHandler.counts['/asset'],4)

    def test_late_429_recovers_from_prefix_at_single_connection(self):
        RecoveryHandler.mode = 'throttle'
        stages=[]
        with patch('update_transfer.range_transfer', wraps=__import__('update_transfer').range_transfer) as ranges:
            result=self.client.download(self.info,self.folder,stage=stages.append)
        self.assertEqual(result.read_bytes(),PAYLOAD)
        self.assertEqual([call.kwargs['connections'] for call in ranges.call_args_list],[4,1])
        self.assertEqual(ranges.call_args_list[1].args[4],8*1024*1024)
        self.assertTrue(any('单连接' in stage for stage in stages))
        self.assertEqual(RecoveryHandler.ranges.count((0,2097151)),1)

    def test_expired_signed_link_is_resolved_once_not_repeated_per_piece(self):
        RecoveryHandler.mode='expired'
        result=self.client.download(self.info,self.folder)
        self.assertEqual(result.read_bytes(),PAYLOAD)
        # Concurrent workers may independently notice expiration, but requests
        # remain bounded by worker count rather than every range in the asset.
        self.assertGreaterEqual(RecoveryHandler.counts['/origin'],2)
        self.assertLessEqual(RecoveryHandler.counts['/origin'],5)

    def test_failed_probe_preserves_an_identified_resume_prefix(self):
        part=self.folder/'VideoDownloader-Update.exe.part'
        part.write_bytes(PAYLOAD[:8*1024*1024])
        meta={'version':self.info.version,'url':self.info.url,'sha256':DIGEST,'size':len(PAYLOAD),'validator':'"fixed"'}
        (self.folder/'VideoDownloader-Update.resume.json').write_text(json.dumps(meta))
        RecoveryHandler.mode='probe-throttle'
        with self.assertRaises(UpdateRateLimitError) as caught:
            self.client.download(self.info,self.folder)
        self.assertEqual(caught.exception.status_code,429)
        self.assertEqual(caught.exception.retry_after,0)
        self.assertEqual(part.read_bytes(),PAYLOAD[:8*1024*1024])

    def test_plain_403_is_not_mislabeled_as_a_rate_limit(self):
        RecoveryHandler.mode='forbidden'
        with self.assertRaises(UpdateNetworkError) as caught:
            self.client._request(self.info.url,headers={'Range':'bytes=0-0'})
        self.assertNotIsInstance(caught.exception,UpdateRateLimitError)
        self.assertEqual(caught.exception.status_code,403)
        self.assertIn('HTTP 403',str(caught.exception))

    def test_stream_retries_obey_retry_after_and_are_cancellable(self):
        from update_core import UpdateCancelled
        from update_transfer import stream_transfer
        error=UpdateRateLimitError('limited',retry_after=17)
        with patch.object(self.client,'_request',side_effect=error), patch.object(self.client.cancelled,'wait',return_value=True) as wait:
            self.client.cancelled.set()
            # The first _cancel happens before the request, so trigger cancel
            # only during the server-directed cooldown instead.
            self.client.cancelled.clear()
            wait.side_effect=lambda seconds:(self.client.cancelled.set() or True)
            with self.assertRaises(UpdateCancelled):
                stream_transfer(self.client,self.info,self.folder/'stream.part',lambda *_:None)
        wait.assert_called_once_with(17)

    def test_server_long_cooldown_is_not_shortened_or_waited_indefinitely(self):
        from update_transfer import stream_transfer
        with patch.object(self.client,'_request',side_effect=UpdateRateLimitError('limited',retry_after=300)), patch.object(self.client.cancelled,'wait') as wait:
            with self.assertRaises(UpdateRateLimitError):
                stream_transfer(self.client,self.info,self.folder/'stream.part',lambda *_:None)
        wait.assert_not_called()

    def test_retry_after_supports_seconds_and_http_date(self):
        self.assertEqual(retry_after_seconds('17'),17)
        self.assertIsNone(retry_after_seconds('bad header'))
        date=format_datetime(datetime.now(timezone.utc)+timedelta(seconds=30),usegmt=True)
        self.assertGreater(retry_after_seconds(date),28)
        self.assertLessEqual(retry_after_seconds(date),30)


if __name__=='__main__':unittest.main(verbosity=2)
