"""Paths shared by the Qt app, installed worker and Android runtime."""
import json
import os
from pathlib import Path
import sys

SOURCE = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else SOURCE
SETTINGS = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LocalVideoDownloader/settings.json"


def data_dir():
    folder = SETTINGS.parent
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def output_dir():
    override = os.environ.get("VIDEO_DOWNLOADER_OUTPUT")
    if override:
        return Path(override).resolve()
    try:
        saved = json.loads(SETTINGS.read_text(encoding="utf-8")).get("output")
        if saved:
            return Path(saved).resolve()
    except (OSError, ValueError, AttributeError):
        pass
    if FROZEN:
        return Path.home() / "Videos/视频下载器/video"
    return SOURCE.parent / "video"


def read_settings():
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(**values):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    data = {**read_settings(), **values}
    temporary = SETTINGS.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(SETTINGS)


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
