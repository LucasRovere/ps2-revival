# recomp

EE (R5900) → C++ static recompiler (Phase 5). The recompiler and runtime are
[ps2-web-recomp](https://github.com/snuri00/ps2-web-recomp) (MIT), vendored
in `ps2-web-recomp/` (D14, D16). Our own code: `port.py` (incl. the port folder), `play.py` (launcher), `drawlist.py` (draw-list report), the function
override hook (vendored patch, below), generic overrides in `overrides/`
(none yet; created with the first), the chain handler hook (vendored patch) with a test handler in
`chains/` and the instruction tests in `tests/`.

## port.py (WSL or Windows)

```bash
python3 recomp/port.py <SERIAL> --iso "/mnt/c/path/to/game.iso"   # first run links the ISO
python3 recomp/port.py <SERIAL> [--no-explore] [--no-menu] [--no-patches] [--saves]
```

Needs clang, CMake and Ninja in WSL (SDL2 optional, for the window).

### New game: port.py init (T38, Windows)

```powershell
. work/t22/env.ps1    # LLVM on PATH
python recomp/port.py init "C:\path\to\game.iso" [--serial ABCD-12345] [--textures]
```

Reads `SYSTEM.CNF`, the boot ELF and its CRC from the disc; the serial
comes from the boot ELF's name (`ABCD_123.45` → `ABCD-12345`), else
`--serial` is needed. Writes `local/games/<serial>/game.json` (`serial`,
`title` = serial, `disc.elf`, `disc.crc`, `recomp.entries: []`,
`recomp.explore_frames: 18000`) and `notes.md` (template of
[games.md](../docs/games.md), identity filled in). If either exists it stops
and changes nothing. Then it runs `port.py <serial> --iso <iso> --folder`:
link, translate, exploring runs (entry points found are written into
`game.json`), VU1 compile, with `--textures` the texture pack (T43,
[below](#automatic-texture-pack-t43)), window build, port folder. Last line: where the
folder is (`work/<serial>/port/ps2run.exe`, double-click). No menu run (a new
game has no `recomp.menu`): the automatic exploration (T39, below) drives the
game through its intro and menus, and the VU1 programs it meets are compiled;
the rest run on the interpreter until a later run records them.

Windows (T22): same command with Windows Python 3.12 and a Windows ISO path.
Needs LLVM (clang++), CMake, Ninja and the Visual Studio 2022 Build Tools
(MSVC STL + Windows SDK; clang finds them itself, no developer prompt).
The LLVM installer does not add itself to PATH, so per shell:

```powershell
$env:Path = "C:\Program Files\LLVM\bin;$env:Path"
python recomp/port.py <SERIAL> --iso "C:\path\to\game.iso"
```

On Windows the ISO is hard-linked (symlinks need admin) and the build dirs
are `build-tools-win/`, `build-native-win/`; `generated/` and the run
outputs are shared with WSL. `--window` (T23) also builds
`build-window-win/ps2run.exe` with the SDL2 window and the wgpu GPU
renderer, from SDL2 2.32.10 and wgpu-native v29.0.1.1 in `tools/bin/`
(D20, see [environment.md](../docs/environment.md)), and copies `SDL2.dll`
next to it. Run it with `--window` for the game window (keys: arrows, Z
cross, X circle, A square, S triangle, Enter start, F11 fullscreen; pads via
SDL). Without `--window` it runs headless but still draws on the GPU;
`PS2_GS=cpu` selects the CPU rasterizer. Never
runs upstream's `setup.sh`/`port.sh` (they download wgpu-native and emsdk).
Steps: extract the boot ELF from the ISO, apply the `game.json` `patches`
(below), build `eerecomp`, translate,
build `ps2run` (headless, CPU rasterizer), the automatic exploration
(below; it adds missed entry points and translates again, like upstream
`port.sh`'s loop), the scripted menu run, then `vurecomp` on the VU1 microprograms the runs
recorded (`PS2_VU_RECORD`, into `vu1/`) and a rebuild of the runners with
them (D21, T25). Programs not recorded run on the VU1 interpreter;
`PS2_VU_INTERPRET=1` forces the interpreter for all (for comparisons). Reads the `recomp` block of `local/games/<SERIAL>/game.json`:

| Key | Meaning |
|---|---|
| `entries` | Extra entry points, the runtime's miss format (hex without `0x`; `module:offset` for modules) |
| `aspect` | `"16:9"` when the recipe patches put the game in its own widescreen mode: `play.py`'s default `aspect` |
| `explore_frames` | Frames the automatic exploration plays from boot (below) |
| `menu` | Optional scripted run from boot: `frames`, `frame_every`, `presses` (`frame:button[+button][:hold]`) |
| `overrides` | Optional `{"0x00123456": "name"}`: guest function entry → our C++ function `name` (below) |
| `chain_handler` | Optional `name`: the C++ that takes over VIF1 chain calls, `local/games/<SERIAL>/chains/<name>.cpp` or `chains/<name>.cpp` ([Chain handlers](#chain-handlers-t46)) |
| `save`, `load` | Optional scripted runs for `--saves` (same keys as `menu`, below) |

Output (game-derived, never commit): `work/<SERIAL>/recomp/`: `generated/`
(C++, incl. `vu1_*.cpp`, `overrides.cpp`, copies of the override
sources and `chain_handler.cpp`), `patched/` (the patched ELF), `vu1/` (recorded VU1 program
images), `build-tools/`, `build-native/`, `explore/` (the exploration's
last segment: state, card, frames, log), `explore-frames/` (its new
scenes), `menu.log`, `*-frames/` (PPM), memory cards. New entry points found by exploring are
printed; add them to `entries` (`init` writes them itself).

### Automatic exploration (T39)

The exploring run plays `explore_frames` frames from boot with generated
input, no script (`explore.py` + `Explorer` in `port.py`). It is cut into
segments of 600 frames chained by save states (`--save-state`,
`--load-state`); each segment is one `ps2run` process with one press pattern:
`cross`, `start`+`cross`, a direction+`cross` (down, up, right, left),
`circle`+`triangle` (back out), or a seeded random mix, a press every 40
frames.

**Progress** is new code: the runtime lists every function entry dispatch
enters (`PS2_COVERAGE=<file>`, vendored patch below), and a segment that
enters at least 25 functions never entered before, records a new VU1
program or misses an entry point made progress. Frames do not decide
progress: menus often sit on a looping video or 3D background, so their
frames always look new even when the input goes in a circle (the pilot
game's first menu and a memory card dialog looped for 10,000 frames that
way). A **stalled** segment is retried from its start state with two other
patterns (the next ones in the list, rotating with each stall, so stalls in
a row try every pattern); the run goes on with the try that made progress,
else the one that entered the most new code. A pattern that made progress
is kept for the next segment.

**Frames** (dumped every 30 frames) give the scenes: a frame is a new scene
when its 16×12 block luma differs from every scene so far by more than
0.025 (black frames never count). New scenes of segments that made
progress are kept in `explore-frames/`. The run ends at `explore_frames` or
after 5 stalled segments in a row whose frames were all black, frozen or
already seen (a hang such as the T27 black screen; a movie still shows new
frames, so the run waits it out).

**Entry points:** a segment that halts at a missed entry point gets it
added to `entries.txt`, translated, the runner rebuilt and the segment run
again (8 rounds at most); `init` writes them into `game.json`. **VU1:** new
programs (`PS2_VU_RECORD`) are compiled with `vurecomp` and the runner
rebuilt after the segment that met them, so the following segments (and
gameplay) run them compiled. On Windows the exploration uses the window
build headless (GPU renderer, menus ~20× faster than the CPU rasterizer);
in WSL the native build.

The log prints one line per try (`frames A-B pattern: N new functions, V
new VU1 programs, E new entry points, S new scenes`), stalls, and a summary
(`explored F frames in T s: scenes, functions entered, new VU1 programs,
new entry points`). The hand-written `recomp.menu` run still plays after
it when `game.json` has one.

Check (pilot game, scratch serial through `port.py init`, no script,
18,000 frames; frames looked at): the exploration skipped the intro movies
(`cross` does not skip them: that try stalled, `start` took over), went
through the first menu, memory card dialogs, profile creation and name
entry, the save prompts (the game formatted the fresh card and saved), a
mode menu, a loading screen and the race intro: the scenes of the pilot's
hand-written menu run. A scripted menu run on the explored build
with `PS2_VU_RECORD` on recorded no program the exploration had missed.
In an earlier version without the 25-function threshold, `cross` alone sat
at the title for 6,000 frames until `start` was tried; with it the stall is
left in the next segment. `init` took 8 min (exploring ~5 min). The pilot's
scripted menu run is byte-identical with `PS2_COVERAGE` on and off (same
cycle count). Weak spot: a direction pattern kept after a menu choice typed
into the name entry for several thousand frames before another pattern got
out (two full runs reached the race intro at ~9,000 and ~15,000 frames).

### Saves (T34)

`ps2run --memcard <file>` puts one memory card in slot 1. The file is a raw
card image in PCSX2's `.ps2` layout: 16,384 pages of 512 data bytes + 16
spare bytes (ECC), 8,650,752 bytes. A missing file is a new, unformatted
card (the game offers to format it). The runtime only moves pages; the
format, file system and ECC come from the game's own card modules running
on the IOP. After a write the card file is rewritten once 50 frames pass
without card writes, and the log says `[mc] card saved: <file>` (quitting
less than a second after a save can lose it).

`port.py <SERIAL> --saves` plays two more scripted runs from boot:
`recomp.save` (presses that make the game save to a fresh card `save.ps2`;
stops if no card was written) and `recomp.load` (boots on a copy,
`load.ps2`, and loads that save). Look at `save-frames/` and
`load-frames/`. Without `--saves` nothing changes.

Card check (pilot game, T34): the port's card has PCSX2's layout: page 0
(superblock: "Sony PS2 Memory Card Format 1.2.0.0", 512-byte pages, 2 pages
per cluster, 16 per block, 8,192 clusters, alloc offset 41, root cluster 0,
backup blocks 1023/1022, type 2, flags 0x2B) is byte-identical to a card
PCSX2 made; every written page's ECC (3 bytes per 128) is right; the save
directory and file sizes match a save PCSX2 wrote for the same game. The
port also loads that PCSX2-made save. One difference: superblock page 1 is
all 0xFF on the port's card and holds leftover bytes on PCSX2's own new
card (unused by the file system). *Unverified:* PCSX2 listing a card the
port wrote (owner check: copy the card into PCSX2's `memcards` folder).

### Launcher: play.py (T34, Windows)

```powershell
python recomp/play.py <SERIAL>
```

Starts `build-window-win/ps2run.exe` (from `port.py <SERIAL> --window`) on
the ELF port.py translates (`patched/` when `game.json` has patches) in its
window. Settings: `local/games/<SERIAL>/play.json` (per machine,
git-ignored), created with defaults on first use:

| Key | Default | Meaning |
|---|---|---|
| `memcard` | `local/games/<SERIAL>/memcard.ps2` | Slot 1 card file (relative to the repo or absolute) |
| `scale` | `1` | GPU internal resolution 1-3 (`PS2_SCALE`) |
| `fullscreen` | `false` | Start fullscreen (F11 toggles) |
| `aspect` | `game.json` `recomp.aspect` when patches are on, else `"4:3"` | `"16:9"` presents the image at 16:9 (`PS2_ASPECT`), for a game running its own widescreen mode (e.g. through recipe patches) |
| `textures` | `""` | Texture pack folder (`PS2_TEXTURES`, relative to the repo or absolute), e.g. `local/games/<SERIAL>/textures`; `""` = off (below) |
| `mods` | `""` | Mod folder (`PS2_MODS`, relative to the repo or absolute): replacement disc files ([Mods](#mods-t42)); `""` = off |
| `frame_log` | `false` | `true`: frame-time log in `frame_log.txt` next to the card (`PS2_FRAME_LOG`, [below](#draw-profile-and-frame-time-log-t45)) |
| `gpu_mesh` | `true` | `false`: no GPU mesh path (`PS2_GPU_MESH=0`, [Chain handlers](#chain-handlers-t46)); also read from the port folder's `settings.json` |

Keys missing from an older `play.json` take the defaults. The log shows
`settings: ...`, `[gpu] scale N`, `[gpu] aspect W:H` and
`[mc] card in slot 1: <file>`.

When the port folder `work/<SERIAL>/port/` exists (below), `play.py` starts
its `ps2run.exe` instead, with the same settings, and prints `port folder: ...`
(`play.json` wins over the folder's `settings.json`).

### Port folder (T37, D27, Windows)

```powershell
python recomp/port.py <SERIAL> --no-explore --no-menu --folder [<dir>]
work\<SERIAL>\port\ps2run.exe          # or double-click it; no ISO needed
```

`--folder` builds the window runner and writes a standalone port (default
`work/<SERIAL>/port/`; game data, never commit):

| File | Content |
|---|---|
| `ps2run.exe`, `SDL2.dll` | Window build (wgpu linked in) |
| `<boot ELF>` | The ELF port.py translated (patched when `game.json` has patches), named as in `SYSTEM.CNF` |
| `disc/` | Every disc file at its disc path |
| `layout.txt` | `sectors <n>`, then `file <lba> <size> <path>` per file and `rest <lba> <count>` per run of other non-zero sectors |
| `sectors.bin` | Those other sectors in `rest` order (system area, volume descriptors, path tables, directory records; also a file's last sector when its padding is not zero) |
| `settings.json` | Picture settings for a start in folder mode (T38, below) |
| `textures/` | Copy of the game's texture pack (T43): `play.json` `textures`, else `local/games/<SERIAL>/textures/`, when it has images |

`settings.json` (flat JSON) is written once from `play.json` (`aspect`,
`scale`, `fullscreen`, `mods`; a repo-relative mod folder becomes absolute)
or, without one, the defaults (`aspect` as `play.py` picks it: the recipe's
`recomp.aspect` when patches are on, else `"4:3"`; scale 1; not
fullscreen; no mods), plus `"textures": "textures"` when the folder got a
pack copy (else `""`) and `"memcard": "memcard.ps2"` (the folder's own
card, D30). An existing file is kept (`settings kept: ...`), so edit it by hand.
`ps2run` in folder mode reads it: `aspect` → `PS2_ASPECT`, `scale` →
`PS2_SCALE`, `textures` → `PS2_TEXTURES`, `mods` → `PS2_MODS` (both
relative to the folder or absolute), `memcard` (same; `--memcard` still wins); environment variables
already set win over the file (that is how `play.py` keeps `play.json`).
`fullscreen: true` only applies to a start with no arguments
(double-click). Without the file the defaults are as before (4:3, scale 1).

The disc is unpacked once; a later `--folder` only refreshes the exe, DLL
and ELF (delete `layout.txt` to unpack again). The runtime's folder backend
(`--disc <dir>`, a directory instead of an ISO) reads each sector from the
file that covers it, else from `sectors.bin`, else zeros, so every LBA reads
back as on the ISO and the directory index is built from the same records.
`ps2run` with no ELF argument runs the folder it sits in: ELF name from
`disc/SYSTEM.CNF`, disc = that folder, card `memcard.ps2` there (other
options still apply, e.g. `--memcard`, `--window`). With no arguments at all
it opens the window. The log says `[disc] folder backend: <dir>` or
`[disc] image backend: <file>`. `settings.json` next to it sets the picture
(above).

Editing a file in `disc/` in place changes what the game reads, as long as
the file keeps its size (the disc's directory records keep the old size).
To change files without touching the folder, or to let them grow: a mod
folder ([Mods](#mods-t42)). Limits: layer-1 files
of a dual-layer disc are not unpacked (they stay in `sectors.bin`; no
dual-layer disc tested). The exe needs the Microsoft Visual
C++ 2015-2022 runtime (`MSVCP140.dll`, `VCRUNTIME140.dll`), already present
on a machine with the build tools.

Check (pilot game): the image rebuilt from the folder equals the ISO byte
for byte (the folder is smaller: zero sectors are not stored);
menu run from boot on the folder: 107 of 107 frames byte-identical to the
ISO run and the same cycle count (since T43; before, the guest's `argv[0]`
was the host ELF path on Windows, below); window run with the ISO
link renamed away: intro movies, menus, loading screen and race intro, 60
fps from a race-intro state like the ISO; a same-size string edit in one
archive file in a copy of the folder shows in the loading-screen frames.
Headless race-intro time is the same as the ISO's.

Boot path (T43, D30): the game gets `cdrom0:\<ELF NAME>;1` as `argv[0]`
in every mode, as on a real PS2; the log says `[ee] boot path ...`.
Upstream skipped the conversion for any path with a `:`, so on Windows
(`C:`) the guest saw the host path and the cycle count depended on the
ELF's location. Now only a device path (`cdrom0:`, `host:`: more than one
character before the `:`) stays as given. Pilot menu run: frames
unchanged, ISO and folder mode now have the same cycle count.

### Mods (T42)

`PS2_MODS=<folder>` (`mods` in `play.json` or in the port folder's
`settings.json`) replaces disc files at runtime. The mod folder holds
replacement files at their disc paths: `<mods>/DATA/FILE.BIN` replaces
`DATA/FILE.BIN` (case does not matter). The port folder and the ISO stay
untouched; it works in ISO and folder mode.

For a modder:

1. Make a folder, e.g. `local/games/<SERIAL>/mods/` (game data, never
   commit).
2. Copy the disc file to change from `work/<SERIAL>/port/disc/` into it at
   the same relative path, and edit the copy. It may grow or shrink.
3. Set `"mods": "local/games/<SERIAL>/mods"` in `play.json` and run
   `python recomp/play.py <SERIAL>`. Or, for the port folder alone, add
   `"mods": "<path>"` to its `settings.json` (relative to the folder or
   absolute). Or set `PS2_MODS` for any `ps2run` run.

A file that fits the original's sectors is read at the original's place; a
bigger one gets new sectors past the end of the disc. The new sector and
size are written into the file's directory record in the sectors the game
reads, and the runtime's file index is rebuilt from them. So both the
runtime's lookups (`sceCdSearchFile`, `cdrom0:` opens, IRX loads) and a game
that parses directories itself see the new file. Files not on the disc are
skipped with a log line (they would need a new directory record). The log:

```
[mods] DATA/FILE.BIN: 123456 bytes at sector 400000 (moved past the disc end)
[mods] <folder>: N files
```

A game that reads a file by sector numbers stored in its own data (not by a
lookup) would still read the old place; for such a file a mod must keep its
size (unverified: not met yet). Files inside a game's own archives need an
engine-specific tool that rebuilds the archive (D24: in
`local/games/<serial>/tools/`).

Check (pilot game, menu run from boot, ISO and folder mode): without
`PS2_MODS` frames and cycles are unchanged (107/107). A same-size archive
(text entry recompressed in place, a texture's palette changed) and a grown
archive pair (both entries appended: two data files moved past the disc
end, their index files changed in place) both show the new loading-screen
text and banner colours in frames; the run goes on to the race intro. The
folder still rebuilds the ISO byte for byte afterwards.

### Widescreen and resolution (T32)

`PS2_ASPECT=16:9` (any other value: 4:3) sets the window's presented
aspect: the WebGPU blit viewport (and the SDL fallback's logical size) is
the largest 16:9 rectangle in the window instead of 4:3, and a new window
opens at 1280×720 instead of 960×720. Only the presentation changes: the
game still renders its own buffer (e.g. 640×448), so frame dumps
(`--frames-dir`), cycle counts and emulation are the same with either
setting. Use 16:9 only when the game draws a 16:9 image (its own
widescreen mode); its 2D elements stay as the game draws them in that
mode.

Check (pilot game, patched ELF): presented images read back from the
window's surface (a local, uncommitted debug build) are 960×720 with the
4:3 image and 1280×720 with the 16:9 image filling the window; the 3D view
is unsqueezed at 16:9. Menu run from boot: frames 107 of 107
byte-identical and the same cycle count with `PS2_ASPECT` unset or 16:9.

`PS2_SCALE` (1-3, `scale` in `play.json`) multiplies the internal
resolution. Pilot game, race intro: headless 30.2-31.0 ms/frame at scale 1,
32.6-33.1 at 2, 33.4-33.8 at 3 (render-thread work; GPU load stays under
~13%). In the window (paced, 3 runs each, noisy) the race intro holds
~56-60 fps at scale 1 and dips to ~50-55 fps at 2 and 3. Frames at scale
2 and 3 are sharper (clean polygon edges, sharper text and HUD), with no
new artefacts seen (bloom/glare, 2D overlays, menus, loading screens
lined up). Recommendation: scale 2 or 3 for looks, with small fps dips in
heavy scenes until the render thread gets faster (T29); default stays 1.
Scale 3 already gives ~1340 lines, about a 1440p display's height, so the
clamp stays at 3.

### Texture packs (T33)

`PS2_TEXTURES=<folder>` (`textures` in `play.json`) replaces textures with
PNGs from a pack folder; `PS2_TEX_DUMP=<folder>` writes each new texture the
game draws as a PNG (game-derived: keep it in `work/`). Both use the same file
name, `<key>.png`: 16 hex digits of our texture key. Only the GPU renderer
uses packs.

**Key.** The texel data lives on the GPU, so the key is built from the bytes
the game uploads, not from GS memory. Each image transfer tags every 64-byte
GS column it writes completely with a hash of its bytes (in upload order);
a column it writes partly gets no tag. A CLUT load tags the CLUT entries it
writes with the tags of its source columns. A texture's key mixes its PSM,
TW/TH, the tags of all columns under it (row order) and, for 4/8-bit
textures, the tags of the CLUT entries it reads (for 16/24-bit colours also
TEXA/AEM). The key does not depend on the address, so a texture uploaded to
another place keeps its key. Textures get no key (are never replaced or
dumped) when a column under them has no tag: textures narrower than a GS
column (4-bit < 32 px, 8-bit < 16 px wide, often mip levels), memory loaded
from a save state until the game uploads it again, and pages the GPU drew to
or copied into (render targets, page granularity). Formats replaced: PSMCT32,
PSMCT24, PSMCT16, PSMT8, PSMT4, any wrap mode but region repeat.

**Pack images.** 8-bit RGBA (or RGB, alpha 0x80) PNGs, PS2 alpha (0-128, as
in PCSX2 dumps and `textures/` output), exactly 1, 2, 4 or 8 times the
texture's TW×TH (the dump's size); other sizes are ignored. The raster shader
samples the image at its own resolution (nearest, or bilinear when the game
asks for it; wrap and clamp at the image's resolution). Images are decoded
(own PNG reader, no new library) by loader threads from the start (T53,
below) and kept in a GPU buffer (up to
1 GiB; when full the buffer is flushed and refilled). Mipmaps: the renderer
only samples level 0, so packs hold base levels only.

The conversion tool builds packs itself (below, T43). For PCSX2 players
who already have PCSX2 replacements, `python textures/pack.py <SERIAL>
--dumps <dump folder>` converts them (`docs/textures.md`): each port dump is
matched to a PCSX2 dump by pixels and the replacement of the match is
copied as `<key>.png` into `local/games/<SERIAL>/textures/`.

The log shows `[tex] pack <folder>: N textures` at start, `[tex] pack
decoded in X s` when every image is decoded and, at exit,
`[tex] lookups N: replaced R, render targets D, unsupported U, untagged T;
textures K (replaced L)` (lookups = texture setups the renderer built).

Without `PS2_TEXTURES`/`PS2_TEX_DUMP` nothing runs (no tags, no lookups).
With `PS2_TEX_DUMP` gs.cpp also keeps GS memory on the CPU to decode the
dumped textures, which costs a lot (debug mode only).

Check (pilot game, race intro from a patched state, 600 frames): two dump
runs gave the same files byte for byte (a texture re-uploaded every frame
keeps its key); ~10% of lookups untagged (tiny/narrow textures). A test pack
of solid colours replaced every dumped texture in the frames; the real pack
(`pack.py`; under a third of the port's dumps matched a PCSX2 dump, the rest
were never dumped by PCSX2) shows the upscales in place, sharper at
`PS2_SCALE` 3, no garbled or misplaced textures. The menu run from boot with
the pack replaces the same textures (keys from boot equal keys from the
state) and keeps the same cycle count; without a pack its 107 frames are
byte-identical to the previous build. Cost: headless race intro 27.3 →
28.9-29.3 ms/frame with a pack (CPU: tagging ~6 MB of uploads per frame);
window 60 fps with and without a pack (3 runs each).

### Automatic texture pack (T43)

```powershell
python recomp/port.py <SERIAL> --folder --textures    # or: port.py init <iso> --textures
```

No PCSX2 (D30). The exploring runs (above) run with
`PS2_TEX_DUMP=work/<SERIAL>/recomp/texdump/dumps`, so every texture the game
draws there is written as `<key>.png` (dump-mode frames and cycles are the
same as without). Then `textures/upscale.py <SERIAL> --textures-dir
work/<SERIAL>/recomp/texdump --out local/games/<SERIAL>/textures
--junk-groups` upscales them with Real-ESRGAN (classes, PS2 alpha, detail
check and Lanczos fallback as for PCSX2 dumps, `docs/textures.md`); only
dumps without an upscale are done, so a re-run adds new scenes. Port keys
carry no format suffix, so `--junk-groups` treats every image size shared
by 200 or more dumps as per-frame junk (pilot game: its scripted menu run
dumps one 1024×256 VRAM capture per frame, ~7,600 of ~8,400 dumps; the
exploration met none). `--folder` then copies the pack into the port
folder. `--no-explore --textures` only upscales the dumps already there.
Review and overrides: `/texture-pack`.

Dump mode keeps a CPU copy of GS memory: the pilot's exploration took
394 s instead of 313 s.

Check (pilot disc, scratch `init --textures`, 18,000 frames): 774
textures dumped, 442 upscaled (294 tiny and 38 flat skipped, no junk
group), 83 of them by the Lanczos fallback; exploring 394 s, upscaling
~3.5 min, `init` 13 min. The folder's scripted menu run (scale 2) replaced
429 of 8,407 textures the renderer met (T33's PCSX2-matched pack: 51),
~60% of texture lookups; frames: sharper signs, banners, logos and car
details, placement and alpha right, no garbling; the glare-star sprites
get longer, harder rays (open owner check, as in T33). Same cycle count
with and without the pack.

### Draw profile and frame-time log (T45)

Two opt-in measurements for Phase 8. Unset, frames and cycle counts are
unchanged (pilot menu run 107/107 frames, 52,595,993,647 cycles) and the
headless speed is within noise.

**Draw profile** (headless only): `PS2_DRAW_PROFILE=<from>,<count>` times
the VIF1 DMA list per `call` target for frames from..from+count and prints
`[draw]` lines when the run passes from+count: per target the calls, VIF1
ms (each DMA tag's time, including the VU1 programs and GS front end it
starts) and qwords; VU1 ms per (target, program entry) (chain handler ms per (target, entry) for VU1 starts a
handler did, T46); GS front-end ms per
(target, GIF path 1/2); root chains per frame and channel 2 (path 3)
totals. About 20% slower while on, same cycles. In the window the VU
thread does that work, so the variable is ignored there (one log line);
headless shares map onto the threads (VIF1 + VU1 → VU thread, GS front end
→ render thread). Report:

```powershell
$env:PS2_DRAW_PROFILE = "<from>,<count>"; $env:PS2_TIME = "<from>,<count>"; $env:PS2_DUMP = "work\prof.ram"
work\<SERIAL>\recomp\build-window-win\ps2run.exe <elf> --disc <iso> --load-state <state> --frames <from+count> 2> work\prof.log
python recomp/drawlist.py work\prof.log work\prof.ram [--match work\<SERIAL>\files\<dir>] [--kinds N]
```

`drawlist.py` reads each target's chain from the `PS2_DUMP` RAM dump
(cnt/ref tags up to `ret`), fingerprints it by its VIF commands (unpack
format @ VU1 address, `MSCAL`, `MSCNT`, `DIRECT`, `MPG`) and groups targets
with the same fingerprint into kinds: targets, calls, VIF1 ms, VU1 ms (top
entries), GS ms per path and share of the frame (from a `[time]` line of
the same frames, else of the VIF1 total). `--match <dir>` names the chains
found byte for byte in the files under a folder (e.g. a game's unpacked
mesh files; ~25 s for 400 MB).

**Frame-time log** (threaded window): `PS2_FRAME_LOG=<file>` (`play.json`
`"frame_log": true` → `frame_log.txt` next to the card) writes one line per
presented frame:

| Column | Meaning |
|---|---|
| `frame` | guest frame of the present |
| `ms` | real time since the previous present (render thread) |
| `ee_present` | EE waited for the present queue (more than 2 presents in flight: VU or render behind) |
| `ee_ring` | EE waited for room in the VU ring |
| `ee_pace` | EE waited in the frame pacing (timer, audio correction) |
| `ee_other` | EE waited for the other threads (fences, GS downloads, state saves) |
| `vu_ring` | VU thread waited for room in the render ring (render behind) |
| `vu_idle`, `render_idle` | thread had no work |
| `render_present` | render thread inside the surface present (blocks there while the GPU is behind) |
| `audio_ms` | sound queued for the device |
| `limit` | the thread with the most time not waiting (`render_present` counts as work); `pace` when none worked half the frame |

A wait counts in the frame it is in (a wait in progress is split at the
present). At exit: `# frames N, mean X ms; over 17/20/33 ms: count (per
limit)`, also on stderr as `[window] frame log: ...`. Not written in
one-thread mode (`PS2_ONE_THREAD`, `PS2_TIME`, frame dumps).

**Pacing (T45):** the window spaces frames with the timer at the guest
rate; the audio queue only corrects the speed (no wait under ~40 ms
queued, 5% slower over ~80 ms). Before, the EE waited for the queue to
drain below 80 ms, which released frames in bursts of the audio device's
pulls: in calm menus presents came 2-30 ms apart (p5/p95) at a 60 fps
mean; now 13-20 ms.

### Menu dips (T53)

**Pack loads off the render thread.** With a pack, the render thread used
to decode a PNG the first time a texture appeared: 50-800 ms stalls at
scene changes and loading screens. Now `texpack::init` starts loader
threads (a quarter of the hardware threads, at least one) that decode the
whole pack in the background (pilot pack, 517 images, ~1 GB decoded:
1.3 s with 4 threads); `[tex] pack decoded in X s` marks the end. A
lookup of an image not decoded yet decodes it on the render thread (as
before) or waits for the loader that has it, so what is drawn never
depends on timing: frames with a pack are byte-identical to the previous
build, same cycles. Memory: the decoded pack stays in RAM (as before once
every image had been met). Without a pack nothing starts.

Check (pilot, window, scale 3, 16:9, pack; same states and presses
before/after): menu run max frame 782 → 73 ms, frames over 33 ms 31 → 8,
p99 32.6 → 28.1 ms; race intro max 194 → 40 ms, over 33 ms 8 → 1; menu
run headless with the pack, 120 frames byte-identical; without a pack
107/107 frames and 52,595,993,647 cycles.

**GPU-bound screens at scale 3 (not fixed).** Some menu screens draw the
full screen many times per frame (pilot: a title fade-in ~22 rounds of
upload + ~6 full-screen passes, a menu fade-out 64 rounds of 3 full-screen
copy/fill passes). The generic raster shader then needs ~40 ms of GPU per
frame at scale 3 (~8 ms at scale 1), so the surface acquire waits. Found
by waiting for the queue before the acquire (GPU time) and timing each
dispatch alone (submit + wait): the per-pass timestamps of
`PS2_GPU_PROFILE` read far too low on the pilot machine (a 5 MB copy in
1.6 µs), so they cannot rank dispatches there. *Assumption:* the game
redraws as fast as the EE allows while it loads, and the port's GS
costs no emulated time, so it loops more often per frame than a real GS
could fill (55 M pixels per frame in the fade-out). Options are in
`docs/tasks.md`.

### Chain handlers (T46)

Game code can take over a VIF1 chain at its DMA `call` (D32, D35): e.g. an
engine's static mesh chains, drawn natively instead of by the VU1
program. One handler per game, `recomp.chain_handler` in `game.json`
(source in `local/games/<SERIAL>/chains/<name>.cpp`, game-specific, D24;
or `chains/<name>.cpp`); `port.py` copies it to
`generated/chain_handler.cpp`. It defines `register_chain_handlers()` and
calls `ps2::chain::register_handler(claim, draw)` (`ps2/chain.hpp`):

- `claim(address)` runs on the EE thread at each VIF1 `call` tag and says
  whether the handler wants the chain at that address (it may read
  `g_ram`; cache per address, the call is frequent). A claimed chain's
  data (every qword DMA delivers between the `call` and its `ret`, nested
  calls included) is gathered and handed over as one: headless straight
  to `draw`, in the window as one `kVif1Chain` packet to the VU thread in
  stream order (the EE side runs the VIF state copy over the same words as
  before, so what the EE sees does not change). Unclaimed calls run as
  before.
- `draw(address, data, qwc)` runs where the chain's VIF commands would
  (VU thread in the window, VU1 memory current). Returning false runs the
  words through VIF1 as usual. Returning true means the handler did the
  work: it must have passed the words through
  `ps2::chain::run(data, qwc, hook)`, which runs the VIF commands normally
  (unpacks into VU1 memory, VIF state, MPG) and calls `hook(entry)` at each
  VU1 start (MSCAL, MSCALF, MSCNT) with `vu::top()` set; the hook returns
  true when it did the program's work itself (output through `vu::kick`,
  registers it leaves for later programs, e.g. `tpc`), false to run the
  VU1 program. `ps2::chain::vu1_program(entry)` gives the vurecomp key of
  the program at an entry (as in `vu1_<key>`), `vu1_memory()`,
  `vu1_regs()` the VU1 state; `ps2/vu_ops.hpp` has the VU float ops the
  compiled programs use (same ops in the same order give the same bits).

Emulated time: in this runtime VU1 programs cost no EE cycles (a program
runs to completion at its MSCAL/MSCNT, FLUSH waits for nothing, the EE
never waits on VU1), so a handler charges none either and cycle counts do
not change. A handler must produce the same GS packets (and leave VU1
memory and the registers later programs read as the program would) for
byte-identical frames.

`chains/identity.cpp` claims every call and runs each chain through
`chain::run` with the programs unchanged: the check that the seam itself
changes nothing. With `PS2_DRAW_PROFILE`, VU1 starts a hook did are listed
as `[draw] handler <target> entry <entry>` (drawlist.py column `Hdl ms`,
incl. the GS front-end work of their kicks) instead of VU1 time.

Check (pilot game): no handler: menu run 107/107 frames, 52,595,993,647
cycles; headless race intro 26.7 vs 27.1 ms/frame (3 runs each, noise).
Identity handler: menu run and racing state byte-identical, same cycles.
The pilot's handler (local, the engine's pre-lit static meshes: its three
main batch programs re-done on the CPU with the same float ops, a batch
that needs the program's polygon clipper left to VU1): a debug mode that
runs every native batch on VU1 too found 0 differences in VU1 memory over
15 million batches (racing and race intro); racing and race intro frames
byte-identical, same cycles; window runs at scale 1 and 3 work. Speed:
the batches' VU1 work (excl. the GS front end of their kicks) ~20% less
(VIF unpacks and the GS front end stay); headless and window frame times
unchanged within noise, fewer VU-limited frames at scale 1 (race intro
60 → 16 of 2,397). The speed is for the GPU mesh path (T48).
**GPU mesh path (T48, D36).** In the GPU renderer (window and headless
Windows builds; not with `PS2_GS=both` or the CPU rasterizer;
`PS2_GPU_MESH=0` turns it off) a handler may draw a batch's strip from
vertices kept on the GPU instead of running its VU1 program:
`ps2::chain::mesh_path()` says whether it is on, `mesh_add(vertices,
count)` copies a mesh (position, RGBA, two ST sets, ADC flag per vertex)
and returns its id, `mesh_draw(d)` stands for one path 1 packet of the
strip in stream order (GIF tag with PRE, then ST, RGBAQ, XYZF2 per vertex):
c = m[3] + m[0] x + m[1] y + m[2] z, q = 1 / c.w, ST = st q, XYZF2 =
ftoi4 of c.xyz q (z >> 4), no fog; flat colour, which ST set and extra
ADC bits per draw. `chain::run(data, qwc, hook, unpack)` takes an
unpack hook that may skip an UNPACK's writes (mode 0/1) while the VIF
state advances, so a handler can skip the vertex data it already has.
`mesh_draw` projects the strip's vertices on the calling thread (screen
boxes); the render thread keeps the GS state effects of the tag, and the
GPU does the rest: `mesh_build` (one invocation per triangle) makes the
primitive records `draw()` would make, with VU1's arithmetic (each product
rounded on its own, the reciprocal truncated; 1/area rounded): bit-exact;
a batch of mesh strips holds no other primitives; at its flush the CPU
gives each chunk of 64 records the box of its strips and lists the chunks
per tile, `mesh_bin` keeps each tile's records that touch it (box and
edges) in order, and `raster_mesh` shades them like `raster`. Records and
tile lists sit in `g_data` below the arena (never uploaded); one
`mesh_build` per submit.

Check (pilot's pre-lit scenery, local handler): frames byte-identical with
the path on (racing 15/15, race intro 52/52, menu run 107/107, scale 3
with the pack: racing 15/15 and race intro 26/26 against the path off),
same cycles; ~0.5% of the batches (clipper) unpacked and drawn as before.
Headless (`PS2_TIME`, 200 frames, off → on): racing 25.5 → 22.1 ms
(scale 1), 27.0 → 23.1 (scale 3); race intro 29.8 → 23.2, 30.6 → 26.0.
Window (16:9, pack, frame log, 40 s, off → on): racing 60 fps at scale 1
and 3 (render thread 78% → 69% of a core at scale 3); race intro scale 1
mean 58.1 → 60.0 fps (lowest 1 s window 40 → 56), scale 3 56.1 → 58.2
(36 → 47). Without a texture pack the race intro at scale 3 is GPU-bound
with the path on (~51 fps vs ~59 off; open).
### Patches and overrides (T31)

**Patches:** the top-level `game.json` `patches` (the Phase 4 recipe, see
[patches/README.md](../patches/README.md)) are applied to a copy of the ELF
in `patched/`; every `old` word is checked first (`patches/build.py`
`check_writes`), and a mismatch stops the run. That copy is translated and
run. `--no-patches` translates and runs the disc's ELF (for comparisons).
`gsaspectratio` is PCSX2-only; in the port, `aspect` in `play.json` (T32,
above) presents a 16:9 image.

**Overrides:** `eerecomp --overrides <file>` (one hex address per line, the
`--entries` format) puts a hook at each listed function entry label in the
generated unit, so direct `jal` calls, tail jumps and dispatcher entries
(`jalr`, vtables) all reach it:

```cpp
L_00123456:
    if (run_override(c, 0u)) { c.pc = c.r[31].w[0]; return; }
```

An override is `bool name(ps2::Cpu &c)` in `namespace ovr`, in
`overrides/<name>.cpp` (generic: SDK, libc) or
`local/games/<serial>/overrides/<name>.cpp` (game-specific, never in git,
D24). It reads arguments from `a0`-`a3`, writes the result to `v0`/`v1` and
returns true; the hook then returns to `ra` like `jr ra`. Returning false
runs the recompiled code instead. `port.py` writes the address list, copies
the sources into `generated/` and writes `generated/overrides.cpp`
(`register_overrides()`, called from the generated `register_generated_code`).
At startup the runtime stops with an error if a listed address has no
registered override or the other way round. At exit it prints
`[override] 0x...: N calls` per override. Without overrides the generated
C++ is byte-identical to before.

Overrides must keep emulated time: the recompiled code charges each
instruction to `c.budget` (a branch and its delay slot count 2, also when a
branch-likely skips the slot), and that budget is the EE clock. An override
that does not charge the same cycles runs the game at a different speed
relative to vblank, so frames change. For byte-identical frames an override
also has to respect the preemption checks at taken backward branches
(`c.budget < 0` there runs due events): a side-effect-free override can
compute the guest's path first and return false when the guest would hit
such a check with the budget used up (T31's identity override does this).

## Vendored upstream

`ps2-web-recomp/` is upstream commit `c628ae8` (2026-10-16), tracked files
byte for byte (`.gitattributes` turns off line-ending conversion there),
except:

| Change | Why |
|---|---|
| `docs/media/demo.mp4`, `demo.webp` left out | Gran Turismo 4 footage: copyrighted game art (AGENTS rule 1). Upstream `README.md` still links them. |
| `runtime/src/iop/sif.cpp` line 143, `bind()`: `now() + kEeClock * 4` → `now()` | A bind to a server that is not registered was held 4 s of guest time before the 0 reply. The pilot game binds a debug-print server that no module registers on every print, which stalled its boot. Now the 0 reply goes out on the next SIF pump; a server that registers in the same instant still gets the bind. |
| `CMakeLists.txt` (wgpu block), `runtime/include/ps2/system.hpp` + `runtime/src/gs/gpu/gpu.hpp` (`Windows` surface kind), `runtime/src/gs/gpu/gpu.cpp` (`attach_surface`), `host/window.cpp` | Windows window + GPU build (T23): CMake links `wgpu_native.lib` and its Windows system libs (`d3dcompiler ws2_32 userenv bcrypt ntdll opengl32 propsys runtimeobject`) instead of `libwgpu_native.a dl pthread m`; the WebGPU surface is created from the SDL window's `HWND`; `window.cpp` reads CPU time and RAM with `GetProcessTimes`/`GetProcessMemoryInfo` instead of `getrusage`/`/proc/self/statm` (all under `_WIN32`, Linux code unchanged). |
| `runtime/src/gs/queue.cpp` (`Ring::post`, `Ring::pop`) | Lost wakeup (T23): a producer waiting for ring space could sleep forever. `pop` cleared `producer_waiting_` with `exchange(0)`, so when that pop's `freed_` increment came before the producer's `seen` load, the producer slept on a value no later pop would notify. The producer now loads `seen` after setting `producer_waiting_` and clears the flag itself; `pop` notifies while the flag is set. The pilot game's threaded window run hung in 6 of 7 tries within ~15 s (the 7th had a debug print in the wait path) (emulation thread in `post` from `vif::transfer`, VU ring empty); 0 of 3 after. Not Windows-specific (same logic with the Linux futex). |
| `recomp/codegen.cpp` (`Break`), `runtime/src/dispatch.cpp` (`breakpoint()`), `runtime/src/system.cpp` (`run()` exit code) | `break` halts (T24, D19): generated code returns after `breakpoint()`, which logs `[ee] break at <pc> code <code> (ra ...)`, halts with reason `break <code> at <pc>` and unwinds. `ps2run` then shuts down normally and exits with code 3. Upstream logged and continued; PCSX2 never returns from `break` (T21). |
| `runtime/src/gs/gpu/gpu.cpp`, `runtime/src/gs/gpu/gs.wgsl` (`decode`) | Render thread speed (T26), all output-preserving: (1) a CLUT load identical to the last one (same CBP, CPSM, CSM, CSA, size, TEXCLUT) is skipped while no upload, local copy, state load or drawn frame/Z page has touched its source; (2) the batch-vs-upload/CLUT conflict test checks the 8 KB pages under the batch rectangle instead of one linear range (the pilot game's CLUTs sit in the frame buffer's page span next to the drawn area: hundreds of false conflicts per frame, each flushing the batch); (3) pending uploads and CLUT loads go into alternating upload/CLUT waves by dependency (write-after-write, read-after-write, write-after-read) instead of one dispatch per run of same-kind ops; (4) a batch's texture decodes are one dispatch (the shader looks its record up by prefix sum, like `upload`); (5) `std::min({a, b, c})` → nested `std::min` in `draw` (MSVC's vectorised `min_element` call for 3 floats). Pilot game race intro: GPU commands per frame ~7,000 → ~530, frames byte-identical. |
| `CMakeLists.txt` (`-march=x86-64-v2`) | VU thread speed (T28, D22): x86-64 builds outside Emscripten use SSE4.1 (`pminsd`, blends) for the VU vector code; no AVX/FMA, so float results do not change. |
| `recomp/vurecomp.cpp`, `runtime/include/ps2/vu_ops.hpp` | VU thread speed (T28), output-preserving codegen: (1) VF registers and ACC live in a local copy (`Reg128 vf[32]`, written back before `vu::interpret`, `efu` and every exit), so clang keeps them in registers (through `r` it could not: every store to VU memory, a byte pointer, may alias `r`); (2) `flags` computes MAC/status with vector compares from the result value instead of a per-lane loop; (3) partial-lane LQ/SQ/MOVE/MR32/MFIR/MFP/RNEXT/RGET and OPMULA/OPMSUB write the register or qword with one 16-byte blend instead of 4-byte stores; (4) MAX/MIN of a register with itself (a move in the upper pipe) is a plain copy. |
| `runtime/src/iop/io.cpp` (ioman `AddDrv`, `DelDrv`) | Post-intro stall (T27): `AddDrv` was a stub returning -1, so the game's USB driver module failed to load ("Cannot add driver to IO manager") and never added its SIF command handler. The EE side then sent that command 60 times with a 0.5 s timeout each: ~1,800 frames of black screen (or the skipped movie's last frame) before the title. `AddDrv` now calls the driver's `init` op and returns 0 when it succeeds (as the IOP's ioman does); `DelDrv` returns 0. PCSX2 with the BIOS: the module stays resident (`ret 2`). |
| `runtime/src/vif.cpp`, `runtime/src/vu_micro.cpp` (`xgkick`) | VU thread speed (T28): VIF NOP (about half of all VIF commands, ~100,000 per pilot game race-intro frame) skips the command dispatch; the general unpack path writes each qword with one 16-byte store and wraps with a mask; XGKICK sends a packet that does not wrap around VU memory straight from VU memory instead of copying it to a stack buffer first. |
| `runtime/src/gs/queue.hpp`, `runtime/src/gs/queue.cpp` | VU thread speed (T28): `role()` is inline (thread-local read, asked once per VIF command); ring positions wrap with a mask (capacities are powers of two) instead of a 64-bit division; producer and consumer cache the other side's position and only reload it when they run out; each side's atomics sit on their own cache line; `post` does one locked operation instead of two (`consumer_waiting_` is read before it is exchanged). |
| `recomp/main.cpp`, `recomp/codegen.hpp`, `recomp/codegen.cpp`, `runtime/include/ps2/generated.hpp`, `runtime/src/dispatch.cpp` | Function overrides (T31, D5): `eerecomp --overrides <file>` (each address must be a function entry, else an error); at each listed entry of the main program the unit emits `if (run_override(c, k)) { c.pc = ra; return; }` (k = place in the sorted list); `table.cpp` gets `kOverrides[]` and `register_generated_code` calls `register_overrides()` (written by `port.py`) and `check_overrides`. Runtime: `register_override(addr, fn)`, `check_overrides` (exits on a listed address without an override or an extra registration), `run_override` (counts calls; counts printed at exit). Without `--overrides` the output is byte-identical (pilot game: all 238 units and `table.cpp`). |
| `runtime/src/iop/sio2.cpp` (`flush_cards`), `runtime/src/gs/gpu/gpu.cpp` (scale) | Log lines (T34): `[mc] card saved: <file>` after each card file write, `[gpu] scale N` at GPU start, so save runs and the launcher's settings show in the log. |
| `runtime/src/gs/gpu/gpu.cpp` (blit viewport in `submit`, `present`), `host/window.cpp` (window size, SDL logical size) | 16:9 presentation (T32): `PS2_ASPECT=16:9` replaces the fixed 4:3 of the blit viewport and the SDL fallback with 16:9 and opens a 1280×720 window; `[gpu] aspect W:H` at GPU start. Unset, the arithmetic is the same as upstream's. |
| `runtime/src/gs/gpu/texpack.cpp`, `texpack.hpp` (new), `gpu.cpp` (upload tags, `replacement` in the setup cache, `g_repl` binding 8, plan_decodes skips replaced setups, `[tex]` stats), `gpu.hpp` (`texture_dump`), `gs.wgsl` (`sample_repl`), `gs.cpp` (`cpu_memory`: CPU copy of GS memory for the dump), `CMakeLists.txt` (texpack.cpp) | Texture packs (T33, D25): setup word 24 = `0x80000000 | log2(scale) << 29 | offset/16` points the raster shader at a pack image instead of GS memory. Without `PS2_TEXTURES`/`PS2_TEX_DUMP` the new code does not run and frames and cycle counts are unchanged. |
| `runtime/src/disc.cpp` (`open`, folder backend), `host/main.cpp` (no-ELF folder mode) | Port folder (T37, D27): `disc::open` on a directory reads `layout.txt`, `disc/` and `sectors.bin` through the existing `Reader` hook; one `[disc] folder/image backend` log line. `ps2run` without an ELF argument takes the ELF named in `disc/SYSTEM.CNF`, the disc and `memcard.ps2` from its own folder, and opens the window when started with no arguments. ISO runs: frames and cycle counts unchanged. |
| `host/main.cpp` (`apply_folder_settings`) | Folder settings (T38): in folder mode `settings.json` next to `ps2run` sets `PS2_ASPECT`, `PS2_SCALE`, `PS2_TEXTURES` (only when not already set), the card, and fullscreen for a no-argument start. Runs with an ELF argument are unchanged. T42: `mods` → `PS2_MODS`. |
| `runtime/src/disc.cpp` (`apply_mods`, `index_disc`) | Mods (T42): with `PS2_MODS` set, `disc::open` wraps the reader: replacement files over the original sectors or past the disc end, new LBA/size written into the directory records as read, index rebuilt, `[mods]` log lines. Without `PS2_MODS`: frames and cycle counts unchanged. |
| `runtime/src/system.cpp` (`boot`) | Boot path (T43, D30): a host ELF path (no `:` or a drive letter) becomes `cdrom0:\NAME;1` as `argv[0]`, also on Windows (upstream converted only paths without a `:`); `[ee] boot path ...` log line. Pilot menu run: frames unchanged, cycles 52,595,993,473 → 52,595,993,647 (ISO), folder mode the same. |
| `runtime/src/dispatch.cpp` (`g_reached`, `write_coverage`), `runtime/include/ps2/system.hpp`, `runtime/src/system.cpp` (`run()`) | Code coverage (T39): with `PS2_COVERAGE=<file>`, dispatch marks each EE RAM address it enters translated code at (one byte per word), and `run()` writes the marked addresses (hex, one per line) at exit. The exploration's progress signal. Unset: one extra test of an empty vector per dispatch; frames and cycle counts unchanged. |
| `runtime/src/draw_profile.cpp`, `draw_profile.hpp` (new), `CMakeLists.txt`, `runtime/src/dmac.cpp` (`run_chain`, `start`, channel 2), `runtime/src/vif.cpp` (`run_vu`), `runtime/src/gs/gif.cpp` (`transfer`), `runtime/src/system.cpp` (`vblank`) | Draw profile (T45): `PS2_DRAW_PROFILE=<from>,<count>` times VIF1 tags per DMA `call` target, VU1 runs per entry and GIF paths 1/2 per target, headless only; `[draw]` lines after the last frame. Unset: one test of a false flag per VIF1 tag, VU1 run and GIF packet; frames and cycles unchanged. |
| `runtime/src/gs/queue.hpp`, `queue.cpp` (`time_waits`, `wait_began`, `wait_ended`, `waited_ms`, `wait` kind), `runtime/src/gs/gs.cpp`, `gs.hpp` (`post_present(frame)`, `presented_frame`), `runtime/src/system.cpp`, `runtime/include/ps2/system.hpp` (wrappers, present timed), `host/window.cpp` (`PS2_FRAME_LOG`, `pace`) | Frame-time log (T45): time each thread waits by kind (only after `time_waits()`, i.e. with `PS2_FRAME_LOG`); the present carries its guest frame in the queue header. Pacing: timer-spaced frames with an audio-queue correction instead of waiting for the audio queue (window only; headless unchanged). |
| `runtime/src/gs/gpu/texpack.cpp` (`Slot`, `load`, `claim`, `start_loaders`, `find`) | Pack loader threads (T53): with `PS2_TEXTURES` set, `init` starts threads that decode every pack image; `find` decodes or waits for an image not decoded yet, so frames do not depend on timing. Without a pack nothing starts; frames and cycles unchanged. |
| `runtime/include/ps2/chain.hpp`, `runtime/src/chain.cpp`, `chain.hpp` (new), `CMakeLists.txt`, `runtime/src/dmac.cpp` (`run_chain`, `to_vif`), `runtime/src/vif.cpp`, `vif.hpp` (`transfer_chain`, `run_hooked`, `feed`, hook in `run_vu`), `runtime/src/gs/queue.hpp` (`kVif1Chain`), `runtime/src/system.cpp` (VU thread), `runtime/src/vu_micro.cpp`, `vu_micro.hpp` (`program_key`), `runtime/src/draw_profile.cpp`, `draw_profile.hpp` (`handler_ran`), `host/main.cpp`, `host/web.cpp` (`register_chain_handlers()`) | Chain handlers (T46, D32): a claimed VIF1 `call`'s data goes to the handler as one (`kVif1Chain` in the window), `chain::run` with a hook at each VU1 start; profile `ret` now after the tag's data. No handler: one test of a null pointer per `call` tag and VU1 start; frames and cycles unchanged. |
| `runtime/include/ps2/chain.hpp`, `runtime/src/chain.cpp` (`mesh_path`, `mesh_add`, `mesh_draw`, `run` with an unpack hook), `runtime/src/vif.cpp`, `vif.hpp` (unpack hook in `unpack`, `run_hooked`), `runtime/src/gs/gs.cpp`, `gs.hpp` (`render_mesh`, `kMesh`/`kMeshData`), `runtime/src/gs/queue.hpp`, `runtime/src/gs/gpu/gpu.cpp`, `gpu.hpp` (`draw_mesh`, `mesh_add`, `flush_meshes`, `setup_for`/`add_prim`/`finish_batch`/`dispatch_decodes` split out of `draw`/`flush_batch`, arena `base`, mesh pipelines), `runtime/src/gs/gpu/gs.wgsl` (`raster_mesh`), `runtime/src/gs/gpu/mesh.wgsl` (new: `mesh_build`, `mesh_bin`), `CMakeLists.txt` (`kMeshShader`), `host/main.cpp` (`gpu_mesh` setting) | GPU mesh path (T48, D36): mesh vertices cached on the GPU, strips built and binned there (see [Chain handlers](#chain-handlers-t46)). Off (`PS2_GPU_MESH=0`) or no mesh draws: the same frames and cycles (menu run 107/107, no handler and identity handler). |

The headless Windows build (T22) needs no changes to upstream: the headless path
leaves out `host/window.cpp` (SDL2), `host/profile.cpp` (Linux only) and the
wgpu link list. The futex in `gs/queue.cpp` is Linux-only; elsewhere it
already falls back to `std::atomic` wait/notify and a 1 ms sleep, and
headless runs one thread anyway (the render/VU threads start only in
`window.cpp`). `vurecomp` output (T25, T28 codegen) builds with clang 23
(Windows) and clang 18 (WSL).
The window build (T23) needs the Windows patch above; its render and VU
threads hit the ring deadlock fixed by the `queue.cpp` patch.

Licenses: [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) (MIT;
Play! BSD-2-Clause for the IPU tables).

## tests

Plan and vector format: [../docs/recomp-tests.md](../docs/recomp-tests.md) (D15).

```bash
python -m unittest discover -s recomp/tests   # assembler + every vector on the model
python recomp/tests/ref.py                    # vectors on the reference model, with a summary
python recomp/tests/asm.py <SERIAL>           # local check: re-encode the analysis export
python3 recomp/tests/harness.py [--random N] [--seed S]   # WSL: vectors + random cases on the recompiler (L1, L2) + override case
python3 recomp/tests/harness.py --tables <SERIAL>         # WSL, local: jump tables vs the port's entry tables (L3)
python recomp/tests/oracle.py [--mode rec interp ...]     # Windows: vectors on PCSX2 + the owner's BIOS (L4, D18)
```

| File | Content |
|---|---|
| `tests/asm.py` | Assembler for every mnemonic the pilot game uses (inverse of `analysis/census.py`'s tables) |
| `tests/ref.py` | Python reference model: integer, control flow, 64/128-bit memory, mult/div, MMI, FPU, VU0 macro ops (PS2 float rules) |
| `tests/vectors/*.json` | Test vectors, written by hand (`base`, `branch`, `mem`, `mmi`, `system`, `fpu`, `vu0`) |
| `tests/harness.py` | ELF writer, runs `eerecomp` per case, builds and runs the harness, compares with `ref.py`; `OVERRIDE_CASE`: a function reached through `jal` and `jalr` runs its override (`harness/override.cpp`) both times and returns to the caller |
| `tests/oracle.py` | One test ELF for all eligible vectors, run on PCSX2 (own data folder in `work/`), end states parsed from the EE console log |
| `tests/test_port.py` | `port.py`'s pure parts: serial from the boot ELF name, default `game.json`, refusal to overwrite, folder `settings.json` |
| `tests/test_explore.py` | `explore.py` on synthetic frames: frame signature, black/frozen/repeated frames are not new scenes, stall rule, pattern order (stalls in a row try every pattern), generated presses |
| `tests/test_drawlist.py` | `drawlist.py` on a synthetic chain: log parsing (incl. chain handler lines), chain read and VIF fingerprint, kinds and shares, `--match` at an odd file offset |
| `tests/harness/` | C++ harness (`main.cpp`: load state, `dispatch`, print state as JSON), `override.cpp` (the override case's C++) and its CMake project (links upstream `ps2runtime`) |

Harness output (fixture C++, build): `work/recomp-tests/`.

Stdlib only. Code runs at 0x00100000; vectors put data elsewhere (we use
0x00200000).
