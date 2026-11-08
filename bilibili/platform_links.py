"""Recognize supported video links without requesting any web page."""
from dataclasses import dataclass
import re
from urllib.parse import parse_qs, urlparse, urlencode


@dataclass(frozen=True)
class Platform:
    key: str
    label: str
    hosts: tuple[str, ...]
    cookie_domains: tuple[str, ...]
    login_cookies: tuple[str, ...]


PLATFORMS = {
    "bilibili": Platform("bilibili", "Bilibili", (
        "bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"),
        ("bilibili.com", "b23.tv"), ("SESSDATA",)),
    "douyin": Platform("douyin", "抖音", (
        "douyin.com", "www.douyin.com", "m.douyin.com", "v.douyin.com", "iesdouyin.com", "www.iesdouyin.com"),
        ("douyin.com", "iesdouyin.com"), ("sessionid", "sessionid_ss", "sid_guard")),
    "instagram": Platform("instagram", "Instagram", (
        "instagram.com", "www.instagram.com", "m.instagram.com"),
        ("instagram.com",), ("sessionid",)),
    "youtube": Platform("youtube", "YouTube", (
        "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"),
        ("youtube.com",), ("SAPISID", "__Secure-1PAPISID", "__Secure-3PAPISID", "LOGIN_INFO")),
    "x": Platform("x", "X / Twitter", (
        "x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com",
        "m.twitter.com", "mobile.twitter.com", "t.co"),
        ("x.com", "twitter.com", "t.co"), ("auth_token",)),
}


def youtube_video_id(parsed) -> str | None:
    """Only single-video routes are accepted, never feeds or playlists."""
    if (parsed.hostname or "").lower() == "youtu.be":
        candidate = parsed.path.strip("/") if parsed.path.count("/") <= 2 else ""
    elif parsed.path.rstrip("/") == "/watch":
        values = parse_qs(parsed.query).get("v", [])
        candidate = values[0] if len(values) == 1 else ""
    else:
        match = re.fullmatch(r"/(?:shorts|embed|live)/([A-Za-z0-9_-]+)/?", parsed.path)
        candidate = match.group(1) if match else ""
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None


def domain_matches(domain: str, roots: tuple[str, ...]) -> bool:
    domain = domain.lstrip(".").lower()
    return any(domain == root or domain.endswith("." + root) for root in roots)


def resolve_link(text: str) -> tuple[str, Platform]:
    # Douyin's copied text includes a URL surrounded by Chinese punctuation.
    links = re.findall(r'https?://[^\s<>"“”。，；！？]+', text.strip(), flags=re.I)
    for link in links:
        link = link.rstrip(",）)]};;、。")
        try:
            parsed = urlparse(link)
            if parsed.username or parsed.password or parsed.port:
                continue
        except ValueError:
            continue
        site = next((p for p in PLATFORMS.values() if (parsed.hostname or "").lower() in p.hosts), None)
        if site is None:
            continue
        if site.key == "douyin":
            video_id = (parse_qs(parsed.query).get("modal_id") or
                        parse_qs(parsed.query).get("vid") or [""])[0]
            match = re.search(r"/(?:share/)?(video|note|slides)/(\d+)", parsed.path)
            content_type = "video"
            if match:
                content_type, video_id = match.groups()
            if video_id.isdigit():
                link = f"https://www.douyin.com/{content_type}/{video_id}"
        elif site.key == "x" and parsed.hostname.lower() != "t.co":
            # The extractor supports X and Twitter, including /video/2 selectors.
            link = "https://x.com" + parsed.path
        elif site.key == "instagram":
            match = re.fullmatch(r"/(reel|reels|p|tv)/([A-Za-z0-9_-]+)/?", parsed.path)
            if match:
                kind, post_id = match.groups()
                kind = "reel" if kind == "reels" else kind
                link = f"https://www.instagram.com/{kind}/{post_id}/"
        elif site.key == "youtube":
            video_id = youtube_video_id(parsed)
            if video_id:
                link = "https://www.youtube.com/watch?" + urlencode({"v": video_id})
        return link, site
    raise ValueError("请粘贴 Bilibili、抖音、X、Instagram 或 YouTube 的作品链接，支持带文字的分享链接。")


def normalize_url(text: str) -> str:
    return resolve_link(text)[0]


def download_link(text: str) -> tuple[str, Platform, str]:
    """Validate a post, not just a supported domain; return a tracking-free key."""
    url, site = resolve_link(text)
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    host = parsed.hostname.lower()
    short = host in {"b23.tv", "v.douyin.com", "t.co"}
    valid = bool(re.fullmatch(r"/[A-Za-z0-9_-]{3,}", path)) if short else False
    if site.key == "bilibili" and not short:
        valid = bool(re.fullmatch(r"/video/(?:BV[0-9A-Za-z]+|av\d+)", path)
                     or re.fullmatch(r"/bangumi/play/(?:ep|ss)\d+", path))
        host = "www.bilibili.com"
    elif site.key == "douyin" and not short:
        valid = bool(re.fullmatch(r"/(?:video|note|slides)/\d+", path))
        host = "www.douyin.com"
    elif site.key == "x" and not short:
        valid = bool(re.fullmatch(r"/[^/]+/status/\d+(?:/video/\d+)?", path))
        host = "x.com"
    elif site.key == "instagram":
        match = re.fullmatch(r"/(?:reel|p|tv)/([A-Za-z0-9_-]+)", path)
        valid = bool(match)
        if match:
            # The same Instagram shortcode can be shared as /p/ or /reel/.
            path = "/p/" + match.group(1)
        host = "www.instagram.com"
    elif site.key == "youtube":
        video_id = youtube_video_id(parsed)
        if not video_id:
            raise ValueError("请复制单条 YouTube 视频或 Shorts 链接，暂不支持频道或播放列表。")
        canonical = "https://www.youtube.com/watch?" + urlencode({"v": video_id})
        return canonical, site, canonical
    if not valid:
        raise ValueError("这不是具体的视频或作品链接，请复制视频的分享链接。")
    query = parse_qs(parsed.query)
    selected = {"p": query["p"][0]} if site.key == "bilibili" and query.get("p", [""])[0].isdigit() else {}
    canonical = f"https://{host}{path}" + ("?" + urlencode(selected) if selected else "")
    return url, site, canonical
