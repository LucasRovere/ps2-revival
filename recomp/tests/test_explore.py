import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import explore as ex  # noqa: E402

W, H = 64, 48


def ppm(pixel):
    """Synthetic P6 frame; pixel(x, y) -> gray level."""
    data = bytes(v for y in range(H) for x in range(W) for v in (pixel(x, y),) * 3)
    return f"P6\n{W} {H}\n255\n".encode() + data


def frame(k):
    """A checker pattern; each k shifts its levels, so different k are different scenes."""
    return ex.signature(ppm(lambda x, y: ((x // 8 + y // 8 + k) % 4) * 80))


BLACK = ex.signature(ppm(lambda x, y: 0))


class SignatureTest(unittest.TestCase):
    def test_values(self):
        sig = ex.signature(ppm(lambda x, y: 255 if x < W // 2 else 0))
        self.assertEqual(len(sig), ex.GRID[0] * ex.GRID[1])
        self.assertEqual(sig[0], 255)
        self.assertEqual(sig[ex.GRID[0] - 1], 0)

    def test_black(self):
        self.assertTrue(ex.is_black(BLACK))
        self.assertFalse(ex.is_black(frame(1)))


class SceneTest(unittest.TestCase):
    def test_black_and_frozen_frames_are_not_new(self):
        seen = []
        self.assertEqual(ex.new_scenes([BLACK] * 20, seen), [])
        self.assertEqual(ex.new_scenes([frame(1)] * 20, seen), [0])
        self.assertEqual(ex.new_scenes([frame(1)] * 20, seen), [])

    def test_moving_frames_are_new_until_they_repeat(self):
        seen = []
        movie = [frame(k) for k in range(4)]
        self.assertEqual(ex.new_scenes(movie, seen), [0, 1, 2, 3])
        self.assertEqual(ex.new_scenes(movie + [BLACK], seen), [])

    def test_small_change_is_not_new(self):
        seen = [frame(1)]
        cursor = ex.signature(ppm(lambda x, y: 255 if x < 4 and y < 4 else ((x // 8 + y // 8 + 1) % 4) * 80))
        self.assertEqual(ex.new_scenes([cursor], seen), [])


class StallTest(unittest.TestCase):
    def test_stalled(self):
        self.assertTrue(ex.stalled(set(), set(), []))
        self.assertTrue(ex.stalled({"100000"}, set(), []))
        self.assertFalse(ex.stalled({f"{a:x}" for a in range(ex.MIN_NEW_CODE)}, set(), []))
        self.assertFalse(ex.stalled(set(), {"a.bin"}, []))
        self.assertFalse(ex.stalled(set(), set(), ["100000"]))


class PatternTest(unittest.TestCase):
    def test_order(self):
        self.assertEqual(ex.pattern_order(0, 0, 5)[:ex.TRIES], [0, 1, 2][:ex.TRIES])
        self.assertEqual(ex.pattern_order(2, 0, 5), [2, 0, 1][:ex.TRIES])
        self.assertEqual(len(ex.pattern_order(2, 0, 5)), ex.TRIES)

    def test_stalls_in_a_row_try_every_pattern(self):
        tried = {p for turn in range(4) for p in ex.pattern_order(0, turn * (ex.TRIES - 1), 8)}
        self.assertEqual(tried, set(range(8)))

    def test_presses(self):
        self.assertEqual(ex.presses(("down", ["down", "cross"]), 600, 760), ["620:down", "660:cross", "700:down", "740:cross"])

    def test_random_presses_repeat(self):
        pattern = ("random", None)
        self.assertEqual(ex.presses(pattern, 600, 1200), ex.presses(pattern, 600, 1200))
        self.assertTrue(all(p.split(":")[1] in ex.RANDOM_BUTTONS for p in ex.presses(pattern, 600, 1200)))


if __name__ == "__main__":
    unittest.main()
