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

## Quick start

**No checkout, no setup, no build** — download a release from the
**[Releases](../../releases)** page, then:

```sh
chmod +x BattleHunter-Recompiled-v*-x86_64.AppImage
./BattleHunter-Recompiled-v0.1.0-x86_64.AppImage   # opens the launcher
```

Two clicks and one file pick:

| | You do | What happens |
|---|---|---|
| **1 · Pick your dump** | on first run, point the launcher at your `BattleHunter.cue` / `.bin` | it verifies the supported USA revision (SLUS-01335) and remembers the path |
| **2 · Play** | press PLAY | boots the recompiled game — art, music and levels stream straight from **your** dump |

> **What did you download?** The recompiled *program* — the game's own logic, translated to C once
> (committed in this repo) and compiled by CI. What the download never contains is the game's
> *content*: your disc supplies it at runtime, and your dump never leaves your machine. See
> [Distribution model](#distribution-model--read-this-first).

Prefer the plain zip over an AppImage, or building from source?
[All routes](#steps-from-zero-to-playing).

## Screenshots

<sub>Captured from the recompiled game running natively on PC (software renderer, native 320×240
VRAM, upscaled 2×). *Battle Hunter* and its artwork remain the property of their original creators.</sub>

<p align="center">
<img src="docs/img/shot-title.png" width="31%" alt="Title screen"> <img src="docs/img/shot-menu.png" width="31%" alt="Main menu"> <img src="docs/img/shot-story.png" width="31%" alt="Story scene">
</p>
<p align="center"><sub>Title screen · main menu (OST playing) · story dialogue</sub></p>

---

## Distribution model — read this first

**Bundled releases** — the same model every [psxrecomp](https://github.com/mstan/psxrecomp) title
ships (the framework's `docs/ci/BUNDLED_RELEASES.md`):

- ✅ **committed & shipped:** the translated game C (`generated/`) and the compiled program built
  from it. CI packages the executable with its runtime data — players download and play; nothing
  is generated or compiled on their machine.
- ❌ **never shipped:** the disc image (`.bin`/`.cue`/`.ecm`), Sony's BIOS (the free OpenBIOS is
  bundled instead), memory cards, and any per-machine state. Your saves and settings stay yours.

The game's *content* — art, music, levels, everything the disc carries — is **not** in the download.
The runtime mounts **your own dump** at play time, checks it is the supported USA revision
(data-track SHA-1 `00c0c831…`), and streams from it. You must own the game to play it.

Developers regenerate that committed C from their own disc on a git checkout — see
[Developing](#developing-from-a-git-checkout) below.

## Requirements

- **To play:** an x86-64 Linux desktop (built on Ubuntu 24.04, so glibc ≥ 2.39: Ubuntu 24.04+,
  Debian 13+, Fedora 40+, Arch/CachyOS, Mint 22.x) with OpenGL. Nothing else — the AppImage
  carries its own SDL3.
- **Your own copy of Battle Hunter (USA)** — a `.cue`/`.bin` dump of your disc. The runtime checks
  it matches the supported revision (SLUS-01335) and tells you clearly if it differs.
- **To develop:** git, Python ≥ 3.11, CMake ≥ 3.20, Ninja, and a C/C++ compiler (CMake fetches SDL3
  itself; network once).

---

## Steps (from zero to playing)

### The easiest way — download and play

The [Releases](../../releases) page carries two artifacts with the same validated payload:

- **`BattleHunter-Recompiled-v<version>-x86_64.AppImage`** — one self-contained file:

  ```sh
  chmod +x BattleHunter-Recompiled-v*-x86_64.AppImage
  ./BattleHunter-Recompiled-v0.1.0-x86_64.AppImage
  ```

  First run stages the bundled game into `~/.local/share/BattleHunterRecomp` — your settings, memory
  cards and overlay captures live there and **survive updates** (override with `BH_DATADIR` or
  `XDG_DATA_HOME`).

- **`bh-<version>-linux-x64.zip`** — the same payload as a plain zip: extract, run
  `./BattleHunter_Recompiled`, and everything (settings, cards) is written next to the executable.

Either way, first run asks for your disc image — pick your `BattleHunter.cue` (a `.bin` dump works
the same), the launcher verifies the revision, remembers the path, and you press **PLAY**.

`.ecm` dumps need one unsqueeze step first (the runtime reads plain `.cue`/`.bin`) — the bundled
`unecm` details are under [Developing](#have-an-ecm-file-instead) below.

### Settings

Everything lives in the launcher (**Settings** tab):

- **Controls** — keyboard/gamepad per player (`p1_device = "gamepad"` = first connected pad, or pin
  a GUID in `settings.toml`).
- **Display** — window size, **aspect ratio (4:3 / 16:9)**, internal resolution (native through 8K
  or match-display), renderer, antialiasing, texture filtering, CRT filters, fullscreen
  (windowed / borderless / exclusive).
- **System / Audio** — BIOS, memory cards, volume, vsync, rewind.
- **Mods** — the bundled catalog ships with the release.

Changes apply on launch. "Skip launcher on boot" bypasses it once you're settled.

### Developing (from a git checkout)

A checkout builds the same game **straight from the committed C** — no disc, no generation:

```sh
git clone --recurse-submodules <this-repo-url> BattleHunterRecomp
cd BattleHunterRecomp
cmake -S . -B build-release -G Ninja -DCMAKE_BUILD_TYPE=Release -DPSXRECOMP_REQUIRE_GAME_C=ON
cmake --build build-release --target psx-runtime -j"$(nproc)"
./build-release/BattleHunter_Recompiled
```

On first run the launcher asks for the disc image — pick `disc/BattleHunter.cue` — or pass it:
`./build-release/BattleHunter_Recompiled --disc disc/BattleHunter.cue`.

#### Regenerating the committed C (needs your own disc)

Changing `game.toml`, the discovery `seeds/`, or the framework pin means the committed C has to be
regenerated — the one step that requires a disc. The terminal pipeline wraps
unsqueeze → verify → generate → build → launch:

```sh
python3 tools/drop_and_play.py "~/Downloads/BATTLE HUNTER.iso.ecm"   # .bin/.cue work too
# add --no-play to stop after the build
```

**Commit the regenerated `generated/` with your change** — releases build from the committed C, and
CI's `check_generated` gate refuses a checkout where it is absent or untracked.

### What "Recompile" actually does

One command, four phases — this is exactly what the terminal pipeline walks through:

| | Phase | In plain English |
|---|---|---|
| **Prepare** | Your `.ecm` is a *squeezed* disc image (error-correction bytes removed to shrink it). This phase un-squeezes it back to a raw disc image, then fingerprints it to confirm it's the genuine USA *Battle Hunter* disc — a different revision gets a warning, never a silent guess. |
| **Translate** | The PlayStation's machine code is read off **your** disc and rewritten as ordinary C source code, on your machine. This is the *recompilation* itself — nothing is downloaded. The result is what this repo commits under `generated/` and what releases build from. |
| **Compile** | A normal PC compiler turns that C into a normal executable — `BattleHunter_Recompiled` — just like compiling any other program. |
| **Finish** | Writes a **stamp**: it proves the build matches your disc + this framework, so re-running on an unchanged disc skips straight to the launch — that's why only the first run takes minutes. |

Things worth knowing:

- **It's fully automatic and one-time.** Watch the console scroll if you're curious; cancel if you
  change your mind. A fresh full run was measured at just under **2 minutes** on a fast desktop,
  ~10 minutes on an older laptop.
- **Your files, your machine.** The disc image is staged to `disc/BattleHunter.bin` + `.cue` (never
  modified), the generated C lands in `generated/` (committed), the game + saves live in `build-release/`.
  Nothing is uploaded anywhere.
- **Forcing a rebuild** — delete `build-release/.bh_stamp` (or just pick a different disc file and
  run the pipeline again); picking the same file again is always the fast path.
- **No build tools installed?** The pipeline downloads the framework's bundled toolchain
  (cmake/ninja/clang) on first use — one-time, needs network.

<p align="center">
<img src="docs/img/pipeline.png" width="88%" alt="The recompile pipeline (Drop &amp; Play): your disc image → unsqueeze (bundled unecm) → BIN + verified cue sheet → translate (psxrecomp: MIPS to C) → compile (cmake + gcc) → play (native executable)">
</p>

#### Releasing

CI builds and ships the compiled game ([release workflow](.github/workflows/release.yml)):
the gates (`check_boot_exe` / `check_generated` / `check_bios_stamps`), a Release build from the
committed C, then

- `scripts/package_release.sh build-ci linux-x64 build-recompiler` → `dist/bh-<version>-linux-x64.zip`
- `scripts/package_appimage.sh build-ci build-recompiler` →
  `dist/BattleHunter-Recompiled-v<version>-x86_64.AppImage`

both driving the framework packagers with this title's rendered inputs (`scripts/appimage/`).
Push a tag (`git tag v0.1.1 && git push origin v0.1.1`) or dispatch the workflow to publish.

<details>
<summary>Self-test (full pipeline + 25s headless boot):</summary>

```sh
python3 tools/drop_and_play.py "/path/to/BATTLE HUNTER.iso.ecm" --soak 25
```

</details>

#### Have an `.ecm` file instead?

ECM is a squeeze format that deletes a CD's recomputable error-correction bytes. The runtime reads
plain `.cue`/`.bin`, so unsqueeze first — the terminal pipeline does this for you; by hand:

```sh
# build unecm (Neill Corlett, GPL) from the canonical mirror of cmdpack
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

### Native overlays

Some scenes stream extra code modules off the disc into memory and run them. Two tiers handle them:

- **In every release:** a tiny built-in interpreter runs those fragments **correctly** (the framework's
  safety net), and the bundled `overlay_toolchain/` autocompiles anything you encounter into native
  plug-ins, keyed by the exact bytes it read from **your** disc — the runtime logs
  `overlay autocompile enabled (gcc)`. Nothing to set up.
- **Developers** can pre-compile everything they've already played into a cache (see
  `PSX_OVERLAY_CACHE_ROOT` in `scripts/package_release.sh`):

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

- **Players:** download the new release — your settings, memory cards and captures live in
  `~/.local/share/BattleHunterRecomp` (the zip: next to the executable) and are never touched.
- **Developers:** `git pull --recurse-submodules`, regenerate if the framework pin or config changed
  (`python3 tools/drop_and_play.py <your .ecm>`), rebuild, and commit the refreshed `generated/`.

## Troubleshooting

- **Where did my saves go?** — the AppImage keeps settings, memory cards and captures in
  `~/.local/share/BattleHunterRecomp`; the zip keeps them next to the executable.
- **"known disc digests do not match"** — your dump is a different revision/region. This project
  targets the USA release (SLUS-01335). Check the data track size: 86,003,232 bytes.
- **No audio** — check your system's pipewire/pulse setup; the runtime outputs via SDL3.
- **Black screen during loads only on an overloaded machine** — the game has disc-load timeouts;
  close heavy background load or don't run unthrottled debug builds during loads.
- **The launcher doesn't list your controller** — it appears as "8BitDo … Wireless" etc. in the
  Controls page after you press a button on it (USB dongles sleep).
- **16:9 shows black bars at the sides** — *Battle Hunter* is a 2D game: the Aspect setting changes
  the **window**, but the picture itself pillarboxes (the runtime never stretches 2D content).
  That is also why widescreen is a window choice here rather than a gameplay enhancement.

## Repository layout

```
game.toml            config the generator/runtime read (disc identity, seeds, quirks)
seeds/               function addresses used as translation discovery hints
codegen_setup.c/.h   title-side codegen hooks
CMakeLists.txt       thin build glue (adds the runtime target)
scripts/
  package_release.sh    zip packager (drives psxrecomp/tools/package_game_release.sh)
  package_appimage.sh   AppImage packager (drives psxrecomp/tools/package_appimage.sh)
  appimage/AppRun + battle-hunter-recompiled.desktop   the AppImage's rendered inputs
tools/
  bh_pipeline.py      the developer pipeline library (unsqueeze → verify → generate → build)
  drop_and_play.py   the terminal front-end over the same pipeline (regeneration)
  sync_symbols.py, make_pipeline_diagram.py   dev utilities
psxrecomp/           submodule → the framework (pinned)
recomp-ui/           submodule → the launcher UI (pinned)
docs/                the plain-English PDF report + img/ (screenshots, pipeline diagram)
generated/          the translated game C — COMMITTED (releases ship the compiled game)
disc/                (NOT committed — your dump goes here)
```

## Credits & legal

- **psxrecomp** — mstan and the RetroPortingToolkit community (framework + runtime).
- **OpenBIOS** — the PCSX-Redux project (bundled by the framework; MIT).
- **unecm** — Neill Corlett (ECM disc format, GPL).
- *Battle Hunter* is the property of its original developers and publisher. This project ships the
  translated *program* but no game *content*: art, music and data stream from a disc you must own, at
  runtime. It is a personal-use translation of a personally-owned copy. No affiliation with or
  endorsement by the rights holders.