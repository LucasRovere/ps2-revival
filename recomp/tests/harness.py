"""Run the test vectors through the vendored recompiler (levels L1, L2, L3; run inside WSL).

Each case's instructions go into a minimal ELF (code at 0x00100000 with a
.text section, init memory as data segments, so jump tables are found the
way they are in a game). eerecomp translates each ELF; the C++ harness
(harness/main.cpp) loads the init state, runs the code through the runtime's
dispatcher and prints the end state. This script compares it with:

  L1  the vector's expected values (vectors/*.json)
  L2  the reference model on random single-instruction cases (ref.py)

Fixture adjustments, so a case looks like game code to eerecomp's analysis:
- The code is followed by `j .; nop` (the end). In a game a branch target
  is always code; a target just past the ELF's code is rejected. The run
  ends when that loop uses up the cycle budget there, or at a `break` (the
  runtime halts there).
- GPR init values that point into the code are passed as entries. A game
  has such function pointers as constants, or the port finds them by
  exploring (recomp/port.py).

pc_trace: the recompiler is traced with eerecomp probes, which do not fire
for delay slots run inside a branch, so slot entries are left out of the
expected trace. Everything goes to work/recomp-tests/.

L3 (--tables SERIAL, local only): every census.json jump-table target is an
entry of its unit's entry table in work/<SERIAL>/recomp/generated/
(ps2-web-recomp resolves `jr` through those tables).

Usage (WSL):
  python3 recomp/tests/harness.py [--random N] [--seed S]
  python3 recomp/tests/harness.py --tables <SERIAL>
"""

import argparse
import json
import random
import re
import struct
import subprocess
import sys
from pathlib import Path

from asm import FORMAT, GPR, assemble, census, encode
from ref import CODE_BASE, CONTROL_FLOW, M32, OPS, SIGN, Cpu, ModelError, diff_states, expected, join, load_vectors, run

REPO = Path(__file__).resolve().parents[2]
HARNESS_DIR = Path(__file__).resolve().parent / "harness"
OUT = REPO / "work" / "recomp-tests"
RAM_SIZE = 32 << 20
FCR31_C = 1 << 23

WRAPPER = """#define gen case_{i}
#define register_generated_code register_case_{i}
#define register_overrides register_overrides_{i}
{includes}
#undef gen
#undef register_generated_code
#undef register_overrides
{overrides}
void init_case_{i}(ps2::Cpu &c) {{
{init}
}}
"""

# Override case (T31): F's recompiled code returns 1; the override (harness/override.cpp) returns a0 + 0x100.
# It must be reached through jal and through jalr, and return to the caller both times.
OVERRIDE_CASE = {
    "file": "override", "name": "override reached through jal and jalr",
    "asm": ["jal F", "nop", "addu s0, v0, zero", "jalr t9", "nop", "addu s1, v0, zero", "j END", "nop",
            "F:", "addiu v0, zero, 1", "jr ra", "nop", "END:"],
    "init": {"a0": "0x5", "t9": "0x100020"},
    "overrides": {"0x00100020": "harness_add"},
    "expect": {"v0": "0x105", "s0": "0x105", "s1": "0x105", "ra": "0x100014"},
}


def elf(words, mem):
    """ELF32 little-endian MIPS: code at CODE_BASE (R+X, with a .text section), each mem block as an R+W segment."""
    code = b"".join(w.to_bytes(4, "little") for w in words)
    loads = [(CODE_BASE, code, 5)] + [(int(addr, 16), bytes.fromhex(data), 6) for addr, data in mem.items()]
    shstrtab = b"\0.text\0.shstrtab\0"
    offset = 52 + 32 * len(loads)
    phdrs, body = b"", b""
    for addr, data, flags in loads:
        body += bytes(-(offset + len(body) - addr) % 16)   # PCSX2 2.8 lost 4 bytes at file offset 0x40000 of a segment at offset 4 mod 16 (T21)
        phdrs += struct.pack("<8I", 1, offset + len(body), addr, addr, len(data), len(data), flags, 4)
        body += data
    names_at = offset + len(body)
    body += shstrtab + bytes(-(len(body) + len(shstrtab)) % 4)
    shdrs = (bytes(40) + struct.pack("<10I", 1, 1, 6, CODE_BASE, struct.unpack_from("<I", phdrs, 4)[0], len(code), 0, 0, 4, 0)
             + struct.pack("<10I", 7, 3, 0, 0, names_at, len(shstrtab), 0, 0, 1, 0))
    header = struct.pack("<16sHHIIIIIHHHHHH", b"\x7fELF\x01\x01\x01", 2, 8, 1, CODE_BASE, 52, offset + len(body), 0,
                         52, 32, len(loads), 40, 3, 2)
    return header + phdrs + body + shdrs


def init_cpp(init):
    """C++ statements that load a case's init state."""
    lines = []
    state = Cpu(init).state()
    state["fcr31"] = int(init.get("fcr31", "0"), 16)   # state() keeps only the condition bit
    for name, value in state.items():
        if not value or name in ("zero", "vf0"):
            continue
        if name in GPR:
            target = f"c.r[{GPR.index(name)}]"
        elif name in ("hi", "lo", "sa", "fcr31", "facc"):
            target = f"c.{name}"
        elif name[0] == "f":
            target = f"c.f[{name[1:]}]"
        elif name[:2] == "vf":
            target = f"c.vu0.vf[{name[2:]}]"
        elif name[:2] == "vi":
            target = f"c.vu0.vi[{name[2:]}]"
        else:
            target = f"c.vu0.{name}"
        if name in GPR or name in ("hi", "lo", "acc") or name[:2] == "vf":
            lines.append(f"    {target}.d[0] = 0x{value & (1 << 64) - 1:x}ull; {target}.d[1] = 0x{value >> 64:x}ull;")
        else:
            lines.append(f"    {target} = 0x{value:x}u;")
    for addr, data in init.get("mem", {}).items():
        if int(addr, 16) + len(data) // 2 > RAM_SIZE:
            raise ValueError(f"mem {addr} outside RAM")
        literal = "".join(f"\\x{b:02x}" for b in bytes.fromhex(data))
        lines.append(f'    std::memcpy(ps2::g_ram + {addr}, "{literal}", {len(data) // 2});')
    return "\n".join(lines)


def write_if_changed(path, text):
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def translate(cases, eerecomp):
    """Writes each case's ELF, generated C++ and wrapper, and the case table."""
    cases_dir = OUT / "cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    for i, case in enumerate(cases):
        work = OUT / "gen" / str(i)
        work.mkdir(parents=True, exist_ok=True)
        init, end = case.get("init", {}), CODE_BASE + 4 * len(case["words"])
        (work / "case.elf").write_bytes(elf(case["words"] + [encode(f"j {end}", end), 0], init.get("mem", {})))
        pointers = {int(init[r], 16) & M32 for r in GPR if r in init} & set(range(CODE_BASE, end, 4))
        (work / "entries.txt").write_text("".join(f"{p:x}\n" for p in sorted(pointers)))
        args = [eerecomp, work / "case.elf", "--entries", work / "entries.txt", "--out", work / "cpp"]
        if "pc_trace" in case.get("expect", {}):
            (work / "probes.txt").write_text("".join(f"{CODE_BASE + 4 * k:x}\n" for k in range(len(case["words"]))))
            args += ["--probes", work / "probes.txt"]
        overrides = ""
        if "overrides" in case:
            (work / "overrides.txt").write_text("".join(f"{a}\n" for a in case["overrides"]))
            args += ["--overrides", work / "overrides.txt"]
            names = sorted(set(case["overrides"].values()))
            overrides = ("namespace ovr {\n" + "".join(f"bool {n}(ps2::Cpu &c);\n" for n in names) + "}\n\n"
                         f"void register_overrides_{i}() {{\n"
                         + "".join(f"    ps2::register_override({a}u, &ovr::{n});\n" for a, n in case["overrides"].items()) + "}\n")
        subprocess.run(args, check=True, capture_output=True)
        includes = "\n".join(f'#include "{p}"' for p in sorted((work / "cpp").glob("*.cpp")))
        write_if_changed(cases_dir / f"case_{i}.cpp", WRAPPER.format(i=i, includes=includes, overrides=overrides, init=init_cpp(init)))
    for stale in cases_dir.glob("case_*.cpp"):
        if int(stale.stem[5:]) >= len(cases):
            stale.unlink()
    decls = "".join(f"void register_case_{i}();\nvoid init_case_{i}(ps2::Cpu &c);\n" for i in range(len(cases)))
    rows = "".join(f"    {{register_case_{i}, init_case_{i}}},\n" for i in range(len(cases)))
    write_if_changed(cases_dir / "table.cpp",
                     '#include "ps2/cpu.hpp"\n\n#include <cstddef>\n\n'
                     "struct Case {\n    void (*register_code)();\n    void (*init)(ps2::Cpu &c);\n};\n\n"
                     f"{decls}\nextern const Case kCases[] = {{\n{rows}}};\n"
                     f"extern const std::size_t kCaseCount = {len(cases)};\n")


def cmake(build, target):
    if not (build / "build.ninja").exists():
        subprocess.run(["cmake", "-S", HARNESS_DIR, "-B", build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                        "-DCMAKE_CXX_COMPILER=clang++", f"-DHARNESS_CASES={OUT / 'cases'}"], check=True)
    subprocess.run(["ninja", "-C", build, target], check=True)


def run_harness(binary, count):
    """[(result JSON or None, stderr lines)] per case; a crash is recorded and the run resumes at the next case."""
    results, logs = [None] * count, [[] for _ in range(count)]
    start = 0
    while start < count:
        p = subprocess.run([binary, str(start)], capture_output=True, text=True)
        current = start
        for line in p.stderr.splitlines():
            m = re.match(r"\[case (\d+)\]$", line)
            if m:
                current = int(m.group(1))
            else:
                logs[current].append(line)
        done = [json.loads(line) for line in p.stdout.splitlines()]
        for r in done:
            results[r["case"]] = r
        if p.returncode == 0:
            break
        crashed = done[-1]["case"] + 1 if done else start
        logs[crashed].append(f"harness crashed (exit {p.returncode})")
        start = crashed + 1
    return results, logs


def end_state(result):
    """(registers named as ref.py names them, nonzero memory bytes) from the harness output."""
    regs = {name: int(result[f"r{i}"], 16) for i, name in enumerate(GPR)}
    for name in ["hi", "lo", "sa", "facc", "q", "acc"] + [f"f{i}" for i in range(32)] + \
                [f"vf{i}" for i in range(32)] + [f"vi{i}" for i in range(16)]:
        regs[name] = int(result[name], 16)
    regs["fcr31"] = int(result["fcr31"], 16) & FCR31_C   # only the condition bit is compared (recomp-tests.md)
    mem = {}
    for addr, data in result["mem"].items():
        for k, b in enumerate(bytes.fromhex(data)):
            if b:
                mem[int(addr, 16) + k] = b
    return regs, mem


def outcome(case, result, log):
    """(error text or None, probe trace) of one run."""
    end = CODE_BASE + 4 * len(case["words"])
    trace = [int(m.group(1), 16) for m in (re.match(r"\[probe\] 0x([0-9A-F]+)", line) for line in log) if m]
    stops = [line for line in log if line.startswith("[ee] stopped") or line.startswith("[ee] bad entry") or "crashed" in line]
    if stops or result is None:
        return "; ".join(stops) or "no result", trace
    pc = int(result["pc"], 16)
    if pc & ~1 == end:
        return None, trace
    if pc & 1 and any(line.startswith(f"[ee] break at 0x{pc & ~1:08X} ") for line in log):
        return None, trace   # the runtime halts on break, like PCSX2 (T21, T24): the case ends there
    if pc & 1 and any(f"no translated code at 0x{pc & ~1:08X}" in line for line in log):
        return f"unknown jump target 0x{pc & ~1:08x}", trace
    if pc & 1:
        return f"unwound at 0x{pc & ~1:08x} (budget used up)", trace
    return f"returned to 0x{pc:08x}", trace


def without_slots(words, trace):
    """The trace without delay-slot entries (a slot follows a control-flow instruction at +4)."""
    kept = []
    for k, pc in enumerate(trace):
        prev = trace[k - 1] if k else None
        if prev is not None and pc == prev + 4 and census.decode(words[(prev - CODE_BASE) // 4])[0] in CONTROL_FLOW:
            continue
        kept.append(pc)
    return kept


def check_vector(case, result, log):
    expect = case["expect"]
    error, trace = outcome(case, result, log)
    if "error" in expect:
        if error and expect["error"] in error:
            return []
        return [f"expected error {expect['error']!r}, got {error or 'a normal end'}"]
    if error:
        return [f"run error: {error}"]
    diffs = diff_states(*expected(case), *end_state(result))
    if "pc_trace" in expect:
        want = without_slots(case["words"], [int(a, 16) for a in expect["pc_trace"]])
        if trace != want:
            diffs.append(f"pc_trace (no slots): got {[f'0x{a:08x}' for a in trace]}, expected {[f'0x{a:08x}' for a in want]}")
    return diffs


# Random cases (L2): one instruction with random operands on a fully random register state.
RANDOM_OPS = sorted(n for n in FORMAT if n in OPS and n not in CONTROL_FLOW and n != "break")
VU_DEST_FORMATS = {"vd,vs,vt", "vd,vs,q", "acc,vs,vt", "vt,vs"}
ACCESS_SIZE = {"lh": 2, "lhu": 2, "sh": 2, "lw": 4, "lwu": 4, "sw": 4, "lwc1": 4, "swc1": 4, "ld": 8, "sd": 8}
DATA_BASE, DATA_SIZE, POINTER = 0x00200000, 0x200, 0x00200100
EDGE_WORDS = [0, 1, 0x7fff, 0x8000, 0xffff, 0x7fffffff, 0x80000000, 0xffffffff]
EDGE_FLOATS = [0, SIGN, 1, 0x7fffff, 0x800000, 0x3f800000, 0xbf800000, 0x7f7fffff, 0x7f800000, 0x7fffffff, 0xffffffff]


def random_word(rng):
    r = rng.random()
    if r < 0.3:
        return rng.choice(EDGE_WORDS)
    return rng.getrandbits(32) if r < 0.7 else rng.randrange(-100, 100) & M32


def random_float(rng):
    """Edge values, any bits, or a sign/exponent near 1.0 so that arithmetic results stay in range."""
    r = rng.random()
    if r < 0.25:
        return rng.choice(EDGE_FLOATS)
    if r < 0.5:
        return rng.getrandbits(32)
    return rng.getrandbits(1) << 31 | rng.randrange(117, 138) << 23 | rng.getrandbits(23)


def random_line(rng, name):
    """(asm line, base register or None) for one random instruction."""
    fmt, base = FORMAT[name], None
    args = []
    for token in (t.rstrip("?") for t in fmt.split(",") if t):
        if token in ("rs", "rt", "rd"):
            args.append(rng.choice(GPR))
        elif token in ("fs", "ft", "fd"):
            args.append(f"f{rng.randrange(32)}")
        elif token in ("vs", "vt", "vd"):
            args.append(f"vf{rng.randrange(32)}")
        elif token in ("vsf", "vtf"):
            args.append(f"vf{rng.randrange(32)}{rng.choice('xyzw')}")
        elif token == "is":
            args.append(rng.choice([f"vi{k}" for k in range(16)] + ["vi22"]))
        elif token == "c1":
            args.append("fcr31")
        elif token == "sa":
            args.append(str(rng.randrange(32)))
        elif token == "imm":
            args.append(str(rng.randrange(-0x8000, 0x8000)))
        elif token == "mem":
            size, base = ACCESS_SIZE.get(name, 1), rng.choice(GPR[1:])
            args.append(f"{rng.randrange(-0x80, 0x80) // size * size}({base})")
        else:
            args.append(token)   # acc, q
    mnemonic = name
    if fmt in VU_DEST_FORMATS:
        dest = "xyz" if name in ("vopmula", "vopmsub") else "".join(c for c in "xyzw" if rng.random() < 0.6) or "w"
        mnemonic = (name[:-2] + rng.choice("xyzw") if name.endswith("bc") else name) + "." + dest
    return f"{mnemonic} {', '.join(args)}".strip(), base


def random_case(rng, k):
    """A random case with the model's end state as its expectation, or None if the model can't run it."""
    name = rng.choice(RANDOM_OPS)
    line, base = random_line(rng, name)
    init = {r: hex(join([random_word(rng) for _ in range(4)], 32)) for r in GPR[1:] + ["hi", "lo"]}
    init.update({f"f{i}": hex(random_float(rng)) for i in range(32)})
    init.update({f"vf{i}": hex(join([random_float(rng) for _ in range(4)], 32)) for i in range(1, 32)})
    init.update({f"vi{i}": hex(rng.getrandbits(16)) for i in range(1, 16)})
    init.update(facc=hex(random_float(rng)), q=hex(random_float(rng)), fcr31=hex(rng.getrandbits(32)),
                acc=hex(join([random_float(rng) for _ in range(4)], 32)),
                mem={f"0x{DATA_BASE:08x}": rng.randbytes(DATA_SIZE).hex()})
    if base:
        init[base] = hex(POINTER)
    case = {"name": f"random {k}: {line}", "asm": [line], "init": init}
    try:
        cpu, _ = run(case)
    except ModelError:
        return None
    case["want"] = (cpu.state(), cpu.mem)
    return case


def check_random(case, result, log):
    error, _ = outcome(case, result, log)
    if error:
        return [f"run error: {error}"]
    return diff_states(*case["want"], *end_state(result))


def report(cases, results, logs):
    failed = 0
    for i, case in enumerate(cases):
        diffs = (check_random if "want" in case else check_vector)(case, results[i], logs[i])
        if diffs:
            failed += 1
            note = f" [unverified: {case['unverified']}]" if "unverified" in case else ""
            print(f"FAIL {case.get('file', 'random')}: {case['name']}{note}\n  asm: {case['asm']}\n  " + "\n  ".join(diffs))
    return failed


def elf_words(path):
    """Address → word of an ELF's loaded segments."""
    data = path.read_bytes()
    phoff, phnum = struct.unpack_from("<I", data, 28)[0], struct.unpack_from("<H", data, 44)[0]
    words = {}
    for i in range(phnum):
        kind, offset, vaddr, _, filesz = struct.unpack_from("<5I", data, phoff + 32 * i)
        if kind == 1:
            for k in range(0, filesz - 3, 4):
                words[vaddr + k] = int.from_bytes(data[offset + k:offset + k + 4], "little")
    return words


def check_tables(serial):
    """L3: every bounded census.json jump-table target has an entry id in its unit's entry table."""
    game = json.loads((REPO / "local" / "games" / serial / "game.json").read_text(encoding="utf-8"))
    recomp = REPO / "work" / serial / "recomp"
    census = json.loads((REPO / "work" / serial / "analysis" / "census.json").read_text())
    words = elf_words(recomp / "disc" / game["disc"]["elf"])
    generated = recomp / "generated"
    units = {int(u, 16): int(base, 16) for base, u in
             re.findall(r"\{0x([0-9A-F]{8})u, \d+u, &unit_([0-9A-F]{4}), entries_\2\}", (generated / "table.cpp").read_text())}
    ids = {}
    for path in generated.glob("unit_*.cpp"):
        m = re.search(r"const std::uint16_t entries_([0-9A-F]{4})\[\d+\] = \{([^}]*)\}", path.read_text())
        base = units[int(m.group(1), 16)]
        ids.update({base + 4 * k: int(v) for k, v in enumerate(m.group(2).replace(",", " ").split())})
    tables = [j for j in census["indirect_jumps"] if j["kind"] == "table"]
    unbounded = [j for j in tables if j["entries"] is None]
    targets = {words[int(j["table"], 16) + 4 * k] for j in tables if j["entries"] for k in range(j["entries"])}
    missing = sorted(t for t in targets if not ids.get(t))
    print(f"{len(tables)} jump tables: {len(tables) - len(unbounded)} bounded with {len(targets)} distinct targets, "
          f"{len(missing)} without an entry id; {len(unbounded)} without a bound (not checked)")
    for t in missing:
        print(f"  missing entry: 0x{t:08x}")
    return len(missing)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--random", type=int, default=500, help="random cases for L2 (default 500)")
    ap.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    ap.add_argument("--tables", metavar="SERIAL", help="only run L3 on a ported game")
    args = ap.parse_args()
    if args.tables:
        sys.exit(1 if check_tables(args.tables) else 0)

    vectors = [{**case, "file": file} for file, case in load_vectors()]
    rng = random.Random(args.seed)
    randoms = []
    while len(randoms) < args.random:
        case = random_case(rng, len(randoms))
        if case:
            randoms.append(case)
    cases = vectors + randoms + [OVERRIDE_CASE]
    for case in cases:
        case["words"] = assemble(case["asm"], CODE_BASE)

    build = OUT / "build"
    cmake(build, "eerecomp")
    translate(cases, build / "upstream" / "eerecomp")
    cmake(build, "harness")
    results, logs = run_harness(build / "harness", len(cases))
    failed_vectors = report(vectors, results, logs)
    failed_random = report(randoms, results[len(vectors):-1], logs[len(vectors):-1])
    failed_override = report([OVERRIDE_CASE], results[-1:], logs[-1:])
    print(f"L1: {len(vectors) - failed_vectors}/{len(vectors)} vectors pass on the recompiler")
    print(f"L2: {len(randoms) - failed_random}/{len(randoms)} random cases match the reference model (seed {args.seed})")
    print(f"override case: {'FAIL' if failed_override else 'pass'}")
    sys.exit(1 if failed_vectors or failed_random or failed_override else 0)


if __name__ == "__main__":
    main()
