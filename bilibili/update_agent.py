"""Independent, Qt-free update runner with bounded paths and restore on failure."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time

APP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{734095DC-442F-45DA-AD73-7F3B52741394}_is1"
PRODUCT = "LocalVideoDownloader"


def native_path(path):
    """Qt resource names can make rollback paths exceed legacy MAX_PATH."""
    value = str(Path(path).absolute())
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
    return Path(value)


def copy_file(source, destination):
    target = native_path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(native_path(source), target)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def within(root, relative):
    root = Path(root).resolve()
    part = Path(relative)
    if part.is_absolute() or ".." in part.parts:
        raise ValueError("安装清单包含越界路径。")
    target = (root / part).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError("安装文件超出应用目录。")
    return target


def manifest_files(app):
    path = app / "install-manifest.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("product") != PRODUCT or not isinstance(data.get("files"), list):
            raise ValueError("应用文件清单无效，未执行安装。")
        files = set(data["files"])
    else:
        # Legacy 1.x has no manifest. Restrict fallback to its known runtime.
        files = {"VideoDownloader.exe", "download-worker.exe"}
        runtime = app / "_internal"
        if runtime.is_dir():
            files.update(str(path.relative_to(native_path(app))) for path in native_path(runtime).rglob("*") if path.is_file())
    files.add("install-manifest.json")
    files.update(path.name for path in app.glob("unins[0-9][0-9][0-9].*") if path.is_file())
    for relative in files:
        within(app, relative)
    return files


def _alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000 | 0x00100000, False, int(pid))
        if not handle:
            return False
        result = kernel.WaitForSingleObject(ctypes.c_void_p(handle), 0)
        kernel.CloseHandle(ctypes.c_void_p(handle))
        return result == 0x102
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def wait_old(pid, seconds=30):
    deadline = time.monotonic() + seconds
    while _alive(pid):
        if time.monotonic() > deadline:
            raise RuntimeError("旧程序仍在运行，安装尚未开始。")
        time.sleep(0.15)


def registry_snapshot():
    if os.name != "nt":
        return {}
    import winreg
    result = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APP_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            for number in range(winreg.QueryInfoKey(key)[1]):
                name, value, kind = winreg.EnumValue(key, number)
                if isinstance(value, (str, int)):
                    result[name] = (value, kind)
    except OSError:
        pass
    return result


def restore_registry(values):
    if os.name != "nt" or not values:
        return
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, APP_KEY, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
        for name, (value, kind) in values.items():
            winreg.SetValueEx(key, name, 0, kind, value)


def backup_user_data(data, backup):
    copied = []
    for name in ("settings.json", "library.sqlite3"):
        source = data / name
        if not source.is_file():
            continue
        destination = backup / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith(".sqlite3"):
            connection = sqlite3.connect(source)
            target = sqlite3.connect(destination)
            try:
                connection.backup(target)
            finally:
                target.close()
                connection.close()
        else:
            copy_file(source, destination)
        copied.append(name)
    return copied


def execute_update(plan, *, installer_runner=None, app_launcher=None, readiness=None):
    """Injected callables allow failure tests without touching a real install."""
    if plan.get("product") != PRODUCT or plan.get("schema") != 1:
        raise ValueError("更新计划不属于本程序。")
    if not re.fullmatch(r"[a-f0-9]{32}", str(plan.get("nonce") or "")):
        raise ValueError("更新计划标识无效。")
    for value in (plan.get("version"), plan.get("previous_version")):
        if not isinstance(value, str) or not re.fullmatch(r"\d{1,4}\.\d{1,4}\.\d{1,4}", value):
            raise ValueError("更新版本号无效。")
    if tuple(map(int, plan["version"].split("."))) <= tuple(map(int, plan["previous_version"].split("."))):
        raise ValueError("拒绝安装相同或更旧的版本。")
    app = Path(plan["app_dir"]).resolve()
    cache = Path(plan["cache_dir"]).resolve()
    data = Path(plan["data_dir"]).resolve()
    installer = Path(plan["installer"]).resolve()
    if (not installer.is_relative_to(cache) or cache.is_relative_to(app) or data.is_relative_to(app)
            or not Path(plan["handshake"]).resolve().is_relative_to(cache)):
        raise ValueError("更新缓存或用户数据目录不安全。")
    if not (app / "VideoDownloader.exe").is_file():
        raise ValueError("原程序不存在，已停止更新。")
    with installer.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != plan["sha256"] or installer.stat().st_size != plan["size"]:
        raise ValueError("更新包已发生变化，未执行安装。")
    backup = cache / ("rollback-" + plan["nonce"])
    if backup.exists():
        raise ValueError("本次更新备份目录已存在，请重新检查更新。")
    originals = manifest_files(app)
    acknowledgement = plan.get("helper_ready")
    if acknowledgement:
        if not Path(acknowledgement).resolve().is_relative_to(cache):
            raise ValueError("更新助手状态文件路径无效。")
        write_json(acknowledgement, {"nonce": plan["nonce"], "pid": os.getpid()})
    wait_old(int(plan.get("old_pid") or 0))
    backup.mkdir(parents=True)
    protected = [Path(path).resolve() for path in plan.get("protected_roots", [])]

    def protected_file(path):
        return any(path.is_relative_to(root) for root in protected if root != app and root.is_relative_to(app))

    copied = []
    for relative in sorted(originals):
        source = within(app, relative)
        if native_path(source).is_file() and not protected_file(source):
            destination = within(backup / "program", relative)
            copy_file(source, destination)
            copied.append(relative)
    user_files = backup_user_data(data, backup / "user")
    registry = registry_snapshot() if plan.get("manage_registry") else {}
    write_json(backup / "backup.json", {"product": PRODUCT, "files": copied, "user_files": user_files,
                                       "previous_version": plan["previous_version"]})
    result_file = data / "updates/install-result.json"
    created_process = None
    hidden = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}

    def launch():
        environment = {**os.environ, "VIDEO_DOWNLOADER_UPDATE_HANDSHAKE": plan["handshake"],
                       "VIDEO_DOWNLOADER_UPDATE_NONCE": plan["nonce"], "PYINSTALLER_RESET_ENVIRONMENT": "1"}
        with (cache / "new-version-startup.log").open("wb") as log:
            return subprocess.Popen([str(app / "VideoDownloader.exe")], cwd=app, env=environment,
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, **hidden)

    def ready(process):
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            try:
                value = json.loads(Path(plan["handshake"]).read_text(encoding="utf-8"))
                if value.get("version") == plan["version"] and value.get("nonce") == plan["nonce"]:
                    return True
            except (OSError, ValueError):
                pass
            if process.poll() is not None:
                return False
            time.sleep(0.2)
        return False

    try:
        if installer_runner:
            code = installer_runner(installer, app)
        else:
            command = [str(installer), "/SP-", "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                       "/CLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS", "/DIR=" + str(app),
                       "/LOG=" + str(cache / "install.log")]
            code = subprocess.run(command, cwd=cache, timeout=900, **hidden).returncode
        if code != 0:
            raise RuntimeError(f"安装程序未成功完成（退出码 {code}）。")
        created_process = (app_launcher or launch)()
        if not (readiness or ready)(created_process):
            raise RuntimeError("新版未能正常启动。")
        result = {"success": True, "version": plan["version"], "message": "更新成功，已重新启动新版。", "rollback": False}
        write_json(result_file, result)
        return result
    except Exception as error:
        if created_process is not None and created_process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(created_process.pid), "/T", "/F"],
                               capture_output=True, timeout=15, **hidden)
            else:
                created_process.terminate()
            created_process.wait(timeout=15)
        try:
            try:
                new_files = manifest_files(app)
            except (OSError, ValueError, TypeError):
                # A broken new manifest must not prevent restoration of old files.
                new_files = set()
            for relative in new_files - set(copied):
                target = within(app, relative)
                if native_path(target).is_file() and not protected_file(target):
                    native_path(target).unlink()
            for relative in copied:
                destination = within(app, relative)
                copy_file(within(backup / "program", relative), destination)
            for name in user_files:
                destination = data / name
                if name.endswith(".sqlite3"):
                    for suffix in ("-wal", "-shm"):
                        Path(str(destination) + suffix).unlink(missing_ok=True)
                copy_file(backup / "user" / name, destination)
            if registry:
                restore_registry(registry)
            result = {"success": False, "version": plan["version"], "rollback": True,
                      "message": str(error) + " 已恢复原版本，视频与登录资料保留。"}
            write_json(result_file, result)
            if not plan.get("no_restart_on_failure"):
                subprocess.Popen([str(app / "VideoDownloader.exe")], cwd=app, **hidden)
            return result
        except Exception as restore_error:
            result = {"success": False, "rollback": False, "version": plan["version"],
                      "message": str(error) + " 自动恢复未完成：" + str(restore_error), "backup": str(backup)}
            write_json(result_file, result)
            return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    args = parser.parse_args()
    plan = None
    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        result = execute_update(plan)
    except Exception as error:
        result = {"success": False, "message": str(error)}
        # If validation completed and the old GUI has already closed, failures
        # before installation (for example a full backup disk) restart it intact.
        if plan and plan.get("helper_ready"):
            try:
                ack = json.loads(Path(plan["helper_ready"]).read_text(encoding="utf-8"))
                if ack.get("nonce") == plan["nonce"] and not _alive(plan.get("old_pid")):
                    write_json(Path(plan["data_dir"]) / "updates/install-result.json", result)
                    if not plan.get("no_restart_on_failure"):
                        subprocess.Popen([str(Path(plan["app_dir"]) / "VideoDownloader.exe")],
                                         cwd=plan["app_dir"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, ValueError, KeyError):
                pass
    if not result["success"] and os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, result["message"], "视频下载器 · 更新结果", 0x10)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
