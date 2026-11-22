"""Instagram access gates must remain failures with an actionable login path."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from yt_dlp.utils import DownloadError

import downloader
from platform_links import download_link


class InstagramAccessTests(unittest.TestCase):
    url = "https://www.instagram.com/reel/Dfhq74KRkve/?vrfl=MWgzcnRvaHV1bTV6\u00a0"
    audience_error = ("ERROR: [Instagram] Dfhq74KRkve: This content isn't available to everyone: "
                      "It can't be seen by certain audiences.")

    def test_reported_share_link_is_not_the_failure(self):
        url, site, key = download_link(self.url)
        self.assertEqual(url, "https://www.instagram.com/reel/Dfhq74KRkve/")
        self.assertEqual(site.key, "instagram")
        self.assertEqual(key, "https://www.instagram.com/p/Dfhq74KRkve")

    def test_audience_gate_explains_login_without_promising_access(self):
        for reason in (self.audience_error, "This content isn\u2019t available to everyone",
                       "Restricted Video", "This video is age-restricted", "age restricted"):
            with self.subTest(reason=reason):
                message = downloader.instagram_access_error(reason)
                self.assertIn("设置 → 账号与登录", message)
                self.assertIn("确认登录后能播放", message)
                self.assertIn("仍不可见的视频无法下载", message)

    def test_login_or_expired_session_provides_existing_login_entry(self):
        for reason in ("Login required", "Please log in", "Sign in to watch",
                       "Private video", "The provided cookies are no longer valid"):
            with self.subTest(reason=reason):
                message = downloader.instagram_access_error(reason)
                self.assertIn("Instagram 要求登录或验证", message)
                self.assertIn("设置 → 账号与登录", message)

    def test_unrelated_failure_is_not_misreported_as_a_login_gate(self):
        for reason in ("HTTP Error 404: Not Found", "connection timed out",
                       "Requested format is not available", "HTTP Error 429: Too Many Requests"):
            with self.subTest(reason=reason):
                self.assertIsNone(downloader.instagram_access_error(reason))

    def test_real_worker_download_path_preserves_failure_and_never_publishes(self):
        for mode in ("video", "audio"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                error = DownloadError(self.audience_error)
                with patch.object(downloader, "OUTPUT", Path(folder)), \
                        patch.object(downloader, "AcceleratedYoutubeDL") as factory, \
                        patch.object(downloader, "windows_system_proxy", return_value=None), \
                        patch.object(downloader, "require_tools"), patch.object(downloader, "emit") as emit:
                    worker = factory.return_value.__enter__.return_value
                    worker.extract_info.side_effect = error
                    with self.assertRaisesRegex(ValueError, "Instagram 限制了这条视频的访问") as raised:
                        downloader.download(self.url, auto_cookies=False, mode=mode)
                    self.assertIs(raised.exception.__cause__, error)
                    worker.process_info.assert_not_called()
                    self.assertFalse(any(path.is_file() for path in Path(folder).rglob("*")))
                    self.assertFalse(any(call.args[0] == "complete" for call in emit.call_args_list))


if __name__ == "__main__":
    unittest.main()
