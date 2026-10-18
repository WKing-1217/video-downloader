"""Keep Bilibili's own CDN alternatives for each identical media format."""
from yt_dlp.extractor.bilibili import BiliBiliIE as UpstreamBiliBiliIE


class BiliBiliIE(UpstreamBiliBiliIE):
    def extract_formats(self, play_info):
        formats = super().extract_formats(play_info)
        sources = {}
        pending = [play_info]
        while pending:
            node = pending.pop()
            if isinstance(node, list):
                pending.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            primary = node.get("baseUrl") or node.get("base_url") or node.get("url")
            backups = node.get("backupUrl") or node.get("backup_url") or []
            if isinstance(backups, str):
                backups = [backups]
            if isinstance(primary, str) and isinstance(backups, list):
                sources.setdefault(primary, []).extend(url for url in backups
                                                      if isinstance(url, str) and url.startswith(("https://", "http://")))
            pending.extend(value for value in node.values() if isinstance(value, (dict, list)))
        for fmt in formats:
            backups = sources.get(fmt.get("url"))
            if backups:
                fmt["_backup_urls"] = list(dict.fromkeys(backups))
        return formats
