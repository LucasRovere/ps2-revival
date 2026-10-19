import unittest

from asm import FORMAT, OPCODES, assemble, census
from ref import CODE_BASE, check, load_vectors

# Every mnemonic the pilot game uses except syscall and cop0, which wait for the runtime.
MODELLED = {n for n in FORMAT if census.decode(OPCODES[n])[1] not in ("system", "cop0")} | {"break", "sync", "cache"}


class VectorTest(unittest.TestCase):
    def test_vectors_pass(self):
        for file, case in load_vectors():
            with self.subTest(f"{file}: {case['name']}"):
                self.assertEqual(check(case), [])

    def test_modelled_mnemonics_covered(self):
        used = {census.decode(w)[0] for _, case in load_vectors() for w in assemble(case["asm"], CODE_BASE)}
        self.assertEqual(MODELLED - used, set())

    def test_float_rules_marked_unverified(self):
        for file, case in load_vectors():
            if case["source"] == "ps2-fpu":
                self.assertIn("unverified", case, f"{file}: {case['name']}")


class CheckTest(unittest.TestCase):
    CASE = {"name": "t", "asm": ["addu v0, a0, a1", "sw v0, 0(a2)"],
            "init": {"a0": "0x1", "a1": "0x2", "a2": "0x200000"}}

    def test_wrong_value(self):
        diffs = check({**self.CASE, "expect": {"v0": "0x4", "mem": {"0x00200000": "03000000"}}})
        self.assertEqual(len(diffs), 1)
        self.assertTrue(diffs[0].startswith("v0:"))

    def test_unlisted_changes(self):
        diffs = check({**self.CASE, "expect": {}})
        self.assertEqual(len(diffs), 2)   # v0 and the stored byte

    def test_upper_bits_must_stay(self):
        case = {"name": "t", "asm": ["lq v0, 0(a0)"], "init": {"a0": "0x200000", "mem": {"0x00200000": "01" * 16}}}
        self.assertEqual(len(check({**case, "expect": {"v0": "0x0101010101010101"}})), 1)
        self.assertEqual(check({**case, "expect": {"v0": "0x" + "01" * 16}}), [])

    def test_unknown_register(self):
        self.assertEqual(check({**self.CASE, "expect": {"vf01": "0x0", "v0": "0x3", "mem": {"0x00200000": "03000000"}}}),
                         ["unknown register vf01"])

    def test_branch_in_delay_slot_is_an_error(self):
        diffs = check({"name": "t", "asm": ["beq zero, zero, L", "j L", "L:"], "expect": {}})
        self.assertTrue(diffs[0].startswith("model error: branch in the delay slot"))


if __name__ == "__main__":
    unittest.main()
