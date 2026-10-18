"""Read only supported-site cookies from the current Windows user's browsers.

Cookie values stay in memory. Scan reports contain browser names and status only.
Chromium App-Bound cookies are reported as protected; no security settings change.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
from http.cookiejar import Cookie
import os
from pathlib import Path
import sqlite3
import time

from yt_dlp import cookies as ytdlp_cookies
from platform_links import PLATFORMS, domain_matches


@dataclass(frozen=True)
class BrowserProfile:
    browser: str
    name: str
    path: Path
    root: Path
    database: Path

    @property
    def source_id(self):
        return f"{self.browser}:{self.path}"

    @property
    def label(self):
        return f"{self.name} · {self.path.name}"


class QuietLogger:
    # Never forward the cookie library's diagnostics or data into the UI log.
    def debug(self, *args, **kwargs):
        pass

    info = warning = error = debug


def discover_profiles() -> list[BrowserProfile]:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    locations = (
        ("chrome", "Chrome", local / "Google/Chrome/User Data"),
        ("edge", "Edge", local / "Microsoft/Edge/User Data"),
        ("brave", "Brave", local / "BraveSoftware/Brave-Browser/User Data"),
        ("chromium", "Chromium", local / "Chromium/User Data"),
        ("vivaldi", "Vivaldi", local / "Vivaldi/User Data"),
        ("opera", "Opera", roaming / "Opera Software/Opera Stable"),
        ("firefox", "Firefox", roaming / "Mozilla/Firefox/Profiles"),
    )
    profiles = []
    for browser, name, root in locations:
        if not root.is_dir():
            continue
        try:
            folders = [root, *sorted(p for p in root.iterdir() if p.is_dir())]
            for folder in folders:
                candidates = ((folder / "cookies.sqlite",) if browser == "firefox" else
                              (folder / "Network/Cookies", folder / "Cookies"))
                database = next((p for p in candidates if p.is_file()), None)
                if database:
                    profiles.append(BrowserProfile(browser, name, folder, root, database))
        except OSError:
            continue
    return profiles


def _read_profile(profile: BrowserProfile, platform_key: str | None):
    jar = ytdlp_cookies.YoutubeDLCookieJar()
    sites = [PLATFORMS[platform_key]] if platform_key else list(PLATFORMS.values())
    roots = tuple(root for site in sites for root in site.cookie_domains)
    # Filter in SQL before fetching/decrypting values: unrelated accounts are not read.
    host_column = "host" if profile.browser == "firefox" else "host_key"
    table = "moz_cookies" if profile.browser == "firefox" else "cookies"
    where = " OR ".join(f"({host_column} = ? OR {host_column} = ? OR {host_column} LIKE ?)" for _ in roots)
    parameters = tuple(value for root in roots for value in (root, "." + root, "%." + root))
    blocked = failed = 0
    # SQLite's read-only connection sees committed WAL records without copying or
    # modifying the browser database. An actual read lock is reported to the user.
    with closing(sqlite3.connect(profile.database.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
        if profile.browser == "firefox":
            schema = db.execute("PRAGMA user_version").fetchone()[0]
            columns = {row[1] for row in db.execute("PRAGMA table_info(moz_cookies)")}
            containers = " AND NOT INSTR(originAttributes, 'userContextId=')" if "originAttributes" in columns else ""
            rows = db.execute(f"SELECT host,name,value,path,expiry,isSecure FROM {table} WHERE ({where}){containers}", parameters)
            for host, name, value, path, expiry, secure in rows:
                if schema >= 16 and expiry:
                    expiry /= 1000
                jar.set_cookie(Cookie(0, name, value, None, False, host, True,
                                      host.startswith("."), path, True, bool(secure),
                                      expiry or None, not expiry, None, None, {}))
        else:
            version = int(db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
            columns = {row[1] for row in db.execute("PRAGMA table_info(cookies)")}
            secure = "is_secure" if "is_secure" in columns else "secure"
            rows = db.execute(f"SELECT host_key,name,value,encrypted_value,path,expires_utc,{secure} FROM cookies WHERE {where}", parameters).fetchall()
            decryptor = None
            for host, name, value, encrypted, path, expiry, secure in rows:
                if expiry and expiry / 1_000_000 - 11_644_473_600 <= time.time():
                    continue
                if not value and encrypted:
                    if encrypted.startswith(b"v20"):
                        blocked += 1
                        continue
                    try:
                        if decryptor is None:
                            decryptor = ytdlp_cookies.get_cookie_decryptor(
                                str(profile.root), profile.name, QuietLogger(), meta_version=version)
                        value = decryptor.decrypt(encrypted)
                    except Exception:
                        failed += 1
                        continue
                    if not value:
                        failed += 1
                        continue
                jar.set_cookie(Cookie(0, name, value, None, False, host, True,
                                      host.startswith("."), path, True, bool(secure),
                                      expiry / 1_000_000 - 11_644_473_600 if expiry else None,
                                      not expiry, None, None, {}))
    jar.clear_expired_cookies()
    return jar, blocked, failed


def cookie_summary(jar):
    summary = {}
    for key, site in PLATFORMS.items():
        matching = [c for c in jar if c.value and not c.is_expired() and domain_matches(c.domain, site.cookie_domains)]
        names = {c.name for c in matching}
        summary[key] = {"cookies": len(matching), "login_found": bool(names.intersection(site.login_cookies))}
    return summary


def scan_accounts(platform_key=None, source_id=None, on_progress=None):
    """Return a public report plus private in-memory jars, keyed by source ID."""
    profiles = discover_profiles()
    if source_id:
        profiles = [p for p in profiles if p.source_id == source_id]
    report, jars = [], {}
    for index, profile in enumerate(profiles, 1):
        if on_progress:
            on_progress(f"正在扫描 {profile.label}（{index}/{len(profiles)}）")
        item = {"id": profile.source_id, "label": profile.label, "browser": profile.browser}
        try:
            jar, blocked, failed = _read_profile(profile, platform_key)
            summary = cookie_summary(jar)
            item["sites"] = {platform_key: summary[platform_key]} if platform_key else summary
            useful = any(s["cookies"] for s in item["sites"].values())
            if useful:
                jars[profile.source_id] = jar
            item["status"] = "partial" if useful and (blocked or failed) else "ready" if useful else "protected" if blocked or failed else "empty"
            if blocked or failed:
                item["message"] = "部分登录信息受 Windows 加密保护，无法直接读取。" if useful else "登录信息受 Windows 加密保护，无法直接读取；可点「网页登录」或用 Firefox 登录后扫描。"
            else:
                item["message"] = "已读取可用信息" if useful else "未找到这三个平台的有效登录信息"
        except PermissionError:
            item.update(status="locked", message="浏览器占用或权限限制，请完全退出该浏览器后重新扫描。", sites={})
        except sqlite3.OperationalError:
            item.update(status="locked", message="登录文件正被浏览器占用或无法打开，请完全退出该浏览器后重新扫描。", sites={})
        except (OSError, sqlite3.Error, ValueError, AttributeError):
            item.update(status="unreadable", message="浏览器配置无法读取，请更新下载引擎后重试。", sites={})
        report.append(item)
    return report, jars


def select_account(platform_key, report, jars):
    """Prefer a signed-in profile, never combine cookies from different accounts."""
    candidates = [item for item in report if item["id"] in jars
                  and item.get("sites", {}).get(platform_key, {}).get("cookies")]
    if not candidates:
        return ytdlp_cookies.YoutubeDLCookieJar(), None
    # Number of site cookies breaks ties without exposing identity or secret values.
    chosen = max(candidates, key=lambda item: (
        item["sites"][platform_key]["login_found"], item["sites"][platform_key]["cookies"]))
    site = PLATFORMS[platform_key]
    jar = ytdlp_cookies.YoutubeDLCookieJar()
    for cookie in jars[chosen["id"]]:
        if domain_matches(cookie.domain, site.cookie_domains):
            jar.set_cookie(cookie)
    return jar, chosen


def session_cookie_jar(values, platform_key):
    """Accept a site-scoped cookie snapshot sent privately over process stdin."""
    jar = ytdlp_cookies.YoutubeDLCookieJar()
    site = PLATFORMS[platform_key]
    for item in values:
        domain = str(item.get("domain", ""))
        if not domain_matches(domain, site.cookie_domains):
            continue
        expiry = item.get("expires") or None
        jar.set_cookie(Cookie(0, str(item["name"]), str(item["value"]), None, False,
                              domain, True, domain.startswith("."), item.get("path") or "/",
                              True, bool(item.get("secure")), expiry, not expiry, None, None, {}))
    jar.clear_expired_cookies()
    return jar
