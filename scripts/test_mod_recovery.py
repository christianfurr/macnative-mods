import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mod_environment import ModError, overlay_signature
from mods import Backend


class Recovery(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.backend = Backend.__new__(Backend)
        self.backend.version = "botw160"
        self.backend.load = root / "mods" / "botw160"
        self.backend.slot = root / "game-slot" / "lock"
        self.backend.game = SimpleNamespace(name="Breath of the Wild")
        self.backend.folder = SimpleNamespace(backup_name=lambda folder: folder.with_name("botw160.backup-20261109-200000"))
        self.backend.ot_manifest = None
        self.backend.library = SimpleNamespace(state={"selected_profile": "Default", "enabled": ["demo"]})
        self.backend.load.mkdir(parents=True)
        (self.backend.load / "manifest.tsv").write_text("demo\n")

    def test_unmodded_and_restore_keep_profile_and_previous_manifest(self):
        self.backend.recover()
        self.assertFalse(self.backend.load.exists())
        backup = self.backend.latest_backup()
        self.assertIsNotNone(backup)
        with self.assertRaisesRegex(ModError, "previous overlay changed"):
            self.backend.recover("../botw160")
        self.backend.recover(backup)
        self.assertEqual((self.backend.load / "manifest.tsv").read_text(), "demo\n")
        self.assertEqual(self.backend.library.state, {"selected_profile": "Default", "enabled": ["demo"]})

    def test_recovery_refuses_to_change_overlay_while_game_runs(self):
        with patch("mods.native_game_running", return_value=True):
            with self.assertRaisesRegex(ModError, "Quit Breath of the Wild"):
                self.backend.with_closed_game(self.backend.recover)
        self.assertTrue(self.backend.load.is_dir())
        self.assertIsNone(self.backend.latest_backup())

    def test_same_second_recovery_keeps_the_most_recent_overlay_first(self):
        previous = self.backend.load.with_name("botw160.backup-20261109-200000-3")
        previous.mkdir()
        (previous / "manifest.tsv").write_text("old\n")
        signature, _ = overlay_signature(self.backend.load)
        self.backend.library.state["overlay_profiles"] = {signature: "Default"}

        self.backend.recover()
        latest = self.backend.latest_backup()
        self.assertEqual(latest, "botw160.backup-20261109-200000-4")
        self.backend.recover(latest)
        restored, _ = overlay_signature(self.backend.load)
        self.assertEqual(self.backend.profile_for_overlay(restored), "Default")

    def test_restore_rolls_back_if_previous_overlay_cannot_be_moved(self):
        backup = self.backend.load.with_name("botw160.backup-20261108-200000")
        backup.mkdir()
        (backup / "manifest.tsv").write_text("old\n")
        real_rename = Path.rename

        def rename(folder, destination):
            if folder == backup:
                raise OSError("restore failed")
            return real_rename(folder, destination)

        with patch.object(Path, "rename", rename):
            with self.assertRaisesRegex(OSError, "restore failed"):
                self.backend.recover(backup.name)
        self.assertEqual((self.backend.load / "manifest.tsv").read_text(), "demo\n")
        self.assertEqual(self.backend.latest_backup(), backup.name)


if __name__ == "__main__":
    unittest.main()
