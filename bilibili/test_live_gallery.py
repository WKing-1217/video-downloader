"""Moving Douyin LivePhoto clips must remain videos beside their static covers."""
import hashlib
import os
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid
from unittest.mock import patch

from douyin_gallery import _download_asset, download_gallery, gallery_proxies
from media_export import probe_media
from runtime_paths import configure_tools, tool
from yt_dlp.networking.exceptions import CertificateVerifyError, SSLError


class Response(BytesIO):
    def __init__(self, value):
        super().__init__(value)
        self.headers = {"Content-Length": str(len(value))}


class GalleryTransferTests(unittest.TestCase):
    def test_tls_interruption_restarts_without_corrupt_prefix(self):
        payload = b"complete media"

        class Interrupted(Response):
            def read(self, size=-1):
                if self.tell():
                    raise SSLError("record layer failure")
                return super().read(4)

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "live.part"
            ydl = unittest.mock.Mock()
            ydl.urlopen.side_effect = [Interrupted(b"corrupt prefix"), Response(payload)]
            with patch("douyin_gallery.time.sleep"), patch("douyin_gallery.gallery_proxies", return_value=None):
                _download_asset(ydl, "https://fixture.invalid/live", target,
                                {"name": "实况", "expected_size": len(payload)}, lambda *_a, **_k: None)
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(ydl.urlopen.call_count, 2)

    def test_transport_retries_are_bounded_and_certificates_are_required(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "live.part"
            for error, attempts in [(SSLError("record layer failure"), 3),
                                    (CertificateVerifyError("certificate failed"), 1)]:
                with self.subTest(error=type(error).__name__):
                    ydl = unittest.mock.Mock()
                    ydl.urlopen.side_effect = error
                    with patch("douyin_gallery.time.sleep"), patch("douyin_gallery.gallery_proxies", return_value=None):
                        with self.assertRaises(type(error)):
                            _download_asset(ydl, "https://fixture.invalid/live", target,
                                            {"name": "实况"}, lambda *_a, **_k: None)
                    self.assertEqual(ydl.urlopen.call_count, attempts)


class LivePhotoExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure_tools()
        if not all(shutil.which(tool(name)) for name in ("ffmpeg", "ffprobe")):
            raise unittest.SkipTest("FFmpeg tools are not installed")
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.clip = cls.root / "changing-live.mp4"
        cls.cover = cls.root / "cover.png"
        cls.music = cls.root / "music.m4a"
        cls.run_ffmpeg("-f", "lavfi", "-i", "testsrc2=s=128x96:r=10:d=2", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.clip))
        cls.run_ffmpeg("-i", str(cls.clip), "-frames:v", "1", str(cls.cover))
        cls.run_ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", str(cls.music))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def run_ffmpeg(*args):
        return subprocess.run([tool("ffmpeg"), "-v", "error", "-nostdin", *args], capture_output=True, check=True,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def fixture(self, live_bytes=None):
        payloads = {"https://fixture.invalid/cover": self.cover.read_bytes(),
                    "https://fixture.invalid/live": self.clip.read_bytes() if live_bytes is None else live_bytes,
                    "https://fixture.invalid/music": self.music.read_bytes()}
        assets = [{"kind": "image", "index": 1, "name": "001_图片", "width": 128, "height": 96, "urls": ["https://fixture.invalid/cover"]},
                  {"kind": "live_photo", "index": 1, "name": "001_实况", "width": 128, "height": 96, "duration": 2,
                   "expected_size": len(payloads["https://fixture.invalid/live"]), "urls": ["https://fixture.invalid/live"]},
                  {"kind": "music", "name": "背景音乐", "duration": 2, "urls": ["https://fixture.invalid/music"]}]
        info = {"id": "123", "title": "会动的图文", "image_count": 1, "_douyin_gallery": assets}

        class GalleryYDL:
            def urlopen(inner, request):
                return Response(payloads[request.url])

        output = self.root / ("output-" + uuid.uuid4().hex)
        with patch("douyin_gallery.gallery_proxies", return_value=None):
            return download_gallery(info, GalleryYDL(), output, lambda *_args, **_kwargs: None, probe_media), output

    def test_live_photo_keeps_changing_frames_with_static_cover_and_music(self):
        result, output = self.fixture()
        self.assertEqual((result["image_count"], result["live_photo_count"], result["music_count"]), (1, 1, 1))
        self.assertEqual([Path(asset["path"]).suffix for asset in result["assets"]], [".png", ".mp4", ".mp3"])
        live = Path(result["assets"][1]["path"])
        probe = probe_media(live)
        self.assertEqual([s["codec_type"] for s in probe["streams"]], ["video"])
        video = probe["streams"][0]
        self.assertGreater(int(video["nb_frames"]), 1)
        frames = self.run_ffmpeg("-i", str(live), "-map", "0:v:0", "-f", "framemd5", "-").stdout.decode().splitlines()
        frame_hashes = [line.rsplit(",", 1)[-1].strip() for line in frames if line and not line.startswith("#")]
        self.assertGreater(len(set(frame_hashes)), 1, "LivePhoto must not become a repeated static cover")
        self.assertTrue(result["assets"][1]["full_decode"])
        self.assertEqual(result["assets"][1]["sha256"], hashlib.sha256(live.read_bytes()).hexdigest())
        self.assertFalse(list(output.glob("**/*.json")))

    def test_static_cover_cannot_satisfy_live_photo_clip(self):
        existing = set(self.root.glob("output-*"))
        with self.assertRaisesRegex(ValueError, "作品尚未完整保存"):
            self.fixture(self.cover.read_bytes())
        outputs = set(self.root.glob("output-*")) - existing
        self.assertFalse(any(folder.is_dir() and any(path.suffix == ".mp4" for path in folder.rglob("*")) for folder in outputs))


class AndroidGalleryRoutingTests(unittest.TestCase):
    def test_android_automatic_system_proxy_uses_direct_album_route(self):
        with patch.dict(os.environ, {"VIDEO_DOWNLOADER_NATIVE_LIBS": "/data/app/lib/x86_64",
                                    "VIDEO_DOWNLOADER_AUTO_PROXY": "1", "HTTP_PROXY": "http://10.0.2.2:7897",
                                    "HTTPS_PROXY": "http://10.0.2.2:7897"}), \
                patch("douyin_gallery.windows_system_proxy", return_value=None):
            self.assertEqual(gallery_proxies(), {"all": None, "http": None, "https": None})
            # This is a request-local override: YouTube/Instagram still inherit
            # the same proxy and the process environment is never rewritten.
            self.assertEqual(os.environ["HTTPS_PROXY"], "http://10.0.2.2:7897")

    def test_android_explicit_user_proxy_is_not_bypassed(self):
        with patch.dict(os.environ, {"VIDEO_DOWNLOADER_NATIVE_LIBS": "/data/app/lib/x86_64",
                                    "VIDEO_DOWNLOADER_AUTO_PROXY": "", "HTTP_PROXY": "http://chosen-proxy:8080"}), \
                patch("douyin_gallery.windows_system_proxy", return_value=None):
            self.assertIsNone(gallery_proxies())
            self.assertEqual(os.environ["HTTP_PROXY"], "http://chosen-proxy:8080")

    def test_android_marker_does_not_change_desktop_explicit_proxy(self):
        with patch.dict(os.environ, {"VIDEO_DOWNLOADER_NATIVE_LIBS": "", "VIDEO_DOWNLOADER_AUTO_PROXY": "1"}), \
                patch("douyin_gallery.windows_system_proxy", return_value=None):
            self.assertIsNone(gallery_proxies())


if __name__ == "__main__":
    unittest.main()
