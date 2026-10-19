# PS2 primer for this project

Just enough hardware/software background to follow the porting plan. Numbers
are the commonly documented figures; verify against primary sources (PS2
homebrew SDK docs, hardware references) before relying on details.

## Hardware

| Part | What it is | Why it matters for a port |
|---|---|---|
| **EE (Emotion Engine)** | Main CPU: MIPS **R5900** (~295 MHz), MIPS III-based with some MIPS IV, plus PS2-specific 128-bit multimedia instructions (MMI), 128-bit registers, a scratchpad RAM (16 KB) | Game logic lives here; this is what the recompiler translates. Not a standard MIPS32 target; generic MIPS tools often reject or mis-decode it |
| **COP1 FPU** | Single-precision float, **not IEEE-754 compliant** (no infinities/NaNs, different rounding) | Recompiled float code must emulate these rules where the game depends on them |
| **VU0 / VU1** | Vector units: SIMD float co-processors with their own micro-memory (VU0 4 KB code/4 KB data, VU1 16 KB/16 KB) | Games run small hand-written **microprograms**, mostly on VU1 for geometry (transform, lighting, skinning, clipping). These never existed as C; each must be translated or rewritten (e.g. as GPU shaders) |
| **VIF0 / VIF1** | DMA-side unpackers feeding the VUs | Data packing formats for vertices/matrices |
| **GIF** | Path from EE/VU1 to the GS | Carries drawing packets (GIF tags) |
| **GS (Graphics Synthesizer)** | Fixed-function rasteriser with **4 MB embedded VRAM** (frame buffers, Z, textures share it) | No programmable shaders; unusual blending, swizzled memory layouts, palettes (CLUT), render-to-texture tricks. Emulating it accurately is hard |
| **IOP** | I/O processor: MIPS R3000A-class (~37 MHz, 2 MB RAM), also the PS1 CPU | Runs **IRX modules** (CD/DVD, pad, memory card, sound, USB) that talk to the EE over RPC (SIF) |
| **SPU2** | Sound processor (2 MB sound RAM, ADPCM voices, effects) | Audio streaming and effects |
| RAM | 32 MB main RAM (EE) | Recompiled code addresses must map into a 32 MB guest memory array |

## Software

- **Boot:** the disc's `SYSTEM.CNF` names the main executable, e.g.
  `BOOT2 = cdrom0:\ABCD_123.45;1`. That file is an **ELF** (usually loaded
  around `0x00100000`, statically linked, no dynamic libraries).
- **Games are statically linked.** Sony's SDK libraries (graphics helpers,
  DMA, pad, memory card, sound, file I/O, C runtime) are compiled *into* the
  executable. Unlike PS4/PS5 there are no system libraries to swap at link
  time, so we must recognise these library functions inside the binary
  (signatures) and replace or reimplement them.
- **BIOS/kernel:** the EE kernel provides **syscalls** (threads, semaphores,
  interrupts/handlers, DMA setup, `ExecPS2`, etc.) used via the `syscall`
  instruction. A native runtime implements these directly (HLE), so no BIOS
  file is needed at runtime.
- **IOP side:** IRX modules are loaded from disc or BIOS. A native port
  implements their *services* (file reading, pad, memory card, audio) in the
  runtime, not the modules themselves.
- **Overlays / self-modifying code:** some games load extra code at runtime
  or patch code in memory. Static recompilation must detect and handle this
  (unknown for the pilot game).

## What this means for porting (summary)

- CPU code → static recompilation is feasible because games are statically
  linked and code is mostly fixed; quirks: R5900 instructions (MMI, 128-bit
  regs), delay slots, non-IEEE FPU, VU0 macro-mode instructions.
- Graphics → the hard part: VU1 microprograms + GS behaviour. See
  [native-port-plan.md](native-port-plan.md).
- Platform services → runtime HLE of syscalls and IOP services.

## Terms

CLUT (colour lookup table, palette) · GIF tag (GS packet header) · TEX0 (GS
texture register) · VIFcode (VIF command) · HLE (high-level emulation:
reimplementing what a service does, not the hardware) · SIF (EE↔IOP link) ·
MMI (R5900 multimedia instructions) · delay slot (the instruction after a
MIPS branch executes before the branch takes effect).
