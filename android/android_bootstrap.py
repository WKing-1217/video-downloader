"""Run the shared, tested downloader inside the bundled Android Python."""
import os
from pathlib import Path
import runpy
import signal
import sys

engine = Path(__file__).resolve().parent
try:
    os.setsid()
except OSError:
    pass


def terminate(signum, frame):
    if os.getpgrp() == os.getpid():
        os.killpg(os.getpgrp(), signal.SIGKILL)
    raise SystemExit(143)


signal.signal(signal.SIGTERM, terminate)
sys.path[:0] = [str(engine), str(engine / "yt_dlp.zip")]
from runtime_paths import tool
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor

# Android installs executable helpers as .so files in nativeLibraryDir. Supply
# their actual paths rather than requiring programs named ffmpeg/ffprobe in PATH.
FFmpegPostProcessor._determine_executables = lambda self: {"ffmpeg": tool("ffmpeg"), "ffprobe": tool("ffprobe")}
sys.argv = [str(engine / "downloader.py"), *sys.argv[1:]]
runpy.run_path(str(engine / "downloader.py"), run_name="__main__")
