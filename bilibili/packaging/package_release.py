"""Keep one installer per platform and generate the public GitHub update feed."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bilibili"))
from app_version import APP_VERSION, RELEASE, REPOSITORY


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_files():
    paths = set()
    for path in (ROOT / "bilibili").iterdir():
        if path.is_file() and (path.suffix in {".py", ".bat", ".ps1"} or path.name in {
                "README.md", "DESIGN.md", "requirements.txt", ".gitignore", "version.json"}):
            paths.add(path)
    for folder in ("bilibili/assets", "bilibili/packaging", "android/package/src", "android/package/res"):
        paths.update(path for path in (ROOT / folder).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    for path in (ROOT / "android").iterdir():
        if path.is_file() and (path.suffix in {".cpp", ".h", ".qml", ".py", ".md"}
                              or path.name in {"CMakeLists.txt", "LICENSE", ".gitignore"}):
            paths.add(path)
    paths.update(ROOT / name for name in ("PRODUCT.md", "android/package/build.gradle", "android/package/AndroidManifest.xml"))
    for path in paths:
        relative = path.relative_to(ROOT)
        if any(part in {"signing", "build", "dist", ".venv", "WebProfile"} for part in relative.parts):
            raise RuntimeError("Private/build directory entered source list")
        if path.suffix in {".jks", ".keystore", ".properties", ".db", ".sqlite", ".aar", ".apk", ".exe", ".pyc"}:
            raise RuntimeError("Non-source file entered source list")
    return sorted(paths)


def main():
    release = ROOT / "release"
    windows = release / "VideoDownloader-Windows-Setup.exe"
    android = release / "VideoDownloader-Android.apk"
    built_apk = ROOT / "android/build/android-build/build/outputs/apk/release/android-build-release.apk"
    if not windows.is_file() or windows.stat().st_size < 100_000_000 or not built_apk.is_file():
        raise RuntimeError("Build both installation packages before publishing")
    import pefile
    pe = pefile.PE(str(windows), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
    version = pe.VS_FIXEDFILEINFO[0]
    actual = (version.FileVersionMS >> 16, version.FileVersionMS & 65535, version.FileVersionLS >> 16)
    pe.close()
    if actual != tuple(map(int, APP_VERSION.split("."))):
        raise RuntimeError("Windows installer version does not match version.json")
    sdk = Path(os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME") or "D:/Programs/Android/Sdk")
    tools = sorted((sdk / "build-tools").glob("*/aapt2.exe"))
    if not tools:
        raise RuntimeError("Android SDK aapt2 is needed to verify the APK version")
    badging = subprocess.run([str(tools[-1]), "dump", "badging", str(built_apk)], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", check=True).stdout
    if f"versionName='{APP_VERSION}'" not in badging or f"versionCode='{RELEASE['android_version_code']}'" not in badging:
        raise RuntimeError("APK version does not match version.json")
    with zipfile.ZipFile(built_apk) as archive:
        engine = [name for name in archive.namelist() if name.startswith("assets/engine/")]
        if not any(name.endswith("/bilibili_adapter.py") for name in engine):
            raise RuntimeError("APK is missing the latest shared download engine")
    shutil.copy2(built_apk, android)
    base = f"https://github.com/{REPOSITORY}/releases/download/v{APP_VERSION}/"
    notes = "加入 GitHub 自动检查更新与手动更新入口；发布目录仅保留最新版；保留完整音画、并发下载和 B 站备用节点切换。"
    manifest = {"schema": 1, "product": "LocalVideoDownloader", "notes": notes, "platforms": {}}
    for platform, path in (("windows", windows), ("android", android)):
        manifest["platforms"][platform] = {"version": APP_VERSION, "url": base + path.name,
                                          "sha256": sha256(path), "size": path.stat().st_size}
    (release / "update.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (release / "SHA256SUMS.txt").write_text("".join(f"{sha256(path)}  {path.name}\n" for path in (windows, android)), encoding="utf-8")
    # Only named, older app artifacts in this exact directory are removed.
    removed = []
    for path in release.iterdir():
        match = re.fullmatch(r"VideoDownloader-(?:Windows-Setup|Android|Source)-(\d+\.\d+\.\d+)\.(?:exe|apk|zip)", path.name)
        if match and tuple(map(int, match[1].split("."))) < tuple(map(int, APP_VERSION.split("."))):
            path.unlink()
            removed.append(path.name)
        elif re.fullmatch(r"验证记录-\d+\.\d+\.\d+\.json", path.name):
            path.unlink()
            removed.append(path.name)
    print(json.dumps({"version": APP_VERSION, "packages": manifest["platforms"], "removed_old_files": removed,
                      "source_files_for_github": len(source_files())}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
