"""Find EE kernel syscall wrappers in an analysis export and propose names.

Reads work/<serial>/analysis/functions/*.asm (run analyze.py first).
A wrapper is a function that only loads the syscall number into v1 and
traps: `li v1,<n>; syscall; jr ra; nop`. Other functions containing a
syscall are listed as inline sites, with the number they use.

Usage:
  python syscalls.py <SERIAL>
"""

import argparse
import json
import re
import sys
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent.parent / "work"

# EE kernel syscall numbers. Written from the public PS2SDK header
# ee/kernel/include/syscallnr.h (checked Oct 2026) and cross-checked against
# the syscall labels in ghidra-emotionengine-reloaded's pattern file.
# Negative numbers are the interrupt-context variants. They are not always
# the negated number of the normal call (WakeupThread is 0x33, iWakeupThread -0x34).
SYSCALLS = {
    0x01: "ResetEE", 0x02: "SetGsCrt", 0x04: "Exit", 0x05: "ResumeIntrDispatch",
    0x06: "_LoadExecPS2", 0x07: "_ExecPS2", 0x08: "ResumeT3IntrDispatch",
    0x0a: "AddSbusIntcHandler", 0x0b: "RemoveSbusIntcHandler", 0x0c: "Interrupt2Iop",
    0x0d: "SetVTLBRefillHandler", 0x0e: "SetVCommonHandler", 0x0f: "SetVInterruptHandler",
    0x10: "AddIntcHandler", 0x11: "RemoveIntcHandler", 0x12: "AddDmacHandler",
    0x13: "RemoveDmacHandler", 0x14: "_EnableIntc", 0x15: "_DisableIntc",
    0x16: "_EnableDmac", 0x17: "_DisableDmac", 0x18: "_SetAlarm", 0x19: "_ReleaseAlarm",
    0x20: "CreateThread", 0x21: "DeleteThread", 0x22: "StartThread", 0x23: "ExitThread",
    0x24: "ExitDeleteThread", 0x25: "TerminateThread", 0x27: "DisableDispatchThread",
    0x28: "EnableDispatchThread", 0x29: "ChangeThreadPriority", 0x2b: "RotateThreadReadyQueue",
    0x2d: "ReleaseWaitThread", 0x2f: "GetThreadId", 0x30: "ReferThreadStatus",
    0x32: "SleepThread", 0x33: "WakeupThread", 0x35: "CancelWakeupThread",
    0x37: "SuspendThread", 0x39: "ResumeThread", 0x3b: "JoinThread",
    0x3c: "SetupThread", 0x3d: "SetupHeap", 0x3e: "EndOfHeap",
    0x40: "CreateSema", 0x41: "DeleteSema", 0x42: "SignalSema", 0x44: "WaitSema",
    0x45: "PollSema", 0x47: "ReferSemaStatus", 0x4a: "SetOsdConfigParam",
    0x4b: "GetOsdConfigParam", 0x4c: "GetGsHParam", 0x4d: "GetGsVParam",
    0x4e: "SetGsHParam", 0x4f: "SetGsVParam", 0x50: "CreateEventFlag",
    0x51: "DeleteEventFlag", 0x52: "SetEventFlag", 0x54: "xlaunch", 0x55: "PutTLBEntry",
    0x56: "_SetTLBEntry", 0x57: "GetTLBEntry", 0x58: "ProbeTLBEntry",
    0x59: "ExpandScratchPad", 0x5a: "Copy", 0x5b: "GetEntryAddress",
    0x5c: "EnableIntcHandler", 0x5d: "DisableIntcHandler", 0x5e: "EnableDmacHandler",
    0x5f: "DisableDmacHandler", 0x60: "KSeg0", 0x61: "EnableCache", 0x62: "DisableCache",
    0x63: "GetCop0", 0x64: "FlushCache", 0x66: "CpuConfig", 0x6b: "sceSifStopDma",
    0x6c: "SetCPUTimerHandler", 0x6d: "SetCPUTimer", 0x6e: "SetOsdConfigParam2",
    0x6f: "GetOsdConfigParam2", 0x70: "GsGetIMR", 0x71: "GsPutIMR", 0x72: "SetPgifHandler",
    0x73: "SetVSyncFlag", 0x74: "SetSyscall", 0x75: "_print", 0x76: "sceSifDmaStat",
    0x77: "sceSifSetDma", 0x78: "sceSifSetDChain", 0x79: "sceSifSetReg",
    0x7a: "sceSifGetReg", 0x7b: "_ExecOSD", 0x7c: "Deci2Call", 0x7d: "PSMode",
    0x7e: "MachineType", 0x7f: "GetMemorySize", 0x80: "_GetGsDxDyOffset",
    0x82: "_InitTLB", 0x83: "FindAddress",
    -0x1a: "_iEnableIntc", -0x1b: "_iDisableIntc", -0x1c: "_iEnableDmac",
    -0x1d: "_iDisableDmac", -0x1e: "_iSetAlarm", -0x1f: "_iReleaseAlarm",
    -0x26: "iTerminateThread", -0x2a: "iChangeThreadPriority",
    -0x2c: "_iRotateThreadReadyQueue", -0x2e: "iReleaseWaitThread",
    -0x2f: "_iGetThreadId", -0x31: "iReferThreadStatus", -0x34: "_iWakeupThread",
    -0x36: "iCancelWakeupThread", -0x38: "_iSuspendThread", -0x3a: "iResumeThread",
    -0x43: "iSignalSema", -0x46: "iPollSema", -0x48: "iReferSemaStatus",
    -0x49: "iDeleteSema", -0x55: "iPutTLBEntry", -0x56: "iSetTLBEntry",
    -0x57: "iGetTLBEntry", -0x58: "iProbeTLBEntry", -0x5c: "iEnableIntcHandler",
    -0x5d: "iDisableIntcHandler", -0x5e: "iEnableDmacHandler", -0x5f: "iDisableDmacHandler",
    -0x67: "iGetCop0", -0x68: "iFlushCache", -0x6a: "iCpuConfig", -0x70: "iGsGetIMR",
    -0x71: "iGsPutIMR", -0x76: "isceSifDmaStat", -0x77: "isceSifSetDma",
    -0x78: "isceSifSetDChain", -0xfd: "iSetAlarm", -0xff: "iReleaseAlarm",
}

HEADER_RE = re.compile(r"^// (\S+) @ (0x[0-9a-f]{8})")
LI_V1_RE = re.compile(r"\bli v1,(-?0x[0-9a-f]+|-?\d+)$")


def scan_asm(asm_text):
    """(addr, current name, [syscall numbers], is_wrapper) for one .asm export, or None without a syscall."""
    lines = asm_text.splitlines()
    name, addr = HEADER_RE.match(lines[0]).groups()
    instructions = [line.split(None, 2)[2] for line in lines[1:]]
    numbers = []
    v1 = None
    for ins in instructions:
        m = LI_V1_RE.search(ins)
        if m:
            v1 = int(m.group(1), 0)
        elif ins.startswith("syscall"):
            numbers.append(v1)
    if not numbers:
        return None
    is_wrapper = len(instructions) == 4 and instructions[2] == "jr ra"
    return addr, name, numbers, is_wrapper


def proposed_names(results):
    """{addr: name} for wrappers whose number is in the table."""
    return {addr: SYSCALLS.get(numbers[0]) for addr, _, numbers, wrapper in results
            if wrapper and SYSCALLS.get(numbers[0])}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("serial", help="game serial, e.g. ABCD-12345")
    args = ap.parse_args()

    functions_dir = WORK_DIR / args.serial / "analysis" / "functions"
    if not functions_dir.exists():
        sys.exit(f"{functions_dir} not found; run analyze.py first")
    results = [r for r in (scan_asm(p.read_text(encoding="utf-8")) for p in sorted(functions_dir.glob("*.asm"))) if r]

    print(f"{len(results)} functions contain a syscall\n")
    for addr, name, numbers, wrapper in results:
        calls = ", ".join(f"{n:#x} {SYSCALLS.get(n)}" if n is not None else "unknown v1" for n in numbers)
        print(f"{addr}  {'wrapper' if wrapper else 'inline '}  {name:<24} {calls}")
    print("\nProposed analysis.names (wrappers only):")
    print(json.dumps(proposed_names(results), indent=2))


if __name__ == "__main__":
    main()
