# Recompiler test plan (T17, Oct 2026)

How we check that the EE (R5900) recompiler translates instructions
correctly, whichever recompiler `recomp/` ends up being (D14: ps2-web-recomp
or our own). Decision on tooling: [D15](decisions.md#d15-recompiler-tests-use-self-encoded-fixtures-no-ps2sdk-toolchain-for-phase-5).

Status: **L0 built** (T18 integer, T19 FPU/VU0): assembler, reference model
and 216 vectors in [`recomp/tests/`](../recomp/tests/), all passing on the
model ([T18](#t18-results-oct-2026), [T19](#t19-results-oct-2026)). **L1–L3
built** (T20): the harness runs them on the vendored recompiler
([T20](#t20-results-oct-2026)). **L4 built** (T21): PCSX2 with the owner's
BIOS checked the 34 unverified vectors; 29 PCSX2-confirmed, 5 still open
([T21](#t21-results-oct-2026), D18). T24: the 5 stay on our model,
unverified, and `break` halts the recompiled code; L1 216/216
([T24](#t24-results-oct-2026), D19). Counts
come from the T13 census of the pilot game (`analysis/census.py`; full
census in the local game notes) plus a T17 pattern count (same export,
scripts in `work/`, not kept).

## Approach

A **test vector** = start state + a few instruction words + expected end
state. The same vectors run on two backends:

1. **Reference model** (`recomp/tests/ref.py`, Python): a small interpreter
   for the instructions under test. Checks that vectors are consistent and
   gives a second opinion for random (differential) tests. Needs nothing new.
2. **Recompiler under test**: the vector's words are wrapped in a minimal
   ELF, recompiled, linked with a small C++ harness that loads the start
   state, runs the code, and prints the end state as JSON. Needs a C++
   toolchain (WSL clang, see T15) and the recompiler (T16).

Where the expected value comes from is recorded per vector (`source`):

| Source | Use | Trust |
|---|---|---|
| `spec` | Behaviour defined by the MIPS/R5900 instruction set, written by hand | High for integer, branch and SIMD ops |
| `ps2-fpu` | PS2-specific FPU/VU float rules (no inf/NaN/denormals, truncation, clamping) | **Unverified** until confirmed by a hardware oracle |
| `hw` | Confirmed on a real PS2 or PCSX2 run (T21); the `oracle` field names which and the modes | Highest; PCSX2 = PCSX2-confirmed, not hardware |

Same model and same agent can misread the manual the same way, so `spec`
vectors are hand-checked anchors, and every `ps2-fpu` value stays marked
`Unverified` until T21.

### Vector format

One JSON file per class in `recomp/tests/vectors/` (`base.json`,
`branch.json`, `mem.json`, `mmi.json`, `fpu.json`, `vu0.json`,
`system.json`). Each case:

```json
{
  "name": "addu sign-extends the 32-bit sum",
  "asm": ["addu v0, a0, a1"],
  "init": {"a0": "0x7fffffff", "a1": "0x1"},
  "expect": {"v0": "0xffffffff80000000"},
  "source": "spec"
}
```

- `asm` lines are encoded by our own assembler (`recomp/tests/asm.py`, the
  inverse of `analysis/census.py`'s opcode tables). No compiler needed.
- Registers are hex. In `init`, shorter values are zero-extended.
  GPRs, `hi`, `lo` are 128-bit: in `expect`, up to 16 digits give bits 0–63
  (bits 64–127 must keep their `init` value); more digits give all 128 bits.
  Every other register is compared whole (T19). (T18: the T17 wording
  "only the given digits" made `"0x0"` compare 4 bits, an easy mistake.)
  GPRs by name (`zero` … `s8`, `ra`). Also `hi`, `lo`, `sa`, `fcr31`,
  `f0`..`f31` and `facc` (FPU, 32-bit), `vf0`..`vf31` and `acc` (VU0,
  128-bit: x = bits 0–31 … w = bits 96–127), `vi0`..`vi15` (16-bit), `q`,
  `mem` (`{"0x00100000": "hex bytes"}`), `pc_trace` for control-flow tests.
  An unknown name in `expect` is an error (T19).
- `asm` may contain labels (`L:` on its own line); code starts at
  0x00100000, so jump-table entries in `mem` use those addresses.
- `hi`/`lo`: bits 0–63 = HI/LO, bits 64–127 = HI1/LO1 (pipeline 1).
  `sa` is the shift in bytes (`mtsah` writes `((rs ^ imm) & 7) * 2`).
  `fcr31` bit 23 is the FPU condition read by `bc1*`; it is the only FCR31
  bit compared (flags are not modelled: the pilot game has no `cfc1`).
  `cfc2`/`ctc2` model only `vi0`..`vi15` and `vi22` (Q); others stop the run.
- A case ends when execution reaches the end of `asm` or a `break`.
- `"error": "<text>"` in `expect`: the run must stop with that error
  (e.g. `unknown jump target`), not run past it.
- `"unverified": "<what to confirm>"`: the expected value is an
  assumption (*to confirm* below); T21 replaces it with `source: hw`.
- `"oracle": "<text>"` (with `source: hw`): which oracle and settings
  confirmed the value (T21).
- `expect` lists only what the case is about; the harness also checks that
  no other register changed.

## Priorities (from the census)

Order of work, by how often the pilot game uses each mnemonic:

| Prio | What | Why |
|---|---|---|
| P1 | Control flow: delay slots, branch-likely, `jal`/`jalr` link, jump tables | One mistake breaks every function; 6,933 branch-likely, 39,496 branches with a non-`nop` slot |
| P1 | Top base ops: `lw or addiu sw sll lui ori addu sltu andi subu sra and lh sb srl` | ~579k of 844k base instructions (branches and jumps are most of the rest) |
| P1 | 64-bit and 128-bit moves: `sd`/`ld` (81k), `daddu`, `dsll32`/`dsrl32`/`dsra32`, `ldl`/`ldr`/`sdl`/`sdr`, `lq` 6,466 / `sq` 5,470, `por` | Struct copies; wrong upper bits corrupt data silently |
| P2 | FPU: `lwc1 swc1 mtc1 mfc1 mul.s mov.s add.s sub.s c.lt.s c.le.s c.eq.s bc1f bc1t bc1fl bc1tl cvt.s.w div.s cvt.w.s neg.s max.s sqrt.s adda.s ctc1` | 80k instructions; physics and camera |
| P2 | Integer mult/div incl. 3-operand `mult rd` and pipeline 1 (`mult1`, `div1`, `divu1`, `mflo1`, `mfhi1`) | 441 `mult` and 43 `mult1` write `rd` |
| P2 | VU0 macro: `lqc2 sqc2 qmtc2 qmfc2 vaddbc vmaddabc vmul vmulbc vsub vmaddbc vwaitq vadd vmove vsuba vadda vrsqrt vmulq cfc2 vsqrt vopmula vopmsub vmr32 vmsubabc vmulabc vmsubbc ctc2 vsubbc vaddq` | 12,861 instructions; matrix/vector math |
| P3 | Rest of the mnemonics (rare base ops, MMI SIMD, `syscall`/`break`/`sync`/`cache`, cop0) | Few sites each |
| P4 | Not used by the pilot game (`madd.s`, `rsqrt.s`, `vcallms`, `vdiv`, TLB ops, traps, branch in a delay slot) | Skip until another game needs them |

Target: every P1/P2 mnemonic has at least one plain case and one case per
edge below that applies to it; P3 at least one plain case each.

## Edge cases

Numbers are pilot game sites. Expected values marked *(to confirm)* are
`ps2-fpu` or hardware-specific: assumption until T21.

### Delay slots and branches (P1)

- Slot runs on both paths of a normal branch; condition is read **before**
  the slot. ~6,700 branches have a slot that writes the branch's own
  source register (rough count), e.g. `beql a0,zero,L; lw a0,4(sp)`.
- Branch-likely: slot runs only when taken. All 6,933 likely branches in
  the pilot game have a non-`nop` slot. Include `bc1fl`/`bc1tl` (571).
- `jal`/`jalr`: `ra` (or `rd`) = branch address + 8; slot runs before the
  callee. `jr`/`jalr` whose slot writes the target register: the old value
  is used.
- Branch target inside another branch's delay slot: 1 site (a `bgtz`
  whose target is the slot of a `beq`). The slot word must also run as a
  normal instruction when entered directly.
- `bc1t`/`bc1f` directly after `c.cond.s` (6 sites): new condition is seen.
- Jump tables: both shapes (`lui`+`addu`+`lw` and `lui`+`addiu`+`addu`+`lw 0`),
  with and without an `sltiu` bound (14 without), first/last entry, and a
  target outside any known function (the pilot game has one). Fixtures are
  our own tables; the game's tables are checked at game level (below).
- Unknown `jalr`/`jr` target: must be reported, never run past silently.
- Not in the pilot game: branch or `syscall` in a delay slot (no tests).

### Integer and 64/128-bit (P1–P2)

- 32-bit ops sign-extend into bits 32–63 (`addu`, `addiu`, `sll` by 0,
  `lw`); `lwu`, `lbu`, `lhu` zero-extend.
- Bits 64–127 of a GPR after a 32/64-bit op. *Assumption:* unchanged
  (to confirm; check ps2-web-recomp's choice and Play!'s, then T21).
- `dsll32`/`dsrl32`/`dsra32`, `dsllv` etc. with shift 0 and 31.
- `ldl`/`ldr`, `sdl`/`sdr`, `lwl`/`lwr`, `swl`/`swr` at all byte offsets,
  as pairs and alone.
- `lq`/`sq`, `lqc2`/`sqc2`: low 4 address bits ignored (no exception).
- `por`/`pcpyld`/`pcpyud`/`pextlw`/`pextuw`: full 128 bits.
- `mult`/`multu`/`mult1`/`madd` write `rd` = low 32 bits, sign-extended.
- `mult1`/`div1`/`divu1` use HI1/LO1 = bits 64–127 of HI/LO; `mflo1`/`mfhi1`.
- `div` by zero and `0x80000000 / -1`: results are R5900-specific
  *(to confirm)*. GCC guards most divides with `break 7`.
- `plzcw`, `padduw` (saturation), `psubb`, `pminw`/`pmaxw`, `pcpyh`, `ppach`,
  `mtsah` (1 site) — P3.

### FPU, non-IEEE (P2)

PS2 FPU rules to encode *(all to confirm)*:

- No inf/NaN: exponent 255 is an ordinary number; overflow → ±max
  (`0x7fffffff`/`0xffffffff`).
- Denormal inputs act as ±0; underflow → ±0.
- Rounding toward zero (`add.s`, `sub.s`, `mul.s`, `div.s`, `sqrt.s`).
  Test values whose IEEE round-to-nearest differs.
- `div.s` x/0 → ±max; 0/0 → ±max (flag only, game never reads flags).
- `sqrt.s` of a negative → sqrt of |x|.
- `cvt.w.s`: truncation; |x| ≥ 2³¹ saturates to `0x7fffffff`/`0x80000000`.
- `c.eq.s` +0 = −0; `c.lt.s`/`c.le.s` with ±max and ±0.
- `max.s`/`min.s` with ±0 and negatives.
- `mov.s`/`neg.s`/`abs.s` change only bits (`neg.s` of 0 → −0).
- `adda.s` (1 site) writes ACC.
- Flags (FCR31 bits): low priority. The pilot game has no `cfc1` and one
  `ctc1` to FCR31.

### VU0 macro mode (P2)

- `vf0` reads (0,0,0,1); writes to it are ignored. `vi0` reads 0.
- Destination field masks (`.x`…`.xyzw`) leave other fields unchanged
  (`vmove`, `vadd`, `vmul`, …).
- Broadcast forms (`vaddx`…`vaddw`): each of the four.
- ACC ops: `vmaddabc`, `vadda`, `vsuba`, `vmsubabc`, `vmulabc`; cross
  product pair `vopmula` + `vopmsub`; `vmr32` rotation.
- `vsqrt`/`vrsqrt` → Q, read by `vmulq`, `vaddq` and `cfc2 vi22`
  (127 of 139 `cfc2` read Q); `vwaitq`.
- VU float rules like the FPU *(to confirm)*; VU differences (e.g. rounding
  of `vmadd`) unknown.
- `qmtc2`/`qmfc2`/`lqc2`/`sqc2`: 128-bit bit copies.
- `cfc2`/`ctc2` vi28 (FBRST, 5/6 sites) and `cfc2` vi29 (VPU-STAT, 7):
  runtime behaviour, tested with the runtime (Phase 6). MAC/status/clip
  flags are never read: low priority.

### System and cop0 (P3)

- `syscall` (60) → runtime dispatch with `v1` = number; `break` (46) →
  stop/report; `sync`, `cache`, `pref` → no-ops.
- cop0: `mfc0` Status (15), TagLo (4), Count (2); `mtc0` Status, ErrorEPC;
  `ei`/`di`; `eret` (1). Runtime-level; one plain case each.

## T18 results (Oct 2026)

Verified (`python -m unittest discover -s recomp/tests`, 11 tests OK;
`python recomp/tests/ref.py`: 147/147 vectors pass on the model):

- `recomp/tests/asm.py` encodes every mnemonic the pilot game uses; each encoding decodes
  back to the same mnemonic with `census.py`'s decoder (unit test).
- Local check on the pilot game's analysis export (`python
  recomp/tests/asm.py <SERIAL>`): every instruction it parses re-encodes to
  the same bytes. The rest is Ghidra syntax we don't parse, all checked:
  pseudo-ops skipped (`move`, `b`, `li`, `clear`, `moveq`; they hide
  `padduw`, `mthi`, `mthi1`, `mtlo1`, `mtsah`, `ctc1`), `vrsqrt` (Ghidra
  omits the fsf/ftf fields) and `cache` (Ghidra prints op names); their
  words were checked by hand. Ghidra prints `vadda`/`vsuba` with ft before fs
  (the check swaps them back).
- 147 vectors: `base` 56, `branch` 44, `mem` 25, `mmi` 20, `system` 2
  (counts from the files). Every base and MMI mnemonic the pilot game uses plus
  `break`, `sync`, `cache` has at least one case (unit test); every P1 and
  integer P2 edge above has one. Left for T19 (need FPU/VU0): `bc1t`/`bc1f`
  right after `c.cond.s`, `lqc2`/`sqc2` low address bits. `syscall` and cop0
  wait for the runtime (P3).
- Mutation check (work script, not kept): nine deliberate model bugs (no
  sign extension in `addu`, `lwr` always sign-extending, `beql` not likely,
  32-bit `bltz`, `mult1` on pipeline 0, logical `dsra32`, zero-extended
  `sltiu` immediate, swapped `pextlw`, upper GPR bits cleared) each fail at
  least one vector.

Unverified (9 vectors carry `"unverified"`, all `source: spec`):

- GPR bits 64–127 after 32/64-bit ops and loads: unchanged (3 vectors).
- Partial `lwr` (offset 1–3) keeps bits 32–63 (MIPS III rule).
- `div`/`divu` by zero and `0x80000000 / -1` (4 vectors).
- `plzcw` writes bits 0–63 only.

ps2-web-recomp (read, not run) makes the same choices for all of these
(`runtime/include/ps2/mmi.hpp`, `memory.hpp`, `set32`/`set64` in `generated.hpp`).
That is agreement, not confirmation: T21 decides.

Not modelled (no vector needs it): overflow traps (`addi`), address
exceptions (the model stops on an unaligned `lw`/`ld`), branch in a delay
slot (reported as an error).

## T19 results (Oct 2026)

Verified (`python -m unittest discover -s recomp/tests`, 13 tests OK;
`python recomp/tests/ref.py`: 216/216 vectors pass on the model, 34 marked
unverified):

- `ref.py` models the 23 FPU and 28 VU0 macro mnemonics the pilot game uses.
  Every mnemonic it uses except `syscall` and cop0 now has a vector
  (unit test). 69 new vectors: `fpu` 46, `vu0` 23.
- Float model (shared by FPU and VU0): exact arithmetic with Python
  `Fraction`, then truncation toward zero; exponent 255 is a number;
  denormal inputs read as ±0; overflow → ±`0x7fffffff`; underflow → ±0;
  x/0 and 0/0 → ±max; sqrt of |x|; `cvt.w.s` truncates and saturates.
  `add`/`sub` align the smaller operand keeping **one guard bit** and drop
  the rest (so 1 − 2⁻³⁰ = 1.0, not 0x3f7fffff): Play! (`FpAddTruncate.cpp`,
  BSD-2) and ps2-web-recomp (`fpu.hpp`, MIT) both do this.
- Edges from T18 done: `bc1t`/`bc1f`/`bc1tl` right after `c.cond.s` see the
  new condition (4 vectors); `lqc2`/`sqc2` ignore the low 4 address bits.
- Expected values are hand-written (work script, not kept); values where
  truncation and IEEE round-to-nearest differ were checked against numpy
  `float32` and an exact `Fraction`/`Decimal` computation (e.g. 1/3 →
  0x3eaaaaaa, IEEE 0x3eaaaaab; sqrt(5) → 0x400f1bbc; 1/sqrt(6) → 0x3ed105eb).
- Mutation check (work script, not kept): 16 deliberate model bugs (exact
  add without guard-bit drop, round-to-nearest `mul`/`div`, overflow → inf,
  wrapping `cvt.w.s`, sqrt(−x) = 0, ±0 unequal, dest mask ignored, `vopmsub`
  operand order, `vmr32` direction, `vmadd` without ACC, writable `vf0`,
  `lqc2` keeping low bits, zero-extending `cfc2`/`mfc1`, `c.lt.s` not
  clearing C) each fail at least one vector.

Unverified (25 new vectors, all `source: ps2-fpu`; unit test enforces the
mark): every PS2 float rule above, plus these choices:

- `max.s` of +0 and −0 returns fs (±0 compare equal; ps2-web-recomp's choice).
- VU0 macro ops use the FPU rules; `vmadd`/`vmsub` truncate the product
  before the add (no vector depends on fused vs. two-step rounding).
- `div.s` truncates the exact quotient; ps2-web-recomp divides in `double`
  and truncates that (can differ in rare cases; no vector hits one).

Where the references disagree (read, not run):

- **ps2-web-recomp's micro-mode VU path** (`vu_ops.hpp`, `vuops::`) uses
  host floats: round-to-nearest, inputs with exponent 255 clamped to
  0x7f7fffff, overflow → 0x7f7fffff. Its macro mode (what the pilot game uses)
  and FPU use the truncating soft-float in `fpu.hpp`, which matches our model.
- **Play!** `FpAddTruncate`/`FpMulTruncate` truncate like us but return
  IEEE inf/NaN for exponent 255 and keep denormal results; clamping must
  happen elsewhere in Play! (not checked).
- FCR31 flags: ps2-web-recomp sets bits 16–17 on `div.s` by zero and
  never clears them. Not modelled here (bit positions unconfirmed).

Not modelled (no vector needs it): FCR31 flag bits, VU0 status/MAC/clip
flags, `cfc2`/`ctc2` other than vi0–vi15 and vi22, Q latency (Q is ready at
once; vectors always use `vwaitq` like the game), the COP2 interlock bit
of `qmtc2`/`qmfc2`.

## T20 results (Oct 2026)

Harness: `recomp/tests/harness.py` + `recomp/tests/harness/` (C++, CMake),
run in WSL (clang 18.1.3, CMake 3.28.3, Ninja 1.11.1). No change to the
vendored code. Per case: our ELF writer puts the words at 0x00100000 (with a
`.text` section) and each `init` memory block in a data segment; `eerecomp`
translates it; a wrapper file renames the generated namespace so all cases
link into one `harness` binary with the real `ps2runtime` (dispatcher,
memory, COP2). The harness loads the init state, calls `dispatch`, prints
the end state as JSON; Python compares it with `ref.py`'s expected state
(same rules as L0: no other register or byte may change). Default run
(216 vectors + 500 random cases): ~85 s, most of it compiling.

Fixture adjustments (so a case looks like game code to `eerecomp`'s analysis):

- The code is followed by `j .; nop`; the run ends when that loop uses up
  the cycle budget. Without it, a jump to a trailing label (`END:`) points
  past the code and `eerecomp` rejects the jump-table targets that jump there
  (a game's branch target is always code). `b .` does not work: the
  tentative walk treats `beq zero,zero` as conditional and checks the
  fall-through, which is past the code. Not a problem in a game.
- GPR init values that point into the code are passed with `--entries`
  (4 `jr`/`jalr` vectors). A game has these as constants, or the port finds
  them by exploring (`port.py`). Jump-table targets are not passed: they
  must be found from the data segment, as in the game.
- `pc_trace` uses `eerecomp --probes`. A delay slot run inside its branch
  has no probe, so slot entries are left out of the expected trace (a slot =
  the entry right after a control-flow instruction, at +4).

Results (verified, `python3 recomp/tests/harness.py`):

- **L1: 215/216 vectors pass**, including all 34 marked unverified and all
  jump-table vectors (targets found in the data segment; the unbounded table
  too). Agreement on the unverified ones is not confirmation: ps2-web-recomp
  and our model follow the same readings (T18, T19); T21 decides.
- **L2: random cases match the model**: 500/500 (default, seed 1); also
  2,000/2,000 with seeds 1 and 2. One instruction per case on a fully random
  state (GPRs, HI/LO, FPU, VU0, 512 data bytes), operands and VU dest masks
  random, values biased to edges (0, ±max, denormals, exponent 255, 0x80000000).
  137 mnemonics (all but control flow, system, cop0, `cache`,
  `pref`, `vwaitq`), each at least 4 times per 2,000.
- **L3** (`--tables <SERIAL>`, local): all targets of the bounded census
  jump tables of the pilot game are entries of their unit's entry table;
  unbounded tables not checked (counts in the local game notes). The check
  discriminates: almost none of the target+4 addresses are entries.
- Mutation check (work script, not kept): `addu` without sign extension and
  a wrong last bit in the model's float multiply fail 15 of 300 random cases
  (`addu`, `vmul*`, `vmadd*`, `vmsub*`, `vopmula`).

The one difference:

- `break ends the case` (`system.json`): the runtime's `breakpoint()` logs
  and continues, so `v0` = 2 and the trace goes on past `break`.
  Classification: **unverified-behaviour disagreement**, not a translation
  bug. "A case ends at `break`" is our vector convention; on hardware `break`
  raises a Breakpoint exception, and what the PS2 kernel does then is
  unknown (T21 question). The pilot game's `break` sites are `break 7`
  divide guards; no `[ee] break at` line in the local T15/T16 run logs.

No recompiler bug and no model bug found. Not covered by L1/L2: `syscall`
and cop0 (runtime, P3), branch in a delay slot (not in the pilot game).

## T21 results (Oct 2026)

Oracle: `recomp/tests/oracle.py` (Windows Python) + PCSX2 **2.8.2** (the
installed version; MACHINE.md said 2.6.3) with the owner's BIOS (D18).
One test ELF holds every eligible vector: per case it loads the full start
state (GPRs 128-bit, HI/LO incl. HI1/LO1, FPRs, FCR31, VU0 vf/vi/Q, memory
windows), runs the vector's words, stores the end state and prints it as
hex through the EE SIO TX register (0x1000F180); PCSX2 writes that to its
log. PCSX2 is started with `-datapath work/recomp-tests/oracle/<mode>
-nogui -fastboot -logfile … -elf …` and killed when the program prints
`T21 END`, or 5 s after the log stops growing (a case that never returns;
the run then resumes after it). ~10 s per mode.

- Eligible: 181 of 216 vectors (all 34 unverified): no `j`/`jal`/`jr`/`jalr`
  or `pc_trace` (cases are moved to other addresses), no expected error,
  no k0/k1 (the dump code uses them), `sa`, `facc` or `acc` (not set or read).
  `break` runs on its own.
- The ELF starts in user mode with CU0–CU2 set (Status 0x70030c11); the
  program clears IE/EIE first (the kernel's interrupt handlers clobber k0/k1).
- Fixture fix: PCSX2 lost 4 bytes at file offset 0x40000 of a data segment
  whose file offset was 4 mod 16 (found by dumping memory). `harness.py`'s
  ELF writer now pads each segment's file offset to its address mod 16.
  L1 rerun after the change: unchanged.
- Modes (all with PCSX2's default FPU/VU rounding = chop, FPU divide rounding
  = nearest, normal clamping, unless named): `rec` (EE + VU0 recompilers,
  PCSX2 defaults), `rec-full` (`fpuFullMode`), `rec-divchop`
  (`FPUDiv.Roundmode` = chop), `interp` (EE and VU0 interpreters).

Sanity: the 147 verified vectors match in every mode except known PCSX2
approximations: `neg.s` of 0x7fffffff gives 0xff7fffff in `rec`/`rec-divchop`
(normal clamping clamps the operand); `lwl`+`lwr` of a negative word has
bits 32–63 cleared in the recompiler modes (see `lwr` below); in `interp`
`cfc2` returns all 32 bits written by `ctc2` to vi1 (no 16-bit mask) and
unaligned `lqc2` never returns (its 128-bit read does not mask the address;
the recompilers ignore the low bits as expected).

Results for the 34 unverified vectors (✓ = matches the vector):

| Question | rec | rec-full | rec-divchop | interp | Recorded |
|---|---|---|---|---|---|
| GPR bits 64–127 kept (`addu`, `or`, `ld`, `plzcw`), 4 vectors | ✓ | ✓ | ✓ | ✓ | `hw` |
| `div`/`divu` by zero, `0x80000000 / -1`, 4 vectors | ✓ | ✓ | ✓ | ✓ | `hw` |
| partial `lwr` keeps bits 32–63 | cleared | cleared | cleared | ✓ | `hw` (interp) |
| truncation: `add.s`, `mul.s`, `cvt.s.w`; `cvt.w.s` truncates and saturates, 4+1 vectors | ✓ | ✓ | ✓ | ✓ | `hw` |
| denormal inputs = 0, underflow → ±0 (`add.s`, `mul.s`), 3 vectors | ✓ | ✓ | ✓ | ✓ | `hw` |
| `sqrt.s`/`vsqrt` of a negative = sqrt(\|x\|), 2 vectors | ✓ | ✓ | ✓ | ✓ | `hw` |
| guard bit: 1 − 2⁻³⁰ = 1.0 | ✓ | ✓ | ✓ | 0x3f7fffff | `hw` (rec modes) |
| overflow → ±0x7fffffff, exponent 255 is a number, x/0 → ±max, `c.lt.s` above 0x7f800000, 8 vectors | 0x7f7fffff | ✓ | 0x7f7fffff | 0x7f7fffff | `hw` (rec-full) |
| VU0 `vadd` overflow / denormal / `vmul` truncation | ✓ | ✓ | ✓ | 0x7f7fffff | `hw` (rec modes) |
| `div.s` 1/3 truncates (0x3eaaaaaa) | 0x3eaaaaab | 0x3eaaaaab | ✓ | ✓ | open |
| `sqrt.s` sqrt(5) truncates (0x400f1bbc) | 0x400f1bbd | 0x400f1bbd | 0x400f1bbd | ✓ | open |
| `vrsqrt` 1/sqrt(6) truncates (0x3ed105eb) | 0x3ed105ec | 0x3ed105ec | 0x3ed105ec | 0x3ed105ec | open |
| `vrsqrt` of 0 → 0x7fffffff | 0x7f7fffff | 0x7f7fffff | 0x7f7fffff | 0x7f7fffff | open |
| `max.s` of ±0 returns fs | −0 both orders | +0 both | −0 both | +0 both | open |

Reading of the splits (PCSX2 source read, GPL-3, no code used):

- Exponent-255 range: only `fpuFullMode` emulates it; the other modes use
  host floats and clamp to the IEEE maximum, a documented approximation.
- `lwr`: PCSX2's `recLWR` merges in a 32-bit x86 register, which clears the
  upper half as a side effect (no comment says it is intended); the
  interpreter keeps the bits.
- `div.s`: PCSX2 defaults divide rounding to nearest, unlike its other FPU
  ops; with chop it agrees with us. Which one hardware does is the open
  question. `sqrt.s` rounds to nearest in every recompiler mode.
- VU0 `vrsqrt`: PCSX2 has no VU mode with chop for this op or with the
  extended range, so its answer may be its own limit.
- `max.s`: `rec` returns ft on a tie (SSE `maxss` rule); `rec-full` and
  `interp` order −0 below +0 (integer compare).

Open (5 vectors keep `unverified`, now with the PCSX2 results; `ref.py`
unchanged): owner decision whether PCSX2 or the current docs/models win
for `div.s` rounding, `sqrt.s` rounding, `vrsqrt` rounding and its 0 case,
and `max.s` of ±0. ps2-web-recomp follows our model on all five (T20), so
any change there is a recompiler change too. Settled in T24 (D19): our
model stays, the 5 stay unverified.

`break` (T20 question): in every mode the program **never returns** from
`break` (no further output in 5 s, no kernel message in the log). So the
kernel does not resume after a Breakpoint exception; our convention "a case
ends at `break`" matches, and **ps2-web-recomp differs** (logs and
continues). Recompiler difference, not fixed here (out of scope). Fixed in
T24: the runtime halts on `break`.

L0 after the vector changes: 13 tests OK, 216/216 (5 unverified). L1 (WSL):
215/216 (only `break`, as in T20), L2 500/500. No new recompiler difference:
the recompiler matches `ref.py` on every vector PCSX2 confirmed.

## T24 results (Oct 2026)

Owner decisions (D19):

- The 5 open float cases keep our model and stay `unverified`; their
  `unverified` notes keep PCSX2's per-mode results (table above) and now
  name D19. `ref.py` and the recompiler unchanged.
- Rule for mode-dependent PCSX2 results: `source: hw` when at least one
  PCSX2 mode agrees; the `oracle` note names the agreeing mode(s) and what
  the others give. The 29 T21 confirmations already follow it.
- `break` halts. Patch in the vendored runtime
  ([recomp/README.md](../recomp/README.md#vendored-upstream)): the generated
  code returns after `breakpoint()`, which logs
  `[ee] break at <pc> code <code> (ra <ra>)`, halts with reason
  `break <code> at <pc>` and unwinds; `ps2run` shuts down as for any halt
  (state dumps, `[ee] stopped after … : break …`) and exits with code 3.
  The harness ends a case at a `break` halt (pc = the `break` address, with
  the unwind bit, and a matching log line).

Results: L0 13 tests OK, 216/216 (5 unverified). L1 (WSL) **216/216**,
L2 500/500 (seed 1). The `break` case: v0 = 1, trace stops at the `break`,
log `[ee] break at 0x00100004 code 0x0 (ra 0x00000000)`. End to end
(WSL, work script): `ps2run` on a tiny ELF with `break 7` logs
`break at 0x00100004 code 0x7`, `halted: break 0x7 at 0x00100004`,
`stopped after 0 frames, 1 cycles: …` and exits with 3.

Pilot game (Windows, `port.py <SERIAL>`, full rebuild): every `break`
site in `generated/` is now `breakpoint(…); return;`. Explore run, 0 new
entry points; menu run stopped by the frame limit, no `[ee] break` line.
Frames looked at (save dialog, race intro). The WSL `ps2run` build with the
patch compiles (end-to-end check above).

## Levels

| Level | What | Needs | Task |
|---|---|---|---|
| L0 | Vectors pass on the Python reference model | Python only | T18 (integer), T19 (FPU/VU0): done |
| L1 | Vectors pass on the recompiler (harness) | C++ toolchain, recompiler | T20: done, 215/216; T24: 216/216 |
| L2 | Random differential: generated vectors, reference model vs recompiler | L1 | T20: done |
| L3 | Game level on the pilot game (local, `work/` only): whole ELF translates with no unsupported stop; recompiler's jump tables match `census.json`; boot progress | T15/T16 | T15, T20: done |
| L4 | Hardware oracle for `ps2-fpu` and other *(to confirm)* values | PCSX2 + owner's BIOS (D18) | T21: done, 29/34 PCSX2-confirmed |

## Fixtures and legal

- Every fixture is written by us: vectors in JSON, encoded by our assembler,
  wrapped in an ELF by our writer. No game bytes, no game code sequences
  copied as data (patterns like `beql a0,zero; lw a0,4(sp)` are generic
  MIPS and are re-written by hand). Game addresses appear only in notes.
- Generated C++ of fixtures is ours and may be committed if useful; generated
  C++ of the game never (legal.md).
- Expected values come from public instruction-set docs, written in our own
  words. Emulators (Play! BSD-2, ps2-web-recomp MIT) may be read for
  behaviour; PCSX2 (GPL-3) read only.

## Toolchain decision

Phase 5 tests **do not need the open ps2sdk toolchain** (D15): instruction
tests need exact instruction words, which our own assembler gives more
directly than a compiler. The C++ toolchain is the same one T15 needs (WSL
clang). ps2sdk becomes useful when we test the runtime (Phase 6: kernel
calls, SIF, file I/O) with self-made homebrew, or if T21 uses a real PS2
with a C test program. Installing it needs owner approval at that point.
