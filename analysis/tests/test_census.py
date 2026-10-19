import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from census import census, decode, find_jump_table, gaps, parse_asm  # noqa: E402

AT, V0, V1, A0, T9, RA = 1, 2, 3, 4, 25, 31


def i_type(op, rs, rt, imm):
    return op << 26 | rs << 21 | rt << 16 | imm & 0xffff


def r_type(rs, rt, rd, sa, funct, op=0):
    return op << 26 | rs << 21 | rt << 16 | rd << 11 | sa << 6 | funct


SLTIU, LUI, ADDIU, LW = 11, 15, 9, 35
JR_RA = r_type(RA, 0, 0, 0, 8)
NOP = 0

# Game-code shape: lw r,lo(b) after lui b,hi; addu b,b,idx.
GAME_TABLE = [i_type(SLTIU, A0, V1, 5), r_type(0, A0, A0, 2, 0), i_type(LUI, 0, AT, 0x50),
              r_type(AT, A0, AT, 0, 33), i_type(LW, AT, AT, -0x120), r_type(AT, 0, 0, 0, 8), NOP]
# SDK shape: lui p,hi; addiu p,p,lo; addu b,idx,p; lw r,0(b).
SDK_TABLE = [i_type(SLTIU, V1, V0, 0x10), i_type(LUI, 0, V0, 0x52), r_type(0, V1, V1, 2, 0),
             i_type(ADDIU, V0, V0, -0x1d30), r_type(V1, V0, V1, 0, 33), i_type(LW, V1, A0, 0),
             r_type(A0, 0, 0, 0, 8), NOP]


def numbered(words, start=0x1000):
    return [(start + 4 * i, w) for i, w in enumerate(words)]


class DecodeTest(unittest.TestCase):
    def test_classes(self):
        cases = {
            i_type(LUI, 0, V0, 0x4b): ("lui", "base"),
            r_type(V0, V1, A0, 0, 45): ("daddu", "base"),
            0x70000c28: ("padduw", "mmi"),      # Ghidra prints it as `clear at`
            i_type(30, 29, A0, 0x10): ("lq", "mmi"),
            0x0000000c: ("syscall", "system"),
            0x42000038: ("ei", "cop0"),
            0x46020800: ("add.s", "cop1"),
            0x46800020: ("cvt.s.w", "cop1"),
            i_type(49, 29, 0, 0): ("lwc1", "cop1"),
            0x4be00000: ("vaddbc", "cop2"),      # vaddx, broadcast forms counted together
            0x4a0002ff: ("vnop", "cop2"),
            i_type(54, 29, 0, 0): ("lqc2", "cop2"),
        }
        for word, expected in cases.items():
            self.assertEqual(decode(word), expected, hex(word))

    def test_invalid(self):
        self.assertIsNone(decode(19 << 26)[0])
        self.assertIsNone(decode(r_type(0, 0, 0, 0, 1))[0])
        self.assertIsNone(decode(r_type(0, 0, 0, 0, 2, op=28))[0])


class JumpTableTest(unittest.TestCase):
    def test_game_shape(self):
        self.assertEqual(find_jump_table(numbered(GAME_TABLE), 5), (0x4ffee0, 5))

    def test_sdk_shape(self):
        self.assertEqual(find_jump_table(numbered(SDK_TABLE), 6), (0x51e2d0, 16))

    def test_register_jump(self):
        self.assertIsNone(find_jump_table(numbered([NOP, r_type(T9, 0, 0, 0, 8), NOP]), 1))

    def test_no_bound(self):
        self.assertEqual(find_jump_table(numbered(GAME_TABLE[1:]), 4), (0x4ffee0, None))


class GapsTest(unittest.TestCase):
    def test_runs(self):
        text = b"".join(w.to_bytes(4, "little") for w in [JR_RA, NOP, NOP, JR_RA, 19 << 26, JR_RA])
        runs = gaps({0x1000, 0x1014}, 0x1000, text)
        self.assertEqual(runs, [{"start": "0x00001004", "size": 16, "zero_words": 2, "invalid_words": 1, "jr_ra": 1}])


class CensusTest(unittest.TestCase):
    def test_table_targets_and_counts(self):
        # Image: function at 0x1000 (GAME_TABLE + jr ra), loose code at 0x1024, table at 0x4ffee0.
        words = GAME_TABLE + [JR_RA, NOP, JR_RA, NOP]
        image_addr = 0x1000
        image = bytearray(0x4ffee0 - image_addr + 20)
        for i, w in enumerate(words):
            image[4 * i:4 * i + 4] = w.to_bytes(4, "little")
        for i, target in enumerate([0x1018, 0x101c, 0x1024, 0x1018, 0x1018]):
            off = 0x4ffee0 - image_addr + 4 * i
            image[off:off + 4] = target.to_bytes(4, "little")
        functions = [(0x1000, "f", numbered(words[:9]))]
        result = census(functions, bytes(image), image_addr, 0x1000, 4 * len(words))
        self.assertEqual(result["mnemonics"]["jr"], {"class": "base", "count": 2, "functions": 1})
        site = result["indirect_jumps"][0]
        self.assertEqual((site["kind"], site["table"], site["entries"]), ("table", "0x004ffee0", 5))
        self.assertEqual(site["targets_outside_functions"], ["0x00001024"])
        self.assertEqual([g["start"] for g in result["gaps"]], ["0x00001024"])

    def test_parse_asm(self):
        asm = "// f @ 0x00101f28\n0x00101f28  4d00053c  lui a1,0x4d\n0x00101f2c  00000000  _nop\n"
        self.assertEqual(parse_asm(asm), (0x101f28, "f", [(0x101f28, 0x3c05004d), (0x101f2c, 0)]))


if __name__ == "__main__":
    unittest.main()
