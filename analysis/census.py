"""Count the EE (R5900) instructions a game uses, for the recompiler (Phase 5).

Reads work/<serial>/analysis/functions/*.asm (run analyze.py first) and the
main ELF's .text. Instructions are decoded from their bytes, not from
Ghidra's text, because Ghidra prints pseudo-ops (`move`, `li`, `clear`) that
hide which real instruction is used (e.g. `move` = addu, daddu, or por).

Prints a summary and writes work/<serial>/analysis/census.json:
- mnemonics: count, functions using it, class (base, mmi, cop0, cop1, cop2, system)
- invalid: addresses of words in functions that decode to nothing
- indirect_jumps: `jr` not via ra; `table` when it is a GCC jump table
  (lui/lw base + sltiu bound), else `register`
- indirect_calls: `jalr` sites
- gaps: .text ranges not inside any function's instructions

Usage:
  python census.py <SERIAL>
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent
GAMES_DIR = REPO.parent / "local" / "games"
WORK_DIR = REPO.parent / "work"

# Opcode tables written from the public R5900 (EE Core) instruction set.
# None = reserved / not an EE instruction.
PRIMARY = [
    None, None, "j", "jal", "beq", "bne", "blez", "bgtz",
    "addi", "addiu", "slti", "sltiu", "andi", "ori", "xori", "lui",
    None, None, None, None, "beql", "bnel", "blezl", "bgtzl",
    "daddi", "daddiu", "ldl", "ldr", None, None, "lq", "sq",
    "lb", "lh", "lwl", "lw", "lbu", "lhu", "lwr", "lwu",
    "sb", "sh", "swl", "sw", "sdl", "sdr", "swr", "cache",
    None, "lwc1", None, "pref", None, None, "lqc2", "ld",
    None, "swc1", None, None, None, None, "sqc2", "sd",
]
SPECIAL = [
    "sll", None, "srl", "sra", "sllv", None, "srlv", "srav",
    "jr", "jalr", "movz", "movn", "syscall", "break", None, "sync",
    "mfhi", "mthi", "mflo", "mtlo", "dsllv", None, "dsrlv", "dsrav",
    "mult", "multu", "div", "divu", None, None, None, None,
    "add", "addu", "sub", "subu", "and", "or", "xor", "nor",
    "mfsa", "mtsa", "slt", "sltu", "dadd", "daddu", "dsub", "dsubu",
    "tge", "tgeu", "tlt", "tltu", "teq", None, "tne", None,
    "dsll", None, "dsrl", "dsra", "dsll32", None, "dsrl32", "dsra32",
]
REGIMM = {0: "bltz", 1: "bgez", 2: "bltzl", 3: "bgezl", 8: "tgei", 9: "tgeiu", 10: "tlti",
          11: "tltiu", 12: "teqi", 14: "tnei", 16: "bltzal", 17: "bgezal", 18: "bltzall",
          19: "bgezall", 24: "mtsab", 25: "mtsah"}
MMI = {0: "madd", 1: "maddu", 4: "plzcw", 16: "mfhi1", 17: "mthi1", 18: "mflo1", 19: "mtlo1",
       24: "mult1", 25: "multu1", 26: "div1", 27: "divu1", 32: "madd1", 33: "maddu1",
       52: "psllh", 54: "psrlh", 55: "psrah", 60: "psllw", 62: "psrlw", 63: "psraw"}
MMI0 = {0: "paddw", 1: "psubw", 2: "pcgtw", 3: "pmaxw", 4: "paddh", 5: "psubh", 6: "pcgth",
        7: "pmaxh", 8: "paddb", 9: "psubb", 10: "pcgtb", 16: "paddsw", 17: "psubsw",
        18: "pextlw", 19: "ppacw", 20: "paddsh", 21: "psubsh", 22: "pextlh", 23: "ppach",
        24: "paddsb", 25: "psubsb", 26: "pextlb", 27: "ppacb", 30: "pext5", 31: "ppac5"}
MMI1 = {1: "pabsw", 2: "pceqw", 3: "pminw", 4: "padsbh", 5: "pabsh", 6: "pceqh", 7: "pminh",
        10: "pceqb", 16: "padduw", 17: "psubuw", 18: "pextuw", 20: "padduh", 21: "psubuh",
        22: "pextuh", 24: "paddub", 25: "psubub", 26: "pextub", 27: "qfsrv"}
MMI2 = {0: "pmaddw", 2: "psllvw", 3: "psrlvw", 4: "pmsubw", 8: "pmfhi", 9: "pmflo", 10: "pinth",
        12: "pmultw", 13: "pdivw", 14: "pcpyld", 16: "pmaddh", 17: "phmadh", 18: "pand",
        19: "pxor", 20: "pmsubh", 21: "phmsbh", 26: "pexeh", 27: "prevh", 28: "pmulth",
        29: "pdivbw", 30: "pexew", 31: "prot3w"}
MMI3 = {0: "pmadduw", 3: "psravw", 8: "pmthi", 9: "pmtlo", 10: "pinteh", 12: "pmultuw",
        13: "pdivuw", 14: "pcpyud", 18: "por", 19: "pnor", 26: "pexch", 27: "pcpyh", 30: "pexcw"}
COP0_C0 = {1: "tlbr", 2: "tlbwi", 6: "tlbwr", 8: "tlbp", 24: "eret", 56: "ei", 57: "di"}
COP1_S = {0: "add.s", 1: "sub.s", 2: "mul.s", 3: "div.s", 4: "sqrt.s", 5: "abs.s", 6: "mov.s",
          7: "neg.s", 22: "rsqrt.s", 24: "adda.s", 25: "suba.s", 26: "mula.s", 28: "madd.s",
          29: "msub.s", 30: "madda.s", 31: "msuba.s", 36: "cvt.w.s", 40: "max.s", 41: "min.s",
          48: "c.f.s", 50: "c.eq.s", 52: "c.lt.s", 54: "c.le.s"}
# VU0 macro mode. The four broadcast (x/y/z/w) forms are counted as one "...bc".
COP2_SPECIAL1 = {**{i: n for base, n in ((0, "vaddbc"), (4, "vsubbc"), (8, "vmaddbc"), (12, "vmsubbc"),
                                         (16, "vmaxbc"), (20, "vminibc"), (24, "vmulbc"))
                    for i in range(base, base + 4)},
                 28: "vmulq", 29: "vmaxi", 30: "vmuli", 31: "vminii", 32: "vaddq", 33: "vmaddq",
                 34: "vaddi", 35: "vmaddi", 36: "vsubq", 37: "vmsubq", 38: "vsubi", 39: "vmsubi",
                 40: "vadd", 41: "vmadd", 42: "vmul", 43: "vmax", 44: "vsub", 45: "vmsub",
                 46: "vopmsub", 47: "vmini", 48: "viadd", 49: "visub", 50: "viaddi", 52: "viand",
                 53: "vior", 56: "vcallms", 57: "vcallmsr"}
COP2_SPECIAL2 = {**{i: n for base, n in ((0, "vaddabc"), (4, "vsubabc"), (8, "vmaddabc"), (12, "vmsubabc"),
                                         (24, "vmulabc"))
                    for i in range(base, base + 4)},
                 16: "vitof0", 17: "vitof4", 18: "vitof12", 19: "vitof15", 20: "vftoi0", 21: "vftoi4",
                 22: "vftoi12", 23: "vftoi15", 28: "vmulaq", 29: "vabs", 30: "vmulai", 31: "vclip",
                 32: "vaddaq", 33: "vmaddaq", 34: "vaddai", 35: "vmaddai", 36: "vsubaq", 37: "vmsubaq",
                 38: "vsubai", 39: "vmsubai", 40: "vadda", 41: "vmadda", 42: "vmula", 44: "vsuba",
                 45: "vmsuba", 46: "vopmula", 47: "vnop", 48: "vmove", 49: "vmr32", 52: "vlqi",
                 53: "vsqi", 54: "vlqd", 55: "vsqd", 56: "vdiv", 57: "vsqrt", 58: "vrsqrt",
                 59: "vwaitq", 60: "vmtir", 61: "vmfir", 62: "vilwr", 63: "viswr", 64: "vrnext",
                 65: "vrget", 66: "vrinit", 67: "vrxor"}
BC = ["f", "t", "fl", "tl"]

MMI_CLASS = {"lq", "sq", "mfsa", "mtsa", "mtsab", "mtsah"}
SYSTEM_CLASS = {"syscall", "break", "sync", "cache", "tge", "tgeu", "tlt", "tltu", "teq", "tne",
                "tgei", "tgeiu", "tlti", "tltiu", "teqi", "tnei"}

RA = 31
HEADER_RE = re.compile(r"^// (\S+) @ (0x[0-9a-f]{8})")


def decode(word):
    """(mnemonic, class) of one instruction word; mnemonic is None for an invalid word."""
    op, rs, rt = word >> 26, (word >> 21) & 31, (word >> 16) & 31
    funct, sa = word & 63, (word >> 6) & 31
    if op == 0:
        name = SPECIAL[funct]
    elif op == 1:
        name = REGIMM.get(rt)
    elif op == 16:
        name = {0: "mfc0", 4: "mtc0"}.get(rs) or (f"bc0{BC[rt]}" if rs == 8 and rt < 4 else None)
        if rs == 16:
            name = COP0_C0.get(funct)
        return name, "cop0"
    elif op == 17:
        name = {0: "mfc1", 2: "cfc1", 4: "mtc1", 6: "ctc1"}.get(rs)
        if rs == 8 and rt < 4:
            name = f"bc1{BC[rt]}"
        elif rs == 16:
            name = COP1_S.get(funct)
        elif rs == 20 and funct == 32:
            name = "cvt.s.w"
        return name, "cop1"
    elif op == 18:
        name = {1: "qmfc2", 2: "cfc2", 5: "qmtc2", 6: "ctc2"}.get(rs)
        if rs == 8 and rt < 4:
            name = f"bc2{BC[rt]}"
        elif rs >= 16:
            name = COP2_SPECIAL2.get(sa << 2 | funct & 3) if funct >= 60 else COP2_SPECIAL1.get(funct)
        return name, "cop2"
    elif op == 28:
        sub = {8: MMI0, 40: MMI1, 9: MMI2, 41: MMI3}.get(funct)
        if sub is not None:
            name = sub.get(sa)
        elif funct == 48:
            name = "pmfhl" if sa <= 4 else None
        elif funct == 49:
            name = "pmthl" if sa == 0 else None
        else:
            name = MMI.get(funct)
        return name, "mmi"
    else:
        name = PRIMARY[op]
    if name in ("lwc1", "swc1"):
        return name, "cop1"
    if name in ("lqc2", "sqc2"):
        return name, "cop2"
    if name in MMI_CLASS:
        return name, "mmi"
    if name in SYSTEM_CLASS:
        return name, "system"
    return name, "base"


def parse_asm(asm_text):
    """(function addr, name, [(addr, word)]) from one .asm export."""
    lines = asm_text.splitlines()
    name, addr = HEADER_RE.match(lines[0]).groups()
    words = [(int(a, 16), int.from_bytes(bytes.fromhex(h), "little"))
             for a, h in (line.split()[:2] for line in lines[1:])]
    return int(addr, 16), name, words


def simm(word):
    return (word & 0xffff) - ((word & 0x8000) << 1)


def find_jump_table(words, i):
    """(table address, entries or None) if `jr` at words[i] reads a GCC jump table, else None.

    Two shapes seen in the pilot game, both after `sltiu t,idx,N` (N = entries):
    game code   lui b,hi; addu b,b,idx; lw r,lo(b); jr r
    SDK/libc    lui p,hi; addiu p,p,lo; addu b,idx,p; lw r,0(b); jr r
    """
    reg = (words[i][1] >> 21) & 31
    window = range(i - 1, max(i - 8, -1), -1)
    lw = next((j for j in window if words[j][1] >> 26 == 35 and (words[j][1] >> 16) & 31 == reg), None)
    if lw is None:
        return None
    base = (words[lw][1] >> 21) & 31
    addu = next((j for j in range(lw - 1, max(lw - 8, -1), -1)
                 if words[j][1] >> 26 == 0 and words[j][1] & 63 == 33 and (words[j][1] >> 11) & 31 == base), None)
    if addu is None:
        return None
    sources = {(words[addu][1] >> 21) & 31, (words[addu][1] >> 16) & 31}
    lui = next((k for k in range(addu - 1, max(addu - 8, -1), -1)
                if words[k][1] >> 26 == 15 and (words[k][1] >> 16) & 31 in sources), None)
    if lui is None:
        return None
    p = (words[lui][1] >> 16) & 31
    lo = sum(simm(w) for _, w in words[lui + 1:addu] if w >> 26 == 9 and (w >> 21) & 31 == p and (w >> 16) & 31 == p)
    table = ((words[lui][1] & 0xffff) << 16) + lo + simm(words[lw][1])
    entries = next((w & 0xffff for _, w in reversed(words[max(lui - 12, 0):lui]) if w >> 26 == 11), None)
    return table, entries


def census(functions, image, image_addr, text_start, text_size):
    """Counts and lists for [(addr, name, [(addr, word)])].

    image: the loaded segment's bytes at image_addr; .text is text_size bytes at text_start inside it.
    """
    counts, users, classes = Counter(), defaultdict(set), {}
    invalid, jumps, calls, covered = [], [], [], set()
    for faddr, fname, words in functions:
        for i, (addr, word) in enumerate(words):
            covered.add(addr)
            name, cls = decode(word)
            if name is None:
                invalid.append(f"0x{addr:08x}")
                continue
            counts[name] += 1
            users[name].add(faddr)
            classes[name] = cls
            if name == "jr" and (word >> 21) & 31 != RA:
                site = {"addr": f"0x{addr:08x}", "function": fname, "reg": (word >> 21) & 31}
                table = find_jump_table(words, i)
                site["kind"] = "table" if table else "register"
                if table:
                    site["table"], site["entries"] = f"0x{table[0]:08x}", table[1]
                    site["targets"] = [int.from_bytes(image[table[0] - image_addr + 4 * k:][:4], "little")
                                       for k in range(table[1] or 0)]
                jumps.append(site)
            elif name == "jalr":
                calls.append({"addr": f"0x{addr:08x}", "function": fname})
    for site in jumps:
        if "targets" in site:
            site["targets_outside_functions"] = [f"0x{t:08x}" for t in site.pop("targets") if t not in covered]
    mnemonics = {n: {"class": classes[n], "count": c, "functions": len(users[n])} for n, c in counts.most_common()}
    text = image[text_start - image_addr:text_start - image_addr + text_size]
    return {"mnemonics": mnemonics, "invalid": invalid, "indirect_jumps": jumps,
            "indirect_calls": calls, "gaps": gaps(covered, text_start, text)}


def gaps(covered, text_start, text):
    """Runs of .text words outside every function, with what they contain."""
    runs, run = [], None
    for off in range(0, len(text) - 3, 4):
        addr = text_start + off
        if addr in covered:
            run = None
            continue
        word = int.from_bytes(text[off:off + 4], "little")
        if run is None:
            run = {"start": f"0x{addr:08x}", "size": 0, "zero_words": 0, "invalid_words": 0, "jr_ra": 0}
            runs.append(run)
        run["size"] += 4
        run["zero_words"] += word == 0
        run["invalid_words"] += decode(word)[0] is None
        run["jr_ra"] += word == 0x03e00008
    return runs


def report(result, text_size):
    m = result["mnemonics"]
    by_class = Counter()
    for v in m.values():
        by_class[v["class"]] += v["count"]
    total = sum(by_class.values())
    lines = [f"{total} instructions, {len(m)} distinct mnemonics, {len(result['invalid'])} invalid words", "",
             "| Class | Instructions | Mnemonics |", "|---|---|---|"]
    lines += [f"| {c} | {n} | {sum(v['class'] == c for v in m.values())} |" for c, n in by_class.most_common()]
    for c, _ in by_class.most_common():
        lines += ["", f"{c}: " + ", ".join(f"{n} {v['count']}" for n, v in m.items() if v["class"] == c)]
    jumps = result["indirect_jumps"]
    tables = [j for j in jumps if j["kind"] == "table"]
    lines += ["", f"Indirect jumps (jr not ra): {len(jumps)}, of which jump tables: {len(tables)} "
              f"({sum(j['entries'] or 0 for j in tables)} entries, {sum(j['entries'] is None for j in tables)} without bound)",
              f"- jump tables with targets outside every function: "
              f"{sum(bool(j['targets_outside_functions']) for j in tables)} "
              f"({sum(len(j['targets_outside_functions']) for j in tables)} targets)",
              f"Indirect calls (jalr): {len(result['indirect_calls'])}"]
    g = result["gaps"]
    zero = [r for r in g if r["zero_words"] * 4 == r["size"]]
    code = [r for r in g if r not in zero and r["invalid_words"] == 0 and r["jr_ra"]]
    lines += ["", f"Gaps: {len(g)} runs, {sum(r['size'] for r in g)} of {text_size} .text bytes",
              f"- all zero (padding): {len(zero)} runs, {sum(r['size'] for r in zero)} bytes",
              f"- no invalid word and contains jr ra (likely code): {len(code)} runs, {sum(r['size'] for r in code)} bytes",
              f"- other: {len(g) - len(zero) - len(code)} runs, "
              f"{sum(r['size'] for r in g) - sum(r['size'] for r in zero + code)} bytes", "", "Largest gaps:"]
    lines += [f"- {r['start']} {r['size']} bytes, {r['zero_words']} zero, {r['invalid_words']} invalid, "
              f"{r['jr_ra']} jr ra" for r in sorted(g, key=lambda r: -r["size"])[:10]]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="game serial, e.g. ABCD-12345")
    args = ap.parse_args()

    out_dir = WORK_DIR / args.serial / "analysis"
    functions_dir = out_dir / "functions"
    if not functions_dir.exists():
        sys.exit(f"{functions_dir} not found; run analyze.py first")
    config = json.loads((GAMES_DIR / args.serial / "game.json").read_text(encoding="utf-8"))
    disc = WORK_DIR / args.serial / "disc"
    elf = (disc / config["disc"]["elf"]).read_bytes()
    headers = json.loads((disc / "elf.json").read_text(encoding="utf-8"))
    seg = headers["program_headers"][0]
    sec = next(s for s in headers["section_headers"] if s["name"] == ".text")
    image = elf[seg["offset"]:seg["offset"] + seg["filesz"]]

    functions = [parse_asm(p.read_text(encoding="utf-8")) for p in sorted(functions_dir.glob("*.asm"))]
    result = census(functions, image, int(seg["vaddr"], 16), int(sec["addr"], 16), sec["size"])
    (out_dir / "census.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(report(result, sec["size"]))
    print(f"\n-> {out_dir / 'census.json'}")


if __name__ == "__main__":
    main()
