# Roadmap

Goal: make PS2 games look and run better on modern PCs, first inside PCSX2,
then as native Windows ports that are moddable. Each phase must be useful on
its own; the project should never be "nothing works until the port is done".

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
| 6 | Port hooks & runtime gaps | **In progress** (D23). Done (T31): function override table in `eerecomp` + runtime (D5), `game.json` patches applied in the port (pilot game: 16:9 camera in the port's frames, identity override byte-identical). Next: saves and launcher (T34) | Override table, recipe patches in the port, saves checked, launcher with settings; later audio clock (T30) and speed (T29) |
| 7 | Look better (GS renderer) | Planned (D23) | Widescreen (D12 recipe + 16:9 output), higher internal resolution, texture packs from `textures/` by content hash |
| 8 | Native draw paths | Planned (D23), selective | Engine draw-list survey, then native model drawing via overrides where the GS path can't reach ("option C", per engine) |
| 9 | Assets & mods | Planned (D23) | Disc-file mod folder (runtime disc layer + archive entries), model export to glTF (T14), re-import via Phase 8 |

Phases 0–4 help PCSX2 players directly. Phases 5–9 are the native port; see
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
