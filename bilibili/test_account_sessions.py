"""Manual web login remains usable when automatic browser scanning is disabled."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from download_service import AccountService
from platform_links import PLATFORMS


class AccountSessionTests(unittest.TestCase):
    def service(self, *, automatic=True, source="", snapshots=None):
        web = None
        if snapshots is not None:
            web = SimpleNamespace(
                for_platform=Mock(side_effect=lambda key: snapshots.get(key, [])),
                profile=SimpleNamespace(httpUserAgent=Mock(return_value="Synthetic browser agent")))
        return SimpleNamespace(auto_login=automatic, source_id=source, web=web)

    def cookie(self, site="instagram"):
        return {"domain": "." + site + ".com", "name": "sessionid",
                "value": "synthetic-test-session", "path": "/"}

    def test_manual_web_login_is_passed_when_automatic_browser_scan_is_disabled(self):
        cookies = [self.cookie()]
        accounts = self.service(automatic=False, snapshots={"instagram": cookies})
        arguments, payload = AccountService.arguments(accounts, PLATFORMS["instagram"])
        self.assertEqual(arguments, ["--no-browser-cookies", "--session-stdin"])
        self.assertEqual(payload, {"cookies": cookies, "user_agent": "Synthetic browser agent"})
        accounts.web.for_platform.assert_called_once_with("instagram")
        accounts.web.profile.httpUserAgent.assert_called_once_with()

    def test_disabled_browser_scan_does_not_use_a_saved_browser_selection(self):
        cookies = [self.cookie()]
        accounts = self.service(automatic=False, source="chrome:synthetic-profile",
                                snapshots={"instagram": cookies})
        arguments, payload = AccountService.arguments(accounts, PLATFORMS["instagram"])
        self.assertEqual(arguments, ["--no-browser-cookies", "--session-stdin"])
        self.assertEqual(payload["cookies"], cookies)

    def test_disabled_browser_scan_without_web_profile_keeps_public_access(self):
        accounts = self.service(automatic=False, source="chrome:synthetic-profile")
        self.assertEqual(AccountService.arguments(accounts, PLATFORMS["instagram"]),
                         (["--no-browser-cookies"], None))

    def test_disabled_browser_scan_without_site_cookies_does_not_send_empty_session(self):
        accounts = self.service(automatic=False, snapshots={"instagram": []})
        self.assertEqual(AccountService.arguments(accounts, PLATFORMS["instagram"]),
                         (["--no-browser-cookies"], None))
        accounts.web.for_platform.assert_called_once_with("instagram")
        accounts.web.profile.httpUserAgent.assert_not_called()

    def test_explicit_browser_selection_retains_precedence_when_scan_is_enabled(self):
        accounts = self.service(source="firefox:synthetic-profile",
                                snapshots={"instagram": [self.cookie()]})
        self.assertEqual(AccountService.arguments(accounts, PLATFORMS["instagram"]),
                         (["--browser-source", "firefox:synthetic-profile"], None))
        accounts.web.profile.httpUserAgent.assert_not_called()

    def test_automatic_login_passes_embedded_session_with_its_user_agent(self):
        cookies = [self.cookie()]
        accounts = self.service(snapshots={"instagram": cookies})
        self.assertEqual(AccountService.arguments(accounts, PLATFORMS["instagram"]),
                         (["--session-stdin"], {"cookies": cookies,
                                                "user_agent": "Synthetic browser agent"}))
        accounts.web.for_platform.assert_called_once_with("instagram")

    def test_session_request_stays_scoped_to_requested_platform(self):
        for automatic in (False, True):
            for key in ("instagram", "youtube", "douyin"):
                with self.subTest(automatic=automatic, platform=key):
                    cookies = [self.cookie(key)]
                    accounts = self.service(automatic=automatic, snapshots={key: cookies})
                    arguments, payload = AccountService.arguments(accounts, PLATFORMS[key])
                    accounts.web.for_platform.assert_called_once_with(key)
                    self.assertEqual(payload["cookies"], cookies)
                    self.assertIn("--session-stdin", arguments)
                    self.assertEqual("--no-browser-cookies" in arguments, not automatic)

    def test_another_platform_session_is_not_sent_as_instagram_login(self):
        for automatic in (False, True):
            with self.subTest(automatic=automatic):
                accounts = self.service(automatic=automatic,
                                        snapshots={"youtube": [self.cookie("youtube")]})
                expected = [] if automatic else ["--no-browser-cookies"]
                self.assertEqual(AccountService.arguments(accounts, PLATFORMS["instagram"]),
                                 (expected, None))
                accounts.web.for_platform.assert_called_once_with("instagram")
                accounts.web.profile.httpUserAgent.assert_not_called()

    def test_automatic_login_without_embedded_cookies_falls_back_to_browser_scan(self):
        for snapshots in (None, {}):
            with self.subTest(web_profile=snapshots is not None):
                accounts = self.service(snapshots=snapshots)
                self.assertEqual(AccountService.arguments(accounts, PLATFORMS["instagram"]),
                                 ([], None))


if __name__ == "__main__":
    unittest.main()
