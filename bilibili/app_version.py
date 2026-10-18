"""Public release identity, shared by builds and the desktop updater."""
import json
from pathlib import Path

RELEASE = json.loads((Path(__file__).resolve().parent / "version.json").read_text(encoding="utf-8"))
APP_VERSION = RELEASE["version"]
REPOSITORY = RELEASE["repository"]
RELEASE_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
UPDATE_URL = RELEASE_PAGE + "/download/update.json"
