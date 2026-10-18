"""Publish this application with Git Credential Manager; credentials stay in memory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bilibili"))
from app_version import APP_VERSION, REPOSITORY
from network_settings import windows_system_proxy


class ProgressFile:
    def __init__(self, stream, name):
        self.stream, self.name = stream, name
        self.size = os.fstat(stream.fileno()).st_size
        self.reported = 0

    def __len__(self):
        return self.size

    def tell(self):
        return self.stream.tell()

    def read(self, size=-1):
        block = self.stream.read(size)
        current = self.stream.tell()
        if current - self.reported >= 16 * 1024 * 1024 or current == self.size:
            self.reported = current
            print(json.dumps({"asset": self.name, "sent_bytes": current, "total": self.size}), flush=True)
        return block


def session():
    owner = REPOSITORY.split("/")[0]
    environment = {**os.environ, "GCM_INTERACTIVE": "never", "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(["git", "credential", "fill"],
                            input=f"protocol=https\nhost=github.com\nusername={owner}\n\n",
                            capture_output=True, text=True, env=environment, timeout=30,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if result.returncode or not fields.get("password"):
        raise RuntimeError("GitHub 登录不可用，请先通过 Git Credential Manager 登录。")
    client = requests.Session()
    client.headers.update({"Authorization": "Bearer " + fields["password"],
                           "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"})
    proxy = windows_system_proxy()
    if proxy:
        client.proxies.update({"http": proxy, "https": proxy})
    return client


def api(client, method, path, *, acceptable=(200, 201, 204), **kwargs):
    response = client.request(method, "https://api.github.com" + path, timeout=(15, 90), **kwargs)
    if response.status_code not in acceptable:
        raise RuntimeError(f"GitHub {method} {path}: HTTP {response.status_code}")
    return response.json() if response.content else {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("whoami", "create", "publish"))
    args = parser.parse_args()
    with session() as client:
        user = api(client, "GET", "/user")
        owner, name = REPOSITORY.split("/")
        if user["login"].lower() != owner.lower():
            raise RuntimeError("GitHub 登录账号与发布仓库不一致，已停止。")
        if args.action == "whoami":
            print(json.dumps({"login": user["login"], "id": user["id"], "authenticated": True}), flush=True)
            return
        if args.action == "create":
            existing = client.get(f"https://api.github.com/repos/{REPOSITORY}", timeout=20)
            if existing.status_code == 404:
                repo = api(client, "POST", "/user/repos", json={"name": name, "private": False,
                           "description": "Qt 视频下载器 · 自动识别 Bilibili / 抖音 / X，支持自动检查更新。",
                           "auto_init": True})
                print(json.dumps({"created": True, "url": repo["html_url"], "default_branch": repo["default_branch"]}), flush=True)
            elif existing.status_code == 200:
                print(json.dumps({"created": False, "url": existing.json()["html_url"]}), flush=True)
            else:
                raise RuntimeError(f"Cannot inspect repository: HTTP {existing.status_code}")
            return
        release_dir = ROOT / "release"
        tag = "v" + APP_VERSION
        response = client.get(f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{tag}", timeout=20)
        instructions = release_dir / "RELEASE_NOTES.md"
        if instructions.is_file():
            body = instructions.read_text(encoding="utf-8")
        else:
            manifest = json.loads((release_dir / "update.json").read_text(encoding="utf-8"))
            body = (f"# 视频下载器 {APP_VERSION}\n\n" + manifest.get("notes", "")
                    + "\n\nWindows 下载 VideoDownloader-Windows-Setup.exe；Android 下载 VideoDownloader-Android.apk。"
                    + "\n\n安装到原目录即可升级。使用方法和构建说明见仓库 README。")
        if response.status_code == 404:
            release = api(client, "POST", f"/repos/{REPOSITORY}/releases", json={"tag_name": tag,
                          "name": "视频下载器 " + APP_VERSION, "body": body, "draft": True})
        elif response.status_code == 200:
            release = response.json()
        else:
            raise RuntimeError(f"Cannot inspect release: HTTP {response.status_code}")
        assets = {asset["name"]: asset for asset in release.get("assets", [])}
        names = ("VideoDownloader-Windows-Setup.exe", "VideoDownloader-Android.apk", "VideoDownloader-Source.zip", "SHA256SUMS.txt", "update.json")
        for name in names:
            path = release_dir / name
            with path.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            old = assets.get(name)
            if old and old.get("digest") == "sha256:" + sha and old.get("size") == path.stat().st_size:
                print(json.dumps({"asset": name, "reused": True}), flush=True)
                continue
            if old:
                api(client, "DELETE", f"/repos/{REPOSITORY}/releases/assets/{old['id']}")
            print(json.dumps({"asset": name, "uploading_bytes": path.stat().st_size}), flush=True)
            with path.open("rb") as stream:
                uploaded = client.post(release["upload_url"].split("{")[0], params={"name": name},
                                       data=ProgressFile(stream, name), headers={"Content-Type": "application/octet-stream"}, timeout=(20, 1200))
            if uploaded.status_code != 201:
                raise RuntimeError(f"Upload failed for {name}: HTTP {uploaded.status_code}")
            asset = uploaded.json()
            if asset.get("size") != path.stat().st_size or asset.get("digest") not in (None, "sha256:" + sha):
                raise RuntimeError("Uploaded asset did not pass byte-length/hash verification: " + name)
            print(json.dumps({"asset": name, "uploaded": True, "sha256": sha}), flush=True)
        published = api(client, "PATCH", f"/repos/{REPOSITORY}/releases/{release['id']}",
                        json={"draft": False, "make_latest": "true", "body": body})
        print(json.dumps({"published": True, "url": published["html_url"]}), flush=True)
        # Preserve previous formal releases for recovery. Test fixtures never
        # create, replace or remove published resources.


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, requests.RequestException, subprocess.SubprocessError) as error:
        print(json.dumps({"error": str(error) if isinstance(error, RuntimeError) else type(error).__name__}), flush=True)
        raise SystemExit(1)
