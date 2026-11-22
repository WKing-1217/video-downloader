"""Regression for Douyin choosing a longer download variant over the post."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import downloader
from parallel_http import AcceleratedYoutubeDL
from platform_links import download_link
from runtime_paths import configure_tools, tool


class DouyinShortExportTests(unittest.TestCase):
    url = "https://www.douyin.com/video/7710539439218720357"

    @classmethod
    def setUpClass(cls):
        configure_tools()
        if not all(shutil.which(tool(name)) for name in ("ffmpeg", "ffprobe")):
            raise unittest.SkipTest("FFmpeg tools are not installed")
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.samples = Path(temp.name)
        for name, size, duration in (("playback", "96x128", 8), ("download", "144x192", 11)):
            subprocess.run([tool("ffmpeg"), "-hide_banner", "-v", "error", "-nostdin",
                            "-f", "lavfi", "-i", f"color=c=blue:s={size}:r=15:d={duration}",
                            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            str(cls.samples / (name + ".mp4"))], check=True, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def run_worker(self, output, *, mode="video", download_id="download_addr-3",
                   playback=True, download_duration=11):
        playback_url = "https://cdn.example/playback.mp4"
        download_url = "https://cdn.example/download.mp4"
        common = {"vcodec": "h264", "acodec": "aac", "ext": "mp4", "fps": 15, "preference": -1}
        formats = [{**common, "url": download_url, "format_id": download_id,
                    "format_note": "Download video, watermarked", "width": 144, "height": 192}]
        if playback:
            formats.append({**common, "url": playback_url, "format_id": "play_addr",
                            "format_note": "Direct video", "width": 96, "height": 128})
        fixtures = {playback_url: self.samples / "playback.mp4",
                    download_url: self.samples / ("download.mp4" if download_duration == 11 else "playback.mp4")}
        transferred = []

        class FixtureDownloader(AcceleratedYoutubeDL):
            def extract_info(self, url, *, download=False, process=True):
                if process or download or url != DouyinShortExportTests.url:
                    raise AssertionError(f"Unexpected extraction request: {url}")
                return {"id": "7710539439218720357", "title": "Douyin duration fixture",
                        "duration": 8, "formats": formats}

            def process_info(self, info):
                # Keep yt-dlp's production format selection. Substitute only media transfer.
                selected = info["url"]
                transferred.append(selected)
                info["filepath"] = self.prepare_filename(info)
                shutil.copyfile(fixtures[selected], info["filepath"])

        with patch.object(downloader, "OUTPUT", output), \
                patch.object(downloader, "AcceleratedYoutubeDL", FixtureDownloader), \
                patch.object(downloader, "windows_system_proxy", return_value=None), \
                patch.object(downloader, "emit"):
            result = downloader.download(self.url, auto_cookies=False, mode=mode)
        return result, transferred

    def test_video_uses_playback_even_when_download_variant_has_higher_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result, transferred = self.run_worker(output)
            self.assertEqual(transferred, ["https://cdn.example/playback.mp4"])
            self.assertEqual(result["selected_formats"], ["play_addr"])
            self.assertAlmostEqual(result["duration"], 8, delta=0.1)
            self.assertTrue(result["full_decode"])
            self.assertEqual(list(output.glob("*.mp4")), [Path(result["path"])])
            self.assertFalse(list(output.rglob("*.json")))

    def test_audio_uses_playback_when_download_id_was_replaced_by_codec_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            result, transferred = self.run_worker(Path(directory), mode="audio", download_id="h264_720p_2500000")
            self.assertEqual(transferred, ["https://cdn.example/playback.mp4"])
            self.assertEqual(result["selected_formats"], ["play_addr"])
            self.assertEqual(result["audio_codec"], "mp3")
            self.assertAlmostEqual(result["duration"], 8, delta=0.1)

    def test_only_download_variant_still_passes_or_fails_on_actual_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaisesRegex(ValueError, "完整性校验失败.*8.00 秒.*11.00 秒"):
                self.run_worker(output, playback=False)
            self.assertFalse(list(output.glob("*.mp4")))
            result, _ = self.run_worker(output, playback=False, download_duration=8)
            self.assertEqual(result["selected_formats"], ["download_addr-3"])
            self.assertAlmostEqual(result["duration"], 8, delta=0.1)
            self.assertTrue(result["full_decode"])


class DouyinShareInputTests(unittest.TestCase):
    def test_escaped_scheme_matches_ordinary_share_link(self):
        normal = "4.69 复制打开抖音 https://v.douyin.com/DDd0wBwVQEM/ R@X.Mw 08/14 WzG:/ :7pm"
        escaped = normal.replace("https://", r"https\://")
        self.assertEqual(download_link(escaped), download_link(normal))

    def test_escaped_scheme_does_not_allow_unrelated_hosts(self):
        for link in (r"https\://v.douyin.com.example/DDd0wBwVQEM/",
                     r"https\://v.douyin.com@evil.example/DDd0wBwVQEM/"):
            with self.subTest(link=link), self.assertRaises(ValueError):
                download_link(link)


if __name__ == "__main__":
    unittest.main()
