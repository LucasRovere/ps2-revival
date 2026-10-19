"""Run the test vectors on PCSX2 as an oracle (level L4, Windows).

All eligible vectors go into one test ELF (our assembler and ELF writer).
Per case the ELF sets the start state, runs the vector's instructions, stores
the end state and prints it as hex through the EE SIO TX register
(0x1000F180), which PCSX2 logs as EE console output. PCSX2 boots the ELF
with the owner's BIOS; this script parses the log and compares each case
with its expected values (= ref.py = the recompiler, L0/L1).

PCSX2 runs with its own data folder (work/recomp-tests/oracle/<mode>/): a copy
of the user's PCSX2.ini with the mode's settings, the BIOS folder pointing to
the user's (not copied). The user's own config is only read.

Eligible: code that does not depend on its address (no j/jal/jr/jalr, no
pc_trace), no expected error, and no k0/k1 (the dump code uses them; the
kernel's interrupt handlers clobber them anyway), sa, facc or acc (not set or
read here). `break` runs last, on its own: what the kernel does with it is
the question.

Usage (Windows):
  python recomp/tests/oracle.py [--mode rec interp ...]
"""

import argparse
import configparser
import re
import subprocess
import time
from pathlib import Path

from asm import GPR, OPCODES, assemble, census
from harness import elf
from ref import CODE_BASE, M32, diff_states, expected, load_vectors, Cpu

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "work" / "recomp-tests" / "oracle"
DATA = 0x01000000
SIO_TX = 0x1000f180
WINDOW = 256
UNOBSERVED = {"k0", "k1", "sa", "facc", "acc"}
HANG_SECONDS = 5   # no new log output for this long after the status line = a case hung
NOT_RELOCATABLE = {"j", "jal", "jr", "jalr", "break", "syscall"}

# State block (start state and dump): GPRs, HI, LO, FPRs, FCR31, VU0 vf, vi, Q.
GPR_AT, HI_AT, LO_AT, F_AT, FCR31_AT, VF_AT, VI_AT, Q_AT, BLOCK = 0, 512, 528, 544, 672, 688, 1200, 1264, 1280

SETTINGS = {"EmuCore/CPU": {"FPU.Roundmode": "3", "FPUDiv.Roundmode": "0", "VU0.Roundmode": "3"},
            "EmuCore/CPU/Recompiler": {"EnableEE": "true", "EnableVU0": "true", "fpuOverflow": "true",
                                       "fpuExtraOverflow": "false", "fpuFullMode": "false", "vu0Overflow": "true",
                                       "vu0ExtraOverflow": "false", "vu0SignOverflow": "false", "vu0Underflow": "false"}}
MODES = {
    "rec": {},   # PCSX2 2.8 defaults: recompilers, FPU/VU round toward zero, FPU divide round to nearest, normal clamping
    "rec-full": {"EmuCore/CPU/Recompiler": {"fpuFullMode": "true"}},
    "rec-divchop": {"EmuCore/CPU": {"FPUDiv.Roundmode": "3"}},
    "interp": {"EmuCore/CPU/Recompiler": {"EnableEE": "false", "EnableVU0": "false"}},
}


class Program:
    """Code words from CODE_BASE and a data image from DATA."""

    def __init__(self):
        self.words, self.data = [], bytearray()

    @property
    def pc(self):
        return CODE_BASE + 4 * len(self.words)

    def code(self, lines):
        self.words += assemble(lines, self.pc)

    def put(self, blob, align=16):
        self.data += bytes(-len(self.data) % align)
        addr = DATA + len(self.data)
        self.data += blob
        return addr


def la(reg, addr):
    return [f"lui {reg}, {addr >> 16}", f"ori {reg}, {reg}, {addr & 0xffff}"]


def cfc1(rt):
    return OPCODES["cfc1"] | GPR.index(rt) << 16 | 31 << 11


ROUTINES = [   # puts(a0 = string), hexdump(a0 = address, a1 = bytes, a multiple of 32): "T21 <64 hex digits>" lines
    "puts:", *la("t1", SIO_TX), "puts_loop:", "lbu t0, 0(a0)", "beq t0, zero, puts_end", "nop", "sb t0, 0(t1)",
    "beq zero, zero, puts_loop", "addiu a0, a0, 1", "puts_end:", "jr ra", "nop",
    "hexdump:", *la("t1", SIO_TX), "hex_line:", "blez a1, hex_end", "nop",
    *[x for c in b"T21 " for x in (f"addiu t0, zero, {c}", "sb t0, 0(t1)")], "addiu t2, zero, 32",
    "hex_byte:", "lbu t0, 0(a0)", "srl t4, t0, 4", "addu t4, t4, t3", "lbu t4, 0(t4)", "sb t4, 0(t1)",
    "andi t4, t0, 15", "addu t4, t4, t3", "lbu t4, 0(t4)", "sb t4, 0(t1)", "addiu a0, a0, 1", "addiu t2, t2, -1",
    "bgtz t2, hex_byte", "nop", "addiu t0, zero, 10", "sb t0, 0(t1)", "addiu a1, a1, -32",
    "beq zero, zero, hex_line", "nop", "hex_end:", "jr ra", "nop",
]


def eligible(case):
    names = {census.decode(w)[0] for w in assemble(case["asm"], CODE_BASE)}
    expect, init = case["expect"], case.get("init", {})
    return not (names & NOT_RELOCATABLE or "pc_trace" in expect or "error" in expect
                or UNOBSERVED & (set(init) | set(expect)))


def windows(case):
    """256-byte blocks holding the case's init and expected memory."""
    blocks = set()
    for mem in (case.get("init", {}).get("mem", {}), case["expect"].get("mem", {})):
        for addr, data in mem.items():
            start = int(addr, 16)
            blocks |= set(range(start // WINDOW * WINDOW, start + len(bytes.fromhex(data)), WINDOW))
    return sorted(blocks)


def state_block(init):
    cpu = Cpu(init)
    block = bytearray(BLOCK)
    for i, value in enumerate(cpu.gpr):
        block[GPR_AT + 16 * i:GPR_AT + 16 * i + 16] = value.to_bytes(16, "little")
    block[HI_AT:HI_AT + 16], block[LO_AT:LO_AT + 16] = cpu.hi.to_bytes(16, "little"), cpu.lo.to_bytes(16, "little")
    for i, value in enumerate(cpu.f):
        block[F_AT + 4 * i:F_AT + 4 * i + 4] = value.to_bytes(4, "little")
    block[FCR31_AT:FCR31_AT + 4] = (int(init.get("fcr31", "0"), 16) & M32).to_bytes(4, "little")
    for i, value in enumerate(cpu.vf):
        block[VF_AT + 16 * i:VF_AT + 16 * i + 16] = value.to_bytes(16, "little")
    for i, value in enumerate(cpu.vi):
        block[VI_AT + 4 * i:VI_AT + 4 * i + 4] = value.to_bytes(4, "little")
    block[Q_AT:Q_AT + 4] = cpu.q.to_bytes(4, "little")
    return bytes(block), cpu.mem


def load_state(block):
    """Code that loads every register from block (k0 = base; at is the scratch register, loaded last)."""
    lines = la("k0", block)
    for reg, at in (("hi", HI_AT), ("lo", LO_AT)):
        lines += [f"ld at, {at}(k0)", f"mt{reg} at", f"ld at, {at + 8}(k0)", f"mt{reg}1 at"]
    lines += [f"lw at, {FCR31_AT}(k0)", "ctc1 at, fcr31"]
    lines += [f"lwc1 f{i}, {F_AT + 4 * i}(k0)" for i in range(32)]
    lines += [f"lqc2 vf{i}, {VF_AT + 16 * i}(k0)" for i in range(1, 32)]
    lines += [x for i in range(1, 16) for x in (f"lw at, {VI_AT + 4 * i}(k0)", f"ctc2 at, vi{i}")]
    lines += [f"lw at, {Q_AT}(k0)", "ctc2 at, vi22"]
    lines += [f"lq {r}, {GPR_AT + 16 * i}(k0)" for i, r in enumerate(GPR) if r not in ("zero", "k0", "k1", "at")]
    return lines + [f"lq at, {GPR_AT + 16}(k0)"]


def store_state(prog, dump):
    """Code that stores every register to dump (same layout as the start state)."""
    lines = la("k0", dump) + [f"sq {r}, {GPR_AT + 16 * i}(k0)" for i, r in enumerate(GPR) if r not in ("k0", "k1")]
    for reg, at in (("hi", HI_AT), ("lo", LO_AT)):
        lines += [f"mf{reg} at", f"sd at, {at}(k0)", f"mf{reg}1 at", f"sd at, {at + 8}(k0)"]
    lines += [f"swc1 f{i}, {F_AT + 4 * i}(k0)" for i in range(32)]
    prog.code(lines)
    prog.words.append(cfc1("at"))
    lines = [f"sw at, {FCR31_AT}(k0)"] + [f"sqc2 vf{i}, {VF_AT + 16 * i}(k0)" for i in range(32)]
    lines += [x for i in range(16) for x in (f"cfc2 at, vi{i}", f"sw at, {VI_AT + 4 * i}(k0)")]
    prog.code(lines + ["cfc2 at, vi22", f"sw at, {Q_AT}(k0)"])


def call(prog, routine, a0, a1=None):
    prog.code(la("a0", a0) + ([f"addiu a1, zero, {a1}"] if a1 is not None else []) + [f"jal {routine}", "nop"])


def build(cases):
    """The test ELF: a status line, then every case in turn."""
    prog = Program()
    prog.code(["j 0x00100008", "nop"])   # over the routines
    puts = prog.pc
    hexdump = puts + 4 * sum(not line.endswith(":") for line in ROUTINES[:ROUTINES.index("hexdump:")])
    prog.code(ROUTINES)
    prog.words[0] = assemble([f"j {prog.pc}"], CODE_BASE)[0]
    hexdigits = prog.put(b"0123456789abcdef")
    dump = prog.put(bytes(BLOCK))
    # Interrupts off (IE and EIE cleared): the kernel's handlers clobber k0/k1, which the dump code uses.
    prog.code(["mfc0 t0, Status", "lui t2, 1", "ori t2, t2, 1", "nor t2, t2, zero", "and t0, t0, t2",
               "mtc0 t0, Status", "sync", "mfc0 t0, Status"] + la("t1", dump) + ["sw t0, 0(t1)"])
    call(prog, puts, prog.put(b"T21 STATUS\n\0"))
    prog.code(la("t3", hexdigits))
    call(prog, hexdump, dump, 32)
    for i, case in enumerate(cases):
        call(prog, puts, prog.put(f"T21 CASE {i}\n\0".encode()))
        block, mem = state_block(case.get("init", {}))
        for w in windows(case):
            stage = prog.put(bytes(mem.get(w + k, 0) for k in range(WINDOW)))
            prog.code(la("k0", stage) + la("k1", w) + [x for k in range(0, WINDOW, 16)
                                                       for x in (f"lq at, {k}(k0)", f"sq at, {k}(k1)")])
        prog.code(load_state(prog.put(block)))
        prog.code(case["asm"])
        store_state(prog, dump)
        prog.code(la("t3", hexdigits))
        call(prog, hexdump, dump, BLOCK)
        for w in windows(case):
            call(prog, hexdump, w, WINDOW)
    call(prog, puts, prog.put(b"T21 END\n\0"))
    prog.code(["loop:", "beq zero, zero, loop", "nop"])
    if prog.pc > 0x001fff00:
        raise ValueError("program overlaps the vectors' memory")
    return elf(prog.words, {f"0x{DATA:08x}": prog.data.hex()})


def write_config(user_dir, mode, folder):
    """PCSX2.ini for one mode: the user's settings plus logging, the mode's CPU settings and the user's BIOS folder."""
    ini = configparser.RawConfigParser(strict=False)
    ini.optionxform = str
    ini.read(user_dir / "inis" / "PCSX2.ini", encoding="utf-8")
    changes = {"Logging": {"EnableFileLogging": "true", "EnableEEConsole": "true"},
               "UI": {"ConfirmShutdown": "false"},
               "Folders": {"Bios": str(user_dir / ini.get("Folders", "Bios", fallback="bios"))}}
    for section, values in [*changes.items(), *SETTINGS.items(), *MODES[mode].items()]:
        if not ini.has_section(section):
            ini.add_section(section)
        for key, value in values.items():
            ini.set(section, key, value)
    (folder / "PCSX2" / "inis").mkdir(parents=True, exist_ok=True)   # -datapath X uses X/PCSX2
    with open(folder / "PCSX2" / "inis" / "PCSX2.ini", "w", encoding="utf-8") as f:
        ini.write(f, space_around_delimiters=True)


def run_pcsx2(exe, folder, elf_path, timeout):
    """EE console lines of one PCSX2 run; stops PCSX2 at 'T21 END' or when the log stops growing (a case hung)."""
    log = folder / "emulog.txt"
    log.unlink(missing_ok=True)
    proc = subprocess.Popen([exe, "-datapath", folder, "-nogui", "-nofullscreen", "-fastboot",
                             "-logfile", log, "-elf", elf_path])
    deadline, size, still = time.time() + timeout, -1, 0
    try:
        while time.time() < deadline and proc.poll() is None:
            time.sleep(1)
            text = log.read_text(errors="replace") if log.exists() else ""
            if "T21 END" in text:
                break
            still = still + 1 if "T21 STATUS" in text and len(text) == size else 0
            if still >= HANG_SECONDS:
                break
            size = len(text)
    finally:
        proc.kill()
        proc.wait()
    return log.read_text(errors="replace").splitlines() if log.exists() else []


def parse(lines):
    """{case index or 'status': dumped bytes}."""
    out, current = {}, None
    for line in lines:
        m = re.search(r"T21 (STATUS|CASE \d+|END|[0-9a-f]{64})\s*$", line)
        if not m:
            continue
        token = m.group(1)
        if token == "STATUS":
            current = "status"
        elif token.startswith("CASE"):
            current = int(token[5:])
            out[current] = bytearray()
        elif token == "END":
            current = None
        elif current is not None:
            out.setdefault(current, bytearray()).extend(bytes.fromhex(token))
    return out


def run_mode(args, mode, cases):
    """({case index: dump}, [indices of cases that never returned], Status). A run resumes after a hung case."""
    folder = OUT / mode
    write_config(args.user_dir, mode, folder)
    dumps, hung, status, start = {}, [], b"", 0
    while start < len(cases):
        (folder / "oracle.elf").write_bytes(build(cases[start:]))
        out = parse(run_pcsx2(args.pcsx2, folder, folder / "oracle.elf", args.timeout))
        run_status = out.pop("status", b"")
        status = status or run_status
        done = sorted(k for k, d in out.items() if len(d) == BLOCK + WINDOW * len(windows(cases[start + k])))
        dumps.update({start + k: out[k] for k in done})
        started = max(out, default=-1)
        if started < 0 or started in done and started + start + 1 < len(cases):
            raise RuntimeError(f"{mode}: PCSX2 run gave no usable output (see {folder / 'emulog.txt'})")
        if started not in done:
            hung.append(start + started)
        start += started + 1
    return dumps, hung, status


def end_state(case, data):
    """(registers, memory) from a case's dump; unobserved registers are left out."""
    def word(at, size):
        return int.from_bytes(data[at:at + size], "little")
    regs = {name: word(GPR_AT + 16 * i, 16) for i, name in enumerate(GPR)}
    regs.update(hi=word(HI_AT, 16), lo=word(LO_AT, 16), fcr31=word(FCR31_AT, 4) & 1 << 23, q=word(Q_AT, 4))
    regs.update({f"f{i}": word(F_AT + 4 * i, 4) for i in range(32)})
    regs.update({f"vf{i}": word(VF_AT + 16 * i, 16) for i in range(32)})
    regs.update({f"vi{i}": word(VI_AT + 4 * i, 4) & 0xffff for i in range(16)})
    mem = {}
    for k, w in enumerate(windows(case)):
        for j, b in enumerate(data[BLOCK + WINDOW * k:BLOCK + WINDOW * (k + 1)]):
            if b:
                mem[w + j] = b
    return regs, mem


def compare(case, data):
    want_regs, want_mem = expected(case)
    got_regs, got_mem = end_state(case, data)
    for name in UNOBSERVED:
        got_regs[name] = want_regs[name]
    return diff_states(want_regs, want_mem, got_regs, got_mem)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pcsx2", type=Path, default=Path(r"C:\Program Files\PCSX2\pcsx2-qt.exe"))
    ap.add_argument("--user-dir", type=Path, default=Path.home() / "Documents" / "PCSX2",
                    help="PCSX2 user folder (inis/PCSX2.ini, BIOS); only read")
    ap.add_argument("--mode", nargs="+", choices=MODES, default=list(MODES))
    ap.add_argument("--timeout", type=int, default=120, help="seconds per PCSX2 run")
    args = ap.parse_args()

    vectors = [{**case, "file": file} for file, case in load_vectors()]
    cases = [c for c in vectors if eligible(c)] + [next(c for c in vectors if c["name"] == "break ends the case")]
    unverified = sum("unverified" in c for c in cases)
    print(f"{len(cases) - 1} of {len(vectors)} vectors eligible ({unverified} marked unverified), plus break")
    for mode in args.mode:
        dumps, hung, status = run_mode(args, mode, cases)
        print(f"\n== {mode}: Status 0x{int.from_bytes(status[:4], 'little'):08x}")
        failed = 0
        for i, case in enumerate(cases):
            if i in hung:
                print(f"NO RETURN {case['file']}: {case['name']}\n  asm: {case['asm']}")
            elif case is cases[-1]:
                print(f"RETURNED {case['file']}: {case['name']}: v0 = 0x{int.from_bytes(dumps[i][32:40], 'little'):x}")
            elif diffs := compare(case, dumps[i]):
                failed += 1
                note = " [unverified]" if "unverified" in case else ""
                print(f"DIFF {case['file']}: {case['name']}{note}\n  asm: {case['asm']}\n  " + "\n  ".join(diffs))
        n = len(cases) - 1
        print(f"{mode}: {n - failed - len(set(hung) - {n})}/{n} match, {failed} differ, "
              f"{len(set(hung) - {n})} did not return; break {'did not return' if n in hung else 'returned'}")


if __name__ == "__main__":
    main()
