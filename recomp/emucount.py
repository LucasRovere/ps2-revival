"""Emulation counter report (T56): what emulated PS2 hardware a run used, and how much.

Reads the files a headless run writes with PS2_EMU_COUNT=<file> (one file per
scene, e.g. one per saved state) and prints, per scene: a summary per frame
(IOP instructions, VU1 and VU0 programs, VIF commands, DMA, GIF, GS
primitives and register writes, EE hardware register accesses by block,
SPU2 key-ons, SIF RPC calls, syscalls), the details behind each line (VU1
programs by key, SIF servers and functions, IOP modules, top guest PCs of
EE register accesses mapped to functions of the analysis export), and the
GS census: every GS state used (modes only), frame and Z buffers drawn,
textures read from frame buffers drawn earlier, transfers, display buffers.

Usage:
  python recomp/emucount.py <file>[@from-to] [...] [--analysis <dir>] [--top N] [--sections]

@from-to keeps the 100-frame sections inside those frames (one scene of a long run).
"""

import argparse
import bisect
import collections
import json
from pathlib import Path

EE_BLOCKS = {0x10000000: "timers", 0x10002000: "IPU", 0x10003000: "GIF", 0x10003800: "VIF0", 0x10003C00: "VIF1",
             0x10004000: "VIF0 FIFO", 0x10005000: "VIF1 FIFO", 0x10006000: "GIF FIFO", 0x10007000: "IPU FIFO",
             0x10008000: "DMAC", 0x1000F000: "INTC", 0x1000F200: "SIF", 0x1000F500: "DMAC F500",
             0x11000000: "VU memory", 0x12000000: "GS"}
IOP_BLOCKS = {0x1F900000: "SPU2", 0x1F801600: "USB", 0x1F808200: "SIO2", 0x1F801080: "DMA", 0x1F801100: "timers",
              0x1F801070: "INTC"}
EE_DMA = ["VIF0", "VIF1", "GIF", "fromIPU", "toIPU", "SIF0", "SIF1", "SIF2", "fromSPR", "toSPR"]
IOP_DMA = {4: "SPU2 core0", 7: "SPU2 core1", 9: "SIF0", 10: "SIF1", 11: "SIO2 in", 12: "SIO2 out"}
INTC = ["GS", "SBUS", "VBON", "VBOF", "VIF0", "VIF1", "VU0", "VU1", "IPU", "TIM0", "TIM1", "TIM2", "TIM3", "SFIFO", "VU0WD"]
VIF = {0x00: "NOP", 0x01: "STCYCL", 0x02: "OFFSET", 0x03: "BASE", 0x04: "ITOP", 0x05: "STMOD", 0x06: "MSKPATH3",
       0x07: "MARK", 0x10: "FLUSHE", 0x11: "FLUSH", 0x13: "FLUSHA", 0x14: "MSCAL", 0x15: "MSCALF", 0x17: "MSCNT",
       0x20: "STMASK", 0x30: "STROW", 0x31: "STCOL", 0x4A: "MPG", 0x50: "DIRECT", 0x51: "DIRECTHL"}
GS_REGS = {0x00: "PRIM", 0x01: "RGBAQ", 0x02: "ST", 0x03: "UV", 0x04: "XYZF2", 0x05: "XYZ2", 0x06: "TEX0_1",
           0x07: "TEX0_2", 0x08: "CLAMP_1", 0x09: "CLAMP_2", 0x0A: "FOG", 0x0C: "XYZF3", 0x0D: "XYZ3", 0x14: "TEX1_1",
           0x15: "TEX1_2", 0x16: "TEX2_1", 0x17: "TEX2_2", 0x18: "XYOFFSET_1", 0x19: "XYOFFSET_2", 0x1A: "PRMODECONT",
           0x1B: "PRMODE", 0x1C: "TEXCLUT", 0x22: "SCANMSK", 0x34: "MIPTBP1_1", 0x35: "MIPTBP1_2", 0x36: "MIPTBP2_1",
           0x37: "MIPTBP2_2", 0x3B: "TEXA", 0x3D: "FOGCOL", 0x3F: "TEXFLUSH", 0x40: "SCISSOR_1", 0x41: "SCISSOR_2",
           0x42: "ALPHA_1", 0x43: "ALPHA_2", 0x44: "DIMX", 0x45: "DTHE", 0x46: "COLCLAMP", 0x47: "TEST_1",
           0x48: "TEST_2", 0x49: "PABE", 0x4A: "FBA_1", 0x4B: "FBA_2", 0x4C: "FRAME_1", 0x4D: "FRAME_2",
           0x4E: "ZBUF_1", 0x4F: "ZBUF_2", 0x50: "BITBLTBUF", 0x51: "TRXPOS", 0x52: "TRXREG", 0x53: "TRXDIR",
           0x54: "HWREG", 0x60: "SIGNAL", 0x61: "FINISH", 0x62: "LABEL"}
PRIMS = ["point", "line", "line strip", "triangle", "tri strip", "tri fan", "sprite", "prim 7"]
PSM = {0x00: "CT32", 0x01: "CT24", 0x02: "CT16", 0x0A: "CT16S", 0x13: "T8", 0x14: "T4", 0x1B: "T8H", 0x24: "T4HL",
       0x2C: "T4HH", 0x30: "Z32", 0x31: "Z24", 0x32: "Z16", 0x3A: "Z16S"}
SYSCALLS = {0x02: "SetGsCrt", 0x10: "AddIntcHandler", 0x11: "RemoveIntcHandler", 0x12: "AddDmacHandler",
            0x13: "RemoveDmacHandler", 0x14: "EnableIntc", 0x15: "DisableIntc", 0x16: "EnableDmac", 0x17: "DisableDmac",
            0x1A: "iEnableIntc", 0x1B: "iDisableIntc", 0x1C: "iEnableDmac", 0x1D: "iDisableDmac", 0x20: "CreateThread",
            0x22: "StartThread", 0x2B: "RotateThreadReadyQueue", 0x2F: "GetThreadId", 0x32: "SleepThread",
            0x33: "WakeupThread", 0x34: "iWakeupThread", 0x40: "CreateSema", 0x42: "SignalSema", 0x43: "iSignalSema",
            0x44: "WaitSema", 0x45: "PollSema", 0x46: "iPollSema", 0x64: "FlushCache", 0x68: "iFlushCache",
            0x70: "GsGetIMR", 0x71: "GsPutIMR", 0x73: "SetVSyncFlag", 0x76: "SifDmaStat", 0x77: "SifSetDma",
            0x78: "SifSetDChain", 0x79: "SifSetReg", 0x7A: "SifGetReg"}


def block_name(table, a):
    return table.get(a, f"{a:08X}")


def vif_name(op):
    if op & 0x60 == 0x60:
        return f"UNPACK V{((op >> 2) & 3) + 1}-{[32, 16, 8, 5][op & 3]}{'m' if op & 0x10 else ''}"
    return VIF.get(op, f"VIF {op:02X}")


def parse(text, lo=0, hi=None):
    """Sections inside frames lo..hi summed: {'frames': (first, last), 'c': {(kind, a, b): [n, sum, max]},
    'states': Counter, 'hle': Counter, 'modules': [(base, size, name)], 'sections': [(from, to, c of the section)]}"""
    run = {"c": collections.defaultdict(lambda: [0, 0, 0]), "states": collections.Counter(), "hle": collections.Counter(),
           "modules": [], "sections": []}
    first = last = None
    cur = None
    for line in text.splitlines():
        f = line.split()
        if not f or f[0].startswith("#"):
            continue
        if f[0] == "section":
            a, b = int(f[1]), int(f[2])
            cur = None
            if a >= lo and (hi is None or b <= hi):
                first = a if first is None else first
                last = b
                cur = collections.defaultdict(lambda: [0, 0, 0])
                run["sections"].append((a, b, cur))
        elif f[0] == "iopmodule":
            run["modules"].append((int(f[1], 16), int(f[2], 16), " ".join(f[3:])))
        elif cur is None:
            continue
        elif f[0] == "c":
            key = (f[1], int(f[2], 16), int(f[3], 16))
            n, s, m = int(f[4]), int(f[5]), int(f[6])
            for t in (run["c"][key], cur[key]):
                t[0] += n
                t[1] += s
                t[2] = max(t[2], m)
        elif f[0] == "gsstate":
            run["states"][tuple(int(x, 16) for x in f[2:])] += int(f[1])
        elif f[0] == "hle":
            run["hle"][f[1], int(f[2])] += int(f[3])
    run["frames"] = (first, last)
    return run


def kind(c, name):
    """{(a, b): [n, sum, max]} of one kind."""
    return {(a, b): v for (k, a, b), v in c.items() if k == name}


class Functions:
    def __init__(self, analysis):
        self.addrs, self.names = [], []
        if analysis:
            rows = sorted((int(r["addr"], 16), r["name"], r["size"]) for r in map(json.loads, open(Path(analysis) / "functions.jsonl")))
            self.rows = rows
            self.addrs = [r[0] for r in rows]

    def name(self, pc):
        i = bisect.bisect_right(self.addrs, pc) - 1
        if i >= 0 and pc < self.rows[i][0] + max(self.rows[i][2], 4):
            return self.rows[i][1]
        return f"{pc:08X}"


def iop_module(modules, pc):
    for base, size, name in modules:
        if base <= pc < base + size:
            return name
    return "HLE/kernel" if pc >= 0x1FC00000 or pc < 0x1000 else f"{pc:08X}"


def decode_state(s):
    prim, tex0, tex1, clamp, texa, alpha, test, fba, frame, zbuf, pabe, dthe, colclamp, scanmsk = s
    out = [PRIMS[prim & 7]] + [n for bit, n in [(3, "IIP"), (4, "TME"), (5, "FGE"), (6, "ABE"), (7, "AA1"), (8, "FST"), (9, "CTXT2"), (10, "FIX")]
                               if prim >> bit & 1]
    if prim & 0x10:
        out.append(f"tex {PSM.get(tex0 >> 20 & 0x3F, hex(tex0 >> 20 & 0x3F))} {['MODULATE', 'DECAL', 'HIGHLIGHT', 'HIGHLIGHT2'][tex0 >> 35 & 3]}"
                   f"{' TCC' if tex0 >> 34 & 1 else ''}")
        if (tex0 >> 20 & 0x3F) in (0x13, 0x14, 0x1B, 0x24, 0x2C):
            out.append(f"clut {PSM.get(tex0 >> 51 & 0xF, hex(tex0 >> 51 & 0xF))} CSM{tex0 >> 55 & 1}")
        mmin = ["nearest", "linear", "near-mip-near", "near-mip-lin", "lin-mip-near", "lin-mip-lin", "min6", "min7"][tex1 >> 6 & 7]
        out.append(f"mag {'linear' if tex1 >> 5 & 1 else 'nearest'} min {mmin}" + (f" MXL{tex1 >> 2 & 7} LCM{tex1 & 1} L{tex1 >> 19 & 3} K{tex1 >> 32 & 0xFFF}" if tex1 >> 2 & 7 else ""))
        wrap = ["REPEAT", "CLAMP", "REGION_CLAMP", "REGION_REPEAT"]
        out.append(f"wrap {wrap[clamp & 3]}/{wrap[clamp >> 2 & 3]}")
        out.append(f"TEXA {texa & 0xFF:02X}/{texa >> 32 & 0xFF:02X}{' AEM' if texa >> 15 & 1 else ''}")
    if prim & 0x40:
        cs = ["Cs", "Cd", "0", "?"]
        out.append(f"blend ({cs[alpha & 3]}-{cs[alpha >> 2 & 3]})*{['As', 'Ad', 'FIX', '?'][alpha >> 4 & 3]}+{cs[alpha >> 6 & 3]}"
                   + (f" FIX {alpha >> 32 & 0xFF}" if alpha >> 4 & 3 == 2 else ""))
    if test & 1:
        out.append(f"atest {['NEVER', 'ALWAYS', 'LESS', 'LEQUAL', 'EQUAL', 'GEQUAL', 'GREATER', 'NOTEQUAL'][test >> 1 & 7]} {test >> 4 & 0xFF}"
                   f" fail {['KEEP', 'FB_ONLY', 'ZB_ONLY', 'RGB_ONLY'][test >> 12 & 3]}")
    if test >> 14 & 1:
        out.append(f"DATE{test >> 15 & 1}")
    if test >> 16 & 1:
        out.append(f"ztest {['NEVER', 'ALWAYS', 'GEQUAL', 'GREATER'][test >> 17 & 3]} Z {PSM.get(zbuf >> 24 & 0xF | 0x30, '?')}"
                   f"{' ZMSK' if zbuf >> 32 & 1 else ''}")
    out.append(f"FB {PSM.get(frame >> 24 & 0x3F, hex(frame >> 24 & 0x3F))}" + (f" FBMSK {frame >> 32:08X}" if frame >> 32 else ""))
    out += [n for v, n in [(fba, "FBA"), (pabe, "PABE"), (dthe, "DTHE"), (not colclamp, "no COLCLAMP")] if v]
    if scanmsk:
        out.append(f"SCANMSK {scanmsk}")
    return ", ".join(out)


def buf(v):
    return f"{v & 0x3FFF:04X} {PSM.get(v >> 16 & 0x3F, hex(v >> 16 & 0x3F))}"


def report(run, fn, top, sections=False):
    first, last = run["frames"]
    frames = max(1, (last or 0) - (first or 0))
    c = run["c"]
    pf = lambda x: f"{x / frames:,.1f}"  # noqa: E731
    out = [f"frames {first}-{last} ({frames})", "", "Per frame:"]
    total = lambda name, field=0: sum(v[field] for (k, _, _), v in c.items() if k == name)  # noqa: E731
    rows = [("IOP instructions", total("iop_instr", 1)), ("IOP HLE calls", sum(run["hle"].values())),
            ("VU1 programs", total("vu1")), ("VU1 starts by a chain handler", total("vu1_hook")), ("VU0 micro programs", total("vu0")),
            ("VIF0 commands", sum(v[0] for (a, _), v in kind(c, "vif").items() if a == 0)),
            ("VIF1 commands", sum(v[0] for (a, _), v in kind(c, "vif").items() if a == 1)),
            ("GIF qwords", total("gif", 1)), ("GS primitives", total("gs_prim")), ("GS mesh path strips", total("gs_mesh")),
            ("GS register writes", total("gs_reg")), ("EE hardware register accesses", total("ee_io")),
            ("SPU2 key-ons (voices)", total("spu2_key_on", 1)), ("SIF RPC calls", total("sif_call")),
            ("syscalls", total("syscall")), ("interrupts (INTC)", total("intc"))]
    out += [f"  {name:32} {pf(v):>14}" for name, v in rows]

    def table(title, items, fmt):
        items = sorted(items, key=lambda kv: -kv[1][0])
        if not items:
            return
        out.extend(["", title])
        out.extend("  " + fmt(k, v) for k, v in items[:top])
        if len(items) > top:
            out.append(f"  ... {len(items) - top} more")

    table("VU1 programs (key, entry: runs/frame; entry +10000 = interpreted):", kind(c, "vu1").items(),
          lambda k, v: f"{k[0]:016X} @{k[1]:05X} {pf(v[0]):>10}")
    table("VU1 starts done by a chain handler (entry: starts/frame):", kind(c, "vu1_hook").items(), lambda k, v: f"@{k[0]:04X} {pf(v[0]):>10}")
    table("VU0 micro programs (entry, 0 VIF0 / 1 VCALLMS: runs/frame):", kind(c, "vu0").items(), lambda k, v: f"@{k[0]:04X} {k[1]} {pf(v[0]):>10}")
    table("VIF commands (unit command: per frame):", kind(c, "vif").items(), lambda k, v: f"VIF{k[0]} {vif_name(k[1]):16} {pf(v[0]):>12}")
    starts = kind(c, "dma_start")
    table("EE DMA (channel: starts/frame, qwords/frame; read = from the device):",
          [((a, b), v) for (a, b), v in kind(c, "dma").items()] + [((a, 9), [0, 0, 0]) for (a, _) in starts if (a, 0) not in kind(c, "dma")],
          lambda k, v: f"{EE_DMA[k[0]]:8} {'read' if k[1] == 1 else '':4} starts {pf(starts.get((k[0], 0), [0])[0]):>8} qw {pf(v[1]):>12}")
    table("GIF (path: qwords/frame; tags packed/reglist/image):", kind(c, "gif").items(),
          lambda k, v: f"path {k[0]} qw {pf(v[1]):>12} tags " + "/".join(pf(kind(c, 'gif_tag').get((k[0], f), [0])[0]) for f in range(3)))
    table("GS primitives (kind: per frame):", kind(c, "gs_prim").items(), lambda k, v: f"{PRIMS[k[0]]:12} {pf(v[0]):>12}")
    table("GS mesh path strips (PRIM: strips/frame, vertices/frame):", kind(c, "gs_mesh").items(), lambda k, v: f"{k[0]:03X} {pf(v[0]):>10} {pf(v[1]):>12}")
    table("GS register writes (per frame):", kind(c, "gs_reg").items(), lambda k, v: f"{GS_REGS.get(k[0], hex(k[0])):12} {pf(v[0]):>12}")
    table("EE hardware registers (block read/write: per frame):", kind(c, "ee_io").items(),
          lambda k, v: f"{block_name(EE_BLOCKS, k[0]):10} {'write' if k[1] else 'read':5} {pf(v[0]):>12}")
    pcs = collections.defaultdict(lambda: [0])
    for (a, b), v in kind(c, "ee_pc").items():
        pcs[block_name(EE_BLOCKS, a), "write" if b & 1 else "read", fn.name(b >> 1 & 0x7FFFFFFF), fn.name((b >> 32) - 8)][0] += v[0]
    table("EE hardware register accesses by guest code (block, read/write, function of pc, function of ra-8: per frame):",
          pcs.items(), lambda k, v: f"{k[0]:10} {k[1]:5} {k[2]:28} {k[3]:28} {pf(v[0]):>10}")
    calls = collections.defaultdict(lambda: [0])
    for (a, b), v in kind(c, "syscall").items():
        calls[SYSCALLS.get(a, f"syscall {a:02X}"), fn.name(b - 8)][0] += v[0]
    table("Syscalls (name, calling function: per frame):", calls.items(), lambda k, v: f"{k[0]:22} {k[1]:30} {pf(v[0]):>10}")
    table("Interrupts (INTC cause: per frame):", kind(c, "intc").items(), lambda k, v: f"{INTC[k[0]] if k[0] < len(INTC) else k[0]:6} {pf(v[0]):>10}")
    table("DMAC interrupts (channel: per frame):", kind(c, "dmac_irq").items(), lambda k, v: f"{EE_DMA[k[0]]:8} {pf(v[0]):>10}")
    recv = kind(c, "sif_recv")
    table("SIF RPC calls (server, function, H = served natively: calls/frame, total calls, send bytes max, receive bytes max):",
          kind(c, "sif_call").items(),
          lambda k, v: f"{k[0]:08X} fn {k[1] & 0xFFFFFFFF:4} {'H' if k[1] >> 32 else ' '} {pf(v[0]):>10} {v[0]:>9} {v[2]:>8} {recv.get(k, [0, 0, 0])[2]:>8}")
    table("SIF binds (server: total):", kind(c, "sif_bind").items(), lambda k, v: f"{k[0]:08X} {v[0]:>8}")
    table("SIF commands EE -> IOP (id: total):", kind(c, "sif_cmd").items(), lambda k, v: f"{k[0]:08X} {v[0]:>8}")
    table("SIF packets IOP -> EE (command id: per frame):", kind(c, "sif_to_ee").items(), lambda k, v: f"{k[0]:08X} {pf(v[0]):>10}")
    sifdma = collections.defaultdict(lambda: [0, 0])
    for (a, _), v in kind(c, "iop_sif_dma").items():
        t = sifdma[iop_module(run["modules"], a)]
        t[0] += v[0]
        t[1] += v[1]
    table("IOP -> EE SIF DMA (calling module: transfers/frame, bytes/frame):", sifdma.items(), lambda k, v: f"{k:16} {pf(v[0]):>10} {pf(v[1]):>12}")
    mods = collections.defaultdict(lambda: [0, 0])
    for (a, _), v in kind(c, "iop_instr").items():
        t = mods[iop_module(run["modules"], a << 10)]
        t[0] += v[1]
    table("IOP instructions (module of the slice's first pc: per frame):", mods.items(), lambda k, v: f"{k:16} {pf(v[0]):>12}")
    table("IOP HLE calls (library index: per frame):", [(k, [n]) for k, n in run["hle"].items()], lambda k, v: f"{k[0]:10} {k[1]:4} {pf(v[0]):>10}")
    table("IOP hardware registers (block read/write: per frame):", kind(c, "iop_io").items(),
          lambda k, v: f"{block_name(IOP_BLOCKS, k[0]):10} {'write' if k[1] else 'read':5} {pf(v[0]):>12}")
    table("IOP DMA (channel: starts/frame, words/frame):", kind(c, "iop_dma").items(), lambda k, v: f"{IOP_DMA.get(k[0], k[0])!s:10} {pf(v[0]):>8} {pf(v[1]):>12}")
    table("SPU2 key-ons (core: events/frame, voices/frame):", kind(c, "spu2_key_on").items(), lambda k, v: f"core {k[0]} {pf(v[0]):>8} {pf(v[1]):>8}")

    out += ["", "GS census:"]
    table("GS states (primitives/frame: modes):", [(s, [n]) for s, n in run["states"].items()], lambda k, v: f"{pf(v[0]):>10}  {decode_state(k)}")
    table("Frame buffers drawn (FBP FBW PSM | Z: primitives/frame):", kind(c, "gs_target").items(),
          lambda k, v: f"FB {k[0] & 0x1FF:03X} w{k[0] >> 16 & 0x3F:<2} {PSM.get(k[0] >> 24 & 0x3F, '?'):5} "
                       + ("no Z" if k[1] == (1 << 64) - 1 else f"Z {k[1] & 0x1FF:03X} {PSM.get(k[1] >> 24 & 0xF | 0x30, '?')}{' ZMSK' if k[1] >> 32 & 1 else ''}")
                       + f" {pf(v[0]):>10}")
    table("Textures read from frame buffers drawn earlier (TBP PSM <- frame PSM: primitives/frame):", kind(c, "gs_tex_target").items(),
          lambda k, v: f"{buf(k[0])} <- {PSM.get(k[1], '?'):5} {pf(v[0]):>10}")
    table("GS transfers (0 upload to DBP, 1 download from SBP, 2 copy SBP -> DBP: per frame):", kind(c, "gs_transfer").items(),
          lambda k, v: f"{k[0]} {buf(k[1])}" + (f" -> {buf(k[1] >> 32)}" if k[0] == 2 else "") + f" {pf(v[0]):>10}")
    table("Displayed (DISPFB1 | DISPFB2, PMODE: frames):", kind(c, "gs_display").items(),
          lambda k, v: f"FB1 {k[0] & 0x1FF:03X} w{k[0] >> 9 & 0x3F} {PSM.get(k[0] >> 15 & 0x1F, '?')} FB2 {k[0] >> 32 & 0x1FF:03X} PMODE {k[1]:04X} {v[0]:>6}")
    if sections:
        out += ["", "Per 100 frames (per frame: IOP instr, VU1, GS prims, mesh strips, EE io, SIF calls, SPU2 voices):"]
        for a, b, s in run["sections"]:
            n = max(1, b - a)
            t = lambda name, field=0: sum(v[field] for (k, _, _), v in s.items() if k == name) / n  # noqa: E731
            out.append(f"  {a:>6}-{b:<6} {t('iop_instr', 1):>10,.0f} {t('vu1'):>9,.0f} {t('gs_prim'):>9,.0f} {t('gs_mesh'):>8,.0f}"
                       f" {t('ee_io'):>8,.1f} {t('sif_call'):>6,.1f} {t('spu2_key_on', 1):>6,.1f}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--analysis", help="analysis export folder (functions.jsonl) to name guest PCs")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--sections", action="store_true", help="also a line per 100 frames")
    args = ap.parse_args()
    fn = Functions(args.analysis)
    for spec in args.files:
        f, _, frames = spec.partition("@")
        lo, _, hi = frames.partition("-")
        print(f"== {Path(f).stem} {frames}")
        print("\n".join(report(parse(Path(f).read_text(), int(lo or 0), int(hi) if hi else None), fn, args.top, args.sections)))
        print()


if __name__ == "__main__":
    main()
