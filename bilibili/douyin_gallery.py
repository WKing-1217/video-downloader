"""Export the original assets of a Douyin photo/LivePhoto post.

Photos, LivePhoto clips and background music remain separate original files.
An album never passes through the complete-video duration check.
"""
import hashlib
import json
import math
from pathlib import Path
import subprocess
from urllib.parse import urlparse

from yt_dlp.networking import Request
from yt_dlp.utils import sanitize_filename
from network_settings import windows_system_proxy
from runtime_paths import tool


def gallery_proxies():
    # Keep explicit proxy environment variables, but fetch domestic photo/music
    # resources directly when only an automatic Windows proxy is configured.
    # An overseas exit can make otherwise available background music disappear.
    return {"all": None, "http": None, "https": None} if windows_system_proxy() else None


def _urls(value):
    if isinstance(value, dict):
        value = value.get("url_list") or value.get("url") or value.get("uri") or []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(u for u in value if isinstance(u, str)
                             and urlparse(u).scheme in {"http", "https"} and urlparse(u).hostname))


def _images(detail):
    post = detail.get("image_post_info") or {}
    if not isinstance(post, dict):
        post = {}
    for group in (post, detail):
        for key in ("images", "image_list", "image_infos", "original_images"):
            images = group.get(key)
            if isinstance(images, list) and images:
                return images
    return []


def gallery_info(detail):
    """Keep exact ordered assets, including LivePhoto clips hidden in /note/."""
    images = _images(detail)
    if not images:
        return None
    assets = []
    for index, image in enumerate(images, 1):
        if not isinstance(image, dict):
            raise ValueError(f"第 {index} 张图片信息不完整，不能判定整条作品已导出。")
        origin = image.get("origin_image") or {}
        if not isinstance(origin, dict):
            origin = {}
        urls = (_urls(origin) or list(reversed(_urls(image))) or
                _urls(image.get("display_image")) or _urls(image.get("download_addr")) or
                _urls(image.get("download_url_list")))
        if not urls:
            raise ValueError(f"第 {index} 张图片没有可用地址，请登录抖音后重试。")
        assets.append({"kind": "image", "index": index, "name": f"{index:03d}_图片",
                       "urls": urls, "width": origin.get("width") or image.get("width"),
                       "height": origin.get("height") or image.get("height")})
        video = image.get("video") or {}
        if not isinstance(video, dict):
            video = {}
        live = bool(video or image.get("clip_type") == 3 or image.get("video_play_addr"))
        if not live:
            continue
        choices = []
        for stream in video.get("bit_rate") or []:
            if isinstance(stream, dict) and _urls(stream.get("play_addr")):
                choices.append((stream["play_addr"], stream.get("bit_rate") or 0))
        for key in ("play_addr", "play_addr_h264", "play_addr_lowbr"):
            if _urls(video.get(key)):
                choices.append((video[key], 0))
        if _urls(image.get("video_play_addr")):
            address = image["video_play_addr"]
            choices.append((address if isinstance(address, dict) else {"url_list": _urls(address)}, 0))
        if not choices:
            raise ValueError(f"第 {index} 张是实况照片，但实况视频地址缺失；请登录抖音后重试。")
        address, _ = max(choices, key=lambda c: ((c[0].get("width") or video.get("width") or 0)
                                               * (c[0].get("height") or video.get("height") or 0), c[1]))
        duration = float(video.get("duration") or 0) / 1000
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"无法确认第 {index} 张实况照片的原始时长。")
        assets.append({"kind": "live_photo", "index": index, "name": f"{index:03d}_实况",
                       "urls": _urls(address), "duration": duration,
                       "width": address.get("width") or video.get("width"),
                       "height": address.get("height") or video.get("height"),
                       "expected_size": address.get("data_size")})
    music = detail.get("music") or {}
    music_urls = _urls(music.get("play_url"))
    if music.get("duration") and not music_urls:
        if music.get("offline_desc"):
            raise ValueError("作品配乐暂不可用：" + music["offline_desc"])
        raise ValueError("作品背景音乐地址缺失，请登录抖音后重试。")
    if music_urls:
        assets.append({"kind": "music", "name": "背景音乐", "urls": music_urls,
                       "duration": music.get("duration"), "title": music.get("title")})
    # A playlist marker lets yt-dlp preserve album metadata without selecting a
    # fictitious video format. downloader.py handles this before normal playlists.
    return {"_type": "playlist", "id": str(detail["aweme_id"]),
            "title": detail.get("desc") or f"抖音图文 {detail['aweme_id']}", "entries": [],
            "_douyin_gallery": assets, "image_count": len(images)}


def verify_asset(path, asset, probe):
    """Validate real media type, dimensions and original clip/music duration."""
    streams = probe.get("streams", [])
    kind = asset["kind"]
    track = next((s for s in streams if s.get("codec_type") == ("audio" if kind == "music" else "video")), None)
    if not track:
        raise ValueError("文件缺少应有的图片、实况画面或配乐音轨。")
    result = {"kind": kind, "size": path.stat().st_size, "codec": track.get("codec_name")}
    if kind != "music":
        width, height = int(track.get("width") or 0), int(track.get("height") or 0)
        if width <= 0 or height <= 0:
            raise ValueError("无法确认图片或实况画面的尺寸。")
        if width < (asset.get("width") or 0) or height < (asset.get("height") or 0):
            raise ValueError("图片或实况画面小于源站声明的尺寸。")
        result.update(width=width, height=height, index=asset["index"])
    if kind != "image":
        duration = float(probe.get("format", {}).get("duration") or 0)
        expected = float(asset.get("duration") or 0)
        tolerance = max(0.25 if kind == "live_photo" else 2, expected * 0.01)
        if not math.isfinite(duration) or duration <= 0 or (expected and abs(duration - expected) > tolerance):
            raise ValueError("实况视频或背景音乐时长不完整。")
        stream_duration = track.get("duration")
        if expected and stream_duration not in (None, "N/A"):
            actual = float(stream_duration)
            if not math.isfinite(actual) or abs(actual - expected) > tolerance:
                raise ValueError("实况视频或背景音乐的音画轨时长不完整。")
        result.update(duration=duration, expected_duration=expected)
        if kind == "music":
            result.update(title=asset.get("title"), bitrate=int(track.get("bit_rate") or 0))
    return result


def _extension(asset, probe):
    kind = asset["kind"]
    stream = next(s for s in probe["streams"] if s.get("codec_type") == ("audio" if kind == "music" else "video"))
    codec = stream.get("codec_name")
    container = probe.get("format", {}).get("format_name", "")
    if kind == "image":
        suffix = {"mjpeg": "jpg", "png": "png", "webp": "webp", "gif": "gif", "av1": "avif", "hevc": "heic"}.get(codec)
        if not suffix:
            raise ValueError("源站返回了无法确认格式的图片。")
        return suffix
    if kind == "live_photo":
        return "mkv" if "matroska" in container else "mp4"
    if "mp4" in container or "mov" in container:
        return "m4a"
    return {"mp3": "mp3", "flac": "flac", "opus": "opus", "vorbis": "ogg"}.get(codec, "wav" if "wav" in container else "aac")


def download_gallery(info, ydl, output, emit, probe_media):
    assets = info["_douyin_gallery"]
    title = info.get("title") or "抖音图文"
    safe = sanitize_filename(title, restricted=False).encode("utf-8")[:100].decode("utf-8", errors="ignore").rstrip(" .")
    folder = output / f"{safe or '抖音图文'} [{info['id']}]"
    folder.mkdir(parents=True, exist_ok=True)
    emit("metadata", title=title, content_type="gallery", image_count=info["image_count"],
         live_photo_count=sum(a["kind"] == "live_photo" for a in assets))
    saved = []
    for number, asset in enumerate(assets, 1):
        emit("stage", message=f"正在导出 {number}/{len(assets)} · {asset['name']}…")
        temporary = folder / (asset["name"] + ".part")
        verified = None
        failure = None
        for url in asset["urls"]:
            try:
                with ydl.urlopen(Request(url, proxies=gallery_proxies(), headers={"Referer": "https://www.douyin.com/",
                                                       "Accept-Encoding": "identity"})) as response, temporary.open("wb") as out:
                    expected_size = int(response.headers.get("Content-Length") or 0)
                    written = 0
                    while chunk := response.read(256 * 1024):
                        out.write(chunk)
                        written += len(chunk)
                    if not written or (expected_size and written != expected_size):
                        raise ValueError("传输未完成。")
                    if asset.get("expected_size") and written != int(asset["expected_size"]):
                        raise ValueError("实况视频大小与源站不一致。")
                probe = probe_media(temporary)
                verified = verify_asset(temporary, asset, probe)
                # Full decode catches truncated JPEGs and damaged media packets.
                decoded = subprocess.run([tool("ffmpeg"), "-v", "error", "-xerror", "-i", str(temporary),
                                          "-f", "null", "-"], capture_output=True, timeout=90,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if decoded.returncode:
                    raise ValueError("文件解码检查失败。")
                final = folder / (asset["name"] + "." + _extension(asset, probe))
                with temporary.open("rb") as source:
                    digest = hashlib.sha256()
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                verified.update(path=str(final.resolve()), full_decode=True, sha256=digest.hexdigest())
                temporary.replace(final)
                saved.append(verified)
                break
            except Exception as exc:
                failure = exc
                verified = None
        if verified is None:
            raise ValueError(f"{asset['name']}导出失败，作品尚未完整保存；请重新下载或登录抖音后重试。") from failure
    result = {"content_type": "gallery", "platform": "douyin", "id": info["id"], "title": title,
              "path": str(folder.resolve()), "image_count": info["image_count"],
              "live_photo_count": sum(a["kind"] == "live_photo" for a in saved),
              "music_count": sum(a["kind"] == "music" for a in saved), "assets": saved,
              "size": sum(a["size"] for a in saved)}
    receipt = folder / "作品信息.json"
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    emit("complete", **result)
    return result
