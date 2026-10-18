"""Launch only our own built GUI, with isolated data and no installed Python/FFmpeg on PATH."""
import json
import os
from pathlib import Path
import subprocess
import time
import pefile

root = Path(__file__).resolve().parents[1]
binary = root / "dist/v2/VideoDownloader/VideoDownloader.exe"
assert binary.resolve().is_relative_to(root.resolve())
assert pefile.PE(str(binary)).OPTIONAL_HEADER.Subsystem == 2
work = root / "build" / ("v2-packaged-live-" + str(time.time_ns()))
data = work / "preferences/LocalVideoDownloader"
data.mkdir(parents=True)
environment = os.environ.copy()
environment.update(LOCALAPPDATA=str(data.parent), VIDEO_DOWNLOADER_OUTPUT=str(work / "video"), QT_QPA_PLATFORM="offscreen",
                   PATH=os.environ.get("WINDIR", "C:/Windows") + "/System32;" + os.environ.get("WINDIR", "C:/Windows"))
(data / "settings.json").write_text(json.dumps({"auto_login": False, "auto_update": False,
                                                "output": str(work / "video")}), encoding="utf-8")
report = work / "report.json"
with (work / "process.log").open("wb") as log:
    process = subprocess.Popen([str(binary), "https://www.bilibili.com/video/BV1yUFPzKEC7", "--verify-install", str(report)],
                               cwd=binary.parent, env=environment, stdout=log, stderr=log)
    print(json.dumps({"pid": process.pid, "work": str(work), "subsystem": "Windows GUI"}), flush=True)
    try:
        code = process.wait(timeout=390)
    except subprocess.TimeoutExpired:
        process.terminate()
        raise
assert report.is_file(), (code, (work / "process.log").read_text(encoding="utf-8", errors="replace"))
value = json.loads(report.read_text(encoding="utf-8"))
print(json.dumps({"passed": value["passed"], "elapsed": value.get("elapsed"), "frames": value.get("frames"),
                  "result": value.get("result"), "error": value.get("error"), "report": str(report)}, ensure_ascii=False), flush=True)
assert value["passed"], value.get("error")
