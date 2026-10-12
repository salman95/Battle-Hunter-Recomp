# Battle Hunter, Recompiled

A **static recompilation** port of *Battle Hunter* (PlayStation, USA, serial **SLUS-01335**) to a native PC
program, built on [psxrecomp](https://github.com/mstan/psxrecomp) and
[recomp-ui](https://github.com/RetroPortingToolKit/recomp-ui).

The game's MIPS R3000A machine code is translated **once, ahead of time** into C, which is compiled by an
ordinary PC compiler into a normal executable. No emulator runs the game — the game's own logic executes
directly as x86-64 instructions, on a runtime that re-implements the console's other chips (GPU, SPU, CD
drive, GTE). Even the kernel is real: the free OpenBIOS is recompiled alongside the game.

Verified in play: boot → menus → battles → **game over** → save & load, with the disc's four CD-audio
music tracks playing at the right moments, on a real 8BitDo controller.

| | |
|---|---|
| Players | 2 |
| Region | USA (SLUS-01335) |
| Original | *Battle Hunter*, PlayStation, c. 2000 |

📖 **[docs/Battle-Hunter-Recomp-Explained.pdf](docs/Battle-Hunter-Recomp-Explained.pdf)** — a
plain-English explanation of the whole project (how the disc layout was reconstructed, how the
translation works, how it was tested).

---

## Distribution model — read this first

**This repository contains no game content.** Nothing derived from the copyrighted disc is committed:

- ❌ not the disc image (`.bin`/`.cue`/`.ecm`)
- ❌ not the translated game C (regenerated **on your machine** from **your** disc — see below)
- ❌ not captured overlay bytes, save data, or Sony's BIOS (the free OpenBIOS is bundled by the framework instead)

What *is* here: the config (`game.toml`), glue code, function *addresses* used as discovery seeds, disc
digests (to verify you have the right revision), the CMake scaffolding, and this documentation. Addresses
and digests are facts about the binary, not expression — this is the same metadata every public recomp
project ships.

The consequence: **you supply the game, you run the generator, you build.** It's a few minutes of fully
automated work, all documented below.

## Requirements

- **git**, **Python ≥ 3.11**, **CMake ≥ 3.20**, **Ninja**, and a C/C++ compiler (the recompiler is
  C++20; the runtime is C99/C++17). On Debian/Ubuntu: `sudo apt install git build-essential cmake
  ninja-build python3`. On Arch: `sudo pacman -S git base-devel cmake ninja python`.
- SDL3 — fetched automatically by CMake if no system package is found (network required once).
- **Your own copy of Battle Hunter (USA)**. The build checks that your disc matches the supported
  revision (data track SHA-1 `00c0c831…`, 86,003,232 bytes) — if yours differs, the generator will
  tell you instead of guessing.

---

## Steps (from zero to playing)

```sh
# 1. Clone with submodules (the framework + launcher are pinned gitlinks)
git clone --recurse-submodules <this-repo-url> BattleHunterRecomp
cd BattleHunterRecomp

# 2. Provide your disc. Put a BIN/CUE dump at disc/BattleHunter.cue + disc/BattleHunter.bin.
#    From your own original disc, e.g. with any standard dump tool.
mkdir -p disc && cp /path/to/your/dump.cue disc/BattleHunter.cue
cp /path/to/your/dump.bin disc/BattleHunter.bin
```

<details>
<summary>Have a <code>.ecm</code> file instead (like the original this project was built from)? Click for the extra unsqueeze step.</summary>

ECM is a squeeze format that deletes a CD's recomputable error-correction bytes. Unsqueeze it with
Neill Corlett's `unecm` (GPL, 2002):

```sh
# build unecm from the canonical mirror of cmdpack
curl -sfLO https://raw.githubusercontent.com/qeedquan/ecm/master/unecm.c
gcc -O2 -o unecm unecm.c && ./unecm "BATTLE HUNTER.iso.ecm" BattleHunter.bin
```

Then write `disc/BattleHunter.cue` with this track layout (reconstructed for this revision — one data
track, four audio):

```
FILE "BattleHunter.bin" BINARY
  TRACK 01 MODE2/2352
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    INDEX 00 00:55:55
    INDEX 01 00:57:55
  TRACK 03 AUDIO
    INDEX 00 02:29:26
    INDEX 01 02:31:26
  TRACK 04 AUDIO
    INDEX 00 03:59:05
    INDEX 01 04:01:05
  TRACK 05 AUDIO
    INDEX 00 05:28:59
    INDEX 01 05:30:59
```

</details>

```sh
# 3. Translate YOUR disc into C (the repo ships no generated code — this makes it).
#    Builds the recompiler emitters if needed, then emits the game + OpenBIOS C.
python3 psxrecomp/psxrecomp_cli.py generate \
    --config game.toml --project-root . --disc disc/BattleHunter.cue

# 4. Compile the game into a native executable (~2–3 minutes)
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build-release --target psx-runtime -j"$(nproc)"

# 5. Play
./build-release/BattleHunter_Recompiled
```

On first run the launcher asks for the disc image — pick `disc/BattleHunter.cue`. Set your controller
under **Controls** (or see below). That's it: what you're playing is a normal PC program.

### Optional: native overlays (recommended after your first session)

Some scenes stream extra code modules off the disc into memory and run them. Until you compile them,
a tiny built-in interpreter runs those fragments **correctly** (it's the framework's safety net), just
not as translated code. Two commands arm the automatic compiler tier so they become native plug-ins:

```sh
# stage the bundled overlay toolchain next to the game (one-time)
python3 psxrecomp/tools/release_stage.py stage-toolchain \
    --stage build-release \
    --recomp-dir psxrecomp/recompiler/build \
    --recomp-tools psxrecomp/tools \
    --recomp-include psxrecomp/runtime/include \
    --dl-cache ~/.cache/bh-dl --platform linux
```

(The `generate` step in **step 3** builds the emitter binaries under
`psxrecomp/recompiler/build/` — that's the path above.) On the next launch the
runtime logs `overlay autocompile enabled (gcc)` and quietly turns anything
you encounter into native code, keyed by the exact bytes it saw. You can also
pre-compile everything you've already played:

```sh
python3 psxrecomp/overlay_toolchain/compile_overlays.py \
    --captures build-release/overlay_captures.json --game-toml game.toml \
    --recompiler psxrecomp/recompiler/build/psxrecomp-game \
    --runtime-include psxrecomp/runtime/include \
    --out-dir build-release/cache
```

### Controls

Keyboard (defaults): arrows = D-pad · **X = Cross** · S = Circle · Z = Square · A = Triangle ·
**Enter = Start** · Right Shift = Select · Q/E/W/R = L1/L2/R1/R2. Controllers work directly (or via
the launcher's Controls page). In `settings.toml` (written by the launcher), `p1_device = "gamepad"`
means "first connected pad", or pin a specific one by GUID.

### Updating

`git pull --recurse-submodules`, then re-run steps 3–4 (the generator is incremental; unchanged shards
are reused).

## Troubleshooting

- **"known disc digests do not match"** — your dump is a different revision/region. This project
  targets the USA release (SLUS-01335). Check the data track size: 86,003,232 bytes.
- **No audio** — check your system's pipewire/pulse setup; the runtime outputs via SDL3.
- **Black screen during loads only on an overloaded machine** — the game has disc-load timeouts;
  close heavy background load or don't run unthrottled debug builds during loads.
- **The launcher doesn't list your controller** — it appears as "8BitDo … Wireless" etc. in the
  Controls page after you press a button on it (USB dongles sleep).

## Repository layout

```
game.toml            config the generator/runtime read (disc identity, seeds, quirks)
seeds/               function addresses used as translation discovery hints
codegen_setup.c/.h   title-side codegen hooks
CMakeLists.txt       thin build glue (adds the runtime target)
psxrecomp/           submodule → the framework (pinned)
recomp-ui/           submodule → the launcher UI (pinned)
docs/                the plain-English PDF report
generated/          (NOT committed — you create it in step 3)
disc/                (NOT committed — your dump goes here)
```

## Credits & legal

- **psxrecomp** — mstan and the RetroPortingToolkit community (framework + runtime).
- **OpenBIOS** — the PCSX-Redux project (bundled by the framework; MIT).
- **unecm** — Neill Corlett (ECM disc format, GPL).
- *Battle Hunter* is the property of its original developers and publisher. This project is a
  personal-use translation of a personally-owned copy: the repo distributes no game content,
  and you must supply your own disc. No affiliation with or endorsement by the rights holders.