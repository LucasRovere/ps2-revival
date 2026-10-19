"""Assemble EE (R5900) instructions for the recompiler test vectors.

The inverse of analysis/census.py's opcode tables, for the mnemonics
the pilot game uses, plus `nop`. One instruction per line:

  addu v0, a0, a1          GPR names (zero, at, v0 ... s8, ra)
  lw v0, -0x10(sp)         immediates in decimal or hex, may be negative
  beq a0, zero, done       branch/jump target: a label or an address
  done:                    a label on its own line
  vmaddax.xyz acc, vf1, vf2   VU0 macro ops: dest suffix, broadcast as vaddx/vmulay/...
  vrsqrt q, vf0w, vf1x     vsqrt/vrsqrt: field letter after the register
  cfc2 t0, vi22            FPU f0..f31, fcr31, VU vf0..vf31, vi0..vi31

Usage:
  python asm.py <SERIAL>   local check: re-encode the analysis export's
                             .asm lines and compare with their bytes
"""

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "analysis"))

import census  # noqa: E402

GPR = ["zero", "at", "v0", "v1", "a0", "a1", "a2", "a3", "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
       "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "t8", "t9", "k0", "k1", "gp", "sp", "s8", "ra"]
COP0 = {"Count": 9, "Status": 12, "TagLo": 28, "ErrorEPC": 30}
FIELDS = "xyzw"

# Operand token: (register kind or immediate, bit position). See encode_operand.
OPERANDS = {"rs": ("gpr", 21), "rt": ("gpr", 16), "rd": ("gpr", 11),
            "fs": ("fpr", 11), "ft": ("fpr", 16), "fd": ("fpr", 6), "c1": ("fcr", 11),
            "vs": ("vf", 11), "vt": ("vf", 16), "vd": ("vf", 6), "is": ("vi", 11), "c0": ("c0", 11),
            "sa": ("imm5", 6), "op": ("imm5", 16), "code": ("imm20", 6), "imm": ("imm16", 0)}

FORMATS = {
    "rd,rs,rt": "addu subu and or xor nor slt sltu daddu dsubu movn movz pcpyld pcpyud pextlw pextuw "
                "padduw pand por pnor psubb psubw pxor pminw pmaxw ppach",
    "rd?,rs,rt": "mult multu mult1 multu1 madd",
    "rs,rt": "div divu div1 divu1",
    "rt,rs,imm": "addi addiu daddiu slti sltiu andi ori xori",
    "rt,imm": "lui",
    "rs,imm": "mtsah",
    "rt,mem": "lb lbu lh lhu lw lwu lwl lwr ld ldl ldr lq sb sh sw swl swr sd sdl sdr sq",
    "ft,mem": "lwc1 swc1",
    "vt,mem": "lqc2 sqc2",
    "op,mem": "cache pref",
    "rd,rt,sa": "sll srl sra dsll dsrl dsra dsll32 dsrl32 dsra32",
    "rd,rt,rs": "sllv srlv srav dsllv dsrlv dsrav",
    "rs,rt,off": "beq bne beql bnel",
    "rs,off": "blez bgtz blezl bgtzl bltz bgez bltzl bgezl",
    "off": "bc1f bc1t bc1fl bc1tl",
    "target": "j jal",
    "rs": "jr mthi mtlo mthi1 mtlo1",
    "rd?,rs": "jalr",
    "rd": "mfhi mflo mfhi1 mflo1",
    "rd,rt": "pcpyh",
    "rd,rs": "plzcw",
    "code?": "syscall break",
    "sa?": "sync",
    "": "ei di eret vwaitq",
    "rt,c0": "mfc0 mtc0",
    "rt,fs": "mfc1 mtc1",
    "rt,c1": "ctc1",
    "fd,fs,ft": "add.s sub.s mul.s div.s max.s",
    "fd,ft": "sqrt.s",
    "fd,fs": "mov.s neg.s cvt.w.s cvt.s.w",
    "fs,ft": "c.eq.s c.lt.s c.le.s adda.s",
    "rt,vs": "qmfc2 qmtc2",
    "rt,is": "cfc2 ctc2",
    "vd,vs,vt": "vadd vsub vmul vopmsub vaddbc vsubbc vmulbc vmaddbc vmsubbc",
    "vd,vs,q": "vaddq vmulq",
    "acc,vs,vt": "vadda vsuba vopmula vmaddabc vmsubabc vmulabc",
    "vt,vs": "vmove vmr32",
    "q,vtf": "vsqrt",
    "q,vsf,vtf": "vrsqrt",
}
FORMAT = {name: fmt for fmt, names in FORMATS.items() for name in names.split()}
LABEL_RE = re.compile(r"^(\w+):$")
MEM_RE = re.compile(r"^(.*)\((\w+)\)$")


class AsmError(ValueError):
    pass


def opcodes():
    """Mnemonic → instruction word with only its opcode fields set, from census.py's tables."""
    ops = {}

    def add(table, make):
        for key, name in (table.items() if isinstance(table, dict) else enumerate(table)):
            if name is not None:
                ops.setdefault(name, make(key))   # first index = the .x form of a broadcast group

    add(census.PRIMARY, lambda k: k << 26)
    add(census.SPECIAL, lambda k: k)
    add(census.REGIMM, lambda k: 1 << 26 | k << 16)
    add(census.MMI, lambda k: 28 << 26 | k)
    for funct, table in ((8, census.MMI0), (40, census.MMI1), (9, census.MMI2), (41, census.MMI3)):
        add(table, lambda k, f=funct: 28 << 26 | k << 6 | f)
    add({0: "mfc0", 4: "mtc0"}, lambda k: 16 << 26 | k << 21)
    add(census.COP0_C0, lambda k: 16 << 26 | 16 << 21 | k)
    add({0: "mfc1", 2: "cfc1", 4: "mtc1", 6: "ctc1"}, lambda k: 17 << 26 | k << 21)
    add({i: f"bc1{b}" for i, b in enumerate(census.BC)}, lambda k: 17 << 26 | 8 << 21 | k << 16)
    add(census.COP1_S, lambda k: 17 << 26 | 16 << 21 | k)
    ops["cvt.s.w"] = 17 << 26 | 20 << 21 | 32
    add({1: "qmfc2", 2: "cfc2", 5: "qmtc2", 6: "ctc2"}, lambda k: 18 << 26 | k << 21)
    add(census.COP2_SPECIAL1, lambda k: 18 << 26 | 1 << 25 | k)
    add(census.COP2_SPECIAL2, lambda k: 18 << 26 | 1 << 25 | (k >> 2) << 6 | 60 | k & 3)
    return ops


OPCODES = opcodes()


def split_mnemonic(mnemonic):
    """(table name, word bits from broadcast and dest suffix) of e.g. `vmulax.xyz`."""
    if mnemonic in FORMAT:
        return mnemonic, 0
    base, _, dest = mnemonic.rpartition(".")
    if not dest or any(c not in FIELDS for c in dest):
        raise AsmError(f"unknown mnemonic {mnemonic!r}")
    bits = sum(1 << (24 - FIELDS.index(c)) for c in set(dest))
    if base in FORMAT:
        return base, bits
    if base[-1:] in FIELDS and base[:-1] + "bc" in FORMAT:
        return base[:-1] + "bc", bits + FIELDS.index(base[-1])
    raise AsmError(f"unknown mnemonic {mnemonic!r}")


def number(text):
    try:
        return int(text, 0)
    except ValueError:
        raise AsmError(f"bad number {text!r}") from None


def register(text, kind):
    if kind == "gpr" and text in GPR:
        return GPR.index(text)
    if kind == "c0" and text in COP0:
        return COP0[text]
    prefix = {"fpr": "f", "fcr": "fcr", "vf": "vf", "vi": "vi"}.get(kind)
    if prefix and text.startswith(prefix) and text[len(prefix):].isdigit() and int(text[len(prefix):]) < 32:
        return int(text[len(prefix):])
    raise AsmError(f"bad {kind} register {text!r}")


def immediate(text, bits, signed_ok):
    value = number(text)
    low = -(1 << (bits - 1)) if signed_ok else 0
    if not low <= value < 1 << bits:
        raise AsmError(f"immediate {text} out of range")
    return value & ((1 << bits) - 1)


def encode_operand(token, text, pc, labels):
    """Bits for one operand."""
    if token in ("acc", "q"):
        if text != token:
            raise AsmError(f"expected {token}, got {text!r}")
        return 0
    if token in ("vsf", "vtf"):
        reg, field = text[:-1], text[-1:]
        if field not in FIELDS:
            raise AsmError(f"expected a field letter after {text!r}")
        shift = 11 if token == "vsf" else 16
        return register(reg, "vf") << shift | FIELDS.index(field) << (21 if token == "vsf" else 23)
    if token == "mem":
        m = MEM_RE.match(text)
        if not m:
            raise AsmError(f"expected offset(base), got {text!r}")
        return immediate(m.group(1) or "0", 16, True) | register(m.group(2), "gpr") << 21
    if token in ("off", "target"):
        dest = labels[text] if text in labels else number(text)
        if dest & 3:
            raise AsmError(f"target {text} not word aligned")
        if token == "target":
            if (dest ^ (pc + 4)) & 0xf0000000:
                raise AsmError(f"jump target {text} outside the 256 MB region")
            return dest >> 2 & 0x3ffffff
        return immediate(str((dest - pc - 4) >> 2), 16, True)
    kind, shift = OPERANDS[token]
    if kind.startswith("imm"):
        return immediate(text, int(kind[3:]), kind == "imm16") << shift
    return register(text, kind) << shift


def encode(line, pc=0, labels=None):
    """Instruction word of one line at address pc."""
    mnemonic, _, rest = line.strip().partition(" ")
    if mnemonic == "nop" and not rest:
        return 0
    name, word = split_mnemonic(mnemonic)
    args = [a.strip() for a in rest.split(",")] if rest.strip() else []
    tokens = FORMAT[name].split(",") if FORMAT[name] else []
    if tokens and tokens[0].endswith("?"):
        if len(args) == len(tokens) - 1:
            tokens = tokens[1:]
            word |= 31 << 11 if name == "jalr" else 0
        else:
            tokens[0] = tokens[0][:-1]
    if len(args) != len(tokens):
        raise AsmError(f"{line!r}: expected operands {FORMAT[name]!r}")
    word |= OPCODES[name]
    for token, text in zip(tokens, args):
        word |= encode_operand(token, text, pc, labels or {})
    return word


def assemble(lines, pc=0):
    """Instruction words of lines (labels allowed) placed at address pc."""
    labels, code = {}, []
    for line in lines:
        m = LABEL_RE.match(line.strip())
        if m:
            labels[m.group(1)] = pc + 4 * len(code)
        else:
            code.append(line)
    words = []
    for line in code:
        try:
            words.append(encode(line, pc + 4 * len(words), labels))
        except AsmError as e:
            raise AsmError(f"{e} (in {line!r})") from None
    return words


# Ghidra pseudo-ops hide the real instruction; they are skipped in the export check.
GHIDRA_PSEUDO = {"move", "li", "clear", "b", "moveq", "bal"}


def from_ghidra(text):
    """Our syntax for one line of Ghidra disassembly, or None for a pseudo-op."""
    mnemonic, _, rest = text.partition(" ")
    mnemonic = mnemonic.lstrip("_").lower()
    if mnemonic in GHIDRA_PSEUDO:
        return None
    args = [a for a in re.split(r"[ ,]+", rest.strip()) if a]
    args = [{"ACC": "acc", "Q": "q", "ErrorPC": "ErrorEPC"}.get(a, a) for a in args]
    if mnemonic.split(".")[0] in ("vadda", "vsuba"):
        args[1:] = args[:0:-1]   # Ghidra prints ft before fs for these two
    args = [f"vi{16 + int(a[2:])}" if re.fullmatch(r"vc\d+", a) else a for a in args]
    return f"{mnemonic} {', '.join(args)}".strip()


def check_export(functions_dir):
    """Re-encode every instruction of an analysis export; returns (matches, mismatches, skipped)."""
    ok, bad, skipped = Counter(), Counter(), Counter()
    examples = []
    for path in sorted(functions_dir.glob("*.asm")):
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            addr, hexword, text = line.split(None, 2)
            word = int.from_bytes(bytes.fromhex(hexword), "little")
            ours = from_ghidra(text)
            if ours is None:
                skipped[text.split()[0].lstrip("_")] += 1
                continue
            name = census.decode(word)[0]
            try:
                same = encode(ours, int(addr, 16)) == word
            except AsmError:
                same = False
            (ok if same else bad)[name] += 1
            if not same and len(examples) < 20:
                examples.append(f"{addr} {hexword} {text!r} -> {ours!r}")
    return ok, bad, skipped, examples


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="game serial, e.g. ABCD-12345")
    args = ap.parse_args()
    functions_dir = REPO / "work" / args.serial / "analysis" / "functions"
    if not functions_dir.exists():
        sys.exit(f"{functions_dir} not found; run analysis/analyze.py first")
    ok, bad, skipped, examples = check_export(functions_dir)
    print(f"re-encoded {sum(ok.values())} instructions to the same bytes ({len(ok)} mnemonics)")
    print(f"different: {sum(bad.values())} " + ", ".join(f"{n} {c}" for n, c in bad.most_common()))
    print("skipped Ghidra pseudo-ops: " + ", ".join(f"{n} {c}" for n, c in skipped.most_common()))
    print("\n".join(examples))


if __name__ == "__main__":
    main()
