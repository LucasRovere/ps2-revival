"""Draw-list report (T45): what a frame's VIF1 DMA list costs, per kind of chain.

Reads the `[draw]` lines of a headless run with PS2_DRAW_PROFILE=<from>,<count>
and a PS2_DUMP RAM dump of the same run. Each DMA `call` target's chain is
read from the dump and fingerprinted by its VIF commands (unpack formats and
VU1 addresses, MSCAL/MSCNT, DIRECT, MPG); targets with the same fingerprint
form one kind. Per kind: targets, calls, VIF1 ms (incl. the VU1 and GS work
it starts), VU1 ms, chain handler ms (VU1 starts a chain handler did itself,
T46), GS front-end ms (path 1, path 2), share of the frame
(from a `[time]` line of the same frames, PS2_TIME) or of the VIF1 total.
--match names the chains found byte for byte in the files of a folder (e.g.
a game's unpacked mesh files).

Usage:
  python recomp/drawlist.py <stderr log> <ram dump> [--match <dir>] [--kinds N]
"""

import argparse
import collections
import re
import struct
from pathlib import Path

RAM_SIZE = 32 << 20
PREFIX = 16  # chain bytes indexed for --match: the first DMA tag and its VIF words


def parse_log(text):
    m = re.search(r"\[draw\] frames (\d+)-(\d+) root chains ([\d.]+)/frame channel 2 ([\d.]+) ms", text)
    if not m:
        raise SystemExit("no [draw] summary in the log: run with PS2_DRAW_PROFILE=<from>,<count> past from+count")
    first, last = int(m.group(1)), int(m.group(2))
    t = re.search(rf"\[time\] frames {first}-{last}: ([\d.]+) ms per frame", text)
    targets = {int(a, 16): (float(c), float(ms), float(qw))
               for a, c, ms, qw in re.findall(r"\[draw\] target ([0-9A-F]+) calls ([\d.]+) ms ([\d.]+) qw ([\d.]+)", text)}
    gif = collections.defaultdict(float)
    for a, path, ms in re.findall(r"\[draw\] gif ([0-9A-F]+) path (\d) kicks [\d.]+ ms ([\d.]+)", text):
        gif[int(a, 16), int(path)] += float(ms)
    vu, handler = {}, {}
    for what, a, entry, runs, ms in re.findall(r"\[draw\] (vu|handler) ([0-9A-F]+) entry ([0-9A-F]+) runs ([\d.]+) ms ([\d.]+)", text):
        (vu if what == "vu" else handler)[int(a, 16), entry] = (float(runs), float(ms))
    return {"frames": (first, last), "frame_ms": float(t.group(1)) if t else None, "roots": float(m.group(3)),
            "channel2_ms": float(m.group(4)), "targets": targets, "gif": gif, "vu": vu,
            "handler": handler}


def chain_at(ram, address):
    """(chain bytes from address through its `ret` tag, or None when it is not a cnt/ref...ret chain; its VIF stream)."""
    p, vif = address, bytearray()
    while p + 16 <= len(ram):
        tag = struct.unpack_from("<Q", ram, p)[0]
        qwc, tid = tag & 0xFFFF, (tag >> 28) & 7
        vif += ram[p + 8:p + 16]
        if tid in (1, 6):  # cnt, ret: data follows the tag
            vif += ram[p + 16:p + 16 + 16 * qwc]
            p += 16 + 16 * qwc
            if tid == 6:
                return bytes(ram[address:p]), bytes(vif)
        elif tid == 3:  # ref: data elsewhere
            at = (tag >> 32) & 0x7FFFFFF0
            vif += ram[at:at + 16 * qwc]
            p += 16
        else:
            break
    return None, bytes(vif)


def unpack_name(cmd):
    vn, vl = (cmd >> 2) & 3, cmd & 3
    return f"V{vn + 1}-{(32, 16, 8, 5)[vl]}"


def vif_commands(vif):
    """The VIF commands of a stream, payloads skipped: 'V4-32@010' (unpack format @ VU address), 'MSCAL0000', ..."""
    out, p, cl, wl = [], 0, 1, 1
    while p + 4 <= len(vif):
        word = struct.unpack_from("<I", vif, p)[0]
        cmd, num, imm = (word >> 24) & 0x7F, (word >> 16) & 0xFF, word & 0xFFFF
        p += 4
        if cmd == 0x01:
            cl, wl = imm & 0xFF, imm >> 8
        elif cmd in (0x14, 0x15):
            out.append(f"MSCAL{imm * 8:04x}")
        elif cmd == 0x17:
            out.append("MSCNT")
        elif cmd in (0x50, 0x51):
            out.append("DIRECT")
            p += 16 * (imm or 0x10000)
        elif cmd == 0x4A:
            out.append("MPG")
            p += 8 * (num or 256)
        elif cmd == 0x20:
            p += 4
        elif cmd in (0x30, 0x31):
            p += 16
        elif cmd >= 0x60:
            n = num or 256
            data = (n // wl) * cl + min(n % wl, cl) if wl > cl else n
            vn, vl = (cmd >> 2) & 3, cmd & 3
            bits = 16 if (vn, vl) == (3, 3) else (vn + 1) * (32 >> vl)
            out.append(f"{unpack_name(cmd)}@{imm & 0x3FF:03x}")
            p += (data * bits + 31) // 32 * 4
    return out


def fingerprint(commands, limit=10):
    seen = []
    for c in commands:
        if c not in seen:
            seen.append(c)
    return " ".join(seen[:limit])


def match_chains(chains, folder):
    """{target: [file, ...]} for the chains whose bytes appear in a file under folder."""
    by_prefix = collections.defaultdict(list)
    for target, chain in chains.items():
        by_prefix[chain[:PREFIX]].append((target, chain))
    found = collections.defaultdict(list)
    for f in sorted(Path(folder).rglob("*")):
        if not f.is_file():
            continue
        data = f.read_bytes()
        for prefix, group in by_prefix.items():
            at = data.find(prefix)
            while at >= 0:
                for target, chain in group:
                    if data.startswith(chain, at):
                        found[target].append(f.relative_to(folder).as_posix())
                at = data.find(prefix, at + 1)
    return {t: sorted(set(files)) for t, files in found.items()}


def classify(profile, ram):
    """{kind: summary} and {target: (kind, chain bytes or None)}."""
    kinds = collections.defaultdict(lambda: {"targets": 0, "calls": 0.0, "ms": 0.0, "vu": 0.0, "hdl": 0.0, "gs1": 0.0, "gs2": 0.0,
                                             "entries": collections.Counter()})
    seen = {}
    for target, (calls, ms, _) in profile["targets"].items():
        chain, kind = None, "root list (per-frame packets)"
        if target:
            chain, vif = chain_at(ram, target)
            kind = fingerprint(vif_commands(vif)) or "(no VIF commands)"
        seen[target] = (kind, chain)
        k = kinds[kind]
        k["targets"] += 1
        k["calls"] += calls
        k["ms"] += ms
        k["gs1"] += profile["gif"].get((target, 1), 0.0)
        k["gs2"] += profile["gif"].get((target, 2), 0.0)
    for (target, entry), (_, ms) in profile["vu"].items():
        k = kinds[seen[target][0] if target in seen else "root list (per-frame packets)"]
        k["vu"] += ms
        k["entries"][entry] += ms
    for (target, _), (_, ms) in profile["handler"].items():
        kinds[seen[target][0] if target in seen else "root list (per-frame packets)"]["hdl"] += ms
    return kinds, seen


def report(profile, ram, match=None, top=20):
    lines = []
    kinds, seen = classify(profile, ram)
    vif_total = sum(ms for _, ms, _ in profile["targets"].values())
    vu_total = sum(ms for _, ms in profile["vu"].values())
    hdl_total = sum(ms for _, ms in profile["handler"].values())
    gs = {p: sum(ms for (_, path), ms in profile["gif"].items() if path == p) for p in (1, 2)}
    frame_ms = profile["frame_ms"]
    base, base_name = (frame_ms, "frame") if frame_ms else (vif_total, "VIF1")
    first, last = profile["frames"]
    lines.append(f"frames {first}-{last}: " + (f"{frame_ms:.2f} ms/frame; " if frame_ms else "")
                 + f"VIF1 {vif_total:.2f} ms, VU1 {vu_total:.2f} ms, chain handler {hdl_total:.2f} ms, GS front end path 1 {gs[1]:.2f} ms, path 2 {gs[2]:.2f} ms, "
                 + f"channel 2 {profile['channel2_ms']:.2f} ms per frame; {profile['roots']:.2f} root chains per frame")
    lines.append(f"{'#':>3} {'targets':>7} {'calls':>8} {'VIF1 ms':>8} {'VU1 ms':>7} {'Hdl ms':>7} {'GS p1':>6} {'GS p2':>6} {'% ' + base_name:>8}  kind (VU1 ms by entry)")
    ranked = sorted(kinds, key=lambda kind: -kinds[kind]["ms"])
    for n, kind in enumerate(ranked[:top], 1):
        k = kinds[kind]
        entries = ", ".join(f"{e} {ms:.2f}" for e, ms in k["entries"].most_common(3))
        lines.append(f"{n:3d} {k['targets']:7d} {k['calls']:8.1f} {k['ms']:8.3f} {k['vu']:7.3f} {k['hdl']:7.3f} {k['gs1']:6.3f} {k['gs2']:6.3f} "
                     f"{100 * k['ms'] / base:7.1f}%  {kind}" + (f" ({entries})" if entries else ""))
    if len(kinds) > top:
        rest = sorted(kinds.values(), key=lambda k: -k["ms"])[top:]
        lines.append(f"{'':3} {sum(k['targets'] for k in rest):7d} {sum(k['calls'] for k in rest):8.1f} {sum(k['ms'] for k in rest):8.3f}"
                     f"  ... {len(rest)} more kinds")
    entries = collections.defaultdict(lambda: [0.0, 0.0])
    for (_, entry), (runs, ms) in profile["vu"].items():
        entries[entry][0] += runs
        entries[entry][1] += ms
    lines.append("VU1 entries: " + ", ".join(f"{e} {runs:.0f} runs {ms:.2f} ms" for e, (runs, ms) in
                                             sorted(entries.items(), key=lambda kv: -kv[1][1])[:8]))
    if match:
        chains = {t: chain for t, (_, chain) in seen.items() if chain}
        found = match_chains(chains, match)
        lines.append(f"matched in {match}: {len(found)} of {len(chains)} chains")
        for target in sorted(found, key=lambda t: -profile["targets"][t][1]):
            calls, ms, _ = profile["targets"][target]
            files = found[target]
            more = f" (+{len(files) - 1} more)" if len(files) > 1 else ""
            lines.append(f"  {target:08X} calls {calls:6.2f} VIF1 {ms:6.3f} ms  kind {ranked.index(seen[target][0]) + 1:<3} {files[0]}{more}")
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", type=Path, help="stderr of the PS2_DRAW_PROFILE run")
    ap.add_argument("ram", type=Path, help="PS2_DUMP file of the same run")
    ap.add_argument("--match", type=Path, help="folder whose files are searched for the chains' bytes")
    ap.add_argument("--kinds", type=int, default=20, help="kinds listed (default 20)")
    args = ap.parse_args()
    profile = parse_log(args.log.read_text(errors="replace"))
    ram = args.ram.read_bytes()[:RAM_SIZE]
    print("\n".join(report(profile, ram, args.match, args.kinds)))


if __name__ == "__main__":
    main()
