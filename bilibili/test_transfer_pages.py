"""Page routing stays independent while video and MP3 tasks share one worker."""
from collections import deque
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from app import DownloadWindow
from platform_links import PLATFORMS


def task(mode="video", *, created=1, state="failed", local_path="", platform="bilibili"):
    return SimpleNamespace(mode=mode, created=created, state=state, local_path=local_path,
                           platform=PLATFORMS[platform], url="https://www.bilibili.com/video/BV1yUFPzKEC7",
                           options={"audio_bitrate": 320})


def page(last_task=None, url=""):
    return SimpleNamespace(last_task=last_task, render=Mock(), reject_input=Mock(),
                           input_message=SimpleNamespace(hide=Mock()),
                           url=SimpleNamespace(text=Mock(return_value=url)),
                           queue_label=SimpleNamespace(setText=Mock(), setVisible=Mock()),
                           clear_queue_button=SimpleNamespace(setVisible=Mock()))


class TransferPageRoutingTests(unittest.TestCase):
    def window(self, *, index=0):
        return SimpleNamespace(download_page=page(), audio_page=page(),
                               downloads=SimpleNamespace(active=None, queue=deque(), cancel_current=Mock(),
                                                         submit=Mock(return_value=None), extract_audio=Mock(return_value=None)),
                               pages=SimpleNamespace(currentIndex=Mock(return_value=index)),
                               closing=False, updater=SimpleNamespace(installing=False),
                               render_task=Mock(), set_page=Mock())

    def test_submit_uses_the_source_page_and_mode(self):
        window = self.window()
        window.submit_transfer = Mock()
        DownloadWindow.submit_link(window, "video link")
        DownloadWindow.submit_audio_link(window, "audio link")
        self.assertEqual(window.submit_transfer.call_args_list[0].args,
                         ("video link", window.download_page, "video"))
        self.assertEqual(window.submit_transfer.call_args_list[1].args,
                         ("audio link", window.audio_page, "audio"))

    def test_submission_feedback_and_task_stay_on_the_source_page(self):
        window = self.window()
        audio = task("audio")
        window.downloads.submit.return_value = audio
        result = DownloadWindow.submit_transfer(window, "audio link", window.audio_page, "audio")
        self.assertIs(result, audio)
        self.assertIs(window._feedback_page, window.audio_page)
        window.downloads.submit.assert_called_once_with("audio link", mode="audio")
        window.audio_page.input_message.hide.assert_called_once()
        window.download_page.input_message.hide.assert_not_called()
        window.render_task.assert_called_once_with(audio)

    def test_library_extraction_opens_the_dedicated_page(self):
        window = self.window(index=1)
        audio = task("audio", local_path="existing.mp4")
        window.downloads.extract_audio.return_value = audio
        result = DownloadWindow.extract_audio(window, {"path": "existing.mp4"})
        self.assertIs(result, audio)
        window.set_page.assert_called_once_with(3)
        self.assertIs(window._feedback_page, window.audio_page)
        window.downloads.extract_audio.assert_called_once_with("existing.mp4")
        window.render_task.assert_called_once_with(audio)

    def test_each_page_retries_its_own_task_and_original_export_options(self):
        window = self.window(index=0)
        video = task()
        audio = task("audio", local_path="existing.mp4")
        window.download_page.last_task, window.audio_page.last_task = video, audio
        DownloadWindow.retry_download(window, window.audio_page)
        window.downloads.extract_audio.assert_called_once_with("existing.mp4", force=True, options=audio.options)
        window.downloads.submit.assert_not_called()
        self.assertIs(window._feedback_page, window.audio_page)
        DownloadWindow.retry_download(window, window.download_page)
        window.downloads.submit.assert_called_once_with(video.url, force=True, mode="video", options=video.options)
        self.assertIs(window._feedback_page, window.download_page)

    def test_retry_immediately_shows_waiting_task_while_other_page_is_running(self):
        for mode, local_path in (("video", ""), ("audio", ""), ("audio", "existing.mp4")):
            with self.subTest(mode=mode, local_path=local_path):
                window = self.window(index=3 if mode == "audio" else 0)
                selected_page = window.audio_page if mode == "audio" else window.download_page
                other_page = window.download_page if mode == "audio" else window.audio_page
                selected_page.last_task = task(mode, local_path=local_path)
                queued = task(mode, created=2, state="queued", local_path=local_path)
                window.downloads.active = task("video" if mode == "audio" else "audio", state="running")
                manager_call = window.downloads.extract_audio if local_path else window.downloads.submit
                manager_call.return_value = queued
                window.render_task = lambda incoming: DownloadWindow.render_task(window, incoming)
                result = DownloadWindow.retry_download(window, selected_page)
                self.assertIs(result, queued)
                selected_page.input_message.hide.assert_called_once()
                selected_page.render.assert_called_once_with(queued)
                other_page.render.assert_not_called()

    def test_rejected_retry_keeps_its_error_feedback_and_failed_task(self):
        window = self.window(index=3)
        failed = task("audio")
        window.audio_page.last_task = failed
        self.assertIsNone(DownloadWindow.retry_download(window, window.audio_page))
        window.audio_page.input_message.hide.assert_not_called()
        window.render_task.assert_not_called()
        self.assertIs(window.audio_page.last_task, failed)

    def test_current_platform_uses_active_extraction_page_link_or_its_task(self):
        window = self.window(index=3)
        window.download_page.url.text.return_value = "https://www.bilibili.com/video/BV1yUFPzKEC7"
        window.audio_page.url.text.return_value = "https://www.douyin.com/video/1234567890123456789"
        self.assertEqual(DownloadWindow.current_platform(window), "douyin")
        window.audio_page.url.text.return_value = ""
        window.audio_page.last_task = task("audio", platform="x")
        self.assertEqual(DownloadWindow.current_platform(window), "x")
        window.pages.currentIndex.return_value = 0
        self.assertEqual(DownloadWindow.current_platform(window), "bilibili")

    def test_cancel_cannot_stop_the_opposite_page_task(self):
        window = self.window()
        window.downloads.active = task("video", state="running")
        DownloadWindow.cancel_transfer(window, "audio")
        window.downloads.cancel_current.assert_not_called()
        DownloadWindow.cancel_transfer(window, "video")
        window.downloads.cancel_current.assert_called_once()

    def test_queue_feedback_counts_only_its_page_mode(self):
        window = self.window()
        window.downloads.queue.extend([task("audio"), task("video"), task("audio")])
        DownloadWindow.render_queue(window)
        window.download_page.queue_label.setText.assert_called_once_with("等待 1")
        window.audio_page.queue_label.setText.assert_called_once_with("等待 2")
        window.downloads.queue.clear()
        DownloadWindow.render_queue(window)
        window.download_page.clear_queue_button.setVisible.assert_called_with(False)
        window.audio_page.clear_queue_button.setVisible.assert_called_with(False)

    def test_task_progress_updates_its_own_page(self):
        window = self.window()
        video, audio = task(), task("audio")
        DownloadWindow.render_task(window, video)
        window.download_page.render.assert_called_once_with(video)
        window.audio_page.render.assert_not_called()
        DownloadWindow.render_task(window, audio)
        window.audio_page.render.assert_called_once_with(audio)

    def test_old_catalogue_completion_cannot_replace_newer_page_task(self):
        for mode in ("video", "audio"):
            for active_mode in (None, "audio" if mode == "video" else "video"):
                with self.subTest(mode=mode, active_mode=active_mode):
                    window = self.window()
                    selected_page = window.audio_page if mode == "audio" else window.download_page
                    selected_page.last_task = task(mode, created=2, state="running")
                    window.downloads.active = task(active_mode, created=3) if active_mode else None
                    DownloadWindow.render_task(window, task(mode, created=1, state="done"))
                    selected_page.render.assert_not_called()

    def test_completion_refresh_does_not_render_an_unrelated_page_task(self):
        window = self.window(index=3)
        window.library = SimpleNamespace(reload=Mock(), refresh=Mock())
        result = {"path": "completed.mp4"}
        DownloadWindow.download_completed(window, result)
        self.assertIs(window.last_result, result)
        window.library.reload.assert_called_once()
        window.library.refresh.assert_called_once()
        window.render_task.assert_not_called()
        window.audio_page.render.assert_not_called()


if __name__ == "__main__":
    unittest.main()
