"""Compatibility adapter for public Douyin videos and photo/LivePhoto posts.

The mobile feed can return several posts. Only an exact requested ID is accepted.
Endpoint reference: https://github.com/ucmao/media-parser/blob/main/docs/parsers/douyin.md
Media conversion/format handling remain provided by the installed yt-dlp.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess

from yt_dlp.extractor.tiktok import DouyinIE as UpstreamDouyinIE
from yt_dlp.utils import ExtractorError
from yt_dlp.networking import Request
from douyin_gallery import gallery_info, gallery_proxies
from runtime_paths import tool

MOBILE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Mobile Safari/537.36"
)


def find_requested_video(data, video_id):
    if not isinstance(data, dict):
        return None
    for item in data.get("aweme_list") or data.get("aweme_details") or []:
        if isinstance(item, dict) and str(item.get("aweme_id")) == str(video_id):
            return item
    return None


def probe_audio(fmt, duration):
    """Inspect one representative media URL per video codec, without saving it."""
    try:
        command = [tool("ffprobe"), "-v", "error", "-rw_timeout", "6000000",
                   "-user_agent", MOBILE_USER_AGENT,
                   "-show_entries", "format=duration:stream=codec_type,codec_name,bit_rate,sample_rate,channels",
                   "-of", "json", fmt["url"]]
        run = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace",
                             timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if run.returncode:
            return None
        data = json.loads(run.stdout)
        if abs(float(data.get("format", {}).get("duration", 0)) - duration) > max(2, duration * 0.01):
            return None
        audio = next(s for s in data.get("streams", []) if s.get("codec_type") == "audio")
        if int(audio.get("bit_rate") or 0) <= 0:
            return None
        return {"format": fmt, "codec": audio.get("codec_name"),
                "bitrate": int(audio["bit_rate"]), "channels": int(audio.get("channels") or 0),
                "sample_rate": int(audio.get("sample_rate") or 0)}
    except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired):
        return None


def add_stream_choices(info, probes):
    """Offer explicit stream selections when HD containers have worse audio.

The source URLs are muxed files. The format notes declare stream extraction;
FFmpegMerger maps only the chosen video track and chosen audio track, with copy.
"""
    probes = [p for p in probes if p]
    if len(probes) < 2 or len({p["codec"] for p in probes}) != 1:
        return False
    best = max(probes, key=lambda p: (p["channels"], p["bitrate"], p["sample_rate"]))
    if all(p["channels"] == best["channels"] and p["bitrate"] >= best["bitrate"] * 0.9 for p in probes):
        return False
    video_views = []
    for fmt in info["formats"]:
        if fmt.get("format_id", "").startswith("download"):
            continue  # Download variants can contain an extra logo/outro segment.
        view = dict(fmt, format_id=fmt["format_id"] + "-video", acodec="none",
                    format_note="最佳画面候选，合并时仅提取视频轨")
        view.pop("abr", None)
        view.pop("audio_channels", None)
        video_views.append(view)
    if not video_views:
        return False
    audio_view = dict(best["format"], format_id=best["format"]["format_id"] + "-audio",
                      vcodec="none", acodec=best["codec"], ext="mp4",
                      abr=best["bitrate"] / 1000, tbr=best["bitrate"] / 1000,
                      audio_channels=best["channels"], asr=best["sample_rate"],
                      format_note="最佳音质候选，合并时仅提取音频轨")
    for key in ("width", "height", "fps", "vbr", "resolution"):
        audio_view.pop(key, None)
    info["formats"].extend([*video_views, audio_view])
    return True


class DouyinIE(UpstreamDouyinIE):
    # Keeping the upstream class key replaces just Douyin in YoutubeDL's registry.
    _VALID_URL = r"https?://(?:www\.)?douyin\.com/(?:video|note|slides)/(?P<id>\d+)"

    def _gallery(self, video_id):
        # This is the slides endpoint used by Douyin's own mobile share page.
        # aweme_ids must be a JSON array of numbers, NOT an array of strings:
        # the latter returns no detail. Do not use the unrelated feed entries.
        proxies = gallery_proxies()
        if proxies:
            self.to_screen("图文和配乐使用本机直连访问。")
        for aid in ("6383", "1128"):
            data = self._download_json(
                Request("https://www.iesdouyin.com/web/api/v2/aweme/slidesinfo/", proxies=proxies), video_id,
                note="正在读取抖音图文与实况信息", fatal=False,
                query={"aweme_ids": f"[{video_id}]", "aid": aid, "request_source": "200"},
                headers={"User-Agent": MOBILE_USER_AGENT,
                         "Referer": f"https://www.iesdouyin.com/share/note/{video_id}/"})
            detail = find_requested_video(data, video_id)
            if detail:
                result = gallery_info(detail)
                if result:
                    return result
        return None

    def _real_extract(self, url):
        video_id = self._match_id(url)
        if "/note/" in url or "/slides/" in url:
            gallery = self._gallery(video_id)
            if gallery:
                return gallery
            raise ExtractorError("未读取到这条图文作品，请点「网页登录」确认作品可见、完成验证后重试。", expected=True)
        for host in ("api5-normal-c-hl.amemv.com", "aweme.snssdk.com"):
            data = self._download_json(
                f"https://{host}/aweme/v1/feed/", video_id,
                note="正在读取抖音公开视频信息", fatal=False,
                query={"aweme_id": video_id, "aid": "1128"},
                headers={"User-Agent": MOBILE_USER_AGENT})
            detail = find_requested_video(data, video_id)
            if detail:
                gallery = gallery_info(detail)
                if gallery:
                    return gallery
            if detail and detail.get("video"):
                info = self._parse_aweme_video_app(detail)
                if info.get("formats"):
                    # AVC and HEVC versions of the same post can have different
                    # audio bitrates. Compare one full-length candidate per codec.
                    candidates = {}
                    for fmt in info["formats"]:
                        if fmt.get("format_id", "").startswith("download"):
                            continue
                        codec = fmt.get("vcodec")
                        rank = (min(fmt.get("width") or 0, fmt.get("height") or 0), fmt.get("tbr") or 0)
                        old = candidates.get(codec)
                        if old is None or rank > old[0]:
                            candidates[codec] = (rank, fmt)
                    if len(candidates) > 1:
                        self.to_screen("正在比较高清版本中的音质…")
                        with ThreadPoolExecutor(max_workers=3) as pool:
                            probes = list(pool.map(lambda fmt: probe_audio(fmt, info["duration"]),
                                                   [entry[1] for entry in candidates.values()]))
                        if add_stream_choices(info, probes):
                            self.to_screen("已分别选择最佳画面和最佳音频，将无损合并。")
                    return info
        gallery = self._gallery(video_id)
        if gallery:
            return gallery
        # Fall back to the normal authenticated extractor when public data is absent.
        return super()._real_extract(url)
