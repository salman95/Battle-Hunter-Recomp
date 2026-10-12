#!/usr/bin/env python3
"""Drop & Play — one-click bring-up for Battle Hunter (SLUS-01335), no emulator.

Give this tool your game file — drag it onto the desktop launcher (KDE),
right-click → "Open With" (GNOME), or pass it as an argument — and it:

  1. unsqueezes  .ecm → .bin      (builds the bundled unecm on first use)
  2. reconstructs the .cue sheet  (verified 5-track layout for SLUS-01335)
  3. translates  YOUR disc into C (psxrecomp "generate"; builds its tools)
  4. compiles the native game     (cmake + ninja, ~3 min)
  5. boots straight into gameplay (--no-launcher --disc <your cue>)

Nothing game-derived is shipped in this repository — steps 3–4 rebuild all of
it locally, from your file. Repeat runs are fast: a stamp tracks your disc +
framework, and unchanged means straight to step 5.

Prefer a GUI with a progress bar and a console window? Run the launcher:

  python3 tools/launcher_gui.py

Usage:
  python3 tools/drop_and_play.py [PATH]        # path may be .ecm/.bin/.cue
                                              # no path → file picker
  python3 tools/drop_and_play.py PATH --no-play  # build, don't auto-launch
Self-test (used by CI / after install):
  python3 tools/drop_and_play.py --soak 25    # full pipeline + 25s headless boot
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bh_pipeline as bh  # noqa: E402

RED = "\033[31m"
GRN = "\033[32m"
YLW = "\033[33m"
BLU = "\033[34m"
BOLD = "\033[1m"
DIM = "\033[2m"
RST = "\033[0m"

T0 = time.perf_counter()


def human(sec):
    return f"{int(sec // 60)}m{int(sec % 60):02d}s" if sec >= 60 else f"{sec:.1f}s"


class TerminalReporter(bh.Reporter):
    """Same pretty terminal output the tool always had."""

    def banner(self, msg):
        el = time.perf_counter() - T0
        print(f"\n{BLU}{BOLD}═══ {msg} {DIM}[{el:6.1f}s]{RST}", flush=True)

    def info(self, msg):
        print(f"    {msg}", flush=True)

    def ok(self, msg="done"):
        print(f"{GRN} ✓ {msg}{RST}", flush=True)

    def warn(self, msg):
        print(f"{YLW} ⚠ {msg}{RST}", flush=True)

    def progress(self, pct, message=""):
        pass  # progress lives in the GUI; the banners above carry it here

    def console(self, line):
        if line:
            print(f"{DIM}│{RST} {line}", flush=True)


def fail(msg, code=1):
    print(f"{RED}{BOLD} ✗ {msg}{RST}", flush=True)
    if sys.stdout.isatty():
        try:
            input(f"\n{DIM}Press Enter to close...{RST}")
        except EOFError:
            pass
    sys.exit(code)


def pick_file():
    try:
        import subprocess
        r = subprocess.run(
            ["zenity", "--file-selection", "--title",
             "Pick your Battle Hunter disc image", "--file-filter",
             "Disc images | *.ecm *.bin *.cue"],
            capture_output=True, text=True)
        p = (r.stdout or "").strip()
        if p and Path(p).exists():
            return Path(p)
    except FileNotFoundError:
        pass
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        p = filedialog.askopenfilename(
            title="Pick your Battle Hunter disc image",
            filetypes=[("Disc images", ("*.ecm", "*.bin", "*.cue"))])
        root.destroy()
        if p:
            return Path(p)
    except Exception:
        pass
    try:
        p = input("Path to your .ecm/.bin/.cue: ").strip().strip("'\"")
        return Path(p) if p else None
    except EOFError:
        return None


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("path", nargs="?", type=str)
    ap.add_argument("--soak", type=int, default=0,
                    help="self-test: run headless for N seconds instead of playing")
    ap.add_argument("--no-play", action="store_true",
                    help="stop after the build; don't launch the game")
    a, _ = ap.parse_known_args()

    print(f"{BOLD}Battle Hunter — Drop & Play{RST}"
          f"{DIM}  (psxrecomp static recompilation){RST}")
    src = (Path(a.path).expanduser()
           if a.path and Path(a.path).exists() else None) or pick_file()
    if not src:
        fail("no input file — drag your .ecm onto the launcher, or rerun with a path")
    print(f"{DIM}input: {src}{RST}")

    rep = TerminalReporter()
    try:
        bh.run_pipeline(src, rep, auto_launch=not a.no_play, soak=a.soak)
    except bh.PipelineError as e:
        fail(str(e))
    print(f"{DIM}(elapsed this session: "
          f"{human(time.perf_counter() - T0)}){RST}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
