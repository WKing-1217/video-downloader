"""Run the shared, tested downloader inside the bundled Android Python."""
import os
from pathlib import Path
import runpy
import signal
import shutil
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
import media_export


def publish_private(staged, destination):
    """Android Python omits hardlinks; reserve a unique private file instead.

    DownloadService publishes only a fully copied, verified file to MediaStore
    with IS_PENDING, so partial private copies never appear as public exports.
    """
    staged, destination = Path(staged), Path(destination)
    candidate, number = destination, 2
    while True:
        try:
            descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            candidate = destination.with_name(f"{destination.stem} ({number}){destination.suffix}")
            number += 1
            continue
        try:
            with os.fdopen(descriptor, "wb") as output, staged.open("rb") as source:
                shutil.copyfileobj(source, output, 256 * 1024)
                output.flush()
                os.fsync(output.fileno())
            staged.unlink()
            return candidate
        except BaseException:
            candidate.unlink(missing_ok=True)
            raise


media_export.publish_unique = publish_private

# Android installs executable helpers as .so files in nativeLibraryDir. Supply
# their actual paths rather than requiring programs named ffmpeg/ffprobe in PATH.
FFmpegPostProcessor._determine_executables = lambda self: {"ffmpeg": tool("ffmpeg"), "ffprobe": tool("ffprobe")}
sys.argv = [str(engine / "downloader.py"), *sys.argv[1:]]
runpy.run_path(str(engine / "downloader.py"), run_name="__main__")
