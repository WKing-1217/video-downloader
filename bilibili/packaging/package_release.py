"""Keep one installer per platform and generate the public GitHub update feed."""
import hashlib
import argparse
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
                "README.md", "DESIGN.md", "UI_REVIEW.md", "V2_PLAN.md", "V2_DELIVERY.md", "requirements.txt", ".gitignore", "version.json"}):
            paths.add(path)
    for folder in ("bilibili/assets", "bilibili/packaging", "bilibili/qa", "android/package/src", "android/package/res"):
        paths.update(path for path in (ROOT / folder).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    for path in (ROOT / "android").iterdir():
        if path.is_file() and (path.suffix in {".cpp", ".h", ".qml", ".py", ".md"}
                              or path.name in {"CMakeLists.txt", "LICENSE", ".gitignore"}):
            paths.add(path)
    paths.update(ROOT / name for name in ("AGENTS.md", "PRODUCT.md", "release/RELEASE_NOTES.md", "android/package/build.gradle", "android/package/AndroidManifest.xml"))
    for path in paths:
        relative = path.relative_to(ROOT)
        if any(part in {"signing", "build", "dist", ".venv", "WebProfile"} for part in relative.parts):
            raise RuntimeError("Private/build directory entered source list")
        if path.suffix in {".jks", ".keystore", ".properties", ".db", ".sqlite", ".aar", ".apk", ".exe", ".pyc"}:
            raise RuntimeError("Non-source file entered source list")
    return sorted(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows", type=Path, default=ROOT / f"release/v{APP_VERSION}/VideoDownloader-Windows-Setup.exe")
    args = parser.parse_args()
    release = ROOT / "release"
    windows = release / "VideoDownloader-Windows-Setup.exe"
    android = release / "VideoDownloader-Android.apk"
    candidate = args.windows.resolve()
    if not candidate.is_file() or candidate.stat().st_size < 100_000_000 or not android.is_file():
        raise RuntimeError("Build the Windows package and keep the existing Android package before publishing")
    import pefile
    pe = pefile.PE(str(candidate), fast_load=True)
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
    badging = subprocess.run([str(tools[-1]), "dump", "badging", str(android)], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", check=True).stdout
    android_version = RELEASE.get("android_version", APP_VERSION)
    if f"versionName='{android_version}'" not in badging or f"versionCode='{RELEASE['android_version_code']}'" not in badging:
        raise RuntimeError("APK version does not match version.json")
    with zipfile.ZipFile(android) as archive:
        engine = [name for name in archive.namelist() if name.startswith("assets/engine/")]
        if not any(name.endswith("/bilibili_adapter.py") for name in engine):
            raise RuntimeError("APK is missing the latest shared download engine")
    if candidate != windows.resolve():
        shutil.copy2(candidate, windows)
    base = f"https://github.com/{REPOSITORY}/releases/download/v{APP_VERSION}/"
    notes = (release / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    manifest = {"schema": 1, "product": "LocalVideoDownloader", "notes": notes, "platforms": {}}
    for platform, path in (("windows", windows), ("android", android)):
        manifest["platforms"][platform] = {"version": APP_VERSION if platform == "windows" else android_version, "url": base + path.name,
                                          "sha256": sha256(path), "size": path.stat().st_size}
    (release / "update.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (release / "SHA256SUMS.txt").write_text("".join(f"{sha256(path)}  {path.name}\n" for path in (windows, android)), encoding="utf-8")
    with zipfile.ZipFile(release / "VideoDownloader-Source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for source in source_files():
            archive.write(source, source.relative_to(ROOT))
    print(json.dumps({"version": APP_VERSION, "packages": manifest["platforms"],
                      "source_files_for_github": len(source_files())}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
