"""Transactional media catalogue. No browser data or video bytes enter this DB."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from runtime_paths import data_dir

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".flv", ".ts"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".avif"}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS
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


def discover_album(folder, names):
    """Recognize receipt-free image folders without swallowing unrelated videos."""
    folder = Path(folder)
    images, companions = [], []
    for name in sorted(names):
        path = folder / name
        if path.is_symlink() or name.startswith(".") or re.search(r"\.(?:f\d+|part|temp)(?:\.|$)", name):
            continue
        extension = path.suffix.lower()
        if extension in IMAGE_EXTENSIONS:
            images.append({"kind": "image", "path": str(path)})
        elif extension in AUDIO_EXTENSIONS and re.search(r"背景音乐|music|audio", path.stem, re.IGNORECASE):
            companions.append({"kind": "music", "path": str(path)})
        elif extension in VIDEO_EXTENSIONS and re.search(r"实况|live.?photo", path.stem, re.IGNORECASE):
            companions.append({"kind": "live_photo", "path": str(path)})
    if not images:
        return {}
    assets = sorted(images + companions, key=lambda asset: Path(asset["path"]).name)
    return {"title": folder.name, "content_type": "gallery", "assets": assets}


def regular_path(path):
    path = Path(os.path.abspath(path))
    if any(parent.is_symlink() or getattr(parent, "is_junction", lambda: False)()
           for parent in (path, *path.parents)):
        raise OSError("文件位置含有链接，请在原目录中管理。")
    return path


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

    def rows(self, *, include_hidden=False):
        with closing(self.connect()) as db:
            where = "" if include_hidden else " WHERE hidden=0"
            return [dict(row) for row in db.execute("SELECT * FROM media" + where + " ORDER BY completed DESC,id DESC")]

    def relocate(self, records, roots, save_location):
        """Keep IDs and history; location changes are idempotent for crash recovery."""
        with closing(self.connect()) as db, db:
            for record in records:
                current = db.execute("SELECT path FROM media WHERE id=?", (record["id"],)).fetchone()
                if current is None:
                    continue
                if path_key(current["path"]) not in {path_key(record["old"]), path_key(record["new"])}:
                    raise RuntimeError("视频库位置已变化，请刷新后重试。")
                destination = Path(record["new"])
                db.execute("UPDATE media SET path=?,path_key=?,metadata=?,file_id=?,mtime=?,thumb=? WHERE id=?",
                           (str(destination), path_key(destination), record["metadata"],
                            file_identity(destination), destination.stat().st_mtime, record["thumb"], record["id"]))
            db.execute("DELETE FROM roots")
            db.executemany("INSERT OR IGNORE INTO roots VALUES (?)", ((str(Path(root).resolve()),) for root in roots))
            save_location()

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
        kind = ("gallery" if path.is_dir() else "audio" if path.suffix.lower() in AUDIO_EXTENSIONS
                else "image" if path.suffix.lower() in IMAGE_EXTENSIONS else "video")
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
            state = "ready" if trusted or kind in {"gallery", "image"} or completed else old["state"] if same else "pending"
            if kind == "gallery":
                assets = gallery_assets(path, content)
                size = sum(Path(item["path"]).stat().st_size for item in assets if Path(item["path"]).is_file())
                content.update(content_type="gallery", assets=assets, size=size)
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
        path = regular_path(item["path"])
        if item["kind"] == "gallery":
            content = json.loads(item["metadata"])
            for asset in gallery_assets(path, content):
                regular_path(asset["path"])
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

    def delete_asset(self, identifier, filename):
        """Delete one recorded album member; metadata stays in SQLite only."""
        item = self.get(identifier)
        if not item or item["kind"] != "gallery":
            raise ValueError("图文作品不存在。")
        folder = Path(item["path"])
        content = json.loads(item["metadata"])
        assets = gallery_assets(folder, content)
        chosen = next((asset for asset in assets if path_key(asset["path"]) == path_key(filename)), None)
        if chosen is None:
            raise ValueError("该文件不属于此作品。")
        target = regular_path(chosen["path"])
        if target.parent != folder or target.name in {"", ".", "..", "作品信息.json"}:
            raise ValueError("图片位置无效。")
        remaining = [asset for asset in assets if path_key(asset["path"]) != path_key(target)]
        updated = {**content, "assets": remaining,
                   "size": sum(Path(asset["path"]).stat().st_size for asset in remaining if Path(asset["path"]).is_file())}
        staged = target.with_name(".delete-" + uuid.uuid4().hex)
        renamed = False
        try:
            if target.is_file():
                target.rename(staged)
                renamed = True
            if remaining:
                self.update(identifier, metadata=json.dumps(updated, ensure_ascii=False),
                            size=updated["size"], thumb="",
                            state="ready" if all(Path(asset["path"]).is_file() for asset in remaining) else "missing")
            else:
                self.update(identifier, metadata=json.dumps(updated, ensure_ascii=False),
                            size=0, thumb="", hidden=1, state="missing")
            if renamed:
                staged.unlink()
        except Exception:
            # An occupied file or failed DB write must leave the old view usable.
            if renamed and staged.exists():
                staged.rename(target)
            self.update(identifier, metadata=item["metadata"], size=item["size"], thumb=item["thumb"],
                        hidden=item["hidden"], state=item["state"])
            raise
        if not remaining:
            try:
                folder.rmdir()
            except OSError:
                pass  # Notes and any unrecorded files remain.
        return self.get(identifier)

    def scan(self, cancelled=None):
        count = 0
        galleries = [item for item in self.rows(include_hidden=True) if item["kind"] == "gallery"]
        by_path = {item["path_key"]: item for item in galleries}
        by_identity = {item["file_id"]: item for item in galleries if item["file_id"]}
        for folder in self.roots():
            if not Path(folder).is_dir():
                continue
            for current, directories, files in os.walk(folder, followlinks=False):
                if cancelled and cancelled.is_set():
                    return count
                directories[:] = [name for name in directories if name not in EXCLUDED_FOLDERS
                                  and not name.startswith(".") and not (Path(current) / name).is_symlink()]
                current = Path(current)
                saved_album = by_path.get(path_key(current))
                if saved_album is None:
                    try:
                        previous = by_identity.get(file_identity(current))
                        if previous and not Path(previous["path"]).exists():
                            saved_album = previous
                    except OSError:
                        pass
                if saved_album is not None:
                    # Once catalogued, SQLite owns album membership. Legacy
                    # receipts may describe images the user has since deleted.
                    try:
                        self.upsert(current)
                        count += 1
                    except OSError:
                        pass
                    directories[:] = []
                    continue
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
                album_members = set()
                if path_key(current) != path_key(folder):
                    content = discover_album(current, files)
                    if content:
                        try:
                            self.upsert(current, content)
                            count += 1
                            album_members = {path_key(asset["path"]) for asset in content["assets"]}
                        except OSError:
                            pass
                for name in files:
                    path = current / name
                    if (path.suffix.lower() not in MEDIA_EXTENSIONS or path.is_symlink()
                            or path_key(path) in album_members or name.startswith(".")
                            or re.search(r"\.(?:f\d+|part|temp)(?:\.|$)", name)):
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
