"""Download a complete Bilibili, Douyin or X video; emit JSON-lines events."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import hashlib
import math
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlparse

import yt_dlp
from browser_accounts import cookie_summary, scan_accounts, select_account, session_cookie_jar
from platform_links import PLATFORMS, normalize_url, resolve_link, download_link
from network_settings import windows_system_proxy
from parallel_http import AcceleratedYoutubeDL
from bilibili_adapter import BiliBiliIE
from douyin_adapter import DouyinIE
from douyin_gallery import download_gallery, gallery_proxies
from runtime_paths import configure_tools, output_dir, tool

ROOT = Path(__file__).resolve().parent
configure_tools()
OUTPUT = output_dir()


def emit(event: str, **data):
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def probe_media(path: Path) -> dict:
    command = [tool("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
    result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ValueError("无法读取下载文件：" + result.stderr.strip()[-400:])
    data = json.loads(result.stdout)
    # Matroska commonly omits stream.bit_rate. Measure its real audio packets so
    # the receipt reports actual audio quality instead of an unknown zero value.
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or 0)
    if audio and not audio.get("bit_rate") and math.isfinite(duration) and duration > 0:
        packets = subprocess.run(
            [tool("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=size",
             "-of", "csv=p=0", str(path)], capture_output=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not packets.returncode:
            sizes = [line.split(",", 1)[0].strip() for line in packets.stdout.splitlines()]
            audio["bit_rate"] = round(sum(int(size) for size in sizes if size.isdigit()) * 8 / duration)
    return data


def verify_media(path: Path, expected: float, probe: dict | None = None) -> dict:
    data = probe if probe is not None else probe_media(path)
    videos = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    audios = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not videos or not audios:
        raise ValueError("完整性校验失败：文件必须同时包含画面和声音。")
    duration = float(data.get("format", {}).get("duration", 0))
    if not math.isfinite(expected) or expected <= 0:
        raise ValueError("无法确认原视频时长，不能判定为完整视频。")
    tolerance = max(2.0, expected * 0.01)
    if not math.isfinite(duration) or abs(duration - expected) > tolerance:
        raise ValueError(f"完整性校验失败：原视频 {expected:.2f} 秒，文件 {duration:.2f} 秒。")
    # Check stream lengths too: a long audio track must not hide a short preview video.
    for label, stream in (("画面", videos[0]), ("声音", audios[0])):
        stream_duration = stream.get("duration")
        if stream_duration not in (None, "N/A"):
            stream_duration = float(stream_duration)
            if not math.isfinite(stream_duration) or abs(stream_duration - expected) > tolerance:
                raise ValueError(f"完整性校验失败：{label} {stream_duration:.2f} 秒，原视频 {expected:.2f} 秒。请重新下载，程序会保留旧文件并重新获取。")
    video, audio = videos[0], audios[0]
    return {"path": str(path.resolve()), "duration": duration,
            "width": video.get("width"), "height": video.get("height"),
            "video_codec": video.get("codec_name"), "audio_codec": audio.get("codec_name"),
            "audio_bitrate": int(audio.get("bit_rate") or 0), "size": path.stat().st_size}


class Logger:
    def debug(self, message):
        if not message.startswith("[debug]"):
            emit("log", message=message)

    def warning(self, message):
        emit("log", message=message)

    def error(self, message):
        emit("log", message=message)


def media_candidates(prepared):
    path = Path(prepared)
    return list(dict.fromkeys([path, *(path.with_suffix(ext) for ext in (".mp4", ".mkv", ".webm"))]))


def quarantine_incomplete(info, ydl, expected, directory=None):
    """A failed final file must not make every retry reuse the same bad media."""
    prepared = ydl.prepare_filename(info)
    if directory is not None:
        prepared = Path(directory) / Path(prepared).name
    for path in media_candidates(prepared):
        if not path.is_file():
            continue
        try:
            verify_media(path, expected)
        except ValueError:
            backup = path.parent / "未通过校验"
            backup.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            destination = backup / f"{path.stem} [{stamp}]{path.suffix}"
            path.replace(destination)
            receipt = path.with_suffix(path.suffix + ".info.json")
            if receipt.is_file():
                receipt.replace(destination.with_suffix(destination.suffix + ".info.json"))
            emit("log", message="发现旧文件的音画不完整，已保留到「未通过校验」文件夹，正在重新下载。")


def download(url: str, cookie_file: str | None = None, *, auto_cookies=True, browser_source=None,
             session_cookies=None, user_agent=None) -> dict:
    url, platform = resolve_link(url)
    emit("platform", platform=platform.key, label=platform.label)
    if not shutil.which(tool("ffmpeg")) or not shutil.which(tool("ffprobe")):
        raise ValueError("缺少 FFmpeg，请先运行“安装依赖.bat”。")
    if cookie_file and not Path(cookie_file).is_file():
        raise ValueError("选择的 Cookie 文件不存在。")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    try:
        source_key = download_link(url)[2]
    except ValueError:
        source_key = url
    temporary = OUTPUT / ".downloads" / hashlib.sha256(source_key.encode()).hexdigest()[:20]
    temporary.mkdir(parents=True, exist_ok=True)
    final_paths = []
    last_progress = [0.0]

    def progress(data):
        import time
        now = time.monotonic()
        if data["status"] == "downloading" and now - last_progress[0] >= 0.25:
            last_progress[0] = now
            emit("progress", downloaded=data.get("downloaded_bytes", 0),
                 total=data.get("total_bytes") or data.get("total_bytes_estimate"),
                 speed=data.get("speed"), eta=data.get("eta"), filename=Path(data.get("filename", "")).name)
        elif data["status"] == "finished":
            emit("stage", message="分轨下载完成，正在合并与校验…")

    def postprocess(data):
        if data["status"] == "started":
            emit("stage", message="正在合并画面与声音…")
        if data["status"] == "finished":
            path = data.get("info_dict", {}).get("filepath")
            if path:
                final_paths.append(path)

    options = {
        "format": "bestvideo+bestaudio/best",
        "format_sort": ["res", "fps", "hdr:12", "vcodec", "channels", "acodec", "abr", "vbr"],
        "outtmpl": "%(title).100B [%(id)s] [%(format_id)s].%(ext)s",
        "paths": {"home": str(temporary), "temp": str(temporary)},
        "merge_output_format": "mp4/mkv",
        "noplaylist": True, "windowsfilenames": True,
        "continuedl": True, "retries": 8, "fragment_retries": 8,
        "concurrent_fragment_downloads": 8, "noprogress": True,
        "socket_timeout": 30, "quiet": True, "no_warnings": False,
        "logger": Logger(), "progress_hooks": [progress], "postprocessor_hooks": [postprocess],
    }
    if tool("ffmpeg") != "ffmpeg":
        options["ffmpeg_location"] = tool("ffmpeg")
    proxy = windows_system_proxy()
    if proxy:
        options["proxy"] = proxy
        emit("log", message="已自动使用 Windows 系统代理。")
    if cookie_file:
        options["cookiefile"] = cookie_file
    if user_agent:
        options["http_headers"] = {"User-Agent": user_agent}
    jar, chosen = None, None
    web_jar = session_cookie_jar(session_cookies, platform.key) if session_cookies else None
    if web_jar and cookie_summary(web_jar)[platform.key]["login_found"] and not cookie_file:
        jar = web_jar
        emit("login_source", message="正在使用程序内网页登录状态")
    elif auto_cookies and not cookie_file:
        emit("stage", message=f"正在读取本机浏览器中的 {platform.label} 登录信息…")
        report, jars = scan_accounts(platform.key, browser_source,
                                     lambda message: emit("stage", message=message))
        jar, chosen = select_account(platform.key, report, jars)
        emit("accounts", sources=report, selected=chosen["label"] if chosen else None,
             platform=platform.key)
        if chosen:
            emit("log", message=f"本次使用 {chosen['label']} 的 {platform.label} 站点信息。")
        else:
            emit("log", message="未读取到可用的浏览器登录信息，尝试公开访问；可点击「扫描登录状态」查看原因。")
        if web_jar and (not chosen or not chosen["sites"][platform.key]["login_found"]):
            jar = web_jar
            emit("login_source", message="正在使用程序内的网页访问状态")
    elif web_jar and not cookie_file:
        jar = web_jar
        emit("login_source", message="正在使用程序内的网页访问状态")
    emit("stage", message=f"正在解析 {platform.label}，自动选择最高可用画质和音质…")
    with AcceleratedYoutubeDL(options) as ydl:
        if platform.key == "bilibili":
            ydl.add_info_extractor(BiliBiliIE())
        if platform.key == "douyin":
            ydl.add_info_extractor(DouyinIE())
        if jar is not None:
            for cookie in jar:
                ydl.cookiejar.set_cookie(cookie)
        try:
            if platform.key == "douyin" and urlparse(url).hostname == "v.douyin.com":
                emit("stage", message="正在展开抖音分享短链接…")
                try:
                    # Domestic share redirects use the same route as Douyin's
                    # photo endpoints; explicit proxy preferences still win.
                    with ydl.urlopen(yt_dlp.networking.Request(url, proxies=gallery_proxies())) as response:
                        url, _ = resolve_link(response.url)
                except Exception as exc:
                    raise ValueError("抖音分享短链接未能展开，请点「网页登录」打开链接、完成验证后重试，或粘贴完整视频网址。") from exc
            info = ydl.extract_info(url, download=False, process=platform.key != "douyin")
            if info and platform.key == "douyin" and not info.get("_douyin_gallery"):
                info = ydl.process_ie_result(info, download=False)
        except yt_dlp.utils.DownloadError as exc:
            if platform.key == "douyin" and ("Fresh cookies" in str(exc) or "cookies" in str(exc).lower()):
                raise ValueError("抖音需要有效的网页访问状态。请点「网页登录」打开这条视频并完成验证，返回后重新下载。") from exc
            if platform.key == "x":
                message = str(exc).lower()
                if any(word in message for word in ("timed out", "timeout", "connect", "network")):
                    raise ValueError("连接 X 失败，请确认本机网络能够打开 x.com，然后重新下载。") from exc
                if any(word in message for word in ("login", "authenticate", "sign in", "unauthorized")):
                    raise ValueError("X 要求有效登录，请点击「网页登录」完成登录后重试。") from exc
            raise
        if info and info.get("_douyin_gallery") and platform.key == "douyin":
            return download_gallery(info, ydl, OUTPUT, emit, probe_media)
        if info and info.get("_type") in {"playlist", "multi_video"} and platform.key == "x":
            entries = [entry for entry in info.get("entries", []) if entry]
            if entries:
                info = entries[0]
                emit("log", message="这条帖子包含多个视频，当前下载第一个；可粘贴带 /video/2 等序号的链接选择其他视频。")
        if not info or info.get("_type") in {"playlist", "multi_video"}:
            raise ValueError("请提供单个视频链接。")
        expected = float(info.get("duration") or 0)
        if not expected:
            raise ValueError("无法获取完整时长，请检查视频链接或重新扫描浏览器登录状态。")
        if info.get("is_live"):
            raise ValueError("当前仅支持已经发布的完整视频，暂不支持直播。")
        quarantine_incomplete(info, ydl, expected, OUTPUT)
        emit("metadata", title=info.get("title"), duration=expected,
             height=info.get("height"), formats=[{
                 "id": f.get("format_id"), "height": f.get("height"), "abr": f.get("abr"),
                 "vcodec": f.get("vcodec"), "acodec": f.get("acodec")
             } for f in info.get("requested_formats", [])])
        # Reuse the resolved metadata so selection and the downloaded media are identical.
        existing = next((candidate for candidate in media_candidates(OUTPUT / Path(ydl.prepare_filename(info)).name)
                         if candidate.is_file()), None)
        if existing:
            # The preflight above has already verified this exact format's file.
            path = existing
            emit("log", message="已找到同画质、同音质的完整文件，正在复用并重新校验。")
        else:
            ydl.process_info(info)
        candidates = [info.get("filepath"), *reversed(final_paths), ydl.prepare_filename(info)]
        path = existing or next((Path(p) for p in candidates if p and Path(p).is_file()
                                and Path(p).suffix.lower() in {".mp4", ".mkv", ".webm", ".flv"}), None)
        if path is None:
            path = next((candidate for candidate in media_candidates(ydl.prepare_filename(info))
                         if candidate.is_file()), None)
        if path is None:
            raise ValueError("未找到合并后的视频文件，请查看详细日志。")
    emit("stage", message="正在检查视频、音频和完整时长…")
    result = verify_media(path, expected)
    final = OUTPUT / path.name
    if path.resolve() != final.resolve():
        path.replace(final)  # Same-volume publication happens only after verification.
        path = final
        result["path"] = str(final.resolve())
    result.update(title=info.get("title"), expected_duration=expected,
                  platform=platform.key, source_key=source_key, selected_formats=[f.get("format_id") for f in info.get("requested_formats", [])]
                  or [info.get("format_id")])
    receipt = path.with_suffix(path.suffix + ".info.json")
    pending_receipt = receipt.with_suffix(receipt.suffix + ".tmp")
    pending_receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pending_receipt.replace(receipt)
    try:
        temporary.rmdir()
    except OSError:
        pass
    emit("complete", **result)
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="自动识别 Bilibili、抖音和 X，下载最高可用画质与音质")
    parser.add_argument("url", nargs="?")
    parser.add_argument("--cookies", default=None)
    parser.add_argument("--no-browser-cookies", action="store_true")
    parser.add_argument("--browser-source", default=None)
    parser.add_argument("--scan-browsers", action="store_true")
    parser.add_argument("--session-stdin", action="store_true", help="Read an in-memory web login snapshot from stdin")
    args = parser.parse_args()
    try:
        if args.scan_browsers:
            report, _ = scan_accounts(on_progress=lambda message: emit("scan_progress", message=message))
            emit("accounts", sources=report)
        elif args.url:
            session = json.load(sys.stdin) if args.session_stdin else {}
            if isinstance(session, list):
                session = {"cookies": session}
            download(args.url, args.cookies, auto_cookies=not args.no_browser_cookies,
                     browser_source=args.browser_source,
                     session_cookies=session.get("cookies"), user_agent=session.get("user_agent"))
        else:
            parser.error("请提供视频链接，或使用 --scan-browsers 扫描登录状态")
    except Exception as exc:
        emit("error", message=str(exc))
        sys.exit(1)
