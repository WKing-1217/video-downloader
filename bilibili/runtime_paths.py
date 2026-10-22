"""Paths shared by the Qt app, installed worker and Android runtime."""
import json
import os
from pathlib import Path
import sys
import threading
import uuid

SOURCE = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else SOURCE
SETTINGS = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LocalVideoDownloader/settings.json"
_INITIAL_SETTINGS = SETTINGS
_SETTINGS_LOCK = threading.RLock()


def settings_path():
    # Honour explicit test overrides, while reading the current data environment.
    if SETTINGS != _INITIAL_SETTINGS:
        return SETTINGS
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LocalVideoDownloader/settings.json"


def data_dir():
    folder = settings_path().parent
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def output_dir():
    override = os.environ.get("VIDEO_DOWNLOADER_OUTPUT")
    if override:
        return Path(override).resolve()
    try:
        saved = read_settings().get("output")
        if saved:
            return Path(saved).resolve()
    except (OSError, ValueError, AttributeError):
        pass
    if FROZEN:
        try:
            import winreg
            registry_key = os.environ.get("VIDEO_DOWNLOADER_REGISTRY_KEY", r"Software\LocalVideoDownloader")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_key, 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                chosen = winreg.QueryValueEx(key, "InitialOutputDirectory")[0]
                if isinstance(chosen, str) and Path(chosen).is_absolute():
                    return Path(chosen).resolve()
        except (ImportError, OSError):
            pass
        return Path.home() / "Videos/视频下载器/video"
    return SOURCE.parent / "video"


def read_settings():
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(**values):
    with _SETTINGS_LOCK:
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {**read_settings(), **values}
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def save_output(folder):
    save_settings(output=str(Path(folder).resolve()))


def worker_command(arguments):
    if FROZEN:
        return str(APP_DIR / "download-worker.exe"), list(arguments)
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    return str(executable), [str(SOURCE / "downloader.py"), *arguments]


def tool(name):
    native = os.environ.get("VIDEO_DOWNLOADER_NATIVE_LIBS")
    if native:
        return str(Path(native) / f"lib{name}.so")
    bundled = Path(getattr(sys, "_MEIPASS", SOURCE)) / "tools" / (name + ".exe")
    return str(bundled) if bundled.is_file() else name


def configure_tools():
    folder = Path(getattr(sys, "_MEIPASS", SOURCE)) / "tools"
    if folder.is_dir():
        os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
