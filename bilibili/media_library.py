"""Transactional media catalogue. No browser data or video bytes enter this DB."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from runtime_paths import data_dir

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".ts"}
EXCLUDED_FOLDERS = {"未通过校验", ".downloads", ".downloader-temp", "__pycache__"}


def path_key(path):
    return os.path.normcase(os.path.abspath(str(path)))


def file_identity(path):
    stat = Path(path).stat()
    return f"{stat.st_dev}:{stat.st_ino}" if stat.st_ino else ""


def read_receipt(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def gallery_assets(folder, metadata):
    """Resolve moved albums by basename; never follow receipt paths elsewhere."""
    folder = Path(folder)
    return [{**item, "path": str(folder / Path(item.get("path", "")).name)}
            for item in metadata.get("assets", []) if isinstance(item, dict) and item.get("path")]


class LibraryStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_dir() / "library.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        had_data = self.path.is_file() and self.path.stat().st_size > 0
        with closing(self.connect()) as db:
            old_version = db.execute("PRAGMA user_version").fetchone()[0]
            if old_version > 1:
                raise ValueError("视频库由更新版本创建，请使用对应版本；原数据已保留。")
            db.execute("PRAGMA journal_mode=WAL")
            if old_version == 0:
                if had_data:
                    with closing(sqlite3.connect(str(self.path) + ".before-v1.bak")) as backup:
                        db.backup(backup)
                with db:
                    db.executescript("""
                    CREATE TABLE IF NOT EXISTS roots(path TEXT PRIMARY KEY);
                    CREATE TABLE IF NOT EXISTS media(
                      id INTEGER PRIMARY KEY, path TEXT NOT NULL, path_key TEXT UNIQUE NOT NULL,
                      title TEXT NOT NULL, duration REAL DEFAULT 0, size INTEGER DEFAULT 0,
                      completed REAL NOT NULL, kind TEXT DEFAULT 'video', source_key TEXT DEFAULT '',
                      metadata TEXT DEFAULT '{}', file_id TEXT DEFAULT '', mtime REAL DEFAULT 0,
                      state TEXT DEFAULT 'pending', hidden INTEGER DEFAULT 0, thumb TEXT DEFAULT '');
                    CREATE INDEX IF NOT EXISTS media_source ON media(source_key);
                    CREATE INDEX IF NOT EXISTS media_identity ON media(file_id);
                    PRAGMA user_version=1;
                    """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def add_root(self, folder):
        folder = str(Path(folder).resolve())
        with closing(self.connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO roots VALUES (?)", (folder,))

    def roots(self):
        with closing(self.connect()) as db:
            return [row[0] for row in db.execute("SELECT path FROM roots ORDER BY rowid")]

    def rows(self):
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute("SELECT * FROM media WHERE hidden=0 ORDER BY completed DESC,id DESC")]

    def get(self, identifier):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM media WHERE id=?", (identifier,)).fetchone()
            return dict(row) if row else None

    def find_source(self, key):
        with closing(self.connect()) as db:
            rows = db.execute("SELECT * FROM media WHERE source_key=? AND hidden=0 AND state='ready'", (key,))
            return next((dict(row) for row in rows if Path(row["path"]).exists()), None)

    def upsert(self, path, metadata=None, *, source_key="", completed=False):
        path = Path(path).absolute()
        stat = path.stat()
        metadata = metadata or {}
        key, identity = path_key(path), file_identity(path)
        kind = "gallery" if path.is_dir() else "video"
        with closing(self.connect()) as db, db:
            old = db.execute("SELECT * FROM media WHERE path_key=?", (key,)).fetchone()
            if old and old["hidden"] and not completed:
                return None
            if old is None and identity:
                candidates = db.execute("SELECT * FROM media WHERE file_id=?", (identity,)).fetchall()
                old = next((row for row in candidates if not Path(row["path"]).exists()), None)
            if old and old["hidden"] and not completed:
                return None
            same = bool(old and old["mtime"] == stat.st_mtime and (kind == "gallery" or old["size"] == stat.st_size))
            previous = json.loads(old["metadata"]) if old else {}
            content = {**previous, **metadata}
            title = str(content.get("title") or (old["title"] if old else path.stem))
            duration = float(content.get("duration") or (old["duration"] if old else 0))
            size = int(content.get("size") or stat.st_size)
            trusted = bool(metadata.get("duration") and metadata.get("size") == stat.st_size)
            state = "ready" if trusted or kind == "gallery" or completed else old["state"] if same else "pending"
            if kind == "gallery":
                assets = gallery_assets(path, content)
                state = "ready" if assets and all(Path(item["path"]).is_file() for item in assets) else "missing"
            values = (str(path), key, title, duration, size,
                      time.time() if completed else old["completed"] if old else stat.st_mtime,
                      kind, source_key or content.get("source_key") or (old["source_key"] if old else ""),
                      json.dumps(content, ensure_ascii=False), identity, stat.st_mtime, state,
                      old["thumb"] if same else "")
            if old:
                db.execute("""UPDATE media SET path=?,path_key=?,title=?,duration=?,size=?,completed=?,kind=?,
                  source_key=?,metadata=?,file_id=?,mtime=?,state=?,thumb=?,hidden=0 WHERE id=?""", (*values, old["id"]))
                return old["id"]
            return db.execute("""INSERT INTO media(path,path_key,title,duration,size,completed,kind,source_key,
              metadata,file_id,mtime,state,thumb) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", values).lastrowid

    def update(self, identifier, **values):
        allowed = {"duration", "size", "state", "thumb", "hidden", "metadata", "title"}
        if not values or not set(values).issubset(allowed):
            raise ValueError("Unsupported catalogue update")
        with closing(self.connect()) as db, db:
            db.execute("UPDATE media SET " + ",".join(key + "=?" for key in values) + " WHERE id=?",
                       (*values.values(), identifier))

    def remove_record(self, identifier):
        self.update(identifier, hidden=1)

    def delete_files(self, identifier):
        """Caller confirms first. Only recorded files are removed, never rmtree."""
        item = self.get(identifier)
        if not item:
            return
        path = Path(item["path"])
        if item["kind"] == "gallery":
            content = json.loads(item["metadata"])
            for asset in gallery_assets(path, content):
                target = Path(asset["path"])
                if target.is_file():
                    target.unlink()
            (path / "作品信息.json").unlink(missing_ok=True)
            try:
                path.rmdir()
            except OSError:
                pass  # Unrecorded user files always remain.
        else:
            path.unlink(missing_ok=True)
            path.with_suffix(path.suffix + ".info.json").unlink(missing_ok=True)
        self.update(identifier, hidden=1, state="missing")

    def scan(self, cancelled=None):
        count = 0
        for folder in self.roots():
            if not Path(folder).is_dir():
                continue
            for current, directories, files in os.walk(folder, followlinks=False):
                if cancelled and cancelled.is_set():
                    return count
                directories[:] = [name for name in directories if name not in EXCLUDED_FOLDERS
                                  and not name.startswith(".") and not (Path(current) / name).is_symlink()]
                current = Path(current)
                if "作品信息.json" in files:
                    content = read_receipt(current / "作品信息.json")
                    if content.get("content_type") == "gallery":
                        try:
                            self.upsert(current, content)
                            count += 1
                        except OSError:
                            pass
                        directories[:] = []
                        continue
                for name in files:
                    path = current / name
                    if path.suffix.lower() not in VIDEO_EXTENSIONS or re.search(r"\.(?:f\d+|part|temp)(?:\.|$)", name):
                        continue
                    try:
                        self.upsert(path, read_receipt(path.with_suffix(path.suffix + ".info.json")))
                        count += 1
                    except OSError:
                        continue
        for item in self.rows():
            path = Path(item["path"])
            exists = path.is_dir() if item["kind"] == "gallery" else path.is_file()
            if not exists:
                self.update(item["id"], state="missing")
        return count
