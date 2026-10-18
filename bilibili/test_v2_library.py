"""Catalogue migrations, hidden records, moved files and non-destructive roots."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from media_library import LibraryStore


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "old videos"
        self.output.mkdir()
        self.store = LibraryStore(self.root / "data/library.sqlite3")
        self.store.add_root(self.output)

    def tearDown(self):
        self.temp.cleanup()

    def media(self, name="历史视频.mp4"):
        path = self.output / name
        path.write_bytes(b"known complete fixture")
        info = {"title": "历史视频", "duration": 12, "size": path.stat().st_size, "source_key": "source:one"}
        path.with_suffix(".mp4.info.json").write_text(json.dumps(info), encoding="utf-8")
        return path, info

    def test_existing_receipts_are_imported_with_duration_title_and_size(self):
        path, info = self.media()
        self.store.scan()
        item = self.store.rows()[0]
        self.assertEqual((item["title"], item["duration"], item["size"]), (info["title"], 12, path.stat().st_size))
        self.assertEqual(item["state"], "ready")

    def test_changed_output_keeps_old_root_and_does_not_move_files(self):
        path, _ = self.media()
        new = self.root / "new videos"
        new.mkdir()
        self.store.add_root(new)
        self.store.scan()
        self.assertTrue(path.exists())
        self.assertEqual(len(self.store.roots()), 2)
        self.assertEqual(len(self.store.rows()), 1)
        self.assertFalse(list(new.iterdir()))

    def test_hidden_record_is_not_reimported_and_file_remains(self):
        path, _ = self.media()
        self.store.scan()
        self.store.remove_record(self.store.rows()[0]["id"])
        self.store.scan()
        self.assertTrue(path.exists())
        self.assertFalse(self.store.rows())

    def test_move_within_roots_retains_id_and_external_delete_marks_missing(self):
        path, _ = self.media()
        self.store.scan()
        item = self.store.rows()[0]
        moved = path.with_name("新名字.mp4")
        path.rename(moved)
        self.store.scan()
        updated = self.store.get(item["id"])
        self.assertEqual(Path(updated["path"]), moved)
        moved.unlink()
        self.store.scan()
        self.assertEqual(self.store.get(item["id"])["state"], "missing")

    def test_temp_and_quarantined_files_never_enter_catalogue(self):
        for folder in (".downloads", "未通过校验"):
            path = self.output / folder
            path.mkdir()
            (path / "incomplete.mp4").write_bytes(b"partial")
        (self.output / "video.f100026.mp4").write_bytes(b"unmerged")
        self.store.scan()
        self.assertFalse(self.store.rows())

    def test_stale_receipt_size_cannot_mark_changed_file_ready(self):
        path, _ = self.media()
        path.write_bytes(b"truncated")
        self.store.scan()
        self.assertEqual(self.store.rows()[0]["state"], "pending")

    def test_newer_database_schema_is_preserved_and_rejected(self):
        database = self.root / "future.sqlite3"
        with closing(sqlite3.connect(database)) as db:
            db.execute("PRAGMA user_version=99")
            db.commit()
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            LibraryStore(database)
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)

    def test_deleting_album_removes_only_recorded_assets(self):
        folder = self.output / "图文"
        folder.mkdir()
        asset = folder / "001.jpg"
        asset.write_bytes(b"fixture")
        personal = folder / "个人笔记.txt"
        personal.write_text("must remain", encoding="utf-8")
        info = {"title": "图文", "assets": [{"kind": "image", "path": str(asset)}], "size": 7}
        identifier = self.store.upsert(folder, info, completed=True)
        self.store.delete_files(identifier)
        self.assertFalse(asset.exists())
        self.assertTrue(personal.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
