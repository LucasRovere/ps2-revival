# Roadmap

Goal (D26): a tool that turns a PS2 ISO into a native Windows game, with
per-game work automated as far as possible. Agents, skills and tooling
prepare the ground so each further game goes fast. Final intent: the games
become **fully native** (native renderer, audio and IO; game logic in
hand-written or decompiled C++ instead of recompiled code). Each phase must
still be useful on its own; the project should never be "nothing works
until the port is done".

Pace: Phases 0–7 took about 30 hours of agent work. Plan with that pace
(D26): a full native conversion of one game is on the order of a week.

Every module is proven on a pilot game (D7) before being generalised. Its
identity, recipe and findings stay in `local/games/<serial>/` (D24).

## Phases

| # | Phase | Status | Output |
|---|---|---|---|
| 0 | PCSX2 tuning | **Done** (guide) | [pcsx2-tuning.md](pcsx2-tuning.md) |
| 1 | Texture upscaling | **Working**, verified on the pilot game | [`textures/`](../textures/), [textures.md](textures.md) |
| 2 | Extract | **Working**, verified on the pilot game | [`extract/`](../extract/): ISO → SYSTEM.CNF, main ELF, IRX modules, file listing. Engine-specific archive/texture decoders are local tools (D24) |
| 3 | Analysis | **Working** (export + syscall/SDK naming), verified on the pilot game | [`analysis/`](../analysis/): Ghidra + EE extension, headless export (functions, pseudocode, xrefs, strings), `syscalls.py`; names in `game.json` |
| 4 | Patches | **Done, untested in game** (pilot game: widescreen pnach D12; no 60 FPS patch needed D11; 480p is built into the game D13) | [`patches/`](../patches/): `.pnach` built from the `game.json` recipe, original words checked against the ELF |
| 5 | Recompiler | **Done** (2026-10-18): the pilot game runs natively on Windows: game window, wgpu GPU renderer, VU1 programs compiled, race intro at 60 fps; owner play test: title, menus and racing work. Base: ps2-web-recomp, vendored with patches (D14, D16; list in [recomp/README.md](../recomp/README.md)); Windows build D17, D20; tests L0–L4 pass ([recomp-tests.md](recomp-tests.md), D15, D18, D19). History: [tasks.md](tasks.md) Done table (T13–T28). Optional polish, not blocking: speed headroom and menu fps drops (T29), audio on its own clock (T30), 5 float cases unverified (D19), VU1 programs beyond the race intro run on the interpreter (D21) | `recomp/`: ps2-web-recomp (EE → C++, runtime, GS on WebGPU) + `port.py` + tests |
| 6 | Port hooks & runtime gaps | **In progress** (D23). Done (T31): function override table in `eerecomp` + runtime (D5), `game.json` patches applied in the port (pilot game: 16:9 camera in the port's frames, identity override byte-identical). Done (T34): saves (the game saves to the port's card, a new run loads it; PCSX2 `.ps2` layout, a PCSX2-made save loads) and the launcher `recomp/play.py` with per-machine settings. Left: T29/T30, parked by the owner | Override table, recipe patches in the port, saves checked, launcher with settings; later audio clock (T30) and speed (T29) |
| 7 | Look better (GS renderer) | **In progress** (D23). Done (T32): `aspect: "16:9"` in `play.json` presents the game's own 16:9 image unsqueezed (4:3 default unchanged, frames byte-identical); `PS2_SCALE` 2 and 3 measured and looked at (sharper, no new artefacts, small fps dips in the race intro; default stays 1, clamp stays 3). Owner check of 16:9 in the window pending. Done (T33, D25): texture packs (`textures` in `play.json`, `PS2_TEX_DUMP` dump mode, `textures/pack.py` from the PCSX2 replacements); replaced textures seen in frames, no pack = byte-identical frames, window still 60 fps. Phase 7 items done; open: owner checks, frame rate above 60 (unplanned) | Widescreen (D12 recipe + 16:9 output), higher internal resolution, texture packs from `textures/` by content hash |
| C | Conversion tool | **In progress** (D26). Done (T37, D27): `port.py --folder` writes a standalone port folder (window exe, ELF, disc files unpacked with their sector layout) that runs with no ISO; pilot game: same frames and cycles as the ISO run, plays in the window, an in-place file edit shows in game. Done (T38): `port.py init <iso>` onboards a new disc in one command (serial, ELF, CRC from the disc; `game.json` + `notes.md` written, never overwritten; pipeline to the port folder); the folder carries `settings.json` (picture settings for a double-click). Steps: (a) standalone folder build: exe + unpacked disc files, no ISO at runtime (absorbs T35); (b) one-command onboarding `port.py init <iso>`; (c) automatic exploration (generated input, hang detection); (d) second game from the owner's discs; (e) game-neutral agent skills (`/port-game`, `/diagnose-hang`, `/find-widescreen`, `/texture-pack`) | ISO → playable port folder with one command; the manual method in skills; a second game as the generality check |
| 8 | Native draw paths | Planned (D23), after C; a step towards fully native (D26) | Engine draw-list survey, then native model drawing via overrides where the GS path can't reach ("option C", per engine) |
| 9 | Assets & mods | Planned (D23), after C | Mod folder over the unpacked disc files (from C a), archive entries via local tools, model export to glTF (T14), re-import via Phase 8 |
| — | Fully native | Intent (D26); detailed plan when we do it for the first game | No PS2 hardware layer: native renderer, audio and IO; game logic in hand-written or decompiled C++ |

Phases 0–4 help PCSX2 players directly. Phases 5–9 and the conversion tool
(C) are the native port; see
[native-port-plan.md](native-port-plan.md). The reasoning behind this order
is in [decisions.md](decisions.md).

## Next tasks

The current task, backlog and done log live in [tasks.md](tasks.md).

Phase 5 prior art and licenses: [recomp-survey.md](recomp-survey.md). Only
MIT-compatible code may be reused (see [legal.md](legal.md)). Test plan:
[recomp-tests.md](recomp-tests.md).

## Out of scope (for now)

- Distributing ports, texture packs or any game-derived output.
- Online/network features, PS2 HDD games, PS1 compatibility mode.
- Automatic AI enhancement of 3D models (no reliable technique; models will
  be exported for humans to improve; see [native-port-plan.md](native-port-plan.md)).
