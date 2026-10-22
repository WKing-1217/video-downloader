"""Relocation invariants using disposable media, never the user's library."""
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from media_library import LibraryStore, gallery_assets
from media_storage import MediaMigration, MigrationCancelled, MigrationError, native


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old = self.root / "旧视频"
        self.old.mkdir()
        self.new = self.root / "新视频"
        self.store = LibraryStore(self.root / "data/library.sqlite3")
        self.store.add_root(self.old)
        self.prefs = {"output": str(self.old), "auto_update": False}
        self.migration = MediaMigration(self.store, settings=lambda: self.prefs.copy(), save=self.save)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, **values):
        self.prefs.update(values)

    def video(self, root=None, name="长标题视频.mp4", payload=b"complete original media"):
        path = (root or self.old) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        content = {"title": path.stem, "duration": 12, "size": len(payload), "file": str(path)}
        path.with_suffix(path.suffix + ".info.json").write_text(json.dumps(content), encoding="utf-8")
        identifier = self.store.upsert(path, content, source_key="source:" + str(path), completed=True)
        return path, identifier

    def gallery(self):
        folder = self.old / "图文作品"
        folder.mkdir()
        files = [(folder / name, kind) for name, kind in (("001.jpg", "image"), ("002.jpg", "image"), ("music.m4a", "music"))]
        for path, _ in files:
            path.write_bytes(path.name.encode())
        content = {"title": "图文", "content_type": "gallery", "assets":
                   [{"path": str(path), "kind": kind} for path, kind in files]}
        (folder / "作品信息.json").write_text(json.dumps(content), encoding="utf-8")
        identifier = self.store.upsert(folder, content, completed=True)
        self.store.update(identifier, thumb=str(files[0][0]))
        return folder, identifier

    def test_move_preserves_history_and_removes_old_directory(self):
        old, identifier = self.video()
        before = self.store.get(identifier)
        result = self.migration.run(self.new)
        after = self.store.get(identifier)
        target = Path(after["path"])
        self.assertEqual(target.read_bytes(), b"complete original media")
        self.assertFalse(self.old.exists())
        self.assertEqual((before["completed"], before["source_key"], before["state"]),
                         (after["completed"], after["source_key"], after["state"]))
        self.assertEqual(json.loads(after["metadata"])["file"], str(target))
        self.assertEqual(json.loads(target.with_suffix(".mp4.info.json").read_text())["file"], str(target))
        self.assertEqual(self.store.roots(), [str(self.new)])
        self.assertEqual(self.prefs["output"], str(self.new))
        self.assertFalse(self.prefs["auto_update"])
        self.assertFalse(result["cleanup_pending"])
        self.assertFalse(self.migration.pending())

    def test_gallery_paths_receipt_and_cover_move_together(self):
        folder, identifier = self.gallery()
        self.migration.run(self.new)
        row = self.store.get(identifier)
        assets = gallery_assets(row["path"], json.loads(row["metadata"]))
        self.assertEqual(len(assets), 3)
        self.assertTrue(all(Path(asset["path"]).is_file() for asset in assets))
        self.assertTrue(Path(row["thumb"]).is_file())
        receipt = json.loads((Path(row["path"]) / "作品信息.json").read_text())
        self.assertTrue(all(Path(asset["path"]).is_relative_to(self.new) for asset in receipt["assets"]))
        self.assertFalse(folder.exists())

    def test_unrelated_files_are_never_deleted(self):
        self.video()
        notes = self.old / "个人笔记.txt"
        notes.write_bytes(b"keep this")
        result = self.migration.run(self.new)
        self.assertEqual(notes.read_bytes(), b"keep this")
        self.assertIn(str(self.old), result["retained_directories"])

    def test_unrelated_empty_directory_is_not_pruned(self):
        self.video()
        personal = self.old / "另建的空文件夹"
        personal.mkdir()
        self.migration.run(self.new)
        self.assertTrue(personal.is_dir())

    def test_existing_target_and_orphan_receipt_are_not_overwritten(self):
        old, identifier = self.video()
        self.new.mkdir()
        collision = self.new / old.name
        collision.write_bytes(b"existing target")
        orphan = self.new / (old.stem + " (2).mp4.info.json")
        orphan.write_bytes(b"unrelated receipt")
        self.migration.run(self.new)
        self.assertEqual(Path(self.store.get(identifier)["path"]).name, old.stem + " (3).mp4")
        self.assertEqual(collision.read_bytes(), b"existing target")
        self.assertEqual(orphan.read_bytes(), b"unrelated receipt")

    def test_multiple_old_roots_and_hidden_records_are_migrated(self):
        first, one = self.video()
        other = self.root / "其他旧目录"
        other.mkdir()
        self.store.add_root(other)
        second, two = self.video(other, payload=b"second source")
        self.store.remove_record(two)
        self.migration.run(self.new)
        self.assertFalse(first.exists() or second.exists())
        self.assertEqual(self.store.get(two)["hidden"], 1)
        self.assertNotEqual(self.store.get(one)["path"], self.store.get(two)["path"])
        self.assertEqual(len(self.store.rows()), 1)

    def test_cancel_rolls_back_copies_and_keeps_originals(self):
        old, identifier = self.video(payload=b"a" * (2 * 1024 * 1024))
        def progress(*_):
            self.migration.cancelled.set()
        with self.assertRaises(MigrationCancelled):
            self.migration.run(self.new, progress)
        self.assertTrue(old.is_file())
        self.assertEqual(self.store.get(identifier)["path"], str(old))
        self.assertEqual(self.prefs["output"], str(self.old))
        self.assertFalse(list(self.new.iterdir()))
        self.assertFalse(self.migration.pending())

    def test_failed_settings_switch_leaves_originals_and_can_resume(self):
        old, identifier = self.video()
        self.migration.save = lambda **_: (_ for _ in ()).throw(OSError("settings unavailable"))
        with self.assertRaises(OSError):
            self.migration.run(self.new)
        self.assertTrue(old.exists())
        self.assertEqual(self.store.get(identifier)["path"], str(old))
        self.assertTrue(self.migration.pending())
        self.migration.save = self.save
        self.migration.recover()
        self.assertFalse(old.exists())
        self.assertTrue(Path(self.store.get(identifier)["path"]).is_file())

    def test_interrupted_copy_recovery_only_discards_its_own_copies(self):
        old, identifier = self.video()
        original_finish = self.migration._finish
        def interrupt(job, progress):
            job["phase"] = "copying"
            self.migration._write(job)
            raise KeyboardInterrupt()
        self.migration._finish = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.migration.run(self.new)
        self.migration._finish = original_finish
        self.assertTrue(self.migration.recover()["cancelled"])
        self.assertTrue(old.exists())
        self.assertFalse(list(self.new.iterdir()))
        self.assertEqual(self.store.get(identifier)["path"], str(old))

    def test_new_file_corruption_blocks_cleanup(self):
        old, identifier = self.video()
        self.migration.save = lambda **_: (_ for _ in ()).throw(OSError("stop at switch"))
        with self.assertRaises(OSError):
            self.migration.run(self.new)
        (self.new / old.name).write_bytes(b"damaged")
        self.migration.save = self.save
        with self.assertRaises(MigrationError):
            self.migration.recover()
        self.assertTrue(old.exists())
        self.assertEqual(self.store.get(identifier)["path"], str(old))

    def test_locked_original_keeps_retry_journal_after_switch(self):
        old, identifier = self.video()
        real_unlink = Path.unlink
        def unlink(path, *args, **kwargs):
            if str(path) == str(native(old)):
                raise PermissionError("locked fixture")
            return real_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", unlink):
            result = self.migration.run(self.new)
        self.assertTrue(result["cleanup_pending"])
        self.assertTrue(old.exists())
        self.assertTrue(Path(self.store.get(identifier)["path"]).is_relative_to(self.new))
        self.migration.recover()
        self.assertFalse(self.old.exists())
        self.assertFalse(self.migration.pending())

    def test_modified_source_aborts_copy_without_switch(self):
        old, identifier = self.video()
        def progress(*_):
            old.with_suffix(".mp4.info.json").write_bytes(b"changed during migration")
        with self.assertRaises(MigrationError):
            self.migration.run(self.new, progress)
        self.assertTrue(old.exists())
        self.assertEqual(self.store.get(identifier)["path"], str(old))

    def test_missing_offline_files_keep_their_old_root(self):
        old, identifier = self.video()
        old.unlink()
        result = self.migration.run(self.new)
        self.assertEqual(result["missing"], 1)
        self.assertIn(str(self.old), self.store.roots())
        self.assertEqual(self.store.get(identifier)["path"], str(old))

    def test_downloader_artifacts_follow_the_new_location(self):
        self.video()
        artifact = self.old / ".downloads/partial/video.part"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"partial fixture")
        self.migration.run(self.new)
        self.assertEqual((self.new / ".downloads/partial/video.part").read_bytes(), b"partial fixture")
        self.assertFalse(self.old.exists())

    def test_nested_target_is_rejected(self):
        self.video()
        with self.assertRaises(MigrationError):
            self.migration.run(self.old / "nested")
        self.assertFalse(self.migration.pending())


if __name__ == "__main__":
    unittest.main(verbosity=2)
