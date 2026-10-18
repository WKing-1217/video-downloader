"""Installation and rollback fixtures never touch the user's installed application."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import shutil
import tempfile
import unittest

from update_agent import execute_update, manifest_files, PRODUCT, within, write_json, copy_file, native_path


class ExitedProcess:
    pid = 0
    def poll(self):
        return 0


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app, self.data, self.cache = (self.root / name for name in ("app", "data", "cache"))
        for path in (self.app, self.data, self.cache):
            path.mkdir()
        (self.app / "VideoDownloader.exe").write_bytes(b"MZ-original-gui")
        (self.app / "_internal").mkdir()
        (self.app / "_internal/runtime.dll").write_bytes(b"original-runtime")
        (self.app / "video").mkdir()
        (self.app / "video/personal.mp4").write_bytes(b"do not touch media")
        (self.app / "personal.txt").write_text("do not touch unrelated file")
        (self.data / "WebProfile").mkdir()
        (self.data / "WebProfile/Cookies").write_bytes(b"preserve profile fixture")
        write_json(self.data / "settings.json", {"output": str(self.app / "video"), "auto_login": True})
        with closing(sqlite3.connect(self.data / "library.sqlite3")) as database:
            database.execute("CREATE TABLE history(title TEXT)")
            database.execute("INSERT INTO history VALUES ('original record')")
            database.commit()
        self.installer = self.cache / "installer.exe"
        self.installer.write_bytes(b"MZ-controlled-installer")
        self.plan = {"schema": 1, "product": PRODUCT, "version": "2.0.0", "previous_version": "1.0.4",
                     "nonce": "a" * 32, "app_dir": str(self.app), "data_dir": str(self.data),
                     "cache_dir": str(self.cache), "installer": str(self.installer), "old_pid": 0,
                     "handshake": str(self.cache / "ready.json"), "helper_ready": str(self.cache / "ack.json"),
                     "sha256": hashlib.sha256(self.installer.read_bytes()).hexdigest(), "size": self.installer.stat().st_size,
                     "protected_roots": [str(self.app / "video")], "manage_registry": False, "no_restart_on_failure": True}

    def tearDown(self):
        assert self.root.resolve() == Path(self.temp.name).resolve() and self.root.parent == Path(tempfile.gettempdir())
        shutil.rmtree(native_path(self.root))
        self.temp.cleanup()

    def damage_install(self, installer, app):
        (app / "VideoDownloader.exe").write_bytes(b"MZ-new-gui")
        (app / "_internal/runtime.dll").write_bytes(b"new-runtime")
        (app / "new.dll").write_bytes(b"new file")
        write_json(app / "install-manifest.json", {"product": PRODUCT, "files": ["VideoDownloader.exe", "_internal/runtime.dll", "new.dll"]})
        write_json(self.data / "settings.json", {"bad": "changed by broken new version"})
        with closing(sqlite3.connect(self.data / "library.sqlite3")) as database:
            database.execute("DELETE FROM history")
            database.commit()
        return 0

    def assert_original(self):
        self.assertEqual((self.app / "VideoDownloader.exe").read_bytes(), b"MZ-original-gui")
        self.assertEqual((self.app / "_internal/runtime.dll").read_bytes(), b"original-runtime")
        self.assertFalse((self.app / "new.dll").exists())
        self.assertEqual(json.loads((self.data / "settings.json").read_text())["auto_login"], True)
        database = sqlite3.connect(self.data / "library.sqlite3")
        try:
            self.assertEqual(database.execute("SELECT title FROM history").fetchone()[0], "original record")
        finally:
            database.close()
        self.assertEqual((self.app / "video/personal.mp4").read_bytes(), b"do not touch media")
        self.assertEqual((self.data / "WebProfile/Cookies").read_bytes(), b"preserve profile fixture")
        self.assertTrue((self.app / "personal.txt").exists())

    def test_nonzero_installer_restores_program_settings_history_and_preserves_media_profile(self):
        def fail(installer, app):
            self.damage_install(installer, app)
            return 5
        result = execute_update(self.plan, installer_runner=fail)
        self.assertFalse(result["success"])
        self.assertTrue(result["rollback"])
        self.assert_original()

    def test_new_version_startup_failure_restores_original(self):
        result = execute_update(self.plan, installer_runner=self.damage_install,
                                app_launcher=ExitedProcess, readiness=lambda _: False)
        self.assertTrue(result["rollback"])
        self.assert_original()

    def test_invalid_new_manifest_does_not_block_restoring_old_runtime(self):
        def fail(installer, app):
            self.damage_install(installer, app)
            (app / "install-manifest.json").write_text("broken new manifest")
            return 5
        result = execute_update(self.plan, installer_runner=fail)
        self.assertTrue(result["rollback"])
        self.assertEqual((self.app / "VideoDownloader.exe").read_bytes(), b"MZ-original-gui")

    def test_success_requires_new_version_readiness_and_writes_result(self):
        result = execute_update(self.plan, installer_runner=lambda *_: 0,
                                app_launcher=ExitedProcess, readiness=lambda _: True)
        self.assertTrue(result["success"])
        self.assertEqual(json.loads((self.cache / "ack.json").read_text())["nonce"], self.plan["nonce"])
        self.assertTrue((self.data / "updates/install-result.json").is_file())
        self.assert_original()

    def test_modified_installer_is_rejected_before_any_mutation(self):
        self.installer.write_bytes(b"MZ-tampered")
        with self.assertRaisesRegex(ValueError, "更新包"):
            execute_update(self.plan, installer_runner=lambda *_: self.fail("must not execute"))
        self.assert_original()
        self.assertFalse((self.cache / "ack.json").exists())

    def test_user_data_inside_install_dir_is_rejected(self):
        self.plan["data_dir"] = str(self.app / "data")
        with self.assertRaisesRegex(ValueError, "目录"):
            execute_update(self.plan)

    def test_manifest_traversal_is_rejected_and_external_file_preserved(self):
        outside = self.root / "private.txt"
        outside.write_text("private")
        write_json(self.app / "install-manifest.json", {"product": PRODUCT, "files": ["../private.txt"]})
        with self.assertRaises(ValueError):
            manifest_files(self.app)
        self.assertEqual(outside.read_text(), "private")
        for value in ("..\\private.txt", str(outside)):
            with self.assertRaises(ValueError):
                within(self.app, value)

    def test_downgrade_and_reused_backup_are_rejected(self):
        self.plan["version"] = "1.0.3"
        with self.assertRaises(ValueError):
            execute_update(self.plan)
        self.plan["version"] = "2.0.0"
        (self.cache / ("rollback-" + self.plan["nonce"])).mkdir()
        with self.assertRaisesRegex(ValueError, "备份"):
            execute_update(self.plan)

    def test_long_windows_resource_backup_and_restore(self):
        relative = "_internal/" + "/".join(["resource-directory-with-a-long-name"] * 7) + "/plugin.dll"
        resource = self.app / relative
        copy_file(self.app / "_internal/runtime.dll", resource)
        write_json(self.app / "install-manifest.json", {"product": PRODUCT, "files": [
            "VideoDownloader.exe", "_internal/runtime.dll", relative]})
        def fail(*_):
            native_path(resource).write_bytes(b"damaged by installer")
            return 5
        result = execute_update(self.plan, installer_runner=fail)
        self.assertTrue(result["rollback"])
        self.assertEqual(native_path(resource).read_bytes(), b"original-runtime")


if __name__ == "__main__":
    unittest.main(verbosity=2)
