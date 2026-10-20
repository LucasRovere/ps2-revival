import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import framediff as fd  # noqa: E402


class FrameDiffTest(unittest.TestCase):
    def test_compare(self):
        a = np.zeros((4, 4, 3), dtype=np.int16)
        b = a.copy()
        b[0, 0] = (8, 0, 0)  # under the threshold
        b[1, 1] = (0, 40, 10)  # over it: the largest channel counts
        d, mean, share = fd.compare(a, b, 24)
        self.assertEqual(d[1, 1], 40)
        self.assertAlmostEqual(mean, 48 / 16)
        self.assertAlmostEqual(share, 1 / 16)

    def test_folders_and_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            for name in "a", "b":
                (t / name).mkdir()
            img = np.zeros((8, 8, 3), dtype=np.uint8)
            Image.fromarray(img).save(t / "a" / "frame_00001.ppm")
            Image.fromarray(img).save(t / "b" / "frame_00001.ppm")
            img2 = img.copy()
            img2[:4] = 255
            Image.fromarray(img).save(t / "a" / "frame_00002.ppm")
            Image.fromarray(img2).save(t / "b" / "frame_00002.ppm")
            Image.fromarray(img).save(t / "a" / "frame_00003.ppm")  # only in a: ignored
            out = t / "diff"
            self.assertEqual(fd.main([str(t / "a"), str(t / "b"), "--out", str(out)]), 0)
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["frame_00001.png", "frame_00002.png"])
            self.assertEqual(np.asarray(Image.open(out / "frame_00002.png"))[0, 0], 255)
            self.assertEqual(fd.main([str(t / "a"), str(t / "b"), "--max-share", "10"]), 1)
            self.assertEqual(fd.main([str(t / "a"), str(t / "b"), "--max-mean", "200"]), 0)


if __name__ == "__main__":
    unittest.main()
