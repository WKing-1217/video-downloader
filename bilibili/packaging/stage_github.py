"""Copy the explicit application source list into this app's separate Git repository."""
from pathlib import Path
import shutil
import subprocess

from package_release import ROOT, source_files

destination = ROOT / "bilibili/build/github-project"
if not (destination / ".git").is_dir():
    raise RuntimeError("Clone the new video-downloader repository before staging")
remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=destination,
                        capture_output=True, text=True, check=True).stdout.strip()
if remote != "https://github.com/WKing-1217/video-downloader.git":
    raise RuntimeError("Source publication target is not the authorized app repository")
for path in source_files():
    target = destination / path.relative_to(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
shutil.copy2(ROOT / "bilibili/packaging/README.github.md", destination / "README.md")
docs = destination / "docs"
docs.mkdir(exist_ok=True)
for name in ("desktop.png", "validation.md"):
    shutil.copy2(ROOT / "bilibili/packaging/docs" / name, docs / name)
(destination / ".gitignore").write_text("**/.venv/\n**/build/\n**/dist/\n**/__pycache__/\nandroid/signing/\nandroid/package/assets/engine/\nandroid/package/libs/*.aar\nvideo/\n*.log\n", encoding="utf-8")
print("Staged application source only:", destination)
