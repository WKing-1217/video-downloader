"""Bounded HTTP range downloads with contiguous, native-compatible resume files."""
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
import re
import threading
import time

import yt_dlp
from yt_dlp.downloader import get_suitable_downloader
from yt_dlp.downloader.http import HttpFD
from yt_dlp.networking import Request
from yt_dlp.networking.exceptions import HTTPError, TransportError
from yt_dlp.utils.networking import HTTPHeaderDict

CONNECTIONS = 8
CHUNK = 2 * 1024 * 1024
MIN_SIZE = 4 * 1024 * 1024


class RangeUnavailable(Exception):
    """The server cannot safely provide independent pieces of this resource."""


def content_range(value):
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", value or "")
    if not match:
        raise RangeUnavailable("Missing or invalid Content-Range")
    start, end, total = map(int, match.groups())
    if not 0 <= start <= end < total:
        raise RangeUnavailable("Invalid range boundaries")
    return start, end, total


class ParallelHttpFD(HttpFD):
    def real_download(self, filename, info_dict):
        urls = list(dict.fromkeys([info_dict["url"], *info_dict.get("_backup_urls", [])]))
        for index, url in enumerate(urls):
            try:
                return self._parallel_download(filename, {**info_dict, "url": url})
            except (RangeUnavailable, HTTPError, TransportError, TimeoutError):
                if index + 1 < len(urls):
                    self.to_screen("[download] 当前下载节点返回异常，正在切换同画质、同音质的备用节点。")
        # Only a verified contiguous prefix is ever stored in .part, so the
        # standard downloader can continue after range/connection failures.
        self.to_screen("[download] 多连接暂不可用，已切换到兼容下载并保留已完成数据。")
        return super().real_download(filename, info_dict)

    def _parallel_download(self, filename, info_dict):
        headers = HTTPHeaderDict(info_dict.get("http_headers") or {})
        headers["Accept-Encoding"] = "identity"
        url = info_dict["url"]
        probe_headers = HTTPHeaderDict(headers)
        probe_headers["Range"] = "bytes=0-0"
        with self.ydl.urlopen(Request(url, headers=probe_headers, extensions={"timeout": 10})) as response:
            start, end, total = content_range(response.headers.get("Content-Range"))
            if response.status != 206 or (start, end) != (0, 0):
                raise RangeUnavailable("Range request was not honored")
            if len(response.read(2)) != 1:
                raise RangeUnavailable("Invalid probe body")
            validator = response.headers.get("ETag")
            if not validator or validator.startswith("W/"):
                validator = response.headers.get("Last-Modified")
        if total < MIN_SIZE:
            raise RangeUnavailable("Small file uses the native downloader")
        if getattr(self, "_expected_total", total) != total:
            raise RangeUnavailable("Backup node has a different resource length")
        self._expected_total = total

        part = Path(self.temp_name(filename))
        resume = part.stat().st_size if part.is_file() and self.params.get("continuedl", True) else 0
        if resume > total:
            resume = 0  # A stale oversized prefix cannot belong to this file.
        if validator:
            headers["If-Range"] = validator
        self.report_destination(filename)
        self.to_screen(f"[download] 已启用 {CONNECTIONS} 连接分段下载，支持断点续传。")
        lock = threading.Lock()
        stop = threading.Event()
        active = {}
        finished_bytes = resume
        begin = time.monotonic()
        samples = deque([(begin, resume)], maxlen=12)

        def fetch(offset, last):
            request_headers = HTTPHeaderDict(headers)
            request_headers["Range"] = f"bytes={offset}-{last}"
            for attempt in range(3):
                if stop.is_set():
                    return b""
                with lock:
                    active[offset] = 0
                try:
                    with self.ydl.urlopen(Request(url, headers=request_headers, extensions={"timeout": 10})) as response:
                        actual = content_range(response.headers.get("Content-Range"))
                        if response.status != 206 or actual != (offset, last, total):
                            raise RangeUnavailable("Response does not match the requested piece")
                        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                            raise RangeUnavailable("Encoded range response")
                        expected = last - offset + 1
                        chunks = []
                        length = 0
                        while length < expected:
                            if stop.is_set():
                                return b""
                            data = response.read(min(65536, expected - length))
                            if not data:
                                raise RangeUnavailable("Truncated range response")
                            chunks.append(data)
                            length += len(data)
                            with lock:
                                active[offset] = length
                        # An oversized response is unsafe even when its range
                        # header was plausible. Never append it to a resume file.
                        if response.read(1):
                            raise RangeUnavailable("Oversized range response")
                        return b"".join(chunks)
                except (HTTPError, TransportError, TimeoutError):
                    if attempt == 2:
                        raise
            raise RangeUnavailable("Incomplete range")

        def progress():
            now = time.monotonic()
            with lock:
                current = finished_bytes + sum(active.values())
            # Discard a speed window after a retry resets a partially read piece.
            if current < samples[-1][1]:
                samples.clear()
                samples.append((now, current))
            elapsed = now - samples[0][0]
            speed = (current - samples[0][1]) / elapsed if elapsed > 0 else 0
            samples.append((now, current))
            self._hook_progress({"status": "downloading", "filename": filename,
                                 "tmpfilename": str(part), "downloaded_bytes": current,
                                 "total_bytes": total, "elapsed": now - begin,
                                 "speed": speed, "eta": (total - current) / speed if speed > 0 else None}, info_dict)

        if resume:
            # Existing prefixes can come from older app versions or another
            # CDN node. Check their beginning and end before appending new data.
            spans = [(0, min(resume, 65536) - 1)]
            if resume > 65536:
                spans.append((resume - 65536, resume - 1))
            with part.open("rb") as existing:
                for offset, last in spans:
                    existing.seek(offset)
                    if existing.read(last - offset + 1) != fetch(offset, last):
                        resume = finished_bytes = 0
                        samples.clear()
                        samples.append((time.monotonic(), 0))
                        self.to_screen("[download] 旧断点内容与原始文件不一致，正在重新下载这一轨。")
                        break
            active.clear()

        # Each batch contains at most 16 MiB. Files on disk contain no holes or
        # unverified/out-of-order bytes, including when the app is cancelled.
        with part.open("ab" if resume else "wb") as output:
            with ThreadPoolExecutor(max_workers=CONNECTIONS, thread_name_prefix="media-range") as pool:
                try:
                    cursor = resume
                    while cursor < total:
                        pieces = [(offset, min(offset + CHUNK, total) - 1)
                                  for offset in range(cursor, min(cursor + CONNECTIONS * CHUNK, total), CHUNK)]
                        futures = {offset: pool.submit(fetch, offset, last) for offset, last in pieces}
                        pending = set(futures.values())
                        while pending:
                            done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                            for future in done:
                                future.result()
                            progress()
                        for offset, last in pieces:
                            data = futures[offset].result()
                            if len(data) != last - offset + 1:
                                raise RangeUnavailable("Incomplete piece")
                            output.write(data)
                            with lock:
                                active.pop(offset, None)
                                finished_bytes += len(data)
                        output.flush()
                        cursor = finished_bytes
                finally:
                    stop.set()
        if part.stat().st_size != total:
            raise RangeUnavailable("Incorrect final file length")
        self.try_rename(str(part), filename)
        if part.exists() or not Path(filename).is_file():
            return False
        self._hook_progress({"status": "finished", "filename": filename,
                             "downloaded_bytes": total, "total_bytes": total,
                             "elapsed": time.monotonic() - begin}, info_dict)
        return True


class AcceleratedYoutubeDL(yt_dlp.YoutubeDL):
    def dl(self, name, info, subtitle=False, test=False):
        # Manifest downloads keep yt-dlp's native concurrent fragment engine.
        # Range headers, POSTs, impersonation and stream/stdout outputs also keep
        # their original behavior rather than being silently reinterpreted.
        eligible = (not subtitle and not test and isinstance(name, str) and name != "-"
                    and info.get("request_data") is None and not info.get("impersonate")
                    and not info.get("is_live") and not self.params.get("nopart")
                    and not HTTPHeaderDict(info.get("http_headers") or {}).get("Range")
                    and get_suitable_downloader(info, self.params) is HttpFD
                    and info.get("url", "").startswith(("https://", "http://")))
        if not eligible:
            return super().dl(name, info, subtitle=subtitle, test=test)
        data = self._copy_infodict(info)
        if data.get("http_headers") is None:
            data["http_headers"] = self._calc_headers(data)
        downloader = ParallelHttpFD(self, self.params)
        for hook in self._progress_hooks:
            downloader.add_progress_hook(hook)
        return downloader.download(name, data, subtitle)
