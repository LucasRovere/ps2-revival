# Environment

Primary platform: **Windows 10/11 x64**. Machine-specific paths and hardware
for the owner's PC live in `local/MACHINE.md` (git-ignored); keep this file
generic.

## Tools

| Tool | Used by | Version known to work | Notes |
|---|---|---|---|
| Python | textures, extract, future scripts | 3.12.10 | `pip install -r textures/requirements.txt` (numpy, pillow) |
| Real-ESRGAN ncnn-vulkan | textures | release v0.2.5.0 (`realesrgan-ncnn-vulkan-20220424-windows.zip`, SHA-256 `ABC02804E17982A3BE33675E4D471E91EA374E65B70167ABC09E31ACB412802D`) | From the official `xinntao/Real-ESRGAN` GitHub releases. Includes models `realesrgan-x4plus`, `realesrgan-x4plus-anime`, `realesr-animevideov3-x2/3/4` |
| PCSX2 | testing in-game, test oracle (T21) | 2.8.2 (Qt; log of 2026-10-18) | User folder: `Documents\PCSX2` (inis, gamesettings, textures) |
| Git for Windows | repo | 2.55.0 | Includes Git Credential Manager for GitHub sign-in |
| Ghidra | analysis | 12.1.4 (`ghidra_12.1.4_PUBLIC_20260921.zip`, SHA-256 `DDAC49F903DA9D5BAC833E5CC79395098B9C33CFD3279BE5F31BD00387D2D4DB`) | Official `NationalSecurityAgency/ghidra` GitHub releases. Unzip to `tools/bin/ghidra_12.1.4_PUBLIC/` |
| JDK 21 (Eclipse Temurin) | analysis (Ghidra) | 21.0.12.1+1 (`OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip`, SHA-256 `F9D6E191AB098C0D416E7D588A24420A8621CD2F4720DAB2459B8B7B2D2D8B4E`) | From `adoptium/temurin21-binaries` GitHub releases. Unzip to `tools/bin/jdk-21.0.12.1+1/`; `analysis/analyze.py` sets `JAVA_HOME` to it |
| ghidra-emotionengine-reloaded | analysis | v2.1.38 for Ghidra 12.1.4 (`ghidra_12.1.4_PUBLIC_20261004_ghidra-emotionengine-reloaded.zip`, SHA-256 `E389FF3E921D9F7D4DB2ECE9906F808545CE4FF519D9E25A019B72EA509F240B`) | From `chaoticgd/ghidra-emotionengine-reloaded` GitHub releases. Unzip into `tools/bin/ghidra_12.1.4_PUBLIC/Ghidra/Extensions/`. Must match the Ghidra version exactly. Language ID `r5900:LE:32:default` |

| WSL 2 + Ubuntu 24.04 | recomp (`recomp/port.py`, `recomp/tests/harness.py`, vendored ps2-web-recomp) | clang 18.1.3, CMake 3.28.3, Ninja 1.11.1, libsdl2-dev (Ubuntu apt) | Installed by the owner: `sudo apt update && sudo apt install -y clang cmake ninja-build libsdl2-dev`. Third-party code is built and run only inside WSL (until T22) |
| LLVM (clang++) | recomp on Windows (`recomp/port.py`) | 23.1.3 (`winget install --id LLVM.LLVM -e`) | Not added to PATH: `$env:Path = "C:\Program Files\LLVM\bin;$env:Path"` per shell. Target `x86_64-pc-windows-msvc`; MSVC can't build the generated code (clang vector builtins, `musttail`) |
| CMake | recomp on Windows | 4.4.4 (`winget install --id Kitware.CMake -e`) | |
| Ninja | recomp on Windows | 1.13.2 (`winget install --id Ninja-build.Ninja -e`) | |
| Visual Studio 2022 Build Tools | recomp on Windows (MSVC STL, CRT, linker, Windows SDK for clang) | 17.14 (MSVC 14.44.35207, Windows SDK 10.0.26100) | `winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--quiet --wait --norestart --nocache --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --add Microsoft.VisualStudio.Component.Windows11SDK.26100"` (~1.7 GB). clang finds it without a developer prompt |
| SDL2 (VC dev package) | recomp window build on Windows (`port.py --window`) | 2.32.10 (`SDL2-devel-2.32.10-VC.zip`, 7,172,966 bytes, SHA-256 `AF347939395A58B365846AAEA27391E69F9EC9D4DD650D6AC40802159B418A6E`) | https://github.com/libsdl-org/SDL/releases/download/release-2.32.10/SDL2-devel-2.32.10-VC.zip (D20). Unzip into `tools/bin/` (gives `tools/bin/SDL2-2.32.10/`). zlib license |
| wgpu-native | recomp GPU renderer on Windows (`port.py --window`) | v29.0.1.1 (`wgpu-windows-x86_64-msvc-release.zip`, 17,062,968 bytes, SHA-256 `7E67D7445C42AEB85E30F88930FD8D7D83EE769E3390AEB1ADA75EBF3CF78132`) | https://github.com/gfx-rs/wgpu-native/releases/download/v29.0.1.1/wgpu-windows-x86_64-msvc-release.zip (D20; the version upstream's `fetch_wgpu.sh` pins). Unzip into `tools/bin/wgpu-native-v29.0.1.1/`. MIT or Apache-2.0 |

Real-ESRGAN lookup order in `textures/upscale.py`: `--esrgan <dir>`, env
`PS2R_REALESRGAN`, `tools/bin/realesrgan/` (git-ignored), then
`Documents\PCSX2\tools\realesrgan\`.

Installing on a new machine (ask the owner first):

```bash
winget install --id Python.Python.3.12 -e --scope user
```

```bash
winget install --id Git.Git -e
```

## Windows / PowerShell traps

- **PowerShell 5.1**: no `&&`/`||` (use `; if ($?) { ... }`), no ternary.
- **`python -c "..."` breaks**: PowerShell strips inner double quotes when
  calling native programs. Write a `.py` file in `work/` and run it.
- **`python` may be the Microsoft Store alias** (prints "Python was not
  found"). Use the full interpreter path or `py`.
- **Long paths**: Python failed to open a script whose path exceeded ~260
  characters even though PowerShell could see it. Keep scripts in `work/`.
- **Native stderr**: avoid `2>&1` on native tools in PowerShell 5.1 (it turns
  stderr lines into errors). Real-ESRGAN prints GPU info and progress to
  stderr; the pipeline suppresses it.
- **`wsl -e bash -c "..."` breaks**: PowerShell expands `$var` and strips
  quotes before WSL sees them. Write a `.sh` file in `work/` and run
  `wsl -e bash /mnt/c/.../script.sh`.
- A newly installed tool is not on PATH in shells opened before the install;
  use its full path or open a new shell.

## GPU notes

Real-ESRGAN uses Vulkan and picks GPU 0. On machines with an integrated GPU
plus a discrete one, check its startup line names the discrete GPU. The same
problem exists in PCSX2 (see [pcsx2-tuning.md](pcsx2-tuning.md)).
