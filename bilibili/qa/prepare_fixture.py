"""Generate a six-second local audiovisual test clip with the project's FFmpeg."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
folder = root / "build/v2-fixtures"
folder.mkdir(parents=True, exist_ok=True)
subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-movflags", "+faststart", str(folder / "sample.mp4")], check=True)
