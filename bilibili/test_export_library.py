"""Receipt-free exports keep their catalogue, grouping and migration behavior."""
import json
from pathlib import Path
import tempfile
import unittest

from media_library import LibraryStore, gallery_assets
from media_storage import MediaMigration


class ReceiptFreeLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "media"
        self.output.mkdir()
        self.store = LibraryStore(self.root / "private/library.sqlite3")
        self.store.add_root(self.output)

    def tearDown(self):
        self.temp.cleanup()

    def album(self):
        folder = self.output / "完整图文"
        folder.mkdir()
        assets = []
        for name, kind in (("001_图片.png", "image"), ("002_图片.webp", "image"),
                           ("002_实况.mp4", "live_photo"), ("背景音乐.m4a", "music")):
            path = folder / name
            path.write_bytes(name.encode("utf-8"))
            assets.append({"kind": kind, "path": str(path)})
        metadata = {"title": "保存的标题", "platform": "douyin", "assets": assets}
        identifier = self.store.upsert(folder, metadata, completed=True)
        return folder, assets, identifier

    def test_saved_album_rescan_retains_metadata_and_grouping_without_json(self):
        folder, assets, identifier = self.album()
        self.store.scan()
        rows = self.store.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["id"], rows[0]["title"], rows[0]["kind"]),
                         (identifier, "保存的标题", "gallery"))
        self.assertEqual(gallery_assets(folder, json.loads(rows[0]["metadata"])), assets)
        self.assertEqual(rows[0]["size"], sum(Path(asset["path"]).stat().st_size for asset in assets))
        self.assertFalse(list(self.output.rglob("*.json")))

    def test_new_catalogue_discovers_album_and_separate_root_audio_and_image(self):
        folder, assets, _ = self.album()
        audio = self.output / "配音.mp3"
        audio.write_bytes(b"fixture audio")
        image = self.output / "封面.png"
        image.write_bytes(b"fixture image")
        fresh = LibraryStore(self.root / "fresh/library.sqlite3")
        fresh.add_root(self.output)
        fresh.scan()
        rows = {Path(row["path"]): row for row in fresh.rows()}
        self.assertEqual(set(rows), {folder, audio, image})
        self.assertEqual((rows[folder]["kind"], rows[audio]["kind"], rows[image]["kind"]),
                         ("gallery", "audio", "image"))
        self.assertEqual(len(json.loads(rows[folder]["metadata"])["assets"]), len(assets))
        self.assertEqual(rows[audio]["state"], "pending")
        self.assertEqual(rows[image]["state"], "ready")

    def test_unrelated_video_next_to_album_is_not_swallowed(self):
        folder, _, _ = self.album()
        movie = folder / "另外的视频.mp4"
        movie.write_bytes(b"unrelated video fixture")
        fresh = LibraryStore(self.root / "fresh/library.sqlite3")
        fresh.add_root(self.output)
        fresh.scan()
        rows = {Path(row["path"]): row for row in fresh.rows()}
        self.assertEqual(set(rows), {folder, movie})
        self.assertNotIn(str(movie), [asset["path"] for asset in json.loads(rows[folder]["metadata"])["assets"]])

    def test_moved_receipt_free_album_keeps_id_and_correct_asset_paths(self):
        folder, _, identifier = self.album()
        moved = folder.with_name("手动重命名")
        folder.rename(moved)
        self.store.scan()
        row = self.store.get(identifier)
        self.assertEqual(Path(row["path"]), moved)
        self.assertEqual(len(self.store.rows()), 1)
        self.assertTrue(all(Path(asset["path"]).is_file() for asset in json.loads(row["metadata"])["assets"]))

    def test_delete_asset_changes_only_database_and_leaves_no_sidecars(self):
        folder, assets, identifier = self.album()
        self.store.delete_asset(identifier, assets[0]["path"])
        self.store.scan()
        row = self.store.get(identifier)
        self.assertEqual(len(json.loads(row["metadata"])["assets"]), 3)
        self.assertEqual(row["state"], "ready")
        self.assertFalse(Path(assets[0]["path"]).exists())
        self.assertFalse(list(folder.glob("*.json")))
        for asset in assets[1:]:
            self.store.delete_asset(identifier, asset["path"])
        self.assertFalse(folder.exists())
        self.assertFalse(self.store.rows())

    def test_audio_and_video_source_keys_are_distinct_after_rescan(self):
        video = self.output / "作品.mp4"
        audio = self.output / "作品.mp3"
        video.write_bytes(b"fixture video")
        audio.write_bytes(b"fixture audio")
        video_id = self.store.upsert(video, {"duration": 5}, source_key="source:one", completed=True)
        audio_id = self.store.upsert(audio, {"duration": 5}, source_key="source:one|audio:192", completed=True)
        self.store.scan()
        self.assertEqual(self.store.find_source("source:one")["id"], video_id)
        self.assertEqual(self.store.find_source("source:one|audio:192")["id"], audio_id)
        self.assertIsNone(self.store.find_source("source:one|audio:320"))
        self.store.delete_files(audio_id)
        self.assertTrue(video.is_file())
        self.assertFalse(audio.exists())
        self.assertIsNone(self.store.find_source("source:one|audio:192"))

    def test_migration_moves_audio_and_receipt_free_album_without_export_json(self):
        folder, _, identifier = self.album()
        audio = self.output / "声音.mp3"
        audio.write_bytes(b"complete MP3 fixture")
        audio_id = self.store.upsert(audio, {"duration": 3}, completed=True)
        target = self.root / "new media"
        preferences = {"output": str(self.output)}
        migration = MediaMigration(self.store, settings=lambda: preferences.copy(),
                                   save=lambda **values: preferences.update(values))
        migration.run(target)
        row = self.store.get(identifier)
        self.assertEqual(Path(row["path"]), target / folder.name)
        self.assertTrue(all(Path(asset["path"]).is_file() for asset in json.loads(row["metadata"])["assets"]))
        self.assertEqual(Path(self.store.get(audio_id)["path"]).read_bytes(), b"complete MP3 fixture")
        self.assertEqual(self.store.get(audio_id)["kind"], "audio")
        self.assertFalse(self.output.exists())
        self.assertFalse(list(target.rglob("*.json")))
        self.store.scan()
        self.assertEqual(len(self.store.rows()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
