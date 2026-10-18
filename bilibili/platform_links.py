"""Recognize supported video links without requesting any web page."""
from dataclasses import dataclass
import re
from urllib.parse import parse_qs, urlparse


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
    "x": Platform("x", "X / Twitter", (
        "x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com",
        "m.twitter.com", "mobile.twitter.com", "t.co"),
        ("x.com", "twitter.com", "t.co"), ("auth_token",)),
}


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
        return link, site
    raise ValueError("请粘贴 Bilibili、抖音或 X（Twitter）的视频链接，支持带文字的分享链接。")


def normalize_url(text: str) -> str:
    return resolve_link(text)[0]
