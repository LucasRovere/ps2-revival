import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from port import REPO, folder_settings, new_game, serial_from_elf, write_new  # noqa: E402


class SerialTest(unittest.TestCase):
    def test_boot_elf_name(self):
        self.assertEqual(serial_from_elf("ABCD_123.45"), "ABCD-12345")
        self.assertEqual(serial_from_elf("DIR/abcd_123.45"), "ABCD-12345")

    def test_other_names(self):
        for name in ("MAIN.ELF", "ABCD_12345", "AB_123.45", "ABCD_123.456"):
            self.assertIsNone(serial_from_elf(name))


class NewGameTest(unittest.TestCase):
    def test_default_game_json(self):
        game = new_game("ABCD-12345", "ABCD_123.45", "0123ABCD")
        self.assertEqual(game["serial"], "ABCD-12345")
        self.assertEqual(game["title"], "ABCD-12345")
        self.assertEqual(game["disc"], {"elf": "ABCD_123.45", "crc": "0123ABCD"})
        self.assertEqual(game["recomp"]["entries"], [])
        self.assertGreater(game["recomp"]["explore_frames"], 0)
        self.assertNotIn("patches", game)


class WriteNewTest(unittest.TestCase):
    def test_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "ABCD-12345"
            write_new(folder, {"game.json": "{}\n", "notes.md": "# x\n"})
            self.assertEqual((folder / "game.json").read_text(), "{}\n")
            self.assertEqual((folder / "notes.md").read_text(), "# x\n")

    def test_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "notes.md").write_text("mine")
            with self.assertRaises(SystemExit):
                write_new(folder, {"game.json": "{}\n", "notes.md": "# x\n"})
            self.assertEqual((folder / "notes.md").read_text(), "mine")
            self.assertFalse((folder / "game.json").exists())


class FolderSettingsTest(unittest.TestCase):
    GAME = {"recomp": {"aspect": "16:9"}, "patches": [{}]}

    def test_defaults(self):
        self.assertEqual(folder_settings(self.GAME, True, None),
                         {"aspect": "16:9", "scale": 1, "fullscreen": False, "textures": "", "memcard": "memcard.ps2"})
        self.assertEqual(folder_settings(self.GAME, False, None)["aspect"], "4:3")

    def test_play_json(self):
        play = {"memcard": "local/x.ps2", "scale": 3, "aspect": "4:3", "textures": "local/pack"}
        settings = folder_settings(self.GAME, True, play)
        self.assertEqual((settings["scale"], settings["aspect"], settings["memcard"]), (3, "4:3", "memcard.ps2"))
        self.assertEqual(settings["textures"], str(REPO / "local/pack"))


if __name__ == "__main__":
    unittest.main()
