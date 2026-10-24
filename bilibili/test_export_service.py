"""Queue choices must survive settings changes, retries and source deduplication."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication

from download_service import DownloadManager
from export_preferences import export_preferences
from platform_links import download_link
from runtime_paths import save_settings


class FakeStore:
    def __init__(self):
        self.known = {}

    def find_source(self, key):
        return self.known.get(key)


class ExportQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name})
        self.environment.start()
        self.timer = patch("download_service.QTimer.singleShot")
        self.timer.start()
        self.store = FakeStore()
        self.manager = DownloadManager(self.store, None, Path(self.temp.name) / "exports")
        self.url = "https://www.bilibili.com/video/BV1yUFPzKEC7"

    def tearDown(self):
        self.manager.shutdown()
        self.timer.stop()
        self.environment.stop()
        self.temp.cleanup()

    def test_video_and_audio_are_separate_but_same_mode_deduplicates(self):
        video = self.manager.submit(self.url)
        self.store.known[video.key] = {"id": 1}
        audio = self.manager.submit(self.url, mode="audio")
        self.assertIsNotNone(audio)
        self.assertNotEqual(video.key, audio.key)
        self.assertIsNone(self.manager.submit(self.url, mode="audio"))

    def test_formats_are_snapshotted_when_enqueued(self):
        save_settings(video_format="mkv", image_format="webp", audio_bitrate=320)
        task = self.manager.submit(self.url)
        save_settings(video_format="mov", image_format="jpg", audio_bitrate=128)
        self.assertEqual(task.options, {"video_format": "mkv", "image_format": "webp", "audio_bitrate": 320})
        self.assertIsNotNone(self.manager.submit(self.url))

    def test_local_extraction_uses_source_identity_and_never_changes_original(self):
        source = Path(self.temp.name) / "已有视频.mp4"
        source.write_bytes(b"local-video")
        task = self.manager.extract_audio(source)
        self.assertEqual(task.mode, "audio")
        self.assertEqual(task.local_path, str(source.resolve()))
        self.assertIsNone(self.manager.extract_audio(source))
        source.write_bytes(b"replaced-local-video")
        self.assertIsNotNone(self.manager.extract_audio(source))
        self.assertEqual(source.read_bytes(), b"replaced-local-video")

    def test_invalid_settings_and_unavailable_files(self):
        self.assertEqual(export_preferences({"video_format": "bogus", "image_format": None, "audio_bitrate": "bad"}),
                         {"video_format": "mp4", "image_format": "png", "audio_bitrate": 192})
        self.assertIsNone(self.manager.extract_audio(Path(self.temp.name) / "missing.mp4"))
        self.manager.output_locked = True
        self.assertIsNone(self.manager.submit(self.url))
        self.assertIsNone(self.manager.extract_audio(Path(self.temp.name) / "missing.mp4"))

    def test_legacy_mp4_is_reused_but_legacy_jpeg_gallery_is_reexported(self):
        key = download_link(self.url)[2]
        self.store.known[key] = {"id": 1, "kind": "video", "path": "old.mp4"}
        self.assertIsNone(self.manager.submit(self.url))
        self.store.known[key] = {"id": 2, "kind": "gallery", "path": "old-gallery", "metadata": "{}"}
        self.assertIsNotNone(self.manager.submit(self.url))

    def test_gallery_music_quality_is_a_distinct_export(self):
        first = self.manager.submit(self.url)
        higher = self.manager.submit(self.url, options={"audio_bitrate": 320})
        self.assertIsNotNone(higher)
        self.assertNotEqual(first.key, higher.key)

    def test_clearing_one_page_queue_preserves_other_mode(self):
        video = self.manager.submit(self.url)
        audio = self.manager.submit(self.url, mode="audio")
        self.manager.clear_queue("audio")
        self.assertEqual(list(self.manager.queue), [video])
        self.assertEqual(self.manager.pending_keys, {video.key})
        self.assertEqual(audio.state, "cancelled")
        self.assertTrue(audio.cancelled)
        self.assertEqual(video.state, "queued")


if __name__ == "__main__":
    unittest.main()
