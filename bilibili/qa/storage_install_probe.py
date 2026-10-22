"""Isolated real Inno first install, frozen storage flow, and preserving upgrade."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import winreg

from PySide6.QtGui import QColor, QImage

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--bundle", type=Path, default=root / "dist/storage-review/VideoDownloader")
args = parser.parse_args()
token = uuid.uuid4().hex[:12]
work = root / "build/storage-review" / ("install-" + token)
work.mkdir(parents=True)
bundle = args.bundle.resolve()
assert bundle.is_relative_to(root.resolve())
compiler = Path("D:/Program/Inno Setup 6/ISCC.exe")
registry = "Software\\LocalVideoDownloader-Storage-QA-" + token
settings_subdir = "LocalVideoDownloader-Storage-QA-" + token
app_id = "LocalVideoDownloader-Storage-QA-" + token
version = json.loads((root / "version.json").read_text())["version"]
data = work / "preferences/LocalVideoDownloader"
data.mkdir(parents=True)
initial, target = work / "安装时选择的视频目录", work / "设置中更改的视频目录"
application = work / "application"
installer = work / "installer/VideoDownloader-Windows-Setup.exe"
report = {"passed": False, "checks": {}, "work": str(work), "qa_registry": registry}

def check(name, condition):
    assert condition, name
    report["checks"][name] = True

def seed_value():
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        return winreg.QueryValueEx(key, "InitialOutputDirectory")[0]

def run_installer(directory, name):
    result = subprocess.run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/SP-", "/NORESTART",
                             "/DIR=" + str(application), "/VIDEODIR=" + str(directory),
                             "/LOG=" + str(work / (name + ".log"))], timeout=120)
    check(name + "_exit_code", result.returncode == 0)

environment = os.environ.copy()
environment.update(LOCALAPPDATA=str(data.parent), VIDEO_DOWNLOADER_REGISTRY_KEY=registry, QT_QPA_PLATFORM="offscreen",
                   PATH=os.environ.get("WINDIR", "C:/Windows") + "/System32;" + os.environ.get("WINDIR", "C:/Windows"))
environment.pop("VIDEO_DOWNLOADER_OUTPUT", None)
process = None
try:
    with (work / "compile.log").open("wb") as log:
        result = subprocess.run([str(compiler), "/Q", "/DAppVersion=" + version, "/DQaInstall=1", "/DSetupAppId=" + app_id,
                                 "/DSettingsRegistryKey=" + registry, "/DSettingsSubdir=" + settings_subdir,
                                 "/DBundleDir=" + str(bundle), "/DReleaseDir=" + str(installer.parent),
                                 str(root / "packaging/installer.iss")], stdout=log, stderr=log, timeout=120)
    check("real_installer_compiled", result.returncode == 0 and installer.is_file())
    run_installer(initial, "first_install")
    check("first_install_saves_selected_directory", seed_value() == str(initial))
    initial.mkdir()
    video = initial / "原有视频.mp4"
    shutil.copy2(root / "build/v2-fixtures/sample.mp4", video)
    info = {"title": "原有视频", "duration": 6, "size": video.stat().st_size}
    video.with_suffix(".mp4.info.json").write_text(json.dumps(info), encoding="utf-8")
    folder = initial / "原有图文"
    folder.mkdir()
    assets = []
    for number in range(2):
        image = QImage(640, 420, QImage.Format_RGB32)
        image.fill(QColor("#666666" if number else "#cccccc"))
        path = folder / f"{number:03d}.png"
        assert image.save(str(path))
        assets.append({"kind": "image", "path": str(path)})
    content = {"title": "原有图文", "content_type": "gallery", "assets": assets,
               "size": sum(Path(asset["path"]).stat().st_size for asset in assets)}
    (folder / "作品信息.json").write_text(json.dumps(content), encoding="utf-8")
    (data / "settings.json").write_text(json.dumps({"auto_login": False, "auto_update": False}), encoding="utf-8")
    (work / "qa-storage-fixture.json").write_text(json.dumps({"product": "LocalVideoDownloader", "nonce": token,
          "initial": str(initial), "target": str(target)}, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"work": str(work), "stage": "frozen storage flow"}), flush=True)
    frozen_report = work / "frozen-report.json"
    with (work / "frozen-process.log").open("wb") as log:
        process = subprocess.Popen([str(application / "VideoDownloader.exe"), "--verify-storage", str(frozen_report)],
                                   cwd=application, env=environment, stdout=log, stderr=log)
        code = process.wait(timeout=110)
    check("frozen_app_exits_cleanly", code == 0 and frozen_report.is_file())
    frozen = json.loads(frozen_report.read_text(encoding="utf-8"))
    check("frozen_storage_and_delete_flow", frozen["passed"])
    report["frozen"] = frozen
    settings_before = (data / "settings.json").read_bytes()
    run_installer(work / "升级时不应生效的目录", "upgrade")
    check("upgrade_preserves_original_registry_seed", seed_value() == str(initial))
    check("upgrade_preserves_current_settings", (data / "settings.json").read_bytes() == settings_before)
    handshake = work / "restart-ready.json"
    environment.update(VIDEO_DOWNLOADER_UPDATE_HANDSHAKE=str(handshake), VIDEO_DOWNLOADER_UPDATE_NONCE=token)
    with (work / "restarted.log").open("wb") as log:
        process = subprocess.Popen([str(application / "VideoDownloader.exe")], cwd=application, env=environment, stdout=log, stderr=log)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not handshake.exists() and process.poll() is None:
            time.sleep(.1)
        check("upgraded_app_restarts", handshake.is_file())
        ready = json.loads(handshake.read_text(encoding="utf-8"))
        check("upgraded_app_uses_new_directory", ready["output"] == str(target) and ready["nonce"] == token)
        process.terminate()
        process.wait(timeout=15)
    report.update(passed=True, installer_sha256=hashlib.file_digest(installer.open("rb"), "sha256").hexdigest(),
                  restart=ready)
finally:
    if process is not None and process.poll() is None:
        # Only the process launched above, whose data is inside this QA directory.
        process.terminate()
        process.wait(timeout=15)
    for key in (registry, "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + app_id + "_is1"):
        try:
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, key, winreg.KEY_WOW64_64KEY)
        except FileNotFoundError:
            pass
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
assert report["passed"]
