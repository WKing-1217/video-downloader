"""Local integrity checks; --ui also runs the real Qt -> downloader workflow."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import sqlite3
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from downloader import media_candidates, normalize_url, quarantine_incomplete, verify_media
from browser_accounts import BrowserProfile, scan_accounts, select_account, session_cookie_jar
from platform_links import resolve_link
from network_settings import windows_system_proxy
from douyin_adapter import DouyinIE, add_stream_choices, find_requested_video
from douyin_gallery import gallery_info, gallery_proxies, verify_asset

ROOT = Path(__file__).resolve().parent
SAMPLE = "https://www.bilibili.com/video/BV1yUFPzKEC7"


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "sample.mp4"
        self.path.write_bytes(b"fixture")
        self.probe = {
            "format": {"duration": "294.785"},
            "streams": [
                {"codec_type": "video", "codec_name": "av1", "width": 1920,
                 "height": 1080, "duration": "294.760"},
                {"codec_type": "audio", "codec_name": "aac", "duration": "294.785"},
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_copied_share_text(self):
        self.assertEqual(normalize_url(f"【分享视频】 {SAMPLE}。"), SAMPLE)

    def test_reject_unrelated_host(self):
        for url in ("https://bilibili.com.example.org/video/test", "https://example.com/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_url(url)

    def test_complete_streams(self):
        result = verify_media(self.path, 295, self.probe)
        self.assertAlmostEqual(result["duration"], 294.785)

    def test_reject_missing_audio(self):
        probe = copy.deepcopy(self.probe)
        probe["streams"].pop()
        with self.assertRaises(ValueError):
            verify_media(self.path, 295, probe)

    def test_reject_short_video_hidden_by_full_audio(self):
        probe = copy.deepcopy(self.probe)
        probe["streams"][0]["duration"] = "30"
        with self.assertRaises(ValueError):
            verify_media(self.path, 295, probe)

    def test_reject_invalid_or_short_duration(self):
        for duration in ("30", "nan", "inf"):
            probe = copy.deepcopy(self.probe)
            probe["format"]["duration"] = duration
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                verify_media(self.path, 295, probe)

    def test_incomplete_cached_file_and_receipt_are_preserved_before_retry(self):
        receipt = self.path.with_suffix(".mp4.info.json")
        receipt.write_text('{"old":true}', encoding="utf-8")
        ydl = SimpleNamespace(prepare_filename=lambda _info: str(self.path))
        with patch("downloader.verify_media", side_effect=ValueError("short audio")), patch("downloader.emit"):
            quarantine_incomplete({}, ydl, 295)
        self.assertFalse(self.path.exists())
        preserved = list((self.path.parent / "未通过校验").glob("*.mp4"))
        self.assertEqual(len(preserved), 1)
        self.assertEqual(preserved[0].read_bytes(), b"fixture")
        self.assertEqual(preserved[0].with_suffix(".mp4.info.json").read_text(encoding="utf-8"), '{"old":true}')

    def test_complete_cached_file_is_reused(self):
        ydl = SimpleNamespace(prepare_filename=lambda _info: str(self.path))
        with patch("downloader.verify_media", return_value={}), patch("downloader.emit"):
            quarantine_incomplete({}, ydl, 295)
        self.assertEqual(self.path.read_bytes(), b"fixture")
        self.assertFalse((self.path.parent / "未通过校验").exists())

    def test_container_candidates_keep_dots_inside_the_title(self):
        path = self.path.parent / "A.B [video] [format].mp4"
        self.assertIn(path.with_suffix(".mkv"), media_candidates(path))


class PlatformTests(unittest.TestCase):
    def test_detect_all_three_platforms_and_short_links(self):
        samples = {
            SAMPLE: "bilibili", "https://b23.tv/AbCdE": "bilibili",
            "8.66 分享文案 https://v.douyin.com/ABC123/ 复制打开抖音": "douyin",
            "https://www.douyin.com/video/6961737553342991651": "douyin",
            "https://x.com/starwars/status/665052190608723968": "x",
            "https://mobile.twitter.com/example/status/123/video/2?s=20": "x",
        }
        for text, expected in samples.items():
            with self.subTest(text=text):
                self.assertEqual(resolve_link(text)[1].key, expected)

    def test_canonicalize_douyin_modal_and_legacy_share(self):
        expected = "https://www.douyin.com/video/12345678"
        for text in ("https://www.douyin.com/?modal_id=12345678",
                     "https://www.iesdouyin.com/share/video/12345678/?region=CN"):
            self.assertEqual(normalize_url(text), expected)

    def test_douyin_note_and_slides_keep_their_content_type(self):
        for kind in ("note", "slides"):
            expected = f"https://www.douyin.com/{kind}/7547315780212772138"
            for host in ("www.douyin.com", "www.iesdouyin.com", "m.douyin.com"):
                text = f"https://{host}/share/{kind}/7547315780212772138?previous_page=web_code_link"
                self.assertEqual(normalize_url(text), expected)
                self.assertTrue(DouyinIE.suitable(expected))

    def test_skip_unrelated_link_in_share_text(self):
        self.assertEqual(normalize_url("来源 https://example.org 分享 " + SAMPLE), SAMPLE)

    def test_reject_deceptive_or_malformed_links(self):
        for text in ("https://douyin.com.example.org/video/12", "https://x.com@evil.org/a",
                     "https://x.com:abc/a", "file:///local", "https://x.com:8443/a"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                resolve_link(text)


class NetworkTests(unittest.TestCase):
    def test_node_proxy_flag_does_not_hide_windows_proxy(self):
        with patch("network_settings.urllib.request.getproxies_environment", return_value={"node_use_env": "1"}), \
                patch("network_settings.urllib.request.getproxies_registry", return_value={"https": "http://127.0.0.1:7897"}):
            self.assertEqual(windows_system_proxy(), "http://127.0.0.1:7897")

    def test_explicit_network_proxy_keeps_priority(self):
        with patch("network_settings.urllib.request.getproxies_environment", return_value={"https": "http://127.0.0.1:8899"}):
            self.assertIsNone(windows_system_proxy())


class DouyinTests(unittest.TestCase):
    def test_feed_must_match_requested_video(self):
        data = {"aweme_list": [{"aweme_id": "111", "desc": "unrelated"},
                               {"aweme_id": "222", "desc": "requested"}]}
        self.assertEqual(find_requested_video(data, "222")["desc"], "requested")
        self.assertIsNone(find_requested_video(data, "333"))

    def test_gallery_response_also_requires_the_exact_requested_id(self):
        data = {"aweme_details": [{"aweme_id": "111"}, {"aweme_id": "222"}]}
        self.assertEqual(find_requested_video(data, "222")["aweme_id"], "222")
        self.assertIsNone(find_requested_video(data, "333"))

    def test_empty_or_invalid_response_is_not_a_video(self):
        for data in (None, {}, {"aweme_list": [None, "not-video"]}):
            self.assertIsNone(find_requested_video(data, "222"))

    def test_keep_hd_video_and_offer_better_audio_from_another_container(self):
        hd = {"format_id": "hevc-hd", "url": "https://example.org/hd.mp4", "vcodec": "h265",
              "acodec": "aac", "width": 720, "height": 960}
        avc = {"format_id": "avc-sd", "url": "https://example.org/sd.mp4", "vcodec": "h264",
               "acodec": "aac", "width": 576, "height": 768}
        info = {"formats": [hd, avc]}
        probes = [{"format": hd, "codec": "aac", "bitrate": 48000, "channels": 2, "sample_rate": 44100},
                  {"format": avc, "codec": "aac", "bitrate": 128000, "channels": 2, "sample_rate": 44100}]
        self.assertTrue(add_stream_choices(info, probes))
        video = next(f for f in info["formats"] if f["format_id"] == "hevc-hd-video")
        audio = next(f for f in info["formats"] if f["format_id"] == "avc-sd-audio")
        self.assertEqual((video["width"], video["height"], video["acodec"]), (720, 960, "none"))
        self.assertEqual((audio["vcodec"], audio["abr"]), ("none", 128))
        self.assertNotIn("height", audio)
        self.assertEqual(hd["acodec"], "aac", "Original container metadata must remain intact")

    def test_equal_audio_quality_needs_no_extra_download(self):
        fmt = {"format_id": "hd", "vcodec": "h265", "acodec": "aac"}
        probe = {"format": fmt, "codec": "aac", "bitrate": 128000, "channels": 2, "sample_rate": 44100}
        info = {"formats": [fmt]}
        self.assertFalse(add_stream_choices(info, [probe, dict(probe)]))
        self.assertEqual(len(info["formats"]), 1)


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.post = {"aweme_id": "123", "desc": "生日", "images": [
            {"width": 1440, "height": 1920, "url_list": ["https://example.org/1.jpg"]},
            {"width": 1440, "height": 1920, "url_list": ["https://example.org/2.jpg"],
             "clip_type": 3, "video": {"duration": 1880, "width": 720, "height": 960,
                                      "play_addr": {"url_list": ["https://example.org/live.mp4"]}}}],
            "music": {"title": "配乐", "duration": 284,
                      "play_url": {"uri": "https://example.org/music.m4a"}}}

    def test_album_keeps_images_live_video_and_original_music(self):
        info = gallery_info(self.post)
        self.assertEqual(info["image_count"], 2)
        self.assertNotIn("formats", info)
        self.assertEqual([a["kind"] for a in info["_douyin_gallery"]],
                         ["image", "image", "live_photo", "music"])
        self.assertAlmostEqual(info["_douyin_gallery"][2]["duration"], 1.88)
        self.assertEqual(info["_douyin_gallery"][-1]["urls"], ["https://example.org/music.m4a"])

    def test_nested_images_and_best_live_resolution(self):
        post = copy.deepcopy(self.post)
        post["image_post_info"] = {"image_list": post.pop("images")}
        video = post["image_post_info"]["image_list"][1]["video"]
        video["bit_rate"] = [{"bit_rate": 1000, "play_addr": {"width": 1080, "height": 1440,
                                         "url_list": ["https://example.org/live-hd.mp4"]}}]
        info = gallery_info(post)
        live = info["_douyin_gallery"][2]
        self.assertEqual((live["width"], live["height"]), (1080, 1440))
        self.assertEqual(live["urls"], ["https://example.org/live-hd.mp4"])

    def test_missing_photo_or_live_clip_cannot_report_a_complete_album(self):
        for key in ("url_list", "video"):
            post = copy.deepcopy(self.post)
            post["images"][1].pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                gallery_info(post)

    def test_music_unavailable_reports_the_site_reason(self):
        self.post["music"].update(play_url={}, offline_desc="当前地区不可用")
        with self.assertRaisesRegex(ValueError, "当前地区不可用"):
            gallery_info(self.post)

    def test_live_clip_can_be_silent_but_must_have_its_full_original_duration(self):
        asset = gallery_info(self.post)["_douyin_gallery"][2]
        probe = {"format": {"duration": "1.879"}, "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 720, "height": 960}]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "live.mp4"
            path.write_bytes(b"fixture")
            self.assertAlmostEqual(verify_asset(path, asset, probe)["duration"], 1.879)
            for duration in ("0.5", "nan", "inf"):
                probe["format"]["duration"] = duration
                with self.subTest(duration=duration), self.assertRaises(ValueError):
                    verify_asset(path, asset, probe)

    def test_reject_lower_resolution_gallery_asset(self):
        asset = gallery_info(self.post)["_douyin_gallery"][0]
        probe = {"streams": [{"codec_type": "video", "codec_name": "mjpeg", "width": 360, "height": 480}]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "photo.jpg"
            path.write_bytes(b"fixture")
            with self.assertRaises(ValueError):
                verify_asset(path, asset, probe)

    def test_gallery_direct_connection_keeps_explicit_proxy_preferences(self):
        with patch("douyin_gallery.windows_system_proxy", return_value="http://127.0.0.1:1234"):
            self.assertEqual(gallery_proxies(), {"all": None, "http": None, "https": None})
        with patch("douyin_gallery.windows_system_proxy", return_value=None):
            self.assertIsNone(gallery_proxies())

    def test_full_audio_does_not_hide_a_short_live_video(self):
        asset = gallery_info(self.post)["_douyin_gallery"][2]
        probe = {"format": {"duration": "1.879"}, "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 720, "height": 960, "duration": "0.5"}]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "clip.mp4"
            path.write_bytes(b"fixture")
            with self.assertRaises(ValueError):
                verify_asset(path, asset, probe)


class BrowserTests(unittest.TestCase):
    def test_site_scope_expiry_and_protected_cookies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "Cookies"
            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE meta(key TEXT, value TEXT)")
                db.execute("INSERT INTO meta VALUES('version','24')")
                db.execute("CREATE TABLE cookies(host_key TEXT,name TEXT,value TEXT,encrypted_value BLOB,path TEXT,expires_utc INTEGER,is_secure INTEGER)")
                future = int((time.time() + 3600 + 11_644_473_600) * 1_000_000)
                past = int((time.time() - 3600 + 11_644_473_600) * 1_000_000)
                db.executemany("INSERT INTO cookies VALUES(?,?,?,?,?,?,?)", [
                    (".bilibili.com", "SESSDATA", "test-login", b"", "/", future, 1),
                    (".bilibili.com", "expired", "old", b"", "/", past, 1),
                    (".example.org", "unrelated", "unrelated-secret", b"", "/", future, 1),
                    (".bilibili.com.example.org", "deceptive", "wrong-domain", b"", "/", future, 1),
                    (".x.com", "auth_token", "", b"v20protected-test", "/", future, 1),
                ])
            db.close()
            profile = BrowserProfile("chrome", "Chrome", root, root, database)
            with patch("browser_accounts.discover_profiles", return_value=[profile]):
                report, jars = scan_accounts()
            self.assertEqual(report[0]["status"], "partial")
            self.assertTrue(report[0]["sites"]["bilibili"]["login_found"])
            self.assertFalse(report[0]["sites"]["x"]["login_found"])
            jar, source = select_account("bilibili", report, jars)
            self.assertEqual([c.name for c in jar], ["SESSDATA"])
            self.assertEqual(source["id"], profile.source_id)
            self.assertNotIn("test-login", json.dumps(report))
            self.assertNotIn("unrelated-secret", json.dumps(report))

    def test_choose_signed_in_profile_without_mixing_accounts(self):
        login = session_cookie_jar([{"domain": ".bilibili.com", "name": "SESSDATA", "value": "account-one"}], "bilibili")
        visitor = session_cookie_jar([{"domain": ".bilibili.com", "name": "visitor", "value": "account-two"}], "bilibili")
        report = [
            {"id": "visitor", "sites": {"bilibili": {"cookies": 20, "login_found": False}}},
            {"id": "login", "sites": {"bilibili": {"cookies": 1, "login_found": True}}},
        ]
        jar, chosen = select_account("bilibili", report, {"visitor": visitor, "login": login})
        self.assertEqual(chosen["id"], "login")
        self.assertEqual([c.value for c in jar], ["account-one"])

    def test_web_session_only_reaches_its_own_platform(self):
        values = [{"domain": ".x.com", "name": "auth_token", "value": "x-test"},
                  {"domain": ".bilibili.com", "name": "SESSDATA", "value": "bili-test"}]
        self.assertEqual([c.value for c in session_cookie_jar(values, "x")], ["x-test"])


def check_ui(web_session=False, sample=SAMPLE, expected=295, min_width=1920, min_height=1080,
             min_audio_bitrate=0, timeout_seconds=300, gallery=False):
    # Offscreen rendering works on Windows without moving the user's mouse.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QProcess, QTimer, Qt
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication
    from app import DownloadWindow

    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([sys.argv[0]])
    # Qt's offscreen platform has no system font discovery on Windows.
    if os.name == "nt":
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("msyh.ttc", "msyhbd.ttc"):
            QFontDatabase.addApplicationFont(str(fonts / name))
    app.setFont(QFont("Microsoft YaHei UI", 12))
    window = DownloadWindow(restore_web_login=False)
    if web_session:
        from PySide6.QtNetwork import QNetworkCookie
        from web_login import WebLogin
        window.web_login = WebLogin(window, persistent=False)
        cookie = QNetworkCookie(b"qt_smoke_only", b"synthetic-not-an-account")
        cookie.setDomain(".bilibili.com")
        cookie.setPath("/")
        window.web_login.add_cookie(cookie)
    window.show()
    app.processEvents()
    site = resolve_link(sample)[1]
    if site.key == "bilibili":
        window.grab().save(str(ROOT / "preview-idle.png"))
    window.download.click()
    assert window.process is None, "Empty input should not start a download"
    for text, key in (("分享 https://v.douyin.com/ABC123/", "douyin"),
                      ("https://x.com/example/status/123/video/2", "x"), (SAMPLE, "bilibili")):
        window.url.setText(text)
        assert window.platform.key == key, window.platform_label.text()
    app.clipboard().setText(f"【分享视频】 {sample}")
    window.paste.click()
    assert sample in window.url.text(), "Paste button did not read the clipboard"

    errors = []
    completed = []
    timer = QTimer()

    def finish_check():
        if window.process is None or window.process.state() != QProcess.NotRunning:
            return
        timer.stop()
        try:
            assert window.result, window.status.text() + "\n" + window.logs.toPlainText()
            result = window.result
            assert result["platform"] == site.key, result
            if gallery:
                assert result["content_type"] == "gallery", result
                assert (result["image_count"], result["live_photo_count"], result["music_count"]) == (3, 1, 1), result
                assert len(result["assets"]) == 5, result
                assert Path(result["path"]).is_dir(), result
                for asset in result["assets"]:
                    assert asset["full_decode"] and Path(asset["path"]).is_file(), asset
                assert window.open_file.text() == "查看作品文件夹", window.open_file.text()
                assert "导出完成" in window.status.text(), window.status.text()
            else:
                assert abs(result["duration"] - expected) < max(1, expected * 0.01), result
                assert result["width"] >= min_width and result["height"] >= min_height, result
                assert result["audio_bitrate"] >= min_audio_bitrate, result
                assert result["video_codec"] and result["audio_codec"], result
                assert Path(result["path"]).is_file(), result
                assert window.open_file.text() == "播放视频", window.open_file.text()
            assert window.progress.value() == 100, "Completion progress is incorrect"
            assert window.open_file.isEnabled(), "Play button should be enabled"
            assert window.download.isEnabled(), "A second download should be possible"
            assert not window.cancel.isEnabled(), "Cancel should be disabled after completion"
            if web_session:
                assert "--session-stdin" in window.process.arguments(), "Web session was not sent over stdin"
                assert "synthetic-not-an-account" not in window.logs.toPlainText(), "Cookie value leaked into logs"
            suffix = site.key + ("-gallery" if gallery else "")
            window.grab().save(str(ROOT / f"preview-{suffix}.png"))
            if site.key == "bilibili":
                window.grab().save(str(ROOT / "preview.png"))
            window.advanced_toggle.setChecked(True)
            app.processEvents()
            if site.key == "bilibili":
                window.grab().save(str(ROOT / "preview-advanced.png"))
            report = {"passed": True, "status": window.status.text(),
                      "details": window.details.text(), "result": result}
            (ROOT / f"ui-smoke-{suffix}-result.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if site.key == "bilibili":
                (ROOT / "ui-smoke-result.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            completed.append(report)
        except Exception as exc:
            errors.append(str(exc))
        app.quit()

    def timeout():
        timer.stop()
        errors.append(f"Qt download timed out after {timeout_seconds} seconds: " + window.status.text())
        window.stop_process()
        app.quit()

    timer.timeout.connect(finish_check)
    window.download.click()
    timer.start(200)
    QTimer.singleShot(timeout_seconds * 1000, timeout)
    app.exec()
    window.close()
    if errors:
        raise RuntimeError("\n".join(errors))
    assert completed, "Qt application exited before the workflow completed"
    print(json.dumps(completed[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ui", action="store_true", help="Run real sample download through Qt (network required)")
    parser.add_argument("--web-session", action="store_true", help="Also exercise the private stdin cookie path with a synthetic visitor cookie")
    parser.add_argument("--url", default=SAMPLE)
    parser.add_argument("--duration", type=float, default=295)
    parser.add_argument("--min-width", type=int, default=1920)
    parser.add_argument("--min-height", type=int, default=1080)
    parser.add_argument("--min-audio-bitrate", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--gallery", action="store_true", help="Check the birthday photo/LivePhoto sample (3 photos, 1 clip and music)")
    args = parser.parse_args()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case)
                               for case in (IntegrityTests, PlatformTests, BrowserTests, NetworkTests, DouyinTests, GalleryTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
    if args.ui:
        check_ui(args.web_session, args.url, args.duration, args.min_width, args.min_height,
                 args.min_audio_bitrate, args.timeout, args.gallery)
