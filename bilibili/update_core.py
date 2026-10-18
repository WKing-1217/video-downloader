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
    pass


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


class UpdateClient:
    def __init__(self, *, manifest_url=UPDATE_URL, allow_loopback=False, cancelled=None):
        self.manifest_url = manifest_url
        self.allow_loopback = allow_loopback
        self.cancelled = cancelled or threading.Event()
        self.session = requests.Session()
        self.session.trust_env = False  # Public updates must not load .netrc credentials.
        self.session.headers.update({"User-Agent": f"VideoDownloader/{APP_VERSION}", "Cache-Control": "no-cache"})
        proxy = windows_system_proxy()
        environment = urllib.request.getproxies_environment()
        for scheme in ("http", "https"):
            route = environment.get(scheme) or environment.get("all") or proxy
            if route:
                self.session.proxies[scheme] = route

    def close(self):
        self.session.close()

    def _request(self, url):
        if not permitted_url(url, allow_loopback=self.allow_loopback):
            raise UpdateError("更新来源地址无效。")
        self._cancel()
        try:
            for hop in range(6):
                parsed = urlparse(url)
                local = self.allow_loopback and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
                    raise UpdateError("更新连接未使用 HTTPS。")
                self._cancel()
                response = self.session.get(url, params={"t": int(time.time())} if hop == 0 else None,
                                            stream=True, timeout=(5, 3), allow_redirects=False,
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
        except requests.RequestException as error:
            raise UpdateError("暂时无法连接 GitHub，请检查网络后重试。") from error

    def _cancel(self):
        if self.cancelled.is_set():
            raise UpdateCancelled("已取消更新。")

    def check(self, *, current_version=APP_VERSION, platform="windows"):
        import json
        body = bytearray()
        try:
            with self._request(self.manifest_url) as response:
                for chunk in response.iter_content(8192):
                    self._cancel()
                    body.extend(chunk)
                    if len(body) > MAX_MANIFEST:
                        raise UpdateError("更新信息过大。")
            data = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeError, requests.RequestException) as error:
            raise UpdateError("未能读取有效更新信息，请稍后重试。") from error
        return parse_manifest(data, current_version=current_version, platform=platform,
                              allow_loopback=self.allow_loopback)

    def download(self, info, folder, progress=None):
        if not info.available:
            raise UpdateError("当前已经是最新版本。")
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "VideoDownloader-Update.exe"
        part = target.with_suffix(".exe.part")
        digest = hashlib.sha256()
        count = 0
        try:
            with self._request(info.url) as response, part.open("wb") as output:
                length = response.headers.get("Content-Length")
                if length and int(length) != info.size:
                    raise UpdateError("更新包大小与发布信息不一致，请稍后重试。")
                for chunk in response.iter_content(65536):
                    self._cancel()
                    count += len(chunk)
                    if count > info.size:
                        raise UpdateError("更新包超出了发布信息中的大小。")
                    output.write(chunk)
                    digest.update(chunk)
                    if progress:
                        progress(count, info.size)
            if count != info.size or digest.hexdigest() != info.sha256:
                raise UpdateError("更新包校验失败，未运行安装程序。请重新检查更新。")
            part.replace(target)
            return target
        except (OSError, ValueError, requests.RequestException) as error:
            raise UpdateError("更新包下载未完成，请重试。") from error
        finally:
            if part.exists():
                part.unlink()
