"""Analyse a game's main ELF with Ghidra (headless) and export plain files.

Input: work/<serial>/disc/<disc.elf from game.json> (run extract/ first).
Writes the Ghidra project to work/<serial>/ghidra/ and the export to
work/<serial>/analysis/ (format: docs/analysis-plan.md). An existing project
is reused (names + export only); delete work/<serial>/ghidra/ to re-analyse.

Usage:
  python analyze.py <SERIAL>
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent
TOOLS_DIR = REPO.parent / "tools" / "bin"
GAMES_DIR = REPO.parent / "local" / "games"
WORK_DIR = REPO.parent / "work"

# From ghidra-emotionengine-reloaded's .ldefs (v2.1.38).
LANGUAGE = "r5900:LE:32:default"
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_:]*$")
LOG_LINE_RE = re.compile(r"^(WARN|ERROR)\s+(.*)$")


def load_game_config(serial):
    return json.loads((GAMES_DIR / serial / "game.json").read_text(encoding="utf-8"))


def parse_names(config):
    """game.json analysis.names {"0x00123456": "name"} -> sorted [(0x123456, "name")]."""
    names = []
    for addr, name in config.get("analysis", {}).get("names", {}).items():
        if not NAME_RE.match(name):
            raise ValueError(f"invalid name {name!r} at {addr}")
        names.append((int(addr, 16), name))
    return sorted(names)


def find_tool(pattern):
    found = sorted(TOOLS_DIR.glob(pattern))
    if not found:
        sys.exit(f"{TOOLS_DIR / pattern} not found; install it as described in docs/environment.md")
    return found[-1]


def headless_command(ghidra, project_dir, project, elf, out_dir, names_file):
    cmd = [str(ghidra / "support" / "analyzeHeadless.bat"), str(project_dir), project]
    if (project_dir / f"{project}.gpr").exists():
        cmd += ["-process", elf.name, "-noanalysis"]
    else:
        cmd += ["-import", str(elf), "-processor", LANGUAGE]
    cmd += ["-scriptPath", str(REPO), "-postScript", "Export.java", str(out_dir)]
    if names_file:
        cmd.append(str(names_file))
    return cmd


def log_warnings(log_text):
    """Counts identical WARN/ERROR lines in a headless log."""
    counts = Counter()
    for line in log_text.splitlines():
        m = LOG_LINE_RE.match(line.strip())
        if m:
            counts[f"{m.group(1)} {m.group(2).strip()}"] += 1
    return counts


def asm_mismatches(asm_text, elf_data, segments):
    """Lines of a .asm export whose bytes differ from the ELF at that address."""
    bad = []
    for line in asm_text.splitlines()[1:]:
        addr, hex_bytes = line.split()[:2]
        vaddr = int(addr, 16)
        seg = next(s for s in segments if int(s["vaddr"], 16) <= vaddr < int(s["vaddr"], 16) + s["filesz"])
        offset = seg["offset"] + vaddr - int(seg["vaddr"], 16)
        if elf_data[offset:offset + len(hex_bytes) // 2].hex() != hex_bytes:
            bad.append(line)
    return bad


def check_export(out_dir, elf_data, segments):
    """Problems found in an export: unparsable JSONL, missing function files, bytes not matching the ELF."""
    problems = []
    for name in ("functions.jsonl", "strings.jsonl", "data_xrefs.jsonl", "symbols.jsonl"):
        for i, line in enumerate((out_dir / name).read_text(encoding="utf-8").splitlines(), 1):
            try:
                json.loads(line)
            except ValueError:
                problems.append(f"{name}:{i}: not JSON")
    for line in (out_dir / "functions.jsonl").read_text(encoding="utf-8").splitlines():
        stem = json.loads(line)["addr"][2:]
        for ext in (".c", ".asm"):
            if not (out_dir / "functions" / (stem + ext)).exists():
                problems.append(f"functions/{stem}{ext}: missing")
        asm = out_dir / "functions" / (stem + ".asm")
        if asm.exists():
            problems += [f"functions/{stem}.asm: bytes differ: {b}"
                         for b in asm_mismatches(asm.read_text(encoding="utf-8"), elf_data, segments)]
    return problems


def append_run_info(summary, seconds, warnings, problems):
    lines = ["", "## Run", "", f"- Headless run time: {seconds / 60:.1f} min",
             f"- Export check problems: {len(problems)}", "", "## Analysis log warnings", ""]
    lines += [f"- {n}× {msg}" for msg, n in warnings.most_common(30)] or ["- none"]
    if len(warnings) > 30:
        lines.append(f"- ... {len(warnings) - 30} more distinct messages")
    lines += [f"- check: {p}" for p in problems[:30]]
    with summary.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="game serial, e.g. ABCD-12345")
    args = ap.parse_args()

    config = load_game_config(args.serial)
    elf = WORK_DIR / args.serial / "disc" / config["disc"]["elf"]
    elf_json = WORK_DIR / args.serial / "disc" / "elf.json"
    if not elf.exists():
        sys.exit(f"{elf} not found; run extract/extract.py first")
    ghidra = find_tool("ghidra_*_PUBLIC")
    env = dict(os.environ, JAVA_HOME=str(find_tool("jdk-21*")))

    project_dir = WORK_DIR / args.serial / "ghidra"
    out_dir = WORK_DIR / args.serial / "analysis"
    project_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out_dir, ignore_errors=True)

    names = parse_names(config)
    names_file = None
    if names:
        names_file = project_dir / "names.tsv"
        names_file.write_text("".join(f"0x{a:08x}\t{n}\n" for a, n in names), encoding="utf-8")

    log = project_dir / "headless.log"
    print(f"Running Ghidra headless on {elf.name} (log: {log}) ...")
    start = time.monotonic()
    with log.open("w", encoding="utf-8") as f:
        subprocess.run(headless_command(ghidra, project_dir, args.serial, elf, out_dir, names_file),
                       env=env, stdout=f, stderr=subprocess.STDOUT, check=True)
    seconds = time.monotonic() - start

    summary = out_dir / "summary.md"
    if not summary.exists():
        sys.exit(f"Export did not finish; see {log}")
    segments = json.loads(elf_json.read_text(encoding="utf-8"))["program_headers"]
    problems = check_export(out_dir, elf.read_bytes(), segments)
    append_run_info(summary, seconds, log_warnings(log.read_text(encoding="utf-8", errors="replace")), problems)

    print(summary.read_text(encoding="utf-8").split("## Segments")[0].strip())
    print(f"  run time {seconds / 60:.1f} min, export check problems: {len(problems)}")
    print(f"  -> {out_dir}")
    if problems:
        sys.exit(f"Export check failed; see {summary}")


if __name__ == "__main__":
    main()
