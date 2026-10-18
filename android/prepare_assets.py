"""Bundle only application code, yt-dlp and CA roots; never browser profiles."""
from pathlib import Path
import shutil
import zipfile
import json
import yt_dlp
import certifi

root = Path(__file__).resolve().parent
source = root.parent / "bilibili"
engine = root / "package/assets/engine"
engine.mkdir(parents=True, exist_ok=True)
identity = json.loads((source / "version.json").read_text(encoding="utf-8"))
java_version = root / "package/src/com/localvideodownloader/app/AppVersion.java"
java_version.write_text('package com.localvideodownloader.app;\npublic final class AppVersion {\n'
                       + '  public static final String VERSION = ' + json.dumps(identity['version']) + ';\n'
                       + '  public static final String REPOSITORY = ' + json.dumps(identity['repository']) + ';\n'
                       + '  public static final String UPDATE_URL = "https://github.com/" + REPOSITORY + "/releases/latest/download/update.json";\n}\n', encoding="utf-8")
modules = ["downloader.py", "platform_links.py", "douyin_adapter.py", "douyin_gallery.py",
           "browser_accounts.py", "network_settings.py", "runtime_paths.py", "parallel_http.py", "bilibili_adapter.py"]
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
