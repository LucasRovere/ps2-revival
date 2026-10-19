"""Boot a disc in PCSX2 with its own data folder and keep a timestamped EE/IOP console log.

Usage:
  python pcsx2_log.py <iso> <out dir> <seconds> [--pcsx2 <pcsx2-qt.exe>] [--user <PCSX2 user folder>]

The owner's PCSX2.ini is only read: a copy with file logging, EE and IOP
console, timestamps on and texture dumping/replacement off is written to
<out dir>/PCSX2/inis/, and PCSX2 runs with -datapath <out dir> (its own
memory cards, no per-game settings). The BIOS folder points at the owner's.
Output: <out dir>/emulog.txt (PCSX2's log) and timed.txt (each line with
the seconds since start). PCSX2 is killed after <seconds>.
"""

import argparse
import configparser
import subprocess
import time
from pathlib import Path

LOGGING = {"EnableFileLogging": "true", "EnableEEConsole": "true", "EnableIOPConsole": "true", "EnableTimestamps": "true"}


def write_ini(user, out):
    ini = configparser.RawConfigParser(strict=False)
    ini.optionxform = str
    ini.read(user / "inis" / "PCSX2.ini", encoding="utf-8")
    changes = {"Logging": LOGGING, "UI": {"ConfirmShutdown": "false"},
               "Folders": {"Bios": str(user / ini.get("Folders", "Bios", fallback="bios"))},
               "EmuCore/GS": {"DumpReplaceableTextures": "false", "LoadTextureReplacements": "false"}}
    for section, values in changes.items():
        if not ini.has_section(section):
            ini.add_section(section)
        for k, v in values.items():
            ini.set(section, k, v)
    (out / "PCSX2" / "inis").mkdir(parents=True, exist_ok=True)
    with open(out / "PCSX2" / "inis" / "PCSX2.ini", "w", encoding="utf-8") as f:
        ini.write(f, space_around_delimiters=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("iso")
    ap.add_argument("out")
    ap.add_argument("seconds", type=float)
    ap.add_argument("--pcsx2", default=r"C:\Program Files\PCSX2\pcsx2-qt.exe")
    ap.add_argument("--user", default=str(Path.home() / "Documents" / "PCSX2"))
    args = ap.parse_args()

    out = Path(args.out).resolve()
    write_ini(Path(args.user), out)
    log = out / "emulog.txt"
    log.unlink(missing_ok=True)
    start = time.time()
    proc = subprocess.Popen([args.pcsx2, "-datapath", str(out), "-nogui", "-nofullscreen", "-fastboot",
                             "-logfile", str(log), "--", str(Path(args.iso).resolve())])
    seen = 0
    with open(out / "timed.txt", "w", encoding="utf-8") as timed:
        try:
            while time.time() - start < args.seconds and proc.poll() is None:
                time.sleep(0.1)
                if not log.exists():
                    continue
                lines = log.read_text(errors="replace").splitlines()
                for line in lines[seen:]:
                    timed.write(f"{time.time() - start:8.2f} {line}\n")
                seen = len(lines)
                timed.flush()
        finally:
            proc.kill()
            proc.wait()
    print(f"{seen} log lines -> {out / 'timed.txt'}")


if __name__ == "__main__":
    main()
