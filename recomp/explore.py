"""Automatic exploration (T39): the pure parts of port.py's exploring run.

The run is cut into segments of SEGMENT frames chained by save states. Each
segment presses one generated pattern. A segment makes progress when the game
runs code it never ran before (at least MIN_NEW_CODE new entries in the
runtime's PS2_COVERAGE list of entered functions), records a new VU1 program
or misses an entry point. A segment with none of these is stalled: it is
retried from its start state with other patterns (TRIES in all), and the run
goes on with the try that entered the most new code.

Frames do not decide progress: menus often sit on a looping video or 3D
background, so their frames always look new even when the input goes in a
circle. Frames give the scenes for the report and end the run: a stalled
segment whose frames are all black, frozen or already seen counts towards
MAX_STALLS (a movie still shows new frames, so the run waits it out).
"""

import random

SEGMENT = 600  # frames per segment: 10 s at NTSC
SHOT_EVERY = 30  # frame dump interval inside a segment
STEP = 40  # frames between generated presses
GRID = 16, 12  # luma block means per frame
# Mean luma difference (0-1) above which a frame shows a new scene. Tuned on a pilot game: frames of
# one still screen differ by up to 0.01, different screens by 0.04 or more.
NOVEL = 0.025
BLACK = 0.04  # mean luma below this: a black (or faded out) frame
TRIES = 3  # patterns tried on a stalled segment (bounds the cost when the game runs on by itself)
MAX_STALLS = 5  # stalled segments in a row with nothing new on screen end the run
# Fewer newly entered functions than this in a segment is no progress. Tuned on a pilot game: idle
# screens and movies trickle in 1-21 per segment, a menu loop on a video background 6-47, a new
# screen or mode 25-2000.
MIN_NEW_CODE = 25

# Button cycles: past intros and prompts (cross, start), through menus (direction then
# cross), back out (circle, triangle), and a seeded random mix.
PATTERNS = [
    ("cross", ["cross"]),
    ("start", ["start", "cross"]),
    ("down", ["down", "cross"]),
    ("up", ["up", "cross"]),
    ("right", ["right", "cross"]),
    ("left", ["left", "cross"]),
    ("back", ["circle", "triangle"]),
    ("random", None),
]
RANDOM_BUTTONS = ["cross", "cross", "start", "up", "down", "left", "right", "circle"]


def presses(pattern, start, end):
    """--press specs for one pattern over frames start..end (absolute, as the runtime counts)."""
    _, cycle = pattern
    frames = range(start + STEP // 2, end, STEP)
    if cycle is None:
        rng = random.Random(start)
        return [f"{f}:{rng.choice(RANDOM_BUTTONS)}" for f in frames]
    return [f"{f}:{cycle[i % len(cycle)]}" for i, f in enumerate(frames)]


def pattern_order(last, turn, count=len(PATTERNS)):
    """TRIES patterns for a segment: the one that last made progress, then others in list order from
    offset `turn` (the caller moves it on by TRIES - 1 after each stall, so stalls in a row try them all)."""
    others = [i for i in range(count) if i != last]
    k = turn % len(others)
    return [last] + (others[k:] + others[:k])[:TRIES - 1]


def signature(ppm):
    """Luma block means (GRID, 0-255) of a binary PPM (P6, 8-bit) frame dump, from 4x4 samples per block."""
    width, height = (int(v) for v in ppm[:32].split()[1:3])
    pixels = ppm[-3 * width * height:]
    cols, rows = GRID
    sig = []
    for by in range(rows):
        for bx in range(cols):
            total = 0
            for y in range(4):
                row = ((4 * by + y) * height // (4 * rows)) * width
                for x in range(4):
                    i = 3 * (row + (4 * bx + x) * width // (4 * cols))
                    total += 2 * pixels[i] + 5 * pixels[i + 1] + pixels[i + 2]
            sig.append(total // 128)
    return sig


def distance(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / (255 * len(a))


def is_black(sig):
    return sum(sig) / (255 * len(sig)) < BLACK


def new_scenes(sigs, seen):
    """Indices of the frames unlike every frame in seen (and every earlier new one); adds them to seen.
    Black frames and repeats of a frozen screen are never new."""
    found = []
    for i, sig in enumerate(sigs):
        if not is_black(sig) and all(distance(sig, s) > NOVEL for s in seen):
            seen.append(sig)
            found.append(i)
    return found


def stalled(new_code, vu_programs, entries):
    """A segment that ran no new code, recorded no new VU1 program and missed no entry point."""
    return len(new_code) < MIN_NEW_CODE and not (vu_programs or entries)
