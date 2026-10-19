import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analyze import asm_mismatches, check_export, headless_command, log_warnings, parse_names  # noqa: E402

# One segment: file offset 0x10 maps to vaddr 0x100000.
SEGMENTS = [{"offset": 0x10, "vaddr": "0x100000", "filesz": 8}]
ELF = bytes(0x10) + bytes.fromhex("0800e003" "00000000")
ASM = "// FUN_00100000 @ 0x00100000\n0x00100000  0800e003  jr ra\n0x00100004  00000000  _nop\n"


class ParseNamesTest(unittest.TestCase):
    def test_sorted_by_address(self):
        config = {"analysis": {"names": {"0x00100010": "b", "0x00100008": "main_loop"}}}
        self.assertEqual(parse_names(config), [(0x100008, "main_loop"), (0x100010, "b")])

    def test_missing_section_is_empty(self):
        self.assertEqual(parse_names({"serial": "X"}), [])

    def test_rejects_invalid_name(self):
        with self.assertRaises(ValueError):
            parse_names({"analysis": {"names": {"0x100008": "bad name"}}})

    def test_rejects_invalid_address(self):
        with self.assertRaises(ValueError):
            parse_names({"analysis": {"names": {"main": "main"}}})


class HeadlessCommandTest(unittest.TestCase):
    def test_import_then_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            elf = Path("disc/ABCD_000.01")
            cmd = headless_command(Path("ghidra"), project_dir, "ABCD-00001", elf, Path("out"), None)
            self.assertIn("-import", cmd)
            self.assertIn("r5900:LE:32:default", cmd)
            self.assertEqual(cmd[-3:], ["-postScript", "Export.java", "out"])

            (project_dir / "ABCD-00001.gpr").touch()
            cmd = headless_command(Path("ghidra"), project_dir, "ABCD-00001", elf, Path("out"), Path("n.tsv"))
            self.assertEqual(cmd[3:6], ["-process", "ABCD_000.01", "-noanalysis"])
            self.assertEqual(cmd[-1], "n.tsv")


class LogWarningsTest(unittest.TestCase):
    def test_counts_warnings_and_errors(self):
        log = "INFO  ok (X)\nWARN  8 NOP constructors (SleighCompile)\nWARN  8 NOP constructors (SleighCompile)\nERROR boom (Y)\n"
        counts = log_warnings(log)
        self.assertEqual(counts["WARN 8 NOP constructors (SleighCompile)"], 2)
        self.assertEqual(counts["ERROR boom (Y)"], 1)
        self.assertEqual(len(counts), 2)


class CheckExportTest(unittest.TestCase):
    def write_export(self, out, asm):
        (out / "functions").mkdir()
        (out / "functions.jsonl").write_text(json.dumps({"addr": "0x00100000", "name": "FUN_00100000"}) + "\n")
        for name in ("strings.jsonl", "data_xrefs.jsonl", "symbols.jsonl"):
            (out / name).write_text("")
        (out / "functions" / "00100000.asm").write_text(asm)
        (out / "functions" / "00100000.c").write_text("void FUN_00100000(void) {}\n")

    def test_asm_matches_elf(self):
        self.assertEqual(asm_mismatches(ASM, ELF, SEGMENTS), [])

    def test_asm_mismatch_reported(self):
        bad = ASM.replace("0800e003", "0900e003")
        self.assertEqual(len(asm_mismatches(bad, ELF, SEGMENTS)), 1)

    def test_valid_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.write_export(out, ASM)
            self.assertEqual(check_export(out, ELF, SEGMENTS), [])

    def test_missing_file_and_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.write_export(out, ASM)
            (out / "functions" / "00100000.c").unlink()
            (out / "strings.jsonl").write_text("{broken\n")
            problems = check_export(out, ELF, SEGMENTS)
            self.assertIn("functions/00100000.c: missing", problems)
            self.assertIn("strings.jsonl:1: not JSON", problems)


if __name__ == "__main__":
    unittest.main()
