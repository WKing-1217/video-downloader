"""Real Inno install + frozen helper + restart, over an isolated released build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from app_version import APP_VERSION
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--baseline", type=Path, default=root / "dist/VideoDownloader")
parser.add_argument("--installer", type=Path, default=root / "build/v2-qa-installer/VideoDownloader-Windows-Setup.exe",
                    help="An isolated-QA AppId installer, never the public installer")
args = parser.parse_args()
work = root / "build" / ("v2-upgrade-" + str(time.time_ns()))
app = work / "application"
data = work / "preferences/LocalVideoDownloader"
cache = data / "updates"
output = work / "existing-videos"
for folder in (cache, output, data / "WebProfile"):
    folder.mkdir(parents=True, exist_ok=True)
baseline = args.baseline.resolve()
assert baseline.is_relative_to(root.resolve())
baseline_version = json.loads((baseline / "_internal/version.json").read_text())["version"]
assert baseline_version in {"1.0.4", "2.0.0", "2.1.0", "2.1.1", "2.1.2", "2.1.3"}, baseline_version
shutil.copytree(baseline, app)
fixture = root / "build/v2-fixtures/sample.mp4"
history = output / "原有的视频.mp4"
shutil.copy2(fixture, history)
video_hash = hashlib.sha256(history.read_bytes()).hexdigest()
settings = {"output": str(output), "auto_update": False, "auto_login": False, "browser_source": "chrome:Default",
            "migration_fixture": "preserve-v" + baseline_version}
(data / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
(data / "WebProfile/preserve-marker.txt").write_text("existing profile is not removed", encoding="utf-8")
installer = cache / "verified-qa-installer.exe"
candidate = args.installer.resolve()
assert candidate.is_relative_to((root / "build").resolve()) and candidate.is_file(), candidate
shutil.copy2(candidate, installer)
helper = cache / "independent-helper.exe"
shutil.copy2(root / "dist/v2/VideoDownloader/update-helper.exe", helper)
nonce = uuid.uuid4().hex
plan = {"product": "LocalVideoDownloader", "schema": 1, "version": APP_VERSION, "previous_version": baseline_version,
        "nonce": nonce, "app_dir": str(app), "data_dir": str(data), "cache_dir": str(cache), "old_pid": 0,
        "installer": str(installer), "sha256": hashlib.file_digest(installer.open("rb"), "sha256").hexdigest(),
        "size": installer.stat().st_size, "handshake": str(cache / "new-ready.json"),
        "helper_ready": str(cache / "helper-ready.json"), "protected_roots": [str(output)], "manage_registry": False,
        "no_restart_on_failure": True}
target = cache / "plan.json"
target.write_text(json.dumps(plan), encoding="utf-8")
environment = os.environ.copy()
environment.update(LOCALAPPDATA=str(data.parent), QT_QPA_PLATFORM="offscreen")
environment.pop("VIDEO_DOWNLOADER_OUTPUT", None)
started = time.monotonic()
with (work / "helper.log").open("wb") as log:
    process = subprocess.Popen([str(helper), "--plan", str(target)], cwd=cache, env=environment,
                               stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    print(json.dumps({"work": str(work), "helper_pid": process.pid}), flush=True)
    code = process.wait(timeout=240)
result = json.loads((data / "updates/install-result.json").read_text(encoding="utf-8"))
ready = json.loads((cache / "new-ready.json").read_text(encoding="utf-8")) if (cache / "new-ready.json").exists() else {}
try:
    assert code == 0 and result["success"], result
    assert ready["version"] == APP_VERSION and ready["nonce"] == nonce and ready["page"] == 0, ready
    assert ready["output"] == str(output), ready
    assert hashlib.sha256(history.read_bytes()).hexdigest() == video_hash
    assert json.loads((data / "settings.json").read_text(encoding="utf-8")) == settings
    assert (data / "WebProfile/preserve-marker.txt").read_text() == "existing profile is not removed"
    deadline = time.monotonic() + 30
    records = []
    while time.monotonic() < deadline:
        database = sqlite3.connect(data / "library.sqlite3")
        try:
            records = database.execute("SELECT title,path,state FROM media").fetchall()
        finally:
            database.close()
        if records:
            break
        time.sleep(.1)
    assert any(row[1] == str(history) for row in records), records
    value = {"passed": True, "real_installer": True, "real_frozen_helper": True, "isolated_baseline": baseline_version,
             "installed": APP_VERSION, "restarted": ready, "preserved_settings": True, "preserved_video_sha256": video_hash,
             "preserved_login_profile": True, "historical_video_imported": True,
             "elapsed": round(time.monotonic() - started, 2), "installer_result": result}
    (work / "report.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False), flush=True)
finally:
    if ready.get("pid"):
        # This PID was returned by our nonce-bound application inside this QA directory.
        subprocess.run(["taskkill", "/PID", str(ready["pid"]), "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
    import winreg
    for qa_key in (r"Software\Microsoft\Windows\CurrentVersion\Uninstall\LocalVideoDownloader-V2-Isolated-QA_is1",
                   r"Software\LocalVideoDownloader-V2-Isolated-QA"):
        try:
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, qa_key, winreg.KEY_WOW64_64KEY)
        except FileNotFoundError:
            pass
