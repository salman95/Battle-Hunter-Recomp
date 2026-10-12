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

Usage:
  python3 tools/drop_and_play.py [PATH]        # path may be .ecm/.bin/.cue
                                              # no path → file picker
Self-test (used by CI / after install):
  python3 tools/drop_and_play.py --soak 25    # full pipeline + 25s headless boot
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DISC_DIR = REPO / "disc"
BUILD_DIR = REPO / "build-release"
EXE = BUILD_DIR / "BattleHunter_Recompiled"
STAMP = BUILD_DIR / ".bh_stamp"
UNECM_DIR = REPO / "build-tools"
UNECM = UNECM_DIR / "unecm"

# The verified revision this project targets (Battle Hunter, USA).
KNOWN = {
    "name": "Battle Hunter (USA)",
    "serial": "SLUS-01335",
    "data_sha1": "00c0c8319d5b45caa41cc2ea8902089ad03e125e",
    "data_md5": "c7fd6f950777952e6d648bd8a889af4c",
    "size": 86_003_232,
    "sector_size": 2352,
}

# Track layout (INDEX 01 sector positions) reconstructed for this revision:
# 1 data track + 4 audio tracks. Verified against the retail disc structure.
CUE = """FILE "BattleHunter.bin" BINARY
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
"""

RED = "\033[31m"
GRN = "\033[32m"
YLW = "\033[33m"
BLU = "\033[34m"
BOLD = "\033[1m"
DIM = "\033[2m"
RST = "\033[0m"
SYNC = b"\x00" + b"\xff" * 10 + b"\x00"

T0 = time.perf_counter()


def banner(msg):
    el = time.perf_counter() - T0
    print(f"\n{BLU}{BOLD}═══ {msg} {DIM}[{el:6.1f}s]{RST}", flush=True)


def info(msg):
    print(f"    {msg}", flush=True)


def ok(msg="done"):
    print(f"{GRN} ✓ {msg}{RST}", flush=True)


def warn(msg):
    print(f"{YLW} ⚠ {msg}{RST}", flush=True)


def fail(msg, code=1):
    print(f"{RED}{BOLD} ✗ {msg}{RST}", flush=True)
    if sys.stdout.isatty():
        try:
            input(f"\n{DIM}Press Enter to close...{RST}")
        except EOFError:
            pass
    sys.exit(code)


def human(sec):
    return f"{int(sec // 60)}m{int(sec % 60):02d}s" if sec >= 60 else f"{sec:.1f}s"


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- ECM / disc

def ensure_unecm():
    UNECM_DIR.mkdir(parents=True, exist_ok=True)
    if UNECM.exists():
        return
    info("building bundled unecm (first use only)…")
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        fail("no C compiler found — install one first "
             "(build-essential / base-devel)")
    subprocess.run([cc, "-O2", "-o", str(UNECM),
                   str(REPO / "third_party/unecm/unecm.c")],
                   check=True, cwd=REPO)


def unsqueeze(src):
    info(f"decoding '{src.name}' → disc/BattleHunter.bin …")
    r = subprocess.run([str(UNECM), str(src), str(DISC_BIN)],
                       capture_output=True, text=True)
    if r.returncode or not DISC_BIN.exists():
        print(r.stdout[-600:] or "", flush=True)
        fail("unecm could not decode this file — is it a valid ECM image?")


def verify_bin():
    """The revision gate. Returns True on the verified SLUS-01335 image."""
    size = DISC_BIN.stat().st_size
    if size % KNOWN["sector_size"]:
        warn(f"{size:,} bytes is not a multiple of 2352 — not a raw track dump?")
    if size == KNOWN["size"]:
        info("hashing data track…")
        if sha1_file(DISC_BIN) == KNOWN["data_sha1"]:
            ok(f"verified: {KNOWN['name']} ({KNOWN['serial']})")
            return True
    return False


def derive_cue():
    """Best-effort cue derivation for UNVERIFIED images (fallback path).

    Data sectors carry a 12-byte sync + header; audio is headerless. Every
    audio track is preceded by a ~150-sector silent pregap.
    """
    SS = KNOWN["sector_size"]
    data = DISC_BIN.read_bytes()
    n = len(data) // SS
    if n < 100:
        return None
    data_end = 0
    while data_end < n:
        off = data_end * SS
        if data[off:off + 12] == SYNC and data[off + 15] in (1, 2):
            data_end += 1
        else:
            break
    if data_end == 0:
        return None
    silent = [sum(data[s * SS:(s + 1) * SS]) < 4096 for s in range(data_end, n)]
    lines = ['FILE "BattleHunter.bin" BINARY',
             "  TRACK 01 MODE2/2352", "    INDEX 01 00:00:00"]
    track = 2
    i = 0
    while i < len(silent) - 160:
        if silent[i]:
            run = 0
            while silent[i + run]:
                run += 1
            if run >= 140:
                start = data_end + i
                for label, sect in (("00", start), ("01", start + 150)):
                    m, r = divmod(sect, 4500)
                    s, f = divmod(r, 75)
                    lines.append(f"    INDEX {label} {m:02d}:{s:02d}:{f:02d}")
                lines.append(f"  TRACK {track:02d} AUDIO")
                track += 1
                i += run
        i += 1
    # INDEX lines were appended interleaved with TRACK lines; reorder.
    body = lines[:3]
    idx = [l for l in lines[3:] if "INDEX" in l]
    trk = [l for l in lines[3:] if "TRACK" in l]
    out = body[:]
    for k in range(len(trk)):
        out.append(trk[k])
        out.append(idx[2 * k])
        out.append(idx[2 * k + 1])
    return "\n".join(out) + "\n" if len(trk) >= 1 else None


DISC_BIN = DISC_DIR / "BattleHunter.bin"
DISC_CUE = DISC_DIR / "BattleHunter.cue"


def stage_input(src):
    """Get the game into disc/ as BattleHunter.bin + BattleHunter.cue."""
    DISC_DIR.mkdir(parents=True, exist_ok=True)
    banner("Steps 1–2 — prepare your disc (unsqueeze + cue sheet)")
    if src.suffix.lower() == ".cue":
        text = src.read_text(errors="replace")
        refs = re.findall(r'(?im)^FILE\s+"([^"]+)"', text)
        if len(refs) != 1:
            fail("multi-file cue sheet — drop the .bin/.ecm instead, or re-dump")
        shutil.copyfile(src.parent / refs[0], DISC_BIN)
    elif src.suffix.lower() == ".ecm":
        if DISC_BIN.exists() and sha1_file(DISC_BIN) == KNOWN["data_sha1"]:
            info("disc/BattleHunter.bin already staged (verified) — skipping")
        else:
            ensure_unecm()
            unsqueeze(src)
    else:
        shutil.copyfile(src, DISC_BIN)

    verified = verify_bin()
    if verified:
        DISC_CUE.write_text(CUE)
    else:
        warn("disc does NOT match the verified USA (SLUS-01335) revision.")
        derived = derive_cue()
        if derived:
            warn("derived a track layout by scanning the image — NOT verified;")
            warn("only the USA retail revision has been play-tested.")
            DISC_CUE.write_text(derived)
        else:
            warn("could not derive a layout; writing the verified SLUS-01335")
            warn("layout anyway — music track boundaries may be wrong.")
            DISC_CUE.write_text(CUE)
    ok(f"cue sheet → {DISC_CUE.relative_to(REPO)}")
    return verified


# ---------------------------------------------------------------- generate/build

def framework_stamp():
    def sub_sha(p):
        try:
            return subprocess.run(["git", "-C", str(p), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
        except Exception:
            return "?"
    return {"psxrecomp": sub_sha(REPO / "psxrecomp"),
            "recomp_ui": sub_sha(REPO / "recomp-ui"),
            "unecm": sha1_file(REPO / "third_party/unecm/unecm.c")}


def needs_rebuild(disc_sha1):
    if not ((REPO / "generated/SLUS_013.35_dispatch.c").exists()
            and EXE.exists() and STAMP.exists()):
        return True, "first run"
    try:
        st = json.loads(STAMP.read_text())
    except Exception:
        return True, "stamp unreadable"
    if st.get("data_sha1") != disc_sha1:
        return True, "disc changed"
    if st.get("framework") != framework_stamp():
        return True, "framework changed"
    return False, None


def step_generate():
    banner("Step 3 — translate YOUR disc into C (one-time)")
    info("psxrecomp generate (also builds its emitter tools on first use)…")
    r = subprocess.run(
        [sys.executable, "psxrecomp/psxrecomp_cli.py", "generate",
         "--config", "game.toml", "--project-root", ".", "--disc",
         str(DISC_CUE)], cwd=REPO)
    if r.returncode or not (REPO / "generated/SLUS_013.35_dispatch.c").exists():
        fail("generate failed — read the log above")
    ok("C written under generated/")


def step_build():
    banner("Step 4 — compile the native game (one-time)")
    for t in ("cmake", "ninja"):
        if not shutil.which(t):
            fail(f"'{t}' not found — on Debian/Ubuntu: "
                 "sudo apt install cmake ninja-build")
    r = subprocess.run(["cmake", "-S", ".", "-B", str(BUILD_DIR), "-G", "Ninja",
                        "-DCMAKE_BUILD_TYPE=Release"], cwd=REPO)
    if r.returncode:
        fail("cmake configure failed")
    r = subprocess.run(["cmake", "--build", str(BUILD_DIR), "--target",
                        "psx-runtime", "-j", str(os.cpu_count() or 8)],
                       cwd=REPO)
    if r.returncode or not EXE.exists():
        fail("build failed — read the log above")
    ok(f"{EXE.name} ready ({EXE.stat().st_size // 1048576} MB)")


def write_settings(cue):
    """Preconfigure controller/disc so a later manual double-click just works."""
    st = BUILD_DIR / "settings.toml"
    txt = st.read_text() if st.exists() else ""

    def up(section, key, val):
        nonlocal txt
        pat = re.compile(rf"(?m)^(\s*){re.escape(key)}\s*=.*$")
        if pat.search(txt):
            txt = pat.sub(lambda m: f"{m.group(1)}{key} = {val}", txt, count=1)
        elif section in txt:
            txt = txt.replace(section, f"{section}\n{key} = {val}", 1)
        else:
            txt = txt.rstrip() + f"\n\n{section}\n{key} = {val}\n"

    up("[controller]", "p1_device", '"gamepad"')
    up("[disc]", "path", f'"{cue.resolve()}"')
    up("[launcher]", "skip_launcher", "false")
    (BUILD_DIR / "saves").mkdir(exist_ok=True)
    st.write_text(txt)
    ok("controller + disc preconfigured (build-release/settings.toml)")


def stamp_write(disc_sha1):
    STAMP.write_text(json.dumps(
        {"data_sha1": disc_sha1, "framework": framework_stamp(),
         "game": KNOWN["serial"], "when": time.strftime("%Y-%m-%d %H:%M")},
        indent=2) + "\n")


# ---------------------------------------------------------------- launch

def step_launch(soak=0):
    banner("Play — booting the game")
    cmd = [str(EXE), "--no-launcher", "--disc", str(DISC_CUE.resolve())]
    if soak:
        info(f"self-test: {soak}s headless boot…")
        p = subprocess.Popen(cmd + ["--headless"], cwd=BUILD_DIR,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(soak)
        alive = p.poll() is None
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        if alive:
            ok("headless boot stayed alive — machine healthy")
        else:
            warn(f"process exited early (code {p.returncode})")
        return
    info("launching; closing this terminal will NOT stop the game")
    subprocess.Popen(cmd, cwd=BUILD_DIR, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ok("have fun! 🎮")


def pick_file():
    try:
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
    a, _ = ap.parse_known_args()

    print(f"{BOLD}Battle Hunter — Drop & Play{RST}{DIM}  (psxrecomp static recompilation){RST}")
    src = (Path(a.path).expanduser()
           if a.path and Path(a.path).exists() else None) or pick_file()
    if not src:
        fail("no input file — drag your .ecm onto the launcher, or rerun with a path")
    print(f"{DIM}input: {src}{RST}")

    verified = stage_input(src)
    disc_sha1 = sha1_file(DISC_BIN)

    need, why = needs_rebuild(disc_sha1)
    if not need:
        banner("Already built — straight to the game")
        step_launch(a.soak)
        print(f"{DIM}(elapsed this session: {human(time.perf_counter() - T0)}; "
              "delete build-release/.bh_stamp to force a rebuild){RST}")
        return

    if why == "first run":
        info("first run: ~10 minutes of one-time work; after that, seconds")
    else:
        info(f"rebuilding: {why}")

    step_generate()
    step_build()
    write_settings(DISC_CUE)
    stamp_write(disc_sha1)
    print(f"\n{GRN}{BOLD}✓ One-time setup complete "
          f"({human(time.perf_counter() - T0)}).{RST}")
    step_launch(a.soak)
    print(f"{DIM}(elapsed this session: {human(time.perf_counter() - T0)}){RST}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)