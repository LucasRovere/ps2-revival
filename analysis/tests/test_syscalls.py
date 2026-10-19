import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from syscalls import SYSCALLS, proposed_names, scan_asm  # noqa: E402

WRAPPER = """// FUN_00200000 @ 0x00200000
0x00200000  42000324  li v1,0x42
0x00200004  0c000000  syscall 0x0
0x00200008  0800e003  jr ra
0x0020000c  00000000  _nop
"""
INTR_WRAPPER = WRAPPER.replace("FUN_00200000", "iSignalSema").replace("li v1,0x42", "li v1,-0x43")
INLINE = """// entry @ 0x00100008
0x001001d0  3c000324  li v1,0x3c
0x001001d4  0c000000  syscall 0x0
0x001001d8  00000000  nop
0x001001ec  3d000324  li v1,0x3d
0x001001f0  0c000000  syscall 0x0
0x001001f4  4000080c  jal 0x00200100
"""
NO_SYSCALL = "// FUN_00100000 @ 0x00100000\n0x00100000  0800e003  jr ra\n0x00100004  00000000  _nop\n"
UNKNOWN = WRAPPER.replace("li v1,0x42", "li v1,0x81")


class ScanAsmTest(unittest.TestCase):
    def test_wrapper(self):
        self.assertEqual(scan_asm(WRAPPER), ("0x00200000", "FUN_00200000", [0x42], True))

    def test_negative_number(self):
        self.assertEqual(scan_asm(INTR_WRAPPER)[2], [-0x43])

    def test_inline_sites(self):
        self.assertEqual(scan_asm(INLINE), ("0x00100008", "entry", [0x3c, 0x3d], False))

    def test_no_syscall(self):
        self.assertIsNone(scan_asm(NO_SYSCALL))


class ProposedNamesTest(unittest.TestCase):
    def test_only_known_wrappers(self):
        results = [scan_asm(t) for t in (WRAPPER, INTR_WRAPPER, INLINE, UNKNOWN)]
        results[1] = ("0x00200010",) + results[1][1:]
        self.assertEqual(proposed_names(results), {"0x00200000": "SignalSema", "0x00200010": "iSignalSema"})

    def test_interrupt_variant_is_not_negated_base(self):
        self.assertEqual(SYSCALLS[0x33], "WakeupThread")
        self.assertEqual(SYSCALLS[-0x34], "_iWakeupThread")
        self.assertNotIn(0x34, SYSCALLS)


if __name__ == "__main__":
    unittest.main()
