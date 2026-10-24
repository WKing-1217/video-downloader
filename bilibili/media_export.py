"""Verified media conversion with atomic, non-overwriting final publication.

Metadata is returned to the application's catalogue; exports never need a JSON
sidecar. Source files are read only, including when exporting into their folder.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from runtime_paths import configure_tools, tool

VIDEO_FORMATS = ("mp4", "mkv", "mov", "webm")
IMAGE_FORMATS = ("png", "jpg", "webp")
AUDIO_BITRATES = (128, 192, 256, 320)
DEFAULT_AUDIO_BITRATE = 192


def require_tools():
    configure_tools()
    if not all(shutil.which(tool(name)) for name in ("ffmpeg", "ffprobe")):
        raise ValueError("缺少 FFmpeg，请先运行“安装依赖.bat”。")


def validate_options(mode="video", video_format="mp4", image_format="png", audio_bitrate=192):
    if mode not in {"video", "audio"}:
        raise ValueError("请选择下载作品或提取 MP3。")
    if video_format not in VIDEO_FORMATS:
        raise ValueError("不支持的视频格式，请选择 MP4、MKV、MOV 或 WebM。")
    if image_format not in IMAGE_FORMATS:
        raise ValueError("不支持的图片格式，请选择 PNG、JPG 或 WebP。")
    if audio_bitrate not in AUDIO_BITRATES:
        raise ValueError("MP3 音质请选择 128、192、256 或 320 kbps。")


def _run(arguments):
    result = subprocess.run(arguments, capture_output=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise ValueError("媒体处理失败：" + result.stderr.strip()[-700:])
    return result


def probe_media(path: Path) -> dict:
    result = _run([tool("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    data = json.loads(result.stdout)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or 0)
    # Matroska does not always store bit_rate; retain the real measured quality.
    if audio and not audio.get("bit_rate") and math.isfinite(duration) and duration > 0:
        packets = _run([tool("ffprobe"), "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "packet=size", "-of", "csv=p=0", str(path)])
        sizes = [line.split(",", 1)[0].strip() for line in packets.stdout.splitlines()]
        audio["bit_rate"] = round(sum(int(size) for size in sizes if size.isdigit()) * 8 / duration)
    return data


def _duration(probe):
    duration = float(probe.get("format", {}).get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("无法确认媒体完整时长。")
    return duration


def _check_duration(probe, expected, streams, *, tolerance=None):
    duration = _duration(probe)
    if not math.isfinite(expected) or expected <= 0:
        raise ValueError("无法确认原始时长，不能判定文件完整。")
    tolerance = max(2.0, expected * 0.01) if tolerance is None else tolerance
    if abs(duration - expected) > tolerance:
        raise ValueError(f"完整性校验失败：原文件 {expected:.2f} 秒，导出文件 {duration:.2f} 秒。")
    for stream in streams:
        if stream.get("duration") not in (None, "N/A"):
            track_duration = float(stream["duration"])
            if not math.isfinite(track_duration) or abs(track_duration - expected) > tolerance:
                raise ValueError("完整性校验失败：音轨或画面时长不完整，请重新下载。")
    return duration


def verify_video(path, expected, probe=None, *, require_audio=True):
    path = Path(path)
    data = probe if probe is not None else probe_media(path)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not video or (require_audio and not audio):
        raise ValueError("完整性校验失败：文件必须同时包含画面和声音。" if require_audio else "文件缺少视频画面。")
    duration = _check_duration(data, expected, [s for s in (video, audio) if s])
    return {"path": str(path.resolve()), "duration": duration, "kind": "video", "content_type": "video",
            "format": path.suffix.lower().lstrip("."), "width": video.get("width"), "height": video.get("height"),
            "video_codec": video.get("codec_name"), "audio_codec": audio.get("codec_name") if audio else None,
            "audio_bitrate": int(audio.get("bit_rate") or 0) if audio else 0, "size": path.stat().st_size}


def verify_audio(path, expected, probe=None):
    path = Path(path)
    data = probe if probe is not None else probe_media(path)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not audio:
        raise ValueError("这个文件没有可提取的音轨，请选择有声音的视频。")
    duration = _check_duration(data, expected, [audio])
    return {"path": str(path.resolve()), "duration": duration, "kind": "audio", "content_type": "audio",
            "format": path.suffix.lower().lstrip("."), "audio_codec": audio.get("codec_name"),
            "audio_bitrate": int(audio.get("bit_rate") or 0), "size": path.stat().st_size}


def full_decode(path):
    _run([tool("ffmpeg"), "-hide_banner", "-v", "error", "-xerror", "-nostdin", "-i", str(path),
          "-f", "null", "-"])


def publish_unique(staged, destination):
    """Promote one verified same-volume file; never replace existing media."""
    staged, destination = Path(staged), Path(destination)
    candidate, number = destination, 2
    while True:
        try:
            if os.name == "nt":
                staged.rename(candidate)  # Windows rename refuses an existing file.
            else:
                os.link(staged, candidate)  # Atomic no-clobber on POSIX too.
                staged.unlink()
            return candidate
        except FileExistsError:
            candidate = destination.with_name(f"{destination.stem} ({number}){destination.suffix}")
            number += 1


def _filename(source, title, suffix):
    name = title if title else source.stem
    # Win32 disallows these even if a caller supplies a title rather than a path.
    name = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in str(name))
    name = name.encode("utf-8")[:150].decode("utf-8", errors="ignore").strip(" .") or "导出作品"
    if name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name + "." + suffix


def extract_audio(source, output, *, bitrate=192, title=None, progress=None):
    validate_options(audio_bitrate=bitrate)
    require_tools()
    source, output = Path(source), Path(output)
    if not source.is_file():
        raise ValueError("原视频文件已移动或删除，请重新选择。")
    probe = probe_media(source)
    expected = _duration(probe)
    verify_audio(source, expected, probe)
    output.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("正在提取 MP3 音轨…")
    with tempfile.TemporaryDirectory(prefix=".export-", dir=output) as folder:
        staged = Path(folder) / "audio.mp3"
        _run([tool("ffmpeg"), "-hide_banner", "-v", "error", "-xerror", "-nostdin", "-i", str(source),
              "-map", "0:a:0", "-vn", "-sn", "-dn", "-c:a", "libmp3lame", "-b:a", f"{bitrate}k",
              "-map_metadata", "-1", "-y", str(staged)])
        result = verify_audio(staged, expected)
        full_decode(staged)
        final = publish_unique(staged, output / _filename(source, title, "mp3"))
    result.update(path=str(final.resolve()), title=title or source.stem, source_path=str(source.resolve()),
                  format="mp3", expected_duration=expected, full_decode=True)
    return result


def export_video(source, output, *, video_format="mp4", expected=None, require_audio=True, title=None, progress=None):
    validate_options(video_format=video_format)
    require_tools()
    source, output = Path(source), Path(output)
    probe = probe_media(source)
    expected = _duration(probe) if expected is None else expected
    verify_video(source, expected, probe, require_audio=require_audio)
    video = next(s for s in probe["streams"] if s.get("codec_type") == "video")
    audio = next((s for s in probe["streams"] if s.get("codec_type") == "audio"), None)
    output.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("正在导出并校验视频…")
    arguments = [tool("ffmpeg"), "-hide_banner", "-v", "error", "-xerror", "-nostdin", "-i", str(source),
                 "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-map_metadata", "-1"]
    if video_format == "mkv":
        arguments += ["-c", "copy"]
    elif video_format == "webm":
        arguments += (["-c:v", "copy"] if video.get("codec_name") in {"vp8", "vp9", "av1"} else
                      ["-c:v", "libvpx-vp9", "-crf", "28", "-b:v", "0", "-cpu-used", "4", "-row-mt", "1"])
        arguments += ["-c:a", "copy"] if audio and audio.get("codec_name") in {"opus", "vorbis"} else ["-c:a", "libopus", "-b:a", "192k"]
    else:
        compatible = {"h264", "hevc", "av1"} if video_format == "mp4" else {"h264", "hevc"}
        arguments += (["-c:v", "copy"] if video.get("codec_name") in compatible else
                      ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p"])
        arguments += ["-c:a", "copy"] if audio and audio.get("codec_name") == "aac" else ["-c:a", "aac", "-b:a", "192k"]
        arguments += ["-movflags", "+faststart"]
    with tempfile.TemporaryDirectory(prefix=".export-", dir=output) as folder:
        staged = Path(folder) / ("video." + video_format)
        _run([*arguments, "-y", str(staged)])
        result = verify_video(staged, expected, require_audio=require_audio)
        full_decode(staged)
        final = publish_unique(staged, output / _filename(source, title, video_format))
    result.update(path=str(final.resolve()), title=title or source.stem, expected_duration=expected,
                  format=video_format, full_decode=True)
    return result


def export_image(source, output, *, image_format="png", title=None):
    validate_options(image_format=image_format)
    require_tools()
    source, output = Path(source), Path(output)
    original = probe_media(source)
    original_video = next((s for s in original.get("streams", []) if s.get("codec_type") == "video"), None)
    if not original_video:
        raise ValueError("原文件没有可导出的图片。")
    output.mkdir(parents=True, exist_ok=True)
    arguments = [tool("ffmpeg"), "-hide_banner", "-v", "error", "-xerror", "-nostdin", "-i", str(source),
                 "-map", "0:v:0", "-frames:v", "1", "-an", "-map_metadata", "-1"]
    if image_format == "jpg":
        arguments += ["-q:v", "2"]
    elif image_format == "webp":
        arguments += ["-lossless", "1"]
    with tempfile.TemporaryDirectory(prefix=".export-", dir=output) as folder:
        staged = Path(folder) / ("image." + image_format)
        _run([*arguments, "-y", str(staged)])
        probe = probe_media(staged)
        video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
        if not video or not video.get("width") or not video.get("height"):
            raise ValueError("图片导出校验失败。")
        if (video["width"], video["height"]) != (original_video.get("width"), original_video.get("height")):
            raise ValueError("图片导出校验失败：图片尺寸发生变化。")
        full_decode(staged)
        final = publish_unique(staged, output / _filename(source, title, image_format))
    return {"path": str(final.resolve()), "kind": "image", "format": image_format, "width": video["width"],
            "height": video["height"], "codec": video.get("codec_name"), "size": final.stat().st_size, "full_decode": True}
