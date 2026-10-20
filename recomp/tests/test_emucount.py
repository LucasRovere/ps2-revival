import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import emucount as ec  # noqa: E402

# two 100-frame sections as PS2_EMU_COUNT writes them
TEXT = """# ps2 emu_count 1
section 100 200
c vu1 abc 3f0 200 0 0
c iop_instr 1 0 50 10000 300
c ee_io 1000f000 0 400 0 0
c ee_pc 1000f000 200001400 400 0 0
c sif_call 4321 0 100 204800 2048
c gs_prim 4 0 1000 0 0
gsstate 1000 1c 0 0 0 0 0 50000 0 0 1000000 0 0 1 0
hle thsemap 8 20
section 200 300
c vu1 abc 3f0 100 0 0
c gs_tex_target a3200 a 7 0 0
iopmodule 400 1000 SNDDRV
"""


class EmuCountTest(unittest.TestCase):
    def test_parse_and_range(self):
        run = ec.parse(TEXT)
        self.assertEqual(run["frames"], (100, 300))
        self.assertEqual(run["c"]["vu1", 0xABC, 0x3F0], [300, 0, 0])
        self.assertEqual(run["hle"]["thsemap", 8], 20)
        self.assertEqual(run["modules"], [(0x400, 0x1000, "SNDDRV")])
        second = ec.parse(TEXT, 200, 300)
        self.assertEqual(second["frames"], (200, 300))
        self.assertEqual(second["c"]["vu1", 0xABC, 0x3F0], [100, 0, 0])
        self.assertNotIn(("gs_prim", 4, 0), second["c"])
        self.assertEqual(len(second["states"]), 0)

    def test_names(self):
        self.assertEqual(ec.vif_name(0x6C), "UNPACK V4-32")
        self.assertEqual(ec.vif_name(0x7E), "UNPACK V4-8m")
        self.assertEqual(ec.vif_name(0x14), "MSCAL")
        self.assertEqual(ec.iop_module([(0x400, 0x1000, "SNDDRV")], 0x800), "SNDDRV")
        s = ec.decode_state((0x1C, 0, 0, 0, 0, 0, 0x50000, 0, 0, 0x1000000, 0, 0, 1, 0))
        self.assertEqual(s, "tri strip, IIP, TME, tex CT32 MODULATE, mag nearest min nearest, wrap REPEAT/REPEAT, TEXA 00/00,"
                            " ztest GEQUAL Z Z24, FB CT32")

    def test_report(self):
        lines = ec.report(ec.parse(TEXT), ec.Functions(None), 10)
        text = "\n".join(lines)
        self.assertIn("frames 100-300 (200)", text)
        self.assertIn("IOP instructions                           50.0", text)  # 10000 / 200 frames
        self.assertIn("00004321 fn    0", text)
        self.assertIn("INTC       read  00000A00", text)  # pc 0xA00 unnamed without an export
        self.assertIn("3200 CT16S <- CT16S", text)
        self.assertIn("SNDDRV", text)


if __name__ == "__main__":
    unittest.main()
