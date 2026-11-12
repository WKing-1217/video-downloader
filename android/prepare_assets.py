"""Bundle only application code, yt-dlp and CA roots; never browser profiles."""
from pathlib import Path
import shutil
import zipfile
import json
import yt_dlp
import certifi
import yt_dlp_ejs
from importlib.metadata import version
from packaging.requirements import Requirement
from importlib.metadata import requires

root = Path(__file__).resolve().parent
source = root.parent / "bilibili"
engine = root / "package/assets/engine"
engine.mkdir(parents=True, exist_ok=True)
identity = json.loads((source / "version.json").read_text(encoding="utf-8"))
java_version = root / "package/src/com/localvideodownloader/app/AppVersion.java"
java_version.write_text('package com.localvideodownloader.app;\npublic final class AppVersion {\n'
                       + '  public static final String VERSION = ' + json.dumps(identity.get('android_version', identity['version'])) + ';\n'
                       + '  public static final String REPOSITORY = ' + json.dumps(identity['repository']) + ';\n'
                       + '  public static final String UPDATE_URL = "https://github.com/" + REPOSITORY + "/releases/latest/download/update.json";\n}\n', encoding="utf-8")
modules = ["downloader.py", "platform_links.py", "douyin_adapter.py", "douyin_gallery.py",
           "browser_accounts.py", "network_settings.py", "runtime_paths.py", "parallel_http.py", "bilibili_adapter.py",
           "media_export.py"]
for name in modules:
    shutil.copy2(source / name, engine / name)
shutil.copy2(root / "android_bootstrap.py", engine / "android_bootstrap.py")
shutil.copy2(certifi.where(), engine / "cacert.pem")
package = Path(yt_dlp.__file__).resolve().parent
with zipfile.ZipFile(engine / "yt_dlp.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in package.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
            archive.write(path, "yt_dlp/" + path.relative_to(package).as_posix())
print("Android assets ready:", len(modules), "shared modules; yt-dlp and CA roots.")

# EJS resource files need real filesystem paths for QuickJS on Android. Keep
# package metadata and solver scripts together rather than depending on remote
# script downloads from the phone.
ejs = Path(yt_dlp_ejs.__file__).resolve().parent
ejs_target = engine / "yt_dlp_ejs"
for dependency in requires("yt-dlp") or []:
    parsed = Requirement(dependency)
    if parsed.name == "yt-dlp-ejs" and version("yt-dlp-ejs") not in parsed.specifier:
        raise RuntimeError("yt-dlp-ejs does not match the installed yt-dlp")
for path in ejs.rglob("*"):
    if path.is_file() and path.suffix in {".py", ".js"} and "__pycache__" not in path.parts:
        target = ejs_target / path.relative_to(ejs)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
if not list(ejs_target.rglob("*.js")):
    raise RuntimeError("YouTube solver scripts were not bundled")
print("Android YouTube solver ready:", version("yt-dlp-ejs"), "QuickJS uses native libqjs.so")
