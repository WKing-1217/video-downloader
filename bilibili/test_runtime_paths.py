"""Preferences follow the current profile and keep the chosen media directory."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import os

import runtime_paths


class SettingsPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "first"), "VIDEO_DOWNLOADER_OUTPUT": ""})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_changing_profile_after_import_does_not_write_original_profile(self):
        runtime_paths.save_settings(output=str(self.root / "first-videos"))
        original = runtime_paths.settings_path()
        before = original.read_bytes()
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "second")}):
            self.assertNotEqual(runtime_paths.settings_path(), original)
            self.assertEqual(runtime_paths.read_settings(), {})
            runtime_paths.save_settings(output=str(self.root / "second-videos"))
            self.assertEqual(runtime_paths.output_dir(), self.root / "second-videos")
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(runtime_paths.output_dir(), self.root / "first-videos")

    def test_parallel_preference_updates_do_not_drop_download_location(self):
        runtime_paths.save_settings(output=str(self.root / "chosen"))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda number: runtime_paths.save_settings(**{f"fixture_{number}": number}), range(12)))
        values = runtime_paths.read_settings()
        self.assertEqual(values["output"], str(self.root / "chosen"))
        self.assertTrue(all(values[f"fixture_{number}"] == number for number in range(12)))
        self.assertFalse(list(runtime_paths.settings_path().parent.glob("*.tmp")))

    @unittest.skipUnless(os.name == "nt", "Windows installer seed")
    def test_saved_location_takes_priority_over_initial_installer_seed(self):
        chosen = self.root / "installer-choice"
        with patch.object(runtime_paths, "FROZEN", True), patch("winreg.OpenKey"), patch("winreg.QueryValueEx", return_value=(str(chosen), 1)):
            self.assertEqual(runtime_paths.output_dir(), chosen)
            runtime_paths.save_settings(output=str(self.root / "later-choice"))
            self.assertEqual(runtime_paths.output_dir(), self.root / "later-choice")


if __name__ == "__main__":
    unittest.main(verbosity=2)
