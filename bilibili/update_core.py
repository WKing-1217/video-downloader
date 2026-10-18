"""Public, credential-free GitHub update checks and verified installer downloads."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import threading
import time
from urllib.parse import urljoin, urlparse
import urllib.request

import requests

from app_version import APP_VERSION, REPOSITORY, UPDATE_URL
from network_settings import windows_system_proxy

MAX_MANIFEST = 128 * 1024
MAX_INSTALLER = 1024 ** 3


class UpdateError(Exception):
    retryable = False


class UpdateNetworkError(UpdateError):
    retryable = True


class UpdateCancelled(UpdateError):
    pass


def version_parts(text):
    if not isinstance(text, str) or not re.fullmatch(r"v?\d{1,4}\.\d{1,4}\.\d{1,4}", text):
        raise UpdateError("更新信息中的版本号无效。")
    return tuple(map(int, text.lstrip("v").split(".")))


def permitted_url(url, *, allow_loopback=False):
    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            return False
        if allow_loopback and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
            return True
        return (parsed.scheme == "https" and parsed.hostname == "github.com" and parsed.port is None
                and parsed.path.startswith(f"/{REPOSITORY}/releases/"))
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    sha256: str
    size: int
    notes: str
    available: bool
    release_url: str = ""


def parse_manifest(data, *, current_version=APP_VERSION, platform="windows", allow_loopback=False):
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("product") != "LocalVideoDownloader":
        raise UpdateError("更新信息不属于视频下载器。")
    platforms = data.get("platforms")
    entry = platforms.get(platform) if isinstance(platforms, dict) else None
    if not isinstance(entry, dict):
        raise UpdateError("更新信息缺少当前系统的安装包。")
    version = entry.get("version")
    newer = version_parts(version) > version_parts(current_version)
    url, sha, size = entry.get("url"), entry.get("sha256"), entry.get("size")
    if not permitted_url(url, allow_loopback=allow_loopback):
        raise UpdateError("更新包地址无效。")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
        raise UpdateError("更新包缺少有效校验值。")
    if type(size) is not int or not 0 < size <= MAX_INSTALLER:
        raise UpdateError("更新包大小无效。")
    notes = data.get("notes", "")
    return UpdateInfo(version.lstrip("v"), url, sha.lower(), size,
                      notes[:4000] if isinstance(notes, str) else "", newer)


def parse_release(data, *, current_version=APP_VERSION, platform="windows", allow_loopback=False):
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        raise UpdateError("未找到可用的正式发布版本。")
    version = str(data.get("tag_name") or "")
    newer = version_parts(version) > version_parts(current_version)
    name = "VideoDownloader-Windows-Setup.exe" if platform == "windows" else "VideoDownloader-Android.apk"
    asset = next((item for item in data.get("assets", []) if item.get("name") == name), None)
    if not asset:
        raise UpdateError("最新发布尚未提供当前系统的安装包。")
    url = asset.get("browser_download_url")
    if not permitted_url(url, allow_loopback=allow_loopback):
        raise UpdateError("GitHub 安装包地址与项目配置不符。")
    digest = asset.get("digest") or ""
    if digest and not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise UpdateError("GitHub 提供的安装包校验值无效。")
    size = asset.get("size", 0)
    if type(size) is not int or not 0 <= size <= MAX_INSTALLER:
        raise UpdateError("GitHub 安装包大小无效。")
    notes = data.get("body") or "此版本未提供更新说明。"
    return UpdateInfo(version.lstrip("v"), url, digest[7:].lower(), size,
                      str(notes)[:64000], newer, f"https://github.com/{REPOSITORY}/releases/tag/{version}")


class UpdateClient:
    def __init__(self, *, manifest_url=UPDATE_URL, api_url=None, allow_loopback=False, cancelled=None):
        self.manifest_url = manifest_url
        self.api_url = api_url or (f"https://api.github.com/repos/{REPOSITORY}/releases/latest" if manifest_url == UPDATE_URL else None)
        self.allow_loopback = allow_loopback
        self.cancelled = cancelled or threading.Event()
        self.sessions = []
        self.session_lock = threading.Lock()
        self.local = threading.local()
        self.proxies = {}
        proxy = windows_system_proxy()
        environment = urllib.request.getproxies_environment()
        for scheme in ("http", "https"):
            route = environment.get(scheme) or environment.get("all") or proxy
            if route:
                self.proxies[scheme] = route
        self.session = self._new_session()

    def _new_session(self):
        session = requests.Session()
        session.trust_env = False
        session.headers.update({"User-Agent": f"VideoDownloader/{APP_VERSION}", "Cache-Control": "no-cache"})
        session.proxies.update(self.proxies)
        with self.session_lock:
            self.sessions.append(session)
        return session

    def close(self):
        for session in self.sessions:
            session.close()

    def _request(self, url, headers=None):
        api = urlparse(url)
        official_api = (api.scheme == "https" and api.hostname == "api.github.com" and api.port is None
                        and not api.username and not api.password and api.path.startswith(f"/repos/{REPOSITORY}/releases"))
        if not official_api and not permitted_url(url, allow_loopback=self.allow_loopback):
            raise UpdateError("更新来源地址无效。")
        self._cancel()
        if not hasattr(self.local, "session"):
            self.local.session = self._new_session()
        deadline = time.monotonic() + 30
        try:
            for hop in range(6):
                parsed = urlparse(url)
                local = self.allow_loopback and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
                    raise UpdateError("更新连接未使用 HTTPS。")
                self._cancel()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise UpdateNetworkError("连接 GitHub 超时，可重试或打开官方 Releases。")
                response = self.local.session.get(url, params={"t": int(time.time())} if hop == 0 else None,
                                            headers=headers, stream=True, timeout=(min(5, remaining), min(8, remaining)), allow_redirects=False,
                                            proxies={"http": None, "https": None, "all": None} if local else None)
                if response.is_redirect:
                    url = urljoin(response.url, response.headers["Location"])
                    response.close()
                    continue
                try:
                    response.raise_for_status()
                except requests.RequestException:
                    response.close()
                    raise
                return response
            raise UpdateError("更新连接重定向次数过多。")
        except requests.Timeout as error:
            raise UpdateNetworkError("连接 GitHub 超时，请检查网络或使用官方 Releases 下载。") from error
        except requests.exceptions.ProxyError as error:
            raise UpdateNetworkError("系统代理连接失败，请检查代理设置后重试。") from error
        except requests.HTTPError as error:
            code = error.response.status_code if error.response is not None else 0
            message = "GitHub 暂时限制请求，请稍后重试。" if code in {403, 429} else f"GitHub 返回 HTTP {code}，请稍后重试。"
            raise UpdateNetworkError(message) from error
        except requests.RequestException as error:
            raise UpdateNetworkError("无法连接 GitHub，请检查网络、系统代理或打开官方 Releases。") from error

    def _cancel(self):
        if self.cancelled.is_set():
            raise UpdateCancelled("已取消更新。")

    def _json(self, url, limit=MAX_MANIFEST):
        import json
        body = bytearray()
        try:
            with self._request(url) as response:
                for chunk in response.iter_content(8192):
                    self._cancel()
                    body.extend(chunk)
                    if len(body) > limit:
                        raise UpdateError("更新信息过大。")
            return json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeError, requests.RequestException) as error:
            raise UpdateError("未能读取有效更新信息，请稍后重试。") from error
    def check(self, *, current_version=APP_VERSION, platform="windows"):
        api_error = None
        if self.api_url:
            try:
                info = parse_release(self._json(self.api_url, 512 * 1024), current_version=current_version,
                                     platform=platform, allow_loopback=self.allow_loopback)
                if not info.sha256:
                    try:
                        fallback = parse_manifest(self._json(self.manifest_url), current_version=current_version,
                                                  platform=platform, allow_loopback=self.allow_loopback)
                        if fallback.version == info.version and fallback.url == info.url:
                            from dataclasses import replace
                            info = replace(info, sha256=fallback.sha256, size=info.size or fallback.size)
                    except UpdateError:
                        pass
                return info
            except UpdateError as error:
                api_error = error
        try:
            return parse_manifest(self._json(self.manifest_url), current_version=current_version,
                                  platform=platform, allow_loopback=self.allow_loopback)
        except UpdateError as error:
            if api_error:
                raise UpdateError(str(api_error) + "\n备用更新清单也未能读取，请重试。") from error
            raise

    def download(self, info, folder, progress=None, stage=None):
        if not info.available:
            raise UpdateError("当前已经是最新版本。")
        from update_transfer import transfer
        return transfer(self, info, folder, progress, stage)
