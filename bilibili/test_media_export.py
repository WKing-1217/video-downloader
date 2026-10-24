"""Real FFmpeg conversion and worker integration without remote site access."""
import io
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import downloader
from douyin_gallery import download_gallery
from media_export import (AUDIO_BITRATES, IMAGE_FORMATS, VIDEO_FORMATS, export_image,
                          export_video, extract_audio, probe_media, validate_options)
from runtime_paths import configure_tools, tool


class Response(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}


class MediaExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure_tools()
        if not all(shutil.which(tool(name)) for name in ("ffmpeg", "ffprobe")):
            raise unittest.SkipTest("FFmpeg tools are not installed")
        cls.fixtures = tempfile.TemporaryDirectory()
        cls.source = Path(cls.fixtures.name)
        cls.video = cls.source / "有声音的视频.mp4"
        cls.silent = cls.source / "无声音的视频.mp4"
        cls.audio = cls.source / "音乐.m4a"
        cls.image = cls.source / "原始图片.jpg"
        cls.ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=128x96:r=15:d=2", "-f", "lavfi", "-i",
                   "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", cls.video)
        cls.ffmpeg("-i", cls.video, "-an", "-c:v", "copy", cls.silent)
        cls.ffmpeg("-i", cls.video, "-vn", "-c:a", "copy", cls.audio)
        cls.ffmpeg("-i", cls.video, "-frames:v", "1", "-q:v", "2", cls.image)

    @classmethod
    def ffmpeg(cls, *arguments):
        subprocess.run([tool("ffmpeg"), "-hide_banner", "-v", "error", "-nostdin", *map(str, arguments)],
                       check=True, capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / "导出目录"
        self.output.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def assert_no_sidecars(self):
        self.assertFalse(list(self.output.rglob("*.json")))
        self.assertFalse(list(self.output.rglob(".export-*")))

    def test_local_mp3_all_bitrates_preserve_original_and_never_overwrite(self):
        original = self.video.read_bytes()
        existing = self.output / (self.video.stem + ".mp3")
        existing.write_bytes(b"existing user's audio")
        for bitrate in AUDIO_BITRATES:
            with self.subTest(bitrate=bitrate):
                result = extract_audio(self.video, self.output, bitrate=bitrate)
                self.assertNotEqual(Path(result["path"]), existing)
                self.assertEqual((result["kind"], result["audio_codec"]), ("audio", "mp3"))
                self.assertEqual(result["audio_bitrate"], bitrate * 1000)
                self.assertAlmostEqual(result["duration"], 2, delta=0.1)
        self.assertEqual(self.video.read_bytes(), original)
        self.assertEqual(existing.read_bytes(), b"existing user's audio")
        self.assert_no_sidecars()

    def test_silent_video_fails_without_output(self):
        with self.assertRaisesRegex(ValueError, "没有可提取的音轨"):
            extract_audio(self.silent, self.output)
        self.assertFalse(list(self.output.iterdir()))

    def test_all_video_containers_are_real_and_preserve_duration(self):
        for video_format in VIDEO_FORMATS:
            with self.subTest(video_format=video_format):
                result = export_video(self.video, self.output, video_format=video_format, expected=2)
                self.assertEqual(Path(result["path"]).suffix, "." + video_format)
                probe = probe_media(Path(result["path"]))
                self.assertTrue(any(s["codec_type"] == "video" for s in probe["streams"]))
                self.assertTrue(any(s["codec_type"] == "audio" for s in probe["streams"]))
                self.assertAlmostEqual(float(probe["format"]["duration"]), 2, delta=0.15)
                if video_format == "webm":
                    self.assertEqual(result["video_codec"], "vp9")
        self.assert_no_sidecars()

    def test_mp4_preserves_av1_video_codec(self):
        source = self.output / "av1-source.mkv"
        self.ffmpeg("-i", self.video, "-c:v", "libaom-av1", "-cpu-used", "8", "-crf", "35", "-c:a", "copy", source)
        result = export_video(source, self.output, video_format="mp4")
        self.assertEqual(result["video_codec"], "av1")
        self.assertEqual(result["audio_codec"], "aac")
        self.assert_no_sidecars()

    def test_all_image_formats_convert_bytes_and_keep_dimensions(self):
        expected = {"png": "png", "jpg": "mjpeg", "webp": "webp"}
        for image_format in IMAGE_FORMATS:
            with self.subTest(image_format=image_format):
                result = export_image(self.image, self.output, image_format=image_format)
                self.assertEqual(result["codec"], expected[image_format])
                self.assertEqual((result["width"], result["height"]), (128, 96))
        self.assert_no_sidecars()

    def test_incorrect_duration_and_failed_conversion_never_publish(self):
        with self.assertRaisesRegex(ValueError, "完整性校验失败"):
            export_video(self.video, self.output, expected=20)
        with patch("media_export.full_decode", side_effect=ValueError("decode failed")):
            with self.assertRaisesRegex(ValueError, "decode failed"):
                extract_audio(self.video, self.output)
        self.assertFalse(list(self.output.iterdir()))

    def test_cli_extract_audio_writes_to_configured_output(self):
        result = subprocess.run([sys.executable, str(Path(downloader.__file__)), "--extract-audio", str(self.video),
                                 "--audio-bitrate", "256"], capture_output=True, text=True, encoding="utf-8",
                                env={**os.environ, "VIDEO_DOWNLOADER_OUTPUT": str(self.output)},
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        complete = [json.loads(line) for line in result.stdout.splitlines() if line][ -1]
        self.assertEqual((complete["event"], complete["kind"], complete["audio_bitrate"]), ("complete", "audio", 256000))
        self.assertEqual(Path(complete["path"]).parent, self.output)
        self.assertTrue(self.video.is_file())
        self.assert_no_sidecars()

    def download_fixture(self, mode, **settings):
        source = self.audio if mode == "audio" else self.video
        options_seen = []

        class FakeYDL:
            def __init__(inner, options):
                inner.options = options
                options_seen.append(options)

            def __enter__(inner):
                return inner

            def __exit__(inner, *_):
                pass

            def add_info_extractor(inner, _extractor):
                pass

            def extract_info(inner, url, **_):
                return {"id": "fixture", "title": "本地模拟下载", "duration": 2, "format_id": "best",
                        "ext": source.suffix[1:], "formats": []}

            def prepare_filename(inner, info):
                return str(Path(inner.options["paths"]["home"]) / (info["title"] + source.suffix))

            def process_info(inner, info):
                info["filepath"] = inner.prepare_filename(info)
                shutil.copyfile(source, info["filepath"])

        with patch.object(downloader, "OUTPUT", self.output), patch.object(downloader, "AcceleratedYoutubeDL", FakeYDL), \
                patch.object(downloader, "windows_system_proxy", return_value=None), patch.object(downloader, "emit"):
            result = downloader.download("https://www.bilibili.com/video/BV1yUFPzKEC7", auto_cookies=False,
                                         mode=mode, **settings)
        return result, options_seen[0]

    def test_link_mp3_uses_audio_selector_and_has_no_video_or_json(self):
        result, options = self.download_fixture("audio", audio_bitrate=320)
        self.assertEqual(options["format"], "bestaudio/best")
        self.assertFalse(options["writeinfojson"])
        self.assertEqual((result["kind"], result["audio_bitrate"]), ("audio", 320000))
        streams = probe_media(Path(result["path"]))["streams"]
        self.assertEqual([s["codec_type"] for s in streams], ["audio"])
        self.assertFalse(list(self.output.rglob("*.mp4")))
        self.assert_no_sidecars()

    def test_bilibili_http_412_explains_retry_without_promising_login_will_fix(self):
        error = downloader.yt_dlp.utils.DownloadError("Unable to download webpage: HTTP Error 412: Precondition Failed")
        with patch.object(downloader, "OUTPUT", self.output), patch.object(downloader, "AcceleratedYoutubeDL") as factory, \
                patch.object(downloader, "windows_system_proxy", return_value=None), patch.object(downloader, "emit"):
            factory.return_value.__enter__.return_value.extract_info.side_effect = error
            with self.assertRaisesRegex(ValueError, "Bilibili 暂时拒绝访问（HTTP 412）.*稍后重试.*网页登录") as raised:
                downloader.download("https://www.bilibili.com/video/BV1yUFPzKEC7", auto_cookies=False, mode="audio")
        self.assertIs(raised.exception.__cause__, error)
        self.assert_no_sidecars()

    def test_link_default_is_mp4_and_alternate_export_keeps_first(self):
        first, _ = self.download_fixture("video")
        data = Path(first["path"]).read_bytes()
        second, _ = self.download_fixture("video", video_format="webm")
        self.assertEqual(Path(first["path"]).suffix, ".mp4")
        self.assertEqual(Path(second["path"]).suffix, ".webm")
        self.assertEqual(Path(first["path"]).read_bytes(), data)
        self.assert_no_sidecars()

    def test_bad_cached_audio_is_preserved_and_retried(self):
        url = "https://www.bilibili.com/video/BV1yUFPzKEC7"
        source_key = downloader.download_link(url)[2]
        folder = self.output / ".downloads" / hashlib.sha256((source_key + "|audio").encode()).hexdigest()[:20]
        folder.mkdir(parents=True)
        cached = folder / "本地模拟下载.m4a"
        cached.write_bytes(b"truncated cached audio")
        result, _ = self.download_fixture("audio")
        self.assertEqual(result["kind"], "audio")
        quarantined = list((folder / "未通过校验").glob("*.m4a"))
        self.assertEqual(len(quarantined), 1)
        self.assertEqual(quarantined[0].read_bytes(), b"truncated cached audio")
        self.assert_no_sidecars()

    def test_packet_decode_failure_retires_worker_input_before_retry(self):
        with patch("downloader.extract_audio", side_effect=ValueError("corrupt packet")):
            with self.assertRaisesRegex(ValueError, "corrupt packet"):
                self.download_fixture("audio")
        self.assertFalse(list(self.output.glob("*.mp3")))
        self.assertEqual(len(list(self.output.rglob("未通过校验/*.m4a"))), 1)
        result, _ = self.download_fixture("audio")
        self.assertEqual(result["kind"], "audio")
        self.assert_no_sidecars()

    def test_cache_cleanup_permission_error_does_not_fail_a_verified_export(self):
        original_unlink = Path.unlink

        def unlink(path, *args, **kwargs):
            if path.name == "本地模拟下载.m4a":
                raise PermissionError("cache is locked")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", unlink):
            result, _ = self.download_fixture("audio")
        self.assertTrue(Path(result["path"]).is_file())
        self.assertEqual(result["audio_codec"], "mp3")
        self.assert_no_sidecars()

    def gallery_fixture(self, mode="video", **options):
        assets = [{"kind": "image", "name": "001_图片", "index": 1, "width": 128, "height": 96,
                   "urls": ["https://fixture/image"]},
                  {"kind": "live_photo", "name": "001_实况", "index": 1, "width": 128, "height": 96,
                   "duration": 2, "urls": ["https://fixture/live"]},
                  {"kind": "music", "name": "背景音乐", "duration": 2, "urls": ["https://fixture/music"]}]
        info = {"id": "123", "title": "测试图文", "image_count": 1, "_douyin_gallery": assets}
        fixtures = {"https://fixture/image": self.image, "https://fixture/live": self.silent,
                    "https://fixture/music": self.audio}

        class GalleryYDL:
            def urlopen(inner, request):
                return Response(fixtures[request.url].read_bytes())

        with patch("douyin_gallery.gallery_proxies", return_value=None):
            return download_gallery(info, GalleryYDL(), self.output, lambda *_args, **_kwargs: None,
                                    probe_media, mode=mode, **options)

    def test_gallery_defaults_actual_png_mp4_mp3_without_receipt(self):
        result = self.gallery_fixture()
        self.assertEqual(result["content_type"], "gallery")
        self.assertEqual([Path(a["path"]).suffix for a in result["assets"]], [".png", ".mp4", ".mp3"])
        self.assertEqual([a["kind"] for a in result["assets"]], ["image", "live_photo", "music"])
        self.assert_no_sidecars()

    def test_gallery_failure_never_exposes_partial_album(self):
        with patch("douyin_gallery.export_video", side_effect=ValueError("conversion failed")):
            with self.assertRaisesRegex(ValueError, "作品尚未完整保存"):
                self.gallery_fixture()
        self.assertEqual([p.name for p in self.output.iterdir()], [".downloads"])
        self.assertFalse(list((self.output / ".downloads").iterdir()))

    def test_gallery_never_overwrites_an_existing_album(self):
        original = self.gallery_fixture()
        first_files = {a["path"]: Path(a["path"]).read_bytes() for a in original["assets"]}
        again = self.gallery_fixture()
        self.assertNotEqual(original["path"], again["path"])
        for path, data in first_files.items():
            self.assertEqual(Path(path).read_bytes(), data)
        self.assertTrue(all(Path(a["path"]).parent == Path(again["path"]) for a in again["assets"]))
        self.assert_no_sidecars()

    def test_gallery_audio_only_and_selected_formats(self):
        audio = self.gallery_fixture("audio")
        self.assertEqual((audio["kind"], Path(audio["path"]).suffix), ("audio", ".mp3"))
        self.assertEqual(list(self.output.glob("*.mp3")), [Path(audio["path"])])
        gallery = self.gallery_fixture(image_format="webp", video_format="mkv")
        self.assertEqual([Path(a["path"]).suffix for a in gallery["assets"]], [".webp", ".mkv", ".mp3"])
        self.assert_no_sidecars()

    def test_gallery_without_music_audio_request_fails_helpfully(self):
        info = {"id": "123", "title": "无配乐图文", "_douyin_gallery": [{"kind": "image"}], "image_count": 1}
        with self.assertRaisesRegex(ValueError, "没有可提取的背景音乐"):
            download_gallery(info, None, self.output, lambda *_args, **_kwargs: None, probe_media, mode="audio")
        self.assertFalse(list(self.output.iterdir()))

    def test_invalid_settings_rejected_before_work(self):
        for values in ({"mode": "other"}, {"video_format": "exe"}, {"image_format": "gif"}, {"audio_bitrate": 99}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_options(**values)


if __name__ == "__main__":
    unittest.main()
