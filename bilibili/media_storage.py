"""Verified media relocation. Originals are removed only after a durable switch."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import threading
import uuid

from media_library import gallery_assets, path_key
from runtime_paths import APP_DIR, data_dir, read_settings, save_settings

CHUNK = 1024 * 1024
OWNED_FOLDERS = {".downloads", ".downloader-temp", "未通过校验"}


class MigrationError(RuntimeError):
    pass


class MigrationCancelled(MigrationError):
    pass


def native(path):
    value = os.path.abspath(str(path))
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        value = "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
    return Path(value)


def plain(path):
    """Reject links and junctions before resolving a path used for deletion."""
    path = Path(os.path.abspath(str(path)))
    for current in (*reversed(path.parents), path):
        try:
            info = native(current).lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise MigrationError("目录中含有链接或联接，请选择普通文件夹。")
    return path


def stamp(path):
    info = native(path).stat()
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def digest(path):
    with native(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with native(temporary).open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        native(temporary).replace(native(path))
    finally:
        native(temporary).unlink(missing_ok=True)


def remap(value, pairs):
    if isinstance(value, dict):
        return {key: remap(item, pairs) for key, item in value.items()}
    if isinstance(value, list):
        return [remap(item, pairs) for item in value]
    if isinstance(value, str) and Path(value).is_absolute():
        for old, new in pairs:
            try:
                return str(new / Path(value).relative_to(old))
            except ValueError:
                continue
    return value


class MediaMigration:
    def __init__(self, store, *, save=save_settings, settings=read_settings, protected=()):
        self.store, self.save, self.settings = store, save, settings
        self.journal = store.path.parent / "media-migration.json"
        home = Path.home()
        defaults = (home, APP_DIR, data_dir(), *(home / name for name in
                    ("Videos", "Documents", "Downloads", "Desktop", "Pictures", "Music")))
        self.protected = {path_key(path) for path in (*defaults, *protected)}
        self.cancelled = threading.Event()
        self.phase = "idle"

    def pending(self):
        return self.journal.is_file()

    def _write(self, job):
        atomic_json(self.journal, job)

    def _check_cancel(self):
        if self.cancelled.is_set():
            raise MigrationCancelled("迁移已取消，原视频保留。")

    def _unique(self, path, reserved, *, sidecar=False):
        candidate, number = path, 2
        def occupied(value):
            return path_key(value) in reserved or native(value).exists()
        while occupied(candidate) or (sidecar and occupied(candidate.with_suffix(candidate.suffix + ".info.json"))):
            candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
            number += 1
        reserved.add(path_key(candidate))
        if sidecar:
            reserved.add(path_key(candidate.with_suffix(candidate.suffix + ".info.json")))
        return candidate

    def _plan(self, target):
        target = plain(target)
        if path_key(target) in self.protected or target == Path(target.anchor):
            raise MigrationError("请选择专门存放视频的文件夹。")
        roots = [plain(root) for root in self.store.roots()]
        for root in roots:
            if target != root and target.is_relative_to(root):
                raise MigrationError("新目录不能放在旧下载目录内部。")
        rows = self.store.rows(include_hidden=True)
        reserved = {row["path_key"] for row in rows}
        records, files, pairs, missing = [], [], [], []
        cleanup_roots = set(roots)
        for row in rows:
            source = plain(row["path"])
            if not native(source).exists():
                missing.append(source)
                continue
            if source.is_dir() and target != source and target.is_relative_to(source):
                raise MigrationError("新目录不能放在原图文作品内部。")
            owners = [root for root in roots if source.is_relative_to(root)]
            owner = max(owners, key=lambda root: len(root.parts)) if owners else source.parent
            if owner == target or (not owners and source.is_relative_to(target)):
                continue
            if not owners:
                cleanup_roots.add(source.parent)
            relative = source.relative_to(owner)
            destination = self._unique(target / relative, reserved, sidecar=row["kind"] != "gallery")
            content = json.loads(row["metadata"])
            members = []
            if row["kind"] == "gallery":
                for asset in gallery_assets(source, content):
                    old = plain(asset["path"])
                    if native(old).is_file():
                        members.append((old, destination / old.name, False))
                receipt = source / "作品信息.json"
                if native(receipt).is_file():
                    members.append((receipt, destination / receipt.name, True))
                if not members:
                    missing.append(source)
                    continue
            else:
                members.append((source, destination, False))
                receipt = source.with_suffix(source.suffix + ".info.json")
                if native(receipt).is_file():
                    members.append((receipt, destination.with_suffix(destination.suffix + ".info.json"), True))
            pairs.append((source, destination))
            records.append({"id": row["id"], "old": str(source), "new": str(destination),
                            "metadata": row["metadata"], "thumb": row["thumb"]})
            for old, new, receipt in members:
                files.append({"old": str(old), "new": str(new), "receipt": receipt, "before": stamp(old)})
        known = {path_key(item["old"]) for item in files}
        for root in roots:
            if root == target:
                continue
            for name in OWNED_FOLDERS:
                folder = root / name
                if not native(folder).is_dir():
                    continue
                for current, directories, names in os.walk(native(folder), followlinks=False):
                    # Convert the extended Win32 path back to its planned normal path.
                    relative = Path(current).relative_to(native(root))
                    for directory in directories:
                        plain(root / relative / directory)
                    for filename in names:
                        source = plain(root / relative / filename)
                        if path_key(source) not in known:
                            destination = self._unique(target / relative / filename, reserved)
                            files.append({"old": str(source), "new": str(destination), "receipt": False, "before": stamp(source)})
                            known.add(path_key(source))
        for record in records:
            record["metadata"] = json.dumps(remap(json.loads(record["metadata"]), pairs), ensure_ascii=False)
            record["thumb"] = remap(record["thumb"], pairs)
        retained = [str(root) for root in roots if any(path.is_relative_to(root) for path in missing)]
        stage = target / (".media-migrate-" + uuid.uuid4().hex)
        return {"schema": 1, "product": "LocalVideoDownloader", "phase": "copying", "target": str(target),
                "stage": str(stage), "files": files, "records": records, "pairs": [[str(a), str(b)] for a, b in pairs],
                "old_roots": [str(root) for root in cleanup_roots if root != target],
                "new_roots": list(dict.fromkeys([str(target), *retained])), "missing": len(missing)}

    def run(self, target, progress=lambda *_: None):
        if self.pending():
            raise MigrationError("上次迁移尚未完成，请先继续处理。")
        job = self._plan(target)
        target, stage = Path(job["target"]), Path(job["stage"])
        native(target).mkdir(parents=True, exist_ok=True)
        native(stage).mkdir()
        self._write(job)
        total = sum(entry["before"][2] for entry in job["files"])
        free = shutil.disk_usage(native(target)).free
        if free < total:
            self._rollback(job)
            raise MigrationError("新目录所在磁盘空间不足，原视频保留。")
        copied = 0
        self.phase = "copying"
        try:
            progress("copying", 0, total)
            for number, entry in enumerate(job["files"]):
                self._check_cancel()
                old, new = plain(entry["old"]), plain(entry["new"])
                staged = stage / str(number)
                source_hash = hashlib.sha256()
                with native(old).open("rb") as source, native(staged).open("xb") as destination:
                    while chunk := source.read(CHUNK):
                        self._check_cancel()
                        destination.write(chunk)
                        source_hash.update(chunk)
                        copied += len(chunk)
                        progress("copying", copied, total)
                    destination.flush()
                    os.fsync(destination.fileno())
                if stamp(old) != entry["before"] or digest(staged) != source_hash.hexdigest():
                    raise MigrationError("原文件在迁移时发生变化，原视频保留，请重试。")
                entry["source_hash"] = source_hash.hexdigest()
                if entry["receipt"]:
                    try:
                        value = json.loads(native(staged).read_text(encoding="utf-8"))
                    except (ValueError, UnicodeError):
                        pass
                    else:
                        atomic_json(staged, remap(value, [(Path(a), Path(b)) for a, b in job["pairs"]]))
                shutil.copystat(native(old), native(staged), follow_symlinks=False)
                entry["hash"] = digest(staged)
                entry["copy_stamp"] = stamp(staged)
                # Record ownership before promotion; rename preserves file identity.
                self._write(job)
                native(new.parent).mkdir(parents=True, exist_ok=True)
                plain(new.parent)
                if os.name == "nt":
                    native(staged).rename(native(new))  # Windows refuses existing targets.
                else:
                    os.link(staged, new)
                    staged.unlink()
            self._check_cancel()
            job["phase"] = "switching"
            self._write(job)
            return self._finish(job, progress)
        except Exception:
            if job["phase"] == "copying":
                self._rollback(job)
            raise

    def _verify(self, job):
        target = plain(job["target"])
        if job.get("schema") != 1 or job.get("product") != "LocalVideoDownloader":
            raise MigrationError("迁移记录无效，未清理任何原文件。")
        for entry in job["files"]:
            new = plain(entry["new"])
            plain(entry["old"])
            if not new.is_relative_to(target) or new == target:
                raise MigrationError("迁移记录的目录无效，未清理原文件。")
            if not native(new).is_file() or digest(new) != entry["hash"]:
                raise MigrationError("新目录中的文件校验未通过，原文件保留。")

    def _finish(self, job, progress):
        self._verify(job)
        if job["phase"] == "switching":
            self.phase = "switching"
            progress("switching", 0, 0)
            self.store.relocate(job["records"], job["new_roots"],
                                lambda: self.save(output=job["target"], library_roots=job["new_roots"]))
            job["phase"] = "cleaning"
            self._write(job)
        self.phase = "cleaning"
        remaining, changed = [], []
        for number, entry in enumerate(job["files"]):
            old = plain(entry["old"])
            if not native(old).exists():
                continue
            if stamp(old) != entry["before"] or digest(old) != entry["source_hash"]:
                changed.append(str(old))
                continue
            try:
                native(old).unlink()
            except OSError:
                remaining.append(str(old))
            progress("cleaning", number + 1, len(job["files"]))
        self._prune_stage(job)
        retained = []
        for root in sorted((Path(item) for item in job["old_roots"]), key=lambda path: len(path.parts), reverse=True):
            self._prune_empty(root, [Path(entry["old"]) for entry in job["files"]])
            if native(root).exists():
                retained.append(str(root))
        if not remaining:
            self.journal.unlink(missing_ok=True)
        self.phase = "idle"
        return {"target": job["target"], "records": len(job["records"]), "paths": dict(job["pairs"]),
                "retained_directories": retained, "cleanup_pending": bool(remaining),
                "changed_originals": changed, "missing": job["missing"], "cancelled": False}

    def _prune_empty(self, root, files=()):
        root = plain(root)
        if not native(root).is_dir():
            return
        # Only prune parents of files this job handled, never unrelated subtrees.
        candidates = {root}
        for file in files:
            candidates.update(parent for parent in file.parents if parent.is_relative_to(root))
        for candidate in sorted(candidates, key=lambda path: len(path.parts), reverse=True):
            if path_key(candidate) in self.protected or candidate == Path(candidate.anchor):
                continue
            try:
                native(plain(candidate)).rmdir()
            except OSError:
                pass

    def _prune_stage(self, job):
        stage = plain(job["stage"])
        if stage.parent != Path(job["target"]) or not stage.name.startswith(".media-migrate-"):
            raise MigrationError("临时迁移目录无效。")
        if native(stage).is_dir():
            for number, _ in enumerate(job["files"]):
                native(stage / str(number)).unlink(missing_ok=True)
            self._prune_empty(stage)

    def _rollback(self, job):
        parents = set()
        for entry in job["files"]:
            target = plain(entry["new"])
            if "copy_stamp" in entry and native(target).is_file() and stamp(target) == entry["copy_stamp"]:
                native(target).unlink()
                parents.update(parent for parent in target.parents if parent.is_relative_to(Path(job["target"]))
                               and parent != Path(job["target"]))
        for parent in sorted(parents, key=lambda path: len(path.parts), reverse=True):
            try:
                native(parent).rmdir()
            except OSError:
                pass
        self._prune_stage(job)
        self.journal.unlink(missing_ok=True)
        self.phase = "idle"

    def recover(self, progress=lambda *_: None):
        job = json.loads(self.journal.read_text(encoding="utf-8"))
        if job.get("phase") not in {"copying", "switching", "cleaning"}:
            raise MigrationError("迁移记录状态无效，原文件保留。")
        if job["phase"] == "copying":
            self._rollback(job)
            return {"cancelled": True, "target": self.settings().get("output"), "cleanup_pending": False}
        return self._finish(job, progress)
