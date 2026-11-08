"""Single-post recognition, tracking-free deduplication and cookie isolation."""
import unittest
from urllib.parse import urlparse

from browser_accounts import cookie_summary, session_cookie_jar
from platform_links import download_link, normalize_url


class PlatformLinksTests(unittest.TestCase):
    def test_user_instagram_reel(self):
        url, platform, key = download_link("https://www.instagram.com/reel/Deq-gX4SBrF/?psln=YWxhbHR5eXl5NnMw")
        self.assertEqual(platform.key, "instagram")
        self.assertEqual(url, "https://www.instagram.com/reel/Deq-gX4SBrF/")
        self.assertEqual(key, "https://www.instagram.com/p/Deq-gX4SBrF")

    def test_user_youtube_short(self):
        url, platform, key = download_link("https://youtube.com/shorts/dsbT_StiFFU?is=z0Z82UBCJvEl6MuQ")
        self.assertEqual(platform.key, "youtube")
        self.assertEqual(url, "https://www.youtube.com/watch?v=dsbT_StiFFU")
        self.assertEqual(url, key)

    def test_youtube_routes_have_one_key(self):
        urls = ["https://youtu.be/dsbT_StiFFU?si=tracking", "https://m.youtube.com/watch?v=dsbT_StiFFU&list=PLtest&t=2", "https://www.youtube.com/embed/dsbT_StiFFU", "https://youtube.com/shorts/dsbT_StiFFU/"]
        self.assertEqual(len({download_link(url)[2] for url in urls}), 1)

    def test_instagram_routes_have_one_key(self):
        urls = ["https://instagram.com/p/Deq-gX4SBrF/?igsh=tracking", "https://www.instagram.com/reel/Deq-gX4SBrF", "https://m.instagram.com/tv/Deq-gX4SBrF/", "https://instagram.com/reels/Deq-gX4SBrF/"]
        self.assertEqual(len({download_link(url)[2] for url in urls}), 1)

    def test_share_text(self):
        self.assertEqual(download_link("看看这个 https://youtu.be/dsbT_StiFFU）。")[1].key, "youtube")

    def test_reject_non_video_and_deceptive_hosts(self):
        for url in ["https://youtube.com/", "https://youtube.com/@someone", "https://youtube.com/playlist?list=abc", "https://youtube.com/watch?v=short", "https://youtube.com/watch?v=dsbT_StiFFU&v=aaaaaaaaaaa", "https://youtu.be/dsbT_StiFFU/extra", "https://instagram.com/someone/", "https://instagram.com/explore/", "https://youtube.com.evil.example/watch?v=dsbT_StiFFU", "https://evil.example/youtube.com/watch?v=dsbT_StiFFU", "https://user:pass@youtube.com/watch?v=dsbT_StiFFU", "https://youtube.com:443/watch?v=dsbT_StiFFU"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                download_link(url)

    def test_existing_routes_preserved(self):
        for url, site in [("https://www.bilibili.com/video/BV1abc123?p=2", "bilibili"), ("https://www.douyin.com/video/1234567", "douyin"), ("https://x.com/example/status/1234", "x")]:
            self.assertEqual(download_link(url)[1].key, site)

    def test_new_site_cookie_isolation(self):
        values = [{"domain": ".instagram.com", "name": "sessionid", "value": "synthetic-ig", "path": "/"}, {"domain": ".youtube.com", "name": "SAPISID", "value": "synthetic-yt", "path": "/"}, {"domain": ".evilinstagram.com", "name": "sessionid", "value": "synthetic-other", "path": "/"}]
        for site, expected in [("instagram", "sessionid"), ("youtube", "SAPISID")]:
            jar = session_cookie_jar(values, site)
            self.assertEqual([cookie.name for cookie in jar], [expected])
            self.assertTrue(cookie_summary(jar)[site]["login_found"])


if __name__ == "__main__":
    unittest.main()
