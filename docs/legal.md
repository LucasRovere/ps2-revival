# Legal and licensing rules

Not legal advice; this is the project's working policy. When in doubt, leave
it out and ask the owner.

## Never in the repository

- Disc images (ISO/BIN/CHD/CSO…), BIOS dumps, NVM/MEC files.
- Game executables (the boot ELF, other ELFs), IOP modules (`.irx`), overlays.
- Decompiled or recompiled **game** code (even partial), disassembly listings
  of game code, Ghidra projects of game executables.
- Game assets or anything derived from them: dumped textures, upscaled
  textures, texture packs, models, audio, video, fonts, screenshots of game art.
- Personal data: owner's paths, usernames, hardware details → `local/` (git-ignored).
- Anything specific to one game (owner policy, D24): per-game recipes
  (serials, CRCs, texture hashes and suffixes, function/data addresses, patch
  definitions, classification overrides), notes and findings, and
  game- or engine-specific code (format decoders, hand-written
  reimplementations of game functions, overrides). These live in
  `local/games/<serial>/` (git-ignored).

## Allowed

- Generic tools and libraries we write (they may be tested on a pilot game;
  docs call it "the pilot game", without naming it).
- Short factual notes about formats and hardware, in our own words.
- Test fixtures we create ourselves (e.g. homebrew built with the open PS2 SDK).

## Third-party code

The project is **MIT**. Only copy code under MIT-compatible licenses:
MIT, BSD-2/3, Apache-2.0, zlib, ISC, Unlicense/CC0/public domain.

Not allowed (copying): GPL-2/3, AGPL, LGPL (unless used as a separate
dynamically-linked library, so ask first), "non-commercial" licenses (e.g.
CC BY-NC), no license at all. Specifically: **PCSX2 (GPL-3)**, **KytyPS5
(GPL-2-only)**. Check the license of any recompilation project before
reusing code.

Reading any open-source project to understand behaviour is fine; write our
implementation independently. When copying allowed code, keep its notice and
list it in `THIRD_PARTY_NOTICES.md`.

Tools we only *run* (Ghidra, Real-ESRGAN, PCSX2) are not affected; don't
vendor their binaries into the repo.

## Outputs users generate

Users may generate texture packs, analyses and native builds locally from
their own discs. The project does not distribute them, and docs should not
point to places that do.
