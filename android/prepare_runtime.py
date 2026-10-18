"""Fetch the pinned FFmpeg Android AAR from its original Maven repository."""
from pathlib import Path
import hashlib
import urllib.request

folder = Path(__file__).resolve().parent / "package/libs"
folder.mkdir(parents=True, exist_ok=True)
url = "https://repo.maven.apache.org/maven2/io/github/junkfood02/youtubedl-android/ffmpeg/0.18.1/ffmpeg-0.18.1.aar"
dest = folder / "ffmpeg-runtime.aar"
if not dest.is_file():
    urllib.request.urlretrieve(url, dest)
with urllib.request.urlopen(url + ".sha256", timeout=30) as response:
    expected = response.read().decode().strip().split()[0]
actual = hashlib.sha256(dest.read_bytes()).hexdigest()
if actual != expected:
    raise RuntimeError("FFmpeg runtime checksum mismatch; rebuild preparation stopped")
print("Pinned FFmpeg runtime verified:", actual)
