"""Reference model of the EE core for the recompiler test vectors (level L0).

Runs each vector's instructions on a small interpreter and compares the end
state with `expect`. Covers integer ops, control flow, 64/128-bit memory,
mult/div (both pipelines), the MMI ops, the FPU and the VU0 macro ops
the pilot game uses; syscall and cop0 come with the runtime. Plan:
docs/recomp-tests.md.

Usage:
  python ref.py            run every vector in vectors/
"""

import json
import sys
from fractions import Fraction
from math import isqrt
from pathlib import Path

from asm import FORMAT, GPR, assemble, census

VECTORS_DIR = Path(__file__).resolve().parent / "vectors"
CODE_BASE = 0x00100000
MAX_STEPS = 10000
M32, M64, M128 = (1 << 32) - 1, (1 << 64) - 1, (1 << 128) - 1
SPECIAL_REGS = ["hi", "lo", "sa", "fcr31"]
FPR = [f"f{i}" for i in range(32)]
VF = [f"vf{i}" for i in range(32)]
VI = [f"vi{i}" for i in range(16)]
FLOAT_REGS = FPR + ["facc"] + VF + VI + ["q", "acc"]
FCR31_C = 1 << 23
VF0 = 0x3f800000 << 96   # (0, 0, 0, 1.0)
SIGN, MAX = 0x80000000, 0x7fffffff
NO_OPS = {"sync", "cache", "pref", "vwaitq"}
CONTROL_FLOW = {n for n, fmt in FORMAT.items() if fmt.endswith("off") or fmt == "target"} | {"jr", "jalr"}


class ModelError(Exception):
    pass


def sx(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def lanes(value, bits, count):
    return [value >> (bits * i) & ((1 << bits) - 1) for i in range(count)]


def join(values, bits):
    return sum((v & ((1 << bits) - 1)) << (bits * i) for i, v in enumerate(values))


class Cpu:
    def __init__(self, init):
        self.gpr = [int(init.get(name, "0"), 16) for name in GPR]
        self.gpr[0] = 0
        self.hi, self.lo, self.sa, self.fcr31 = (int(init.get(r, "0"), 16) for r in SPECIAL_REGS)
        self.f = [int(init.get(name, "0"), 16) & M32 for name in FPR]
        self.vf = [int(init.get(name, "0"), 16) & M128 for name in VF]
        self.vf[0] = VF0
        self.vi = [int(init.get(name, "0"), 16) & 0xffff for name in VI]
        self.vi[0] = 0
        self.facc, self.q, self.acc = (int(init.get(r, "0"), 16) for r in ("facc", "q", "acc"))
        self.mem = {}
        for addr, data in init.get("mem", {}).items():
            self.write(int(addr, 16), bytes.fromhex(data))

    # Registers. 32/64-bit results leave bits 64-127 unchanged (assumption, see recomp-tests.md).
    def r(self, n):
        return self.gpr[n] & M64

    def r32(self, n):
        return self.gpr[n] & M32

    def set64(self, n, value):
        if n:
            self.gpr[n] = self.gpr[n] & ~M64 | value & M64

    def set32(self, n, value):
        self.set64(n, sx(value, 32))

    def set128(self, n, value):
        if n:
            self.gpr[n] = value & M128

    def set_vf(self, n, value):
        if n:
            self.vf[n] = value & M128

    def state(self):
        """Register name → value, as vectors name them. Only the condition bit of FCR31 is modelled."""
        values = (self.gpr + [self.hi, self.lo, self.sa, self.fcr31 & FCR31_C] + self.f + [self.facc]
                  + self.vf + self.vi + [self.q, self.acc])
        return dict(zip(GPR + SPECIAL_REGS + FLOAT_REGS, values))

    def set_hilo(self, pipe, lo, hi):
        """Store sign-extended 32-bit lo/hi in LO/HI (pipe 0) or LO1/HI1 (pipe 1, bits 64-127)."""
        shift = 64 * pipe
        self.lo = self.lo & ~(M64 << shift) | (sx(lo, 32) & M64) << shift
        self.hi = self.hi & ~(M64 << shift) | (sx(hi, 32) & M64) << shift

    # Memory: sparse bytes, little-endian.
    def read(self, addr, size):
        return int.from_bytes(bytes(self.mem.get(addr + i, 0) for i in range(size)), "little")

    def write(self, addr, data):
        for i, b in enumerate(data):
            self.mem[addr + i] = b

    def store(self, addr, size, value):
        self.write(addr, (value & ((1 << 8 * size) - 1)).to_bytes(size, "little"))


def fields(word):
    """Instruction fields. FPU/VU registers use the same bits: fs = rd, ft = rt, fd = sa."""
    return {"rs": word >> 21 & 31, "rt": word >> 16 & 31, "rd": word >> 11 & 31, "sa": word >> 6 & 31,
            "imm": word & 0xffff, "simm": sx(word, 16),
            "dest": word >> 21 & 15, "bc": word & 3, "fsf": word >> 21 & 3, "ftf": word >> 23 & 3}


def address(cpu, f, size):
    addr = (cpu.r(f["rs"]) + f["simm"]) & M32
    if size in (2, 4, 8) and addr % size:
        raise ModelError(f"unaligned {size}-byte access at 0x{addr:08x}")
    return addr


def load_left(cpu, f, size):
    """lwl/ldl: the bytes from addr down to the aligned address fill rt from the top."""
    addr = address(cpu, f, 1)
    shift = 8 * (size - 1 - addr % size)
    mem = cpu.read(addr - addr % size, size)
    mask = (1 << 8 * size) - 1
    return (mem << shift | cpu.r(f["rt"]) & ((1 << shift) - 1)) & mask


def load_right(cpu, f, size):
    """lwr/ldr: the bytes from addr up to the aligned end fill rt from the bottom. (value, full load)"""
    addr = address(cpu, f, 1)
    shift = 8 * (addr % size)
    mem = cpu.read(addr - addr % size, size)
    mask = (1 << 8 * size) - 1
    return mem >> shift | cpu.r(f["rt"]) & mask & ~(mask >> shift), shift == 0


def store_left(cpu, f, size):
    addr = address(cpu, f, 1)
    shift = 8 * (size - 1 - addr % size)
    base, mask = addr - addr % size, (1 << 8 * size) - 1
    cpu.store(base, size, (cpu.r(f["rt"]) & mask) >> shift | cpu.read(base, size) & ~(mask >> shift))


def store_right(cpu, f, size):
    addr = address(cpu, f, 1)
    shift = 8 * (addr % size)
    base = addr - addr % size
    cpu.store(base, size, cpu.r(f["rt"]) << shift | cpu.read(base, size) & ((1 << shift) - 1))


def lwr(cpu, f):
    value, full = load_right(cpu, f, 4)
    if full:
        cpu.set32(f["rt"], value)
    else:   # partial lwr keeps bits 32-63 (assumption, recomp-tests.md)
        cpu.set64(f["rt"], cpu.r(f["rt"]) & ~M32 | value)


def leading_sign_bits(word):
    """plzcw: count of leading bits equal to the sign bit, minus one."""
    bits = format(word, "032b")
    return len(bits) - len(bits.lstrip(bits[0])) - 1


def divide(cpu, f, pipe, signed):
    if signed:
        n, m = sx(cpu.r(f["rs"]), 32), sx(cpu.r(f["rt"]), 32)
    else:
        n, m = cpu.r32(f["rs"]), cpu.r32(f["rt"])
    if m == 0:   # R5900 result, Unverified
        cpu.set_hilo(pipe, -1 if n >= 0 or not signed else 1, n)
    elif n == -(1 << 31) and m == -1:   # Unverified
        cpu.set_hilo(pipe, n, 0)
    else:
        q = abs(n) // abs(m) * (1 if (n < 0) == (m < 0) else -1)
        cpu.set_hilo(pipe, q, n - q * m)


def multiply(cpu, f, pipe, signed, accumulate=False):
    a, b = cpu.r32(f["rs"]), cpu.r32(f["rt"])
    product = sx(a, 32) * sx(b, 32) if signed else a * b
    if accumulate:
        acc = cpu.lo >> 64 * pipe & M32 | (cpu.hi >> 64 * pipe & M32) << 32
        product += acc
    cpu.set_hilo(pipe, product, product >> 32)
    cpu.set64(f["rd"], sx(product, 32))


def mmi_words(cpu, f, op):
    s, t = lanes(cpu.gpr[f["rs"]], 32, 4), lanes(cpu.gpr[f["rt"]], 32, 4)
    cpu.set128(f["rd"], join([op(a, b) for a, b in zip(s, t)], 32))


def branch(taken, likely):
    return ("branch", taken, likely)


# PS2 float rules (FPU and VU0, all Unverified, see recomp-tests.md): no inf/NaN (exponent 255 is a
# number), denormals read as ±0, results truncated toward zero, overflow → ±max, underflow → ±0.
def exponent(x):
    return x >> 23 & 255


def flush(x):
    return x if exponent(x) else x & SIGN


def mantissa(x):
    return x & 0x7fffff | 0x800000


def value(x):
    """Magnitude of a float as an exact Fraction (0 for ±0 and denormals)."""
    return Fraction(mantissa(x)) * Fraction(2) ** (exponent(x) - 150) if exponent(x) else Fraction(0)


def pack(sign, e, m):
    """Float bits of a 24-bit mantissa m (bit 23 set) with biased exponent e."""
    if e > 255:
        return sign | MAX
    return sign | e << 23 | m & 0x7fffff if e > 0 else sign


def from_exact(sign, magnitude, root=False):
    """Float bits of a positive Fraction (or of its square root), truncated toward zero."""
    e = magnitude.numerator.bit_length() - magnitude.denominator.bit_length()
    while Fraction(2) ** e > magnitude:
        e -= 1
    while Fraction(2) ** (e + 1) <= magnitude:
        e += 1
    if root:
        e //= 2
        return pack(sign, e + 127, isqrt(int(magnitude * Fraction(2) ** (46 - 2 * e))))
    return pack(sign, e + 127, int(magnitude * Fraction(2) ** (23 - e)))


def fadd(a, b):
    """The smaller operand is aligned keeping one guard bit; bits below it are dropped (Play!, ps2-web-recomp)."""
    a, b = flush(a), flush(b)
    if not b & MAX:
        return a if a & MAX else a & b
    if not a & MAX:
        return b
    if b & MAX > a & MAX:
        a, b = b, a
    e = exponent(a)
    big, small = mantissa(a) << 1, mantissa(b) << 1 >> (e - exponent(b))
    m = big - small if (a ^ b) & SIGN else big + small
    if not m:
        return 0
    while m >= 1 << 25:
        m >>= 1
        e += 1
    while m < 1 << 24:
        m <<= 1
        e -= 1
    return pack(a & SIGN, e, m >> 1)


def fsub(a, b):
    return fadd(a, b ^ SIGN)


def fmul(a, b):
    sign = (a ^ b) & SIGN
    return from_exact(sign, value(a) * value(b)) if exponent(a) and exponent(b) else sign


def fdiv(a, b):
    """x/0 and 0/0 → ±max."""
    sign = (a ^ b) & SIGN
    if not exponent(b):
        return sign | MAX
    return from_exact(sign, value(a) / value(b)) if exponent(a) else sign


def fsqrt(a):
    """Negative inputs use |a|."""
    return from_exact(0, value(a), root=True) if exponent(a) else 0


def frsqrt(a, b):
    """a / sqrt(|b|); b = 0 → ±max."""
    if not exponent(b):
        return a & SIGN | MAX
    return from_exact(a & SIGN, value(a) ** 2 / value(b), root=True) if exponent(a) else a & SIGN


def cvt_w(x):
    """Truncate to int32; |x| >= 2^31 saturates."""
    n = min(int(value(x)), 1 << 31)
    if x & SIGN:
        return -n & M32
    return min(n, MAX)


def cvt_s(word):
    n = sx(word, 32)
    return from_exact(SIGN if n < 0 else 0, Fraction(abs(n))) if n else 0


def key(x):
    """Order of floats as signed integers; ±0 and denormals compare equal to 0."""
    x = flush(x)
    return -(x & MAX) if x & SIGN else x & MAX


def compare(cpu, f, test):
    cpu.fcr31 = cpu.fcr31 | FCR31_C if test(key(cpu.f[f["rd"]]), key(cpu.f[f["rt"]])) else cpu.fcr31 & ~FCR31_C


def fpu(cpu, f, op):
    cpu.f[f["sa"]] = op(cpu.f[f["rd"]], cpu.f[f["rt"]])


def ctc1(cpu, f):
    if f["rd"] != 31:
        raise ModelError(f"ctc1 to fcr{f['rd']} not modelled")
    cpu.fcr31 = cpu.r32(f["rt"])


def vf(cpu, n):
    """[x, y, z, w] of a VU0 register."""
    return lanes(cpu.vf[n], 32, 4)


def bc(cpu, f):
    return [vf(cpu, f["rt"])[f["bc"]]] * 4


def masked(old, new, dest):
    """Fields enabled in dest (bit 3 = x … bit 0 = w) from new, the rest from old."""
    return join([n if dest >> (3 - i) & 1 else o for i, (o, n) in enumerate(zip(lanes(old, 32, 4), new))], 32)


def vu(cpu, f, op, s=None, t=None, to_acc=False):
    """VU0 macro op per field: op(fs, ft, acc) → fd or ACC. s and t replace the fs/ft fields when given."""
    s = s or vf(cpu, f["rd"])
    t = t or vf(cpu, f["rt"])
    result = [op(a, b, c) for a, b, c in zip(s, t, lanes(cpu.acc, 32, 4))]
    if to_acc:
        cpu.acc = masked(cpu.acc, result, f["dest"])
    else:
        cpu.set_vf(f["sa"], masked(cpu.vf[f["sa"]], result, f["dest"]))


def move(cpu, f, order):
    """vmove/vmr32: ft = fs fields in the given order."""
    s = vf(cpu, f["rd"])
    cpu.set_vf(f["rt"], masked(cpu.vf[f["rt"]], [s[i] for i in order], f["dest"]))


def yzx(v):
    return [v[1], v[2], v[0], v[3]]


def zxy(v):
    return [v[2], v[0], v[1], v[3]]


def cfc2(cpu, f):
    n = f["rd"]
    if n < 16:
        return cpu.set32(f["rt"], cpu.vi[n])
    if n != 22:
        raise ModelError(f"cfc2 vi{n} not modelled")
    cpu.set32(f["rt"], cpu.q)


def ctc2(cpu, f):
    n = f["rd"]
    if 0 < n < 16:
        cpu.vi[n] = cpu.r(f["rt"]) & 0xffff
    elif n == 22:
        cpu.q = cpu.r32(f["rt"])
    elif n:
        raise ModelError(f"ctc2 vi{n} not modelled")


def madd(s, t, acc):
    return fadd(acc, fmul(s, t))   # product truncated before the add (Unverified)


def msub(s, t, acc):
    return fsub(acc, fmul(s, t))


# Each op returns None (next instruction), "stop", ("jump", target) or
# ("branch", taken, likely); the target of a branch is pc + 4 + 4 * simm.
OPS = {
    # Arithmetic and logic. 32-bit results are sign-extended to 64 bits.
    "addu": lambda c, f: c.set32(f["rd"], c.r(f["rs"]) + c.r(f["rt"])),
    "subu": lambda c, f: c.set32(f["rd"], c.r(f["rs"]) - c.r(f["rt"])),
    "addiu": lambda c, f: c.set32(f["rt"], c.r(f["rs"]) + f["simm"]),
    "addi": lambda c, f: c.set32(f["rt"], c.r(f["rs"]) + f["simm"]),   # overflow trap not modelled
    "daddu": lambda c, f: c.set64(f["rd"], c.r(f["rs"]) + c.r(f["rt"])),
    "dsubu": lambda c, f: c.set64(f["rd"], c.r(f["rs"]) - c.r(f["rt"])),
    "daddiu": lambda c, f: c.set64(f["rt"], c.r(f["rs"]) + f["simm"]),
    "and": lambda c, f: c.set64(f["rd"], c.r(f["rs"]) & c.r(f["rt"])),
    "or": lambda c, f: c.set64(f["rd"], c.r(f["rs"]) | c.r(f["rt"])),
    "xor": lambda c, f: c.set64(f["rd"], c.r(f["rs"]) ^ c.r(f["rt"])),
    "nor": lambda c, f: c.set64(f["rd"], ~(c.r(f["rs"]) | c.r(f["rt"]))),
    "andi": lambda c, f: c.set64(f["rt"], c.r(f["rs"]) & f["imm"]),
    "ori": lambda c, f: c.set64(f["rt"], c.r(f["rs"]) | f["imm"]),
    "xori": lambda c, f: c.set64(f["rt"], c.r(f["rs"]) ^ f["imm"]),
    "lui": lambda c, f: c.set32(f["rt"], f["imm"] << 16),
    "slt": lambda c, f: c.set64(f["rd"], sx(c.r(f["rs"]), 64) < sx(c.r(f["rt"]), 64)),
    "sltu": lambda c, f: c.set64(f["rd"], c.r(f["rs"]) < c.r(f["rt"])),
    "slti": lambda c, f: c.set64(f["rt"], sx(c.r(f["rs"]), 64) < f["simm"]),
    "sltiu": lambda c, f: c.set64(f["rt"], c.r(f["rs"]) < f["simm"] & M64),
    "movn": lambda c, f: c.set64(f["rd"], c.r(f["rs"])) if c.r(f["rt"]) else None,
    "movz": lambda c, f: None if c.r(f["rt"]) else c.set64(f["rd"], c.r(f["rs"])),
    # Shifts.
    "sll": lambda c, f: c.set32(f["rd"], c.r32(f["rt"]) << f["sa"]),
    "srl": lambda c, f: c.set32(f["rd"], c.r32(f["rt"]) >> f["sa"]),
    "sra": lambda c, f: c.set32(f["rd"], sx(c.r(f["rt"]), 32) >> f["sa"]),
    "sllv": lambda c, f: c.set32(f["rd"], c.r32(f["rt"]) << (c.r(f["rs"]) & 31)),
    "srlv": lambda c, f: c.set32(f["rd"], c.r32(f["rt"]) >> (c.r(f["rs"]) & 31)),
    "srav": lambda c, f: c.set32(f["rd"], sx(c.r(f["rt"]), 32) >> (c.r(f["rs"]) & 31)),
    "dsll": lambda c, f: c.set64(f["rd"], c.r(f["rt"]) << f["sa"]),
    "dsrl": lambda c, f: c.set64(f["rd"], c.r(f["rt"]) >> f["sa"]),
    "dsra": lambda c, f: c.set64(f["rd"], sx(c.r(f["rt"]), 64) >> f["sa"]),
    "dsll32": lambda c, f: c.set64(f["rd"], c.r(f["rt"]) << (f["sa"] + 32)),
    "dsrl32": lambda c, f: c.set64(f["rd"], c.r(f["rt"]) >> (f["sa"] + 32)),
    "dsra32": lambda c, f: c.set64(f["rd"], sx(c.r(f["rt"]), 64) >> (f["sa"] + 32)),
    "dsllv": lambda c, f: c.set64(f["rd"], c.r(f["rt"]) << (c.r(f["rs"]) & 63)),
    "dsrlv": lambda c, f: c.set64(f["rd"], c.r(f["rt"]) >> (c.r(f["rs"]) & 63)),
    "dsrav": lambda c, f: c.set64(f["rd"], sx(c.r(f["rt"]), 64) >> (c.r(f["rs"]) & 63)),
    # HI/LO. Pipeline 1 (…1 ops) uses bits 64-127 of HI and LO.
    "mult": lambda c, f: multiply(c, f, 0, True),
    "multu": lambda c, f: multiply(c, f, 0, False),
    "mult1": lambda c, f: multiply(c, f, 1, True),
    "multu1": lambda c, f: multiply(c, f, 1, False),
    "madd": lambda c, f: multiply(c, f, 0, True, accumulate=True),
    "div": lambda c, f: divide(c, f, 0, True),
    "divu": lambda c, f: divide(c, f, 0, False),
    "div1": lambda c, f: divide(c, f, 1, True),
    "divu1": lambda c, f: divide(c, f, 1, False),
    "mfhi": lambda c, f: c.set64(f["rd"], c.hi),
    "mflo": lambda c, f: c.set64(f["rd"], c.lo),
    "mfhi1": lambda c, f: c.set64(f["rd"], c.hi >> 64),
    "mflo1": lambda c, f: c.set64(f["rd"], c.lo >> 64),
    "mthi": lambda c, f: setattr(c, "hi", c.hi & ~M64 | c.r(f["rs"])),
    "mtlo": lambda c, f: setattr(c, "lo", c.lo & ~M64 | c.r(f["rs"])),
    "mthi1": lambda c, f: setattr(c, "hi", c.hi & M64 | c.r(f["rs"]) << 64),
    "mtlo1": lambda c, f: setattr(c, "lo", c.lo & M64 | c.r(f["rs"]) << 64),
    # Loads and stores.
    "lb": lambda c, f: c.set64(f["rt"], sx(c.read(address(c, f, 1), 1), 8)),
    "lbu": lambda c, f: c.set64(f["rt"], c.read(address(c, f, 1), 1)),
    "lh": lambda c, f: c.set64(f["rt"], sx(c.read(address(c, f, 2), 2), 16)),
    "lhu": lambda c, f: c.set64(f["rt"], c.read(address(c, f, 2), 2)),
    "lw": lambda c, f: c.set32(f["rt"], c.read(address(c, f, 4), 4)),
    "lwu": lambda c, f: c.set64(f["rt"], c.read(address(c, f, 4), 4)),
    "ld": lambda c, f: c.set64(f["rt"], c.read(address(c, f, 8), 8)),
    "lq": lambda c, f: c.set128(f["rt"], c.read(address(c, f, 1) & ~15, 16)),
    "lwl": lambda c, f: c.set32(f["rt"], load_left(c, f, 4)),
    "lwr": lwr,
    "ldl": lambda c, f: c.set64(f["rt"], load_left(c, f, 8)),
    "ldr": lambda c, f: c.set64(f["rt"], load_right(c, f, 8)[0]),
    "sb": lambda c, f: c.store(address(c, f, 1), 1, c.r(f["rt"])),
    "sh": lambda c, f: c.store(address(c, f, 2), 2, c.r(f["rt"])),
    "sw": lambda c, f: c.store(address(c, f, 4), 4, c.r(f["rt"])),
    "sd": lambda c, f: c.store(address(c, f, 8), 8, c.r(f["rt"])),
    "sq": lambda c, f: c.store(address(c, f, 1) & ~15, 16, c.gpr[f["rt"]]),
    "swl": lambda c, f: store_left(c, f, 4),
    "swr": lambda c, f: store_right(c, f, 4),
    "sdl": lambda c, f: store_left(c, f, 8),
    "sdr": lambda c, f: store_right(c, f, 8),
    # MMI (128-bit). Lanes are numbered from bit 0.
    "por": lambda c, f: c.set128(f["rd"], c.gpr[f["rs"]] | c.gpr[f["rt"]]),
    "pand": lambda c, f: c.set128(f["rd"], c.gpr[f["rs"]] & c.gpr[f["rt"]]),
    "pxor": lambda c, f: c.set128(f["rd"], c.gpr[f["rs"]] ^ c.gpr[f["rt"]]),
    "pnor": lambda c, f: c.set128(f["rd"], ~(c.gpr[f["rs"]] | c.gpr[f["rt"]])),
    "pcpyld": lambda c, f: c.set128(f["rd"], (c.gpr[f["rs"]] & M64) << 64 | c.gpr[f["rt"]] & M64),
    "pcpyud": lambda c, f: c.set128(f["rd"], c.gpr[f["rt"]] >> 64 << 64 | c.gpr[f["rs"]] >> 64),
    "pextlw": lambda c, f: c.set128(f["rd"], join([w for pair in zip(lanes(c.gpr[f["rt"]], 32, 2),
                                                                     lanes(c.gpr[f["rs"]], 32, 2)) for w in pair], 32)),
    "pextuw": lambda c, f: c.set128(f["rd"], join([w for pair in zip(lanes(c.gpr[f["rt"]] >> 64, 32, 2),
                                                                     lanes(c.gpr[f["rs"]] >> 64, 32, 2)) for w in pair], 32)),
    "padduw": lambda c, f: mmi_words(c, f, lambda a, b: min(a + b, M32)),
    "psubw": lambda c, f: mmi_words(c, f, lambda a, b: a - b),
    "pminw": lambda c, f: mmi_words(c, f, lambda a, b: min(sx(a, 32), sx(b, 32))),
    "pmaxw": lambda c, f: mmi_words(c, f, lambda a, b: max(sx(a, 32), sx(b, 32))),
    "psubb": lambda c, f: c.set128(f["rd"], join([a - b for a, b in zip(lanes(c.gpr[f["rs"]], 8, 16),
                                                                        lanes(c.gpr[f["rt"]], 8, 16))], 8)),
    "ppach": lambda c, f: c.set128(f["rd"], join(lanes(c.gpr[f["rt"]], 32, 4) + lanes(c.gpr[f["rs"]], 32, 4), 16)),
    "pcpyh": lambda c, f: c.set128(f["rd"], join([c.gpr[f["rt"]] & 0xffff] * 4 + [c.gpr[f["rt"]] >> 64 & 0xffff] * 4, 16)),
    # plzcw writes bits 0-63 only (assumption, recomp-tests.md).
    "plzcw": lambda c, f: c.set64(f["rd"], join([leading_sign_bits(w) for w in lanes(c.gpr[f["rs"]], 32, 2)], 32)),
    "mtsah": lambda c, f: setattr(c, "sa", ((c.r(f["rs"]) ^ f["imm"]) & 7) * 2),   # SA in bytes
    # FPU. sqrt.s reads ft.
    "lwc1": lambda c, f: c.f.__setitem__(f["rt"], c.read(address(c, f, 4), 4)),
    "swc1": lambda c, f: c.store(address(c, f, 4), 4, c.f[f["rt"]]),
    "mtc1": lambda c, f: c.f.__setitem__(f["rd"], c.r32(f["rt"])),
    "mfc1": lambda c, f: c.set32(f["rt"], c.f[f["rd"]]),
    "ctc1": ctc1,
    "add.s": lambda c, f: fpu(c, f, fadd),
    "sub.s": lambda c, f: fpu(c, f, fsub),
    "mul.s": lambda c, f: fpu(c, f, fmul),
    "div.s": lambda c, f: fpu(c, f, fdiv),
    "max.s": lambda c, f: fpu(c, f, lambda a, b: a if key(a) >= key(b) else b),
    "sqrt.s": lambda c, f: fpu(c, f, lambda a, b: fsqrt(b)),
    "mov.s": lambda c, f: fpu(c, f, lambda a, b: a),
    "neg.s": lambda c, f: fpu(c, f, lambda a, b: a ^ SIGN),
    "cvt.w.s": lambda c, f: fpu(c, f, lambda a, b: cvt_w(a)),
    "cvt.s.w": lambda c, f: fpu(c, f, lambda a, b: cvt_s(a)),
    "adda.s": lambda c, f: setattr(c, "facc", fadd(c.f[f["rd"]], c.f[f["rt"]])),
    "c.eq.s": lambda c, f: compare(c, f, lambda a, b: a == b),
    "c.lt.s": lambda c, f: compare(c, f, lambda a, b: a < b),
    "c.le.s": lambda c, f: compare(c, f, lambda a, b: a <= b),
    # VU0 macro mode. Field order x, y, z, w = bits 0-127; vf0 = (0, 0, 0, 1) and ignores writes.
    "lqc2": lambda c, f: c.set_vf(f["rt"], c.read(address(c, f, 1) & ~15, 16)),
    "sqc2": lambda c, f: c.store(address(c, f, 1) & ~15, 16, c.vf[f["rt"]]),
    "qmtc2": lambda c, f: c.set_vf(f["rd"], c.gpr[f["rt"]]),
    "qmfc2": lambda c, f: c.set128(f["rt"], c.vf[f["rd"]]),
    "cfc2": cfc2,
    "ctc2": ctc2,
    "vadd": lambda c, f: vu(c, f, lambda s, t, a: fadd(s, t)),
    "vsub": lambda c, f: vu(c, f, lambda s, t, a: fsub(s, t)),
    "vmul": lambda c, f: vu(c, f, lambda s, t, a: fmul(s, t)),
    "vaddbc": lambda c, f: vu(c, f, lambda s, t, a: fadd(s, t), t=bc(c, f)),
    "vsubbc": lambda c, f: vu(c, f, lambda s, t, a: fsub(s, t), t=bc(c, f)),
    "vmulbc": lambda c, f: vu(c, f, lambda s, t, a: fmul(s, t), t=bc(c, f)),
    "vmaddbc": lambda c, f: vu(c, f, madd, t=bc(c, f)),
    "vmsubbc": lambda c, f: vu(c, f, msub, t=bc(c, f)),
    "vaddq": lambda c, f: vu(c, f, lambda s, t, a: fadd(s, t), t=[c.q] * 4),
    "vmulq": lambda c, f: vu(c, f, lambda s, t, a: fmul(s, t), t=[c.q] * 4),
    "vadda": lambda c, f: vu(c, f, lambda s, t, a: fadd(s, t), to_acc=True),
    "vsuba": lambda c, f: vu(c, f, lambda s, t, a: fsub(s, t), to_acc=True),
    "vmulabc": lambda c, f: vu(c, f, lambda s, t, a: fmul(s, t), t=bc(c, f), to_acc=True),
    "vmaddabc": lambda c, f: vu(c, f, madd, t=bc(c, f), to_acc=True),
    "vmsubabc": lambda c, f: vu(c, f, msub, t=bc(c, f), to_acc=True),
    # Cross product: vopmula.xyz acc, a, b; vopmsub.xyz d, b, a → d = a × b.
    "vopmula": lambda c, f: vu(c, f, lambda s, t, a: fmul(s, t), yzx(vf(c, f["rd"])), zxy(vf(c, f["rt"])), True),
    "vopmsub": lambda c, f: vu(c, f, msub, yzx(vf(c, f["rd"])), zxy(vf(c, f["rt"]))),
    "vmove": lambda c, f: move(c, f, [0, 1, 2, 3]),
    "vmr32": lambda c, f: move(c, f, [1, 2, 3, 0]),
    # Q is ready at once in the model; vwaitq is a no-op.
    "vsqrt": lambda c, f: setattr(c, "q", fsqrt(vf(c, f["rt"])[f["ftf"]])),
    "vrsqrt": lambda c, f: setattr(c, "q", frsqrt(vf(c, f["rd"])[f["fsf"]], vf(c, f["rt"])[f["ftf"]])),
    # Control flow.
    "beq": lambda c, f: branch(c.r(f["rs"]) == c.r(f["rt"]), False),
    "bne": lambda c, f: branch(c.r(f["rs"]) != c.r(f["rt"]), False),
    "beql": lambda c, f: branch(c.r(f["rs"]) == c.r(f["rt"]), True),
    "bnel": lambda c, f: branch(c.r(f["rs"]) != c.r(f["rt"]), True),
    "blez": lambda c, f: branch(sx(c.r(f["rs"]), 64) <= 0, False),
    "bgtz": lambda c, f: branch(sx(c.r(f["rs"]), 64) > 0, False),
    "bltz": lambda c, f: branch(sx(c.r(f["rs"]), 64) < 0, False),
    "bgez": lambda c, f: branch(sx(c.r(f["rs"]), 64) >= 0, False),
    "blezl": lambda c, f: branch(sx(c.r(f["rs"]), 64) <= 0, True),
    "bgtzl": lambda c, f: branch(sx(c.r(f["rs"]), 64) > 0, True),
    "bltzl": lambda c, f: branch(sx(c.r(f["rs"]), 64) < 0, True),
    "bgezl": lambda c, f: branch(sx(c.r(f["rs"]), 64) >= 0, True),
    "bc1f": lambda c, f: branch(not c.fcr31 & FCR31_C, False),
    "bc1t": lambda c, f: branch(bool(c.fcr31 & FCR31_C), False),
    "bc1fl": lambda c, f: branch(not c.fcr31 & FCR31_C, True),
    "bc1tl": lambda c, f: branch(bool(c.fcr31 & FCR31_C), True),
    "break": lambda c, f: "stop",
}


def execute(cpu, word, pc):
    """Run one instruction; returns the next pc's rule (see OPS) with jump targets resolved."""
    name = census.decode(word)[0]
    f = fields(word)
    if name in NO_OPS:
        return None
    if name in ("j", "jal"):
        if name == "jal":
            cpu.set64(31, pc + 8)
        return ("jump", (pc + 4) & 0xf0000000 | (word & 0x3ffffff) << 2)
    if name in ("jr", "jalr"):
        target = cpu.r32(f["rs"])   # read before rd is written and before the delay slot
        if name == "jalr":
            cpu.set64(f["rd"], pc + 8)
        return ("jump", target)
    if name not in OPS:
        raise ModelError(f"{name or 'invalid word'} not modelled (0x{word:08x} at 0x{pc:08x})")
    result = OPS[name](cpu, f)
    if isinstance(result, tuple) and result[0] == "branch":
        _, taken, likely = result
        if taken:
            return ("jump", pc + 4 + 4 * f["simm"])
        return "skip slot" if likely else ("jump", pc + 8)
    return result if result == "stop" else None


def run(case):
    """(cpu, pc_trace) after running a vector's code from CODE_BASE."""
    cpu = Cpu(case.get("init", {}))
    words = assemble(case["asm"], CODE_BASE)
    end = CODE_BASE + 4 * len(words)
    pc, trace = CODE_BASE, []

    def fetch(addr):
        if not CODE_BASE <= addr < end:
            raise ModelError(f"unknown jump target 0x{addr:08x}")
        trace.append(addr)
        if len(trace) > MAX_STEPS:
            raise ModelError("too many steps")
        return words[(addr - CODE_BASE) // 4]

    while pc != end:
        result = execute(cpu, fetch(pc), pc)
        if result == "stop":
            break
        if result is None:
            pc += 4
        elif result == "skip slot":
            pc += 8
        else:
            slot = fetch(pc + 4)
            if census.decode(slot)[0] in CONTROL_FLOW:
                raise ModelError(f"branch in the delay slot at 0x{pc + 4:08x}")
            if execute(cpu, slot, pc + 4) == "stop":
                break
            pc = result[1]
    return cpu, trace


def expected_value(init, text):
    """GPRs, hi, lo: up to 16 hex digits set bits 0-63 and bits 64-127 must keep their init value; more digits set all 128."""
    mask = M64 if len(text) - 2 <= 16 else M128
    return init & ~mask | int(text, 16)


def expected(case):
    """(registers, memory) at the end of a case: the listed values, everything else as in init."""
    expect = case["expect"]
    start = Cpu(case.get("init", {}))
    regs = {}
    for name, old in start.state().items():
        if name not in expect:
            regs[name] = old
        elif name in GPR or name in ("hi", "lo"):
            regs[name] = expected_value(old, expect[name])
        else:
            regs[name] = int(expect[name], 16)
    mem = dict(start.mem)
    for addr, data in expect.get("mem", {}).items():
        for i, b in enumerate(bytes.fromhex(data)):
            mem[int(addr, 16) + i] = b
    return regs, mem


def diff_states(want_regs, want_mem, got_regs, got_mem):
    """Differences between two end states; memory not listed is 0."""
    diffs = [f"{name}: got 0x{got_regs[name]:032x}, expected 0x{want:032x}"
             for name, want in want_regs.items() if got_regs[name] != want]
    for addr in sorted(set(want_mem) | set(got_mem)):
        if got_mem.get(addr, 0) != want_mem.get(addr, 0):
            diffs.append(f"mem 0x{addr:08x}: got {got_mem.get(addr, 0):02x}, expected {want_mem.get(addr, 0):02x}")
    return diffs


def check(case):
    """List of differences between the model's end state and the case's expectation."""
    expect = case["expect"]
    try:
        cpu, trace = run(case)
    except ModelError as e:
        if "error" in expect and expect["error"] in str(e):
            return []
        return [f"model error: {e}"]
    if "error" in expect:
        return [f"expected error {expect['error']!r}, ran to the end"]
    diffs = [f"unknown register {name}" for name in expect if name not in cpu.state() and name not in ("mem", "pc_trace")]
    diffs += diff_states(*expected(case), cpu.state(), cpu.mem)
    if "pc_trace" in expect and [int(a, 16) for a in expect["pc_trace"]] != trace:
        diffs.append(f"pc_trace: got {[f'0x{a:08x}' for a in trace]}")
    return diffs


def load_vectors():
    """[(file name, case)] for every vector file."""
    return [(path.name, case) for path in sorted(VECTORS_DIR.glob("*.json"))
            for case in json.loads(path.read_text(encoding="utf-8"))]


def main():
    cases = load_vectors()
    failed = 0
    for file, case in cases:
        diffs = check(case)
        if diffs:
            failed += 1
            print(f"FAIL {file}: {case['name']}\n  " + "\n  ".join(diffs))
    unverified = sum("unverified" in case for _, case in cases)
    print(f"{len(cases) - failed}/{len(cases)} vectors pass on the reference model ({unverified} marked unverified)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
