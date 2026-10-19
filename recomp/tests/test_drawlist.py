import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import drawlist as dl  # noqa: E402


def tag(qwc, tid, vif0=0, vif1=0, addr=0):
    return struct.pack("<QII", qwc | tid << 28 | addr << 32, vif0, vif1)


# cnt: STCYCL 1,1 + UNPACK V4-32 1 qw to VU 0x010, its data, then MSCAL 0; ret: MSCNT
CHAIN = (tag(2, 1, 0x01000101, 0x6C010010) + bytes(range(16)) + struct.pack("<4I", 0x14000000, 0, 0, 0)
         + tag(0, 6, 0x17000000, 0))
LOG = """[draw] frames 100-102 root chains 1.00/frame channel 2 0.0100 ms 1.0 qw per frame
[draw] target 00000000 calls 0.00 ms 1.0000 qw 10.0
[draw] target 00001000 calls 2.00 ms 3.0000 qw 8.0
[draw] target 00002000 calls 1.00 ms 1.0000 qw 4.0
[draw] gif 00001000 path 1 kicks 2.00 ms 0.5000 qw 4.0
[draw] vu 00001000 entry 0000 runs 2.00 ms 2.0000
[draw] vu 00002000 entry 0100 runs 1.00 ms 0.5000
[time] frames 100-102: 8.00 ms per frame
"""


def ram():
    r = bytearray(0x4000)
    r[0x1000:0x1000 + len(CHAIN)] = CHAIN
    r[0x2000:0x2000 + len(CHAIN)] = CHAIN
    return bytes(r)


class DrawListTest(unittest.TestCase):
    def test_parse(self):
        p = dl.parse_log(LOG)
        self.assertEqual(p["frames"], (100, 102))
        self.assertEqual(p["frame_ms"], 8.0)
        self.assertEqual(p["targets"][0x1000], (2.0, 3.0, 8.0))
        self.assertEqual(p["gif"][0x1000, 1], 0.5)
        self.assertEqual(p["vu"][0x2000, "0100"], (1.0, 0.5))

    def test_chain_and_fingerprint(self):
        chain, vif = dl.chain_at(ram(), 0x1000)
        self.assertEqual(chain, CHAIN)
        self.assertEqual(dl.fingerprint(dl.vif_commands(vif)), "V4-32@010 MSCAL0000 MSCNT")
        self.assertIsNone(dl.chain_at(ram(), 0x3000)[0])  # zeros: a refe tag, not a chain

    def test_kinds(self):
        kinds, seen = dl.classify(dl.parse_log(LOG), ram())
        k = kinds["V4-32@010 MSCAL0000 MSCNT"]
        self.assertEqual((k["targets"], k["calls"], k["ms"], k["vu"], k["gs1"]), (2, 3.0, 4.0, 2.5, 0.5))
        self.assertEqual(seen[0][0], "root list (per-frame packets)")
        lines = dl.report(dl.parse_log(LOG), ram())
        self.assertIn("50.0%  V4-32@010 MSCAL0000 MSCNT", lines[2])  # 4 of 8 ms

    def test_match(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "sub").mkdir()
            (Path(d) / "sub" / "mesh.bin").write_bytes(b"xyz" + CHAIN + b"tail")
            changed = bytearray(CHAIN)
            changed[40] ^= 1
            (Path(d) / "other.bin").write_bytes(bytes(changed))
            self.assertEqual(dl.match_chains({0x1000: CHAIN}, Path(d)), {0x1000: ["sub/mesh.bin"]})


if __name__ == "__main__":
    unittest.main()
