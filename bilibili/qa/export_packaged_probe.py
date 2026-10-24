"""Run the opt-in export verifier in the actual bundle with an isolated PATH."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--binary", type=Path, default=ROOT / "dist/v2/VideoDownloader/VideoDownloader.exe")
parser.add_argument("--source", action="store_true", help="Preflight the verifier before building; final acceptance uses the EXE")
args = parser.parse_args()
binary = args.binary.resolve()
if not args.source and (not binary.is_file() or not binary.is_relative_to(ROOT)):
    raise RuntimeError("Choose the built application inside this workspace")
work = ROOT / "build" / ("export-pkg-" + format(time.time_ns(), "x"))
output = work / "media"
data = work / "preferences/LocalVideoDownloader"
for folder in (output, data):
    folder.mkdir(parents=True, exist_ok=True)
video = output / "已有视频.mp4"
shutil.copy2(ROOT / "build/v2-fixtures/sample.mp4", video)
version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]
(work / "qa-export-fixture.json").write_text(json.dumps({"product": "LocalVideoDownloader", "nonce": uuid.uuid4().hex,
      "video": str(video), "output": str(output), "expected_version": version, "expect_frozen": not args.source}, ensure_ascii=False), encoding="utf-8")
(data / "settings.json").write_text(json.dumps({"auto_login": False, "auto_update": False, "output": str(output)}), encoding="utf-8")
environment = os.environ.copy()
environment.update(LOCALAPPDATA=str(data.parent), VIDEO_DOWNLOADER_OUTPUT=str(output), QT_QPA_PLATFORM="offscreen")
if not args.source:
    system = os.environ.get("WINDIR", "C:/Windows")
    environment["PATH"] = system + "/System32;" + system
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
report = work / "report.json"
command = [sys.executable, str(ROOT / "app.py")] if args.source else [str(binary)]
with (work / "process.log").open("wb") as log:
    process = subprocess.Popen([*command, "--verify-export", str(report)], cwd=ROOT if args.source else binary.parent,
                               env=environment, stdout=log, stderr=log,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    print(json.dumps({"pid": process.pid, "work": str(work), "source_preflight": args.source}), flush=True)
    try:
        code = process.wait(timeout=135)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=15)
        raise
if not report.is_file():
    raise AssertionError((code, (work / "process.log").read_text(encoding="utf-8", errors="replace")[-6000:]))
result = json.loads(report.read_text(encoding="utf-8"))
print(json.dumps({"passed": result["passed"], "version": result["version"], "frozen": result["frozen"],
                  "checks": len(result["checks"]), "error": result["error"], "report": str(report)}, ensure_ascii=False), flush=True)
assert code == 0 and result["passed"], result
