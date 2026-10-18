"""Verified update downloads: bounded ranges, real byte progress and safe resume."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time

import requests

BLOCK = 2 * 1024 * 1024
CONNECTIONS = 4


class RangeUnavailable(Exception):
    pass


def parse_range(value):
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", value or "")
    if not match:
        raise RangeUnavailable("服务器未返回有效的数据范围。")
    start, end, total = map(int, match.groups())
    if not 0 <= start <= end < total:
        raise RangeUnavailable("服务器返回的数据范围不正确。")
    return start, end, total


def transfer(client, info, folder, progress=None, stage=None):
    from update_core import MAX_INSTALLER, UpdateCancelled, UpdateError
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "VideoDownloader-Update.exe"
    part = folder / "VideoDownloader-Update.exe.part"
    meta = folder / "VideoDownloader-Update.resume.json"
    emit = progress or (lambda *_: None)
    tell = stage or (lambda *_: None)

    def verified(path):
        if not path.is_file() or not path.stat().st_size:
            return False
        if info.size and path.stat().st_size != info.size:
            return False
        if info.sha256:
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest() == info.sha256
        return False

    client._cancel()
    if verified(target):
        emit(target.stat().st_size, target.stat().st_size)
        tell("已复用通过校验的更新包。")
        return target
    ranged = False
    complete = False
    invalid = False
    total = info.size
    validator = ""
    try:
        if not total or total >= 4 * 1024 * 1024:
            tell("正在连接 GitHub 安装包…")
            try:
                with client._request(info.url, headers={"Range": "bytes=0-0", "Accept-Encoding": "identity"}) as response:
                    if response.status_code == 206:
                        start, end, discovered = parse_range(response.headers.get("Content-Range"))
                        if (start, end) != (0, 0) or len(response.raw.read(2)) != 1:
                            raise RangeUnavailable("范围检测响应不正确。")
                        if info.size and info.size != discovered:
                            raise UpdateError("更新包大小与发布信息不一致。")
                        total = discovered
                        if total > MAX_INSTALLER:
                            raise UpdateError("更新包超出允许的大小。")
                        validator = response.headers.get("ETag") or response.headers.get("Last-Modified") or ""
                        ranged = total >= 4 * 1024 * 1024 and bool(info.sha256)
            except RangeUnavailable:
                ranged = False
        identity = {"version": info.version, "url": info.url, "sha256": info.sha256, "size": total, "validator": validator}
        resume = 0
        if ranged and part.is_file() and meta.is_file():
            try:
                previous = json.loads(meta.read_text(encoding="utf-8"))
                if previous == identity and 0 < part.stat().st_size <= total:
                    resume = part.stat().st_size
            except (OSError, ValueError):
                pass
        if not resume:
            part.unlink(missing_ok=True)
        if ranged:
            meta.write_text(json.dumps(identity), encoding="utf-8")
            tell("正在续传更新包…" if resume else "正在下载更新包…")
            try:
                range_transfer(client, info.url, part, total, resume, validator, emit)
            except RangeUnavailable:
                # Invalid range responses never get appended to the prefix.
                ranged = False
                part.unlink(missing_ok=True)
                meta.unlink(missing_ok=True)
                tell("服务器不支持可靠的分段传输，正在使用兼容下载。")
                stream_transfer(client, info, part, emit)
        else:
            tell("正在下载更新包…")
            stream_transfer(client, info, part, emit)
        client._cancel()
        tell("下载完成，正在校验安装包…")
        count = part.stat().st_size
        if count <= 0 or (total and count != total):
            invalid = True
            raise UpdateError("更新包大小校验失败，请重试。")
        with part.open("rb") as stream:
            magic = stream.read(2)
            stream.seek(0)
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if magic != b"MZ" or (info.sha256 and digest != info.sha256):
            invalid = True
            raise UpdateError("更新包 SHA-256 或文件格式校验失败，未执行安装。")
        client._cancel()
        part.replace(target)
        complete = True
        emit(count, total or count)
        return target
    except UpdateCancelled:
        invalid = True
        raise
    except (OSError, ValueError, requests.RequestException) as error:
        raise UpdateError("更新下载中断，请重试；支持续传的已验证数据会保留。") from error
    finally:
        if complete or invalid or not ranged:
            part.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)


def stream_transfer(client, info, part, emit):
    from update_core import MAX_INSTALLER, UpdateError
    for attempt in range(3):
        client._cancel()
        count = 0
        try:
            with client._request(info.url, headers={"Accept-Encoding": "identity"}) as response, part.open("wb") as output:
                length = int(response.headers.get("Content-Length") or 0)
                if info.size and length and info.size != length:
                    raise UpdateError("更新包大小与发布信息不一致。")
                total = info.size or length
                emit(0, total)
                for block in response.iter_content(64 * 1024):
                    client._cancel()
                    count += len(block)
                    if count > MAX_INSTALLER or (total and count > total):
                        raise UpdateError("更新包超出了声明的大小。")
                    output.write(block)
                    emit(count, total)
                output.flush()
                os.fsync(output.fileno())
                if total and count != total:
                    raise requests.ConnectionError("truncated update")
            return
        except (requests.RequestException, UpdateError) as error:
            from update_core import UpdateCancelled
            if isinstance(error, UpdateCancelled):
                raise
            if isinstance(error, UpdateError) and not getattr(error, "retryable", False):
                raise
            if attempt == 2:
                raise
            if client.cancelled.wait(0.5 * (attempt + 1)):
                client._cancel()


def range_transfer(client, url, part, total, resume, validator, emit):
    from update_core import UpdateError
    lock = threading.Lock()
    stop = threading.Event()
    active = {}
    finished = resume

    def fetch(start, end):
        headers = {"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}
        if validator and not validator.startswith("W/"):
            headers["If-Range"] = validator
        for attempt in range(3):
            client._cancel()
            if stop.is_set():
                raise RangeUnavailable("已停止分段下载。")
            with lock:
                active[start] = 0
            try:
                with client._request(url, headers=headers) as response:
                    if response.status_code != 206 or parse_range(response.headers.get("Content-Range")) != (start, end, total):
                        raise RangeUnavailable("响应与请求范围不一致。")
                    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                        raise RangeUnavailable("不支持压缩的范围响应。")
                    chunks, count = [], 0
                    for block in response.iter_content(64 * 1024):
                        client._cancel()
                        if stop.is_set():
                            raise RangeUnavailable("已停止分段下载。")
                        count += len(block)
                        if count > end - start + 1:
                            raise RangeUnavailable("范围响应超长。")
                        chunks.append(block)
                        with lock:
                            active[start] = count
                    if count != end - start + 1:
                        raise requests.ConnectionError("truncated range")
                    return b"".join(chunks)
            except (requests.RequestException, UpdateError) as error:
                from update_core import UpdateCancelled
                if isinstance(error, UpdateCancelled) or (isinstance(error, UpdateError) and not getattr(error, "retryable", False)) or attempt == 2:
                    raise
                if client.cancelled.wait(0.5 * (attempt + 1)):
                    client._cancel()

    # A resumed prefix is sampled against the same immutable, hashed asset.
    if resume:
        spans = [(0, min(resume, 65536) - 1)]
        if resume > 65536:
            spans.append((resume - 65536, resume - 1))
        with part.open("rb") as existing:
            for start, end in spans:
                existing.seek(start)
                if existing.read(end - start + 1) != fetch(start, end):
                    resume = finished = 0
                    break
        active.clear()
    emit(resume, total)
    with part.open("ab" if resume else "wb") as output:
        with ThreadPoolExecutor(max_workers=CONNECTIONS, thread_name_prefix="update-range") as pool:
            try:
                while finished < total:
                    client._cancel()
                    pieces = [(offset, min(offset + BLOCK, total) - 1)
                              for offset in range(finished, min(finished + CONNECTIONS * BLOCK, total), BLOCK)]
                    jobs = {start: pool.submit(fetch, start, end) for start, end in pieces}
                    pending = set(jobs.values())
                    while pending:
                        done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                        client._cancel()
                        for job in done:
                            job.result()
                        with lock:
                            count = finished + sum(active.values())
                        emit(count, total)
                    for start, end in pieces:
                        output.write(jobs[start].result())
                        with lock:
                            active.pop(start, None)
                            finished += end - start + 1
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                stop.set()
