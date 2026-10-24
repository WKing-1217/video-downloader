"""Catalogue migrations, hidden records, moved files and non-destructive roots."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
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

    def album(self, count=2):
        folder = self.output / "图文"
        folder.mkdir()
        files = [folder / f"{number:03d}.jpg" for number in range(count)]
        for path in files:
            path.write_bytes(b"image fixture")
        info = {"title": "图文", "content_type": "gallery", "assets":
                [{"kind": "image", "path": str(path)} for path in files], "size": 13 * count}
        (folder / "作品信息.json").write_text(json.dumps(info), encoding="utf-8")
        identifier = self.store.upsert(folder, info, completed=True)
        return folder, files, identifier

    def test_single_image_delete_updates_database_and_does_not_reappear(self):
        folder, files, identifier = self.album()
        receipt = (folder / "作品信息.json").read_bytes()
        updated = self.store.delete_asset(identifier, files[0])
        self.assertFalse(files[0].exists())
        self.assertTrue(files[1].is_file())
        content = json.loads(updated["metadata"])
        self.assertEqual(len(content["assets"]), 1)
        self.assertEqual(content["assets"][0]["path"], str(files[1]))
        self.assertEqual(updated["size"], files[1].stat().st_size)
        self.assertEqual(updated["thumb"], "")
        self.assertEqual((folder / "作品信息.json").read_bytes(), receipt)
        self.store.scan()
        self.assertEqual(len(json.loads(self.store.get(identifier)["metadata"])["assets"]), 1)
        self.assertFalse(list(folder.glob(".delete-*")))

    def test_last_image_delete_preserves_existing_legacy_receipt(self):
        folder, files, identifier = self.album(1)
        receipt = (folder / "作品信息.json").read_bytes()
        updated = self.store.delete_asset(identifier, files[0])
        self.assertFalse(files[0].exists())
        self.assertEqual((folder / "作品信息.json").read_bytes(), receipt)
        self.assertTrue(updated["hidden"])
        self.assertFalse(self.store.rows())
        self.store.scan()
        self.assertFalse(self.store.rows())

    def test_last_image_delete_keeps_unrecorded_notes(self):
        folder, files, identifier = self.album(1)
        notes = folder / "笔记.txt"
        notes.write_bytes(b"personal notes")
        self.store.delete_asset(identifier, files[0])
        self.assertEqual(notes.read_bytes(), b"personal notes")
        self.assertTrue((folder / "作品信息.json").exists())

    def test_unrecorded_file_cannot_be_deleted_as_an_image(self):
        folder, files, identifier = self.album()
        notes = folder / "笔记.txt"
        notes.write_bytes(b"keep")
        with self.assertRaises(ValueError):
            self.store.delete_asset(identifier, notes)
        self.assertEqual(notes.read_bytes(), b"keep")
        with self.assertRaises(ValueError):
            self.store.delete_asset(identifier, self.root / files[0].name)
        self.assertTrue(files[0].is_file())

    def test_failed_db_change_restores_image_and_receipt(self):
        folder, files, identifier = self.album()
        receipt = (folder / "作品信息.json").read_bytes()
        update = self.store.update
        calls = [0]
        def fail_once(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 1:
                raise OSError("fixture database failure")
            return update(*args, **kwargs)
        with patch.object(self.store, "update", fail_once):
            with self.assertRaises(OSError):
                self.store.delete_asset(identifier, files[0])
        self.assertTrue(all(path.is_file() for path in files))
        self.assertEqual((folder / "作品信息.json").read_bytes(), receipt)
        self.assertEqual(len(json.loads(self.store.get(identifier)["metadata"])["assets"]), 2)

    def test_failed_image_unlink_restores_image_and_receipt(self):
        folder, files, identifier = self.album()
        real_unlink = Path.unlink
        def unlink(path, *args, **kwargs):
            if path.name.startswith(".delete-"):
                raise PermissionError("fixture file is locked")
            return real_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", unlink):
            with self.assertRaises(PermissionError):
                self.store.delete_asset(identifier, files[0])
        self.assertTrue(all(path.is_file() for path in files))
        self.assertEqual(len(json.loads(self.store.get(identifier)["metadata"])["assets"]), 2)

    def test_preview_does_not_restore_a_deleted_sample_on_restart(self):
        from preview_ui import seed_samples
        sources = self.root / "video"
        sources.mkdir()
        for name in ("手写.mp4", "别怕.mp4", "朋友.mp4"):
            path = sources / name
            path.write_bytes(b"preview fixture")
            path.with_suffix(".mp4.info.json").write_text('{"duration": 6}', encoding="utf-8")
        with patch("preview_ui.ROOT", self.root / "app"):
            seed_samples(self.store, self.output)
            item = self.store.rows()[0]
            self.store.delete_files(item["id"])
            seed_samples(self.store, self.output)
        self.assertFalse(Path(item["path"]).exists())
        self.assertEqual(len(self.store.rows()), 2)
        self.assertEqual(self.store.get(item["id"])["hidden"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
