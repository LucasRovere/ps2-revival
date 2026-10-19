import unittest

from asm import FORMAT, AsmError, assemble, census, encode

SAMPLE = {"rs": "a0", "rt": "a1", "rd": "v0", "fs": "f1", "ft": "f2", "fd": "f3", "c1": "fcr31", "vs": "vf1",
          "vt": "vf2", "vd": "vf3", "is": "vi22", "c0": "Status", "sa": "3", "op": "0x10", "code": "7",
          "imm": "0x10", "mem": "4(sp)", "off": "8", "target": "0x100000", "acc": "acc", "q": "q",
          "vsf": "vf1w", "vtf": "vf2x"}
NO_DEST = {"vwaitq", "vsqrt", "vrsqrt"}


def sample_line(name):
    mnemonic = name[:-2] + "x" if name.endswith("bc") else name
    if name.startswith("v") and name not in NO_DEST:
        mnemonic += ".xyzw"
    tokens = [t.rstrip("?") for t in FORMAT[name].split(",") if t]
    return f"{mnemonic} {', '.join(SAMPLE[t] for t in tokens)}"


class EncodeTest(unittest.TestCase):
    def test_all_mnemonics_decode_back(self):
        self.assertEqual(len(FORMAT), 168)
        for name in FORMAT:
            line = sample_line(name)
            self.assertEqual(census.decode(encode(line))[0], name, line)

    def test_broadcast_and_dest_fields(self):
        for i, field in enumerate("xyzw"):
            word = encode(f"vmadd{field}.xz vf1, vf2, vf3")
            self.assertEqual((census.decode(word)[0], word & 3, word >> 21 & 15), ("vmaddbc", i, 0b1010))
            self.assertEqual(census.decode(encode(f"vmula{field}.w acc, vf2, vf3"))[0], "vmulabc")

    def test_known_words(self):
        cases = {
            "nop": 0x00000000,
            "lui v0, 0x4b": 0x3c02004b,
            "addu v0, a0, a1": 0x00851021,
            "lw v0, -0x10(sp)": 0x8fa2fff0,
            "jr ra": 0x03e00008,
            "jalr t9": 0x0320f809,
            "jalr v1, t9": 0x03201809,
            "mult v0, a0, a1": 0x00851018,
            "mult a0, a1": 0x00850018,
            "sync 0x10": 0x0000040f,
            "break 1": 0x0000004d,
            "lq a1, 0(a0)": 0x78850000,
            "padduw v0, zero, zero": 0x70001428,
            "add.s f1, f2, f3": 0x46031040,
            "sqrt.s f30, f14": 0x460e0784,
            "vmul.xyz vf1, vf1, vf2": 0x4bc2086a,
            "vmaddax.xyz acc, vf3, vf1": 0x4bc118bc,
            "vmove.xyzw vf3, vf0": 0x4be3033c,
            "vsqrt q, vf1x": 0x4a0103bd,
            "vrsqrt q, vf0w, vf1x": 0x4a6103be,
            "cfc2 t0, vi22": 0x4848b000,
        }
        for line, word in cases.items():
            self.assertEqual(encode(line), word, line)

    def test_labels_and_targets(self):
        self.assertEqual(assemble(["beq a0, zero, L", "nop", "L:"], 0x100000), [0x10800001, 0])
        self.assertEqual(assemble(["L:", "nop", "bne a0, zero, L"], 0x100000), [0, 0x1480fffe])
        self.assertEqual(assemble(["j L", "nop", "L:"], 0x100000), [0x08040002, 0])
        self.assertEqual(encode("bc1t 0x100010", 0x100000), 0x45010003)

    def test_errors(self):
        for line in ["foo a0", "addu v0, a0", "addu v0, a0, f1", "addiu v0, a0, 0x10000", "beq a0, a1, 6",
                     "vadd.q vf1, vf2, vf3", "vsqrt q, vf1"]:
            with self.assertRaises(AsmError, msg=line):
                encode(line)
        with self.assertRaises(AsmError):
            assemble(["beq a0, zero, missing"])


if __name__ == "__main__":
    unittest.main()
