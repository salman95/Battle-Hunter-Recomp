#!/usr/bin/env python3
"""bh_pipeline — the Battle Hunter bring-up pipeline as a library.

Everything Drop & Play and the GUI launcher need, in one place:

  1. prepare   your game file (.ecm/.bin/.cue) → disc/BattleHunter.{bin,cue}
               (builds the bundled unecm on first use, verifies the disc)
  2. generate  translate YOUR disc into C    (psxrecomp generate)
  3. build     compile the native game       (cmake + ninja)
  4. play      boot it

Front-ends drive it through a Reporter (see below) so both a terminal and a
GUI can show the same steps with live progress:

    import bh_pipeline as bh

    class MyReporter(bh.Reporter):
        def progress(self, pct, message=""): ...   # pct is 0..1, or None → indeterminate
        def console(self, line): ...               # raw line from a sub-process

    bh.run_pipeline(Path("BATTLE HUNTER.iso.ecm"), MyReporter(),
                    cancel=bh.CancelToken(), auto_launch=False)

run_pipeline() raises PipelineError on failure and Cancelled if the cancel
token was tripped mid-step. Nothing game-derived ships in this repository —
steps 2–3 rebuild all of it locally, from the user's file.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DISC_DIR = REPO / "disc"
BUILD_DIR = REPO / "build-release"
EXE = BUILD_DIR / "BattleHunter_Recompiled"
STAMP = BUILD_DIR / ".bh_stamp"
SETTINGS = BUILD_DIR / "settings.toml"
UNECM_DIR = REPO / "build-tools"
UNECM = UNECM_DIR / "unecm"
DISC_BIN = DISC_DIR / "BattleHunter.bin"
DISC_CUE = DISC_DIR / "BattleHunter.cue"

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

SYNC = b"\x00" + b"\xff" * 10 + b"\x00"

# Overall progress spans for the whole pipeline (0..1). Weights approximate
# real durations: unsqueeze ≈ 30 s, generate ≈ 4–6 min, build ≈ 2–3 min.
SPAN_PREP = (0.00, 0.08)
SPAN_GEN = (0.08, 0.55)
SPAN_BUILD = (0.55, 0.95)
SPAN_END = (0.95, 1.00)


class PipelineError(Exception):
    """A step failed; the message is user-presentable."""


class Cancelled(PipelineError):
    """The user tripped the cancel token mid-step."""


class CancelToken:
    """Thread-safe, one-way 'stop' switch shared with all sub-processes."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled("cancelled by user")


class Reporter:
    """Base reporter: swallow everything. Subclass for a terminal or a GUI.

    pct semantics in progress(pct, message): overall pipeline fraction 0..1;
    pct None means indeterminate (GUIs should pulse).
    """

    def banner(self, msg: str) -> None:  # a step boundary
        pass

    def info(self, msg: str) -> None:
        pass

    def ok(self, msg: str = "done") -> None:
        pass

    def warn(self, msg: str) -> None:
        pass

    def progress(self, pct, message: str = "") -> None:  # pct: float | None
        pass

    def console(self, line: str) -> None:  # raw sub-process output line
        pass


def _lerp(span: tuple[float, float], t: float) -> float:
    lo, hi = span
    return lo + max(0.0, min(1.0, t)) * (hi - lo)


def _popen(cmd, **kw) -> subprocess.Popen:
    """Popen in its own session so a cancel can kill the whole tree."""
    kw.setdefault("start_new_session", True)
    return subprocess.Popen(cmd, **kw)


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, 15)
    except (ProcessLookupError, PermissionError, OSError):
        proc.terminate()


# ---------------------------------------------------------------- hashing

def sha1_file(path: Path, progress=None) -> str:
    """SHA-1 of a file; progress(done, total) is optional (chunked)."""
    h = hashlib.sha1()
    total = path.stat().st_size
    done = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            done += len(chunk)
            if progress and (done % (16 << 20) < (1 << 20) or done == total):
                progress(done, total)
    return h.hexdigest()


# ---------------------------------------------------------------- ECM / disc

def ensure_unecm(rep: Reporter) -> None:
    UNECM_DIR.mkdir(parents=True, exist_ok=True)
    if UNECM.exists():
        return
    rep.info("building bundled unecm (first use only)…")
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        raise PipelineError("no C compiler found — install one first "
                            "(build-essential / base-devel)")
    r = subprocess.run([cc, "-O2", "-o", str(UNECM),
                        str(REPO / "third_party/unecm/unecm.c")],
                       capture_output=True, text=True)
    if r.returncode or not UNECM.exists():
        raise PipelineError("could not build the bundled unecm")


def unsqueeze(src: Path, rep: Reporter, cancel: CancelToken | None = None) -> None:
    """Decode .ecm → disc/BattleHunter.bin, streaming unecm's % progress."""
    rep.info(f"decoding '{src.name}' → disc/BattleHunter.bin …")
    proc = _popen([str(UNECM), str(src), str(DISC_BIN)], stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE)
    assert proc.stderr is not None
    tail = collections.deque(maxlen=15)

    def reader() -> None:
        last_pct = -1
        buf = b""
        try:
            while True:
                chunk = proc.stderr.read1(4096)
                if not chunk:
                    break
                buf += chunk
                parts = re.split(rb"[\r\n]", buf)
                buf = parts.pop()  # keep the trailing partial
                for raw in parts:
                    line = raw.decode("latin-1").strip()
                    if not line:
                        continue
                    tail.append(line)
                    m = re.search(r"Decoding \((\d+)%\)", line)
                    if m:
                        pct = int(m.group(1))
                        if pct != last_pct:
                            last_pct = pct
                            rep.progress(_lerp(SPAN_PREP, pct / 100 * 0.8),
                                         f"Unsqueezing ECM — {pct}%")
                            if pct % 10 == 0:
                                rep.console(f"unecm: decoding {pct}%")
                    elif not line.startswith("Decoding"):
                        rep.console(f"unecm: {line}")
        except OSError:
            pass

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    while proc.poll() is None:
        if cancel and cancel.cancelled:
            _kill(proc)
            raise Cancelled("cancelled while unsqueezing")
        time.sleep(0.05)
    th.join(timeout=2)
    if proc.returncode or not DISC_BIN.exists():
        raise PipelineError(
            "unecm could not decode this file — is it a valid ECM image? "
            + (" | ".join(tail)))


def verify_bin(rep: Reporter, cancel: CancelToken | None = None) -> bool:
    """The revision gate. Returns True on the verified SLUS-01335 image."""
    cancel and cancel.check()
    size = DISC_BIN.stat().st_size
    if size % KNOWN["sector_size"]:
        rep.warn(f"{size:,} bytes is not a multiple of 2352 — "
                 "not a raw track dump?")
    if size == KNOWN["size"]:
        rep.info("hashing data track…")

        def prog(done, total):
            rep.progress(_lerp(SPAN_PREP, 0.8 + 0.2 * done / total),
                         "Verifying disc…")

        if sha1_file(DISC_BIN, prog) == KNOWN["data_sha1"]:
            rep.ok(f"verified: {KNOWN['name']} ({KNOWN['serial']})")
            return True
    return False


def derive_cue() -> str | None:
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


def stage_input(src: Path, rep: Reporter,
                cancel: CancelToken | None = None) -> bool:
    """Get the game into disc/ as BattleHunter.bin + BattleHunter.cue."""
    DISC_DIR.mkdir(parents=True, exist_ok=True)
    rep.banner("Steps 1–2 — prepare your disc (unsqueeze + cue sheet)")
    rep.progress(SPAN_PREP[0], "Preparing disc…")
    if src.suffix.lower() == ".cue":
        text = src.read_text(errors="replace")
        refs = re.findall(r'(?im)^FILE\s+"([^"]+)"', text)
        if len(refs) != 1:
            raise PipelineError("multi-file cue sheet — drop the .bin/.ecm "
                                "instead, or re-dump")
        shutil.copyfile(src.parent / refs[0], DISC_BIN)
    elif src.suffix.lower() == ".ecm":
        if DISC_BIN.exists() and sha1_file(DISC_BIN) == KNOWN["data_sha1"]:
            rep.info("disc/BattleHunter.bin already staged (verified) — skipping")
        else:
            ensure_unecm(rep)
            unsqueeze(src, rep, cancel)
    else:
        rep.info(f"copying '{src.name}' → disc/BattleHunter.bin …")
        shutil.copyfile(src, DISC_BIN)

    verified = verify_bin(rep, cancel)
    if verified:
        DISC_CUE.write_text(CUE)
    else:
        rep.warn("disc does NOT match the verified USA (SLUS-01335) revision.")
        derived = derive_cue()
        if derived:
            rep.warn("derived a track layout by scanning the image — NOT verified;")
            rep.warn("only the USA retail revision has been play-tested.")
            DISC_CUE.write_text(derived)
        else:
            rep.warn("could not derive a layout; writing the verified SLUS-01335")
            rep.warn("layout anyway — music track boundaries may be wrong.")
            DISC_CUE.write_text(CUE)
    rep.ok(f"cue sheet → {DISC_CUE.relative_to(REPO)}")
    rep.progress(SPAN_PREP[1], "Disc prepared")
    return verified


# ---------------------------------------------------------------- generate/build

def framework_stamp() -> dict:
    def sub_sha(p):
        try:
            return subprocess.run(["git", "-C", str(p), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
        except Exception:
            return "?"
    return {"psxrecomp": sub_sha(REPO / "psxrecomp"),
            "recomp_ui": sub_sha(REPO / "recomp-ui"),
            "unecm": sha1_file(REPO / "third_party/unecm/unecm.c")}


def needs_rebuild(disc_sha1: str) -> tuple[bool, str | None]:
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


def disc_staged_sha1() -> str | None:
    """SHA-1 of the staged bin, or None if no disc is staged yet."""
    try:
        return sha1_file(DISC_BIN)
    except OSError:
        return None


def pipeline_state() -> dict:
    """Snapshot for UIs: what is staged / built, and why a rebuild is needed."""
    sha = disc_staged_sha1()
    need, why = needs_rebuild(sha) if sha else (True, "no disc staged")
    return {"disc_sha1": sha,
            "disc_staged": sha is not None,
            "verified": sha == KNOWN["data_sha1"],
            "exe_ready": EXE.exists(),
            "needs_rebuild": need,
            "why": why}


def step_generate(rep: Reporter, cancel: CancelToken | None = None) -> None:
    rep.banner("Step 3 — translate YOUR disc into C (one-time)")
    rep.progress(SPAN_GEN[0], "Generating C (psxrecomp)…")
    rep.info("psxrecomp generate (also builds its emitter tools on first use)…")
    cmd = [sys.executable, "psxrecomp/psxrecomp_cli.py", "generate",
           "--config", "game.toml", "--project-root", ".", "--disc",
           str(DISC_CUE), "--json-progress"]
    proc = _popen(cmd, cwd=REPO, stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, text=True, bufsize=1)
    assert proc.stdout is not None and proc.stderr is not None
    tail = collections.deque(maxlen=30)
    stop = threading.Event()

    def stderr_reader() -> None:
        try:
            for line in proc.stderr:
                tail.append(line.rstrip())
        except (OSError, ValueError):
            pass
        finally:
            stop.set()

    threading.Thread(target=stderr_reader, daemon=True).start()
    assert proc.stdout is not None
    for line in proc.stdout:
        if cancel and cancel.cancelled:
            _kill(proc)
            raise Cancelled("cancelled during generate")
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            rep.console(line)
            continue
        kind = ev.get("event")
        if kind == "phase":
            pct = ev.get("pct")
            msg = ev.get("message") or ev.get("phase") or ""
            rep.progress(_lerp(SPAN_GEN, pct if pct is not None else 0.0),
                         f"Generating C — {msg}" if msg else "Generating C…")
        elif kind == "log":
            m = ev.get("message")
            if m:
                rep.console(m)
        elif kind == "error":
            rep.console(f"error: {ev.get('message', '')}")
    rc = proc.wait()
    stop.wait(timeout=2)
    if rc or not (REPO / "generated/SLUS_013.35_dispatch.c").exists():
        raise PipelineError("generate failed — read the log above"
                            + (f" | last: {' | '.join(list(tail)[-3:])}"
                               if tail else ""))
    rep.ok("C written under generated/")
    rep.progress(SPAN_GEN[1], "C generated")


def step_build(rep: Reporter, cancel: CancelToken | None = None) -> None:
    rep.banner("Step 4 — compile the native game (one-time)")
    for t in ("cmake", "ninja"):
        if not shutil.which(t):
            raise PipelineError(f"'{t}' not found — on Debian/Ubuntu: "
                                "sudo apt install cmake ninja-build")
    rep.progress(None, "Configuring (cmake)…")
    proc = _popen(["cmake", "-S", ".", "-B", str(BUILD_DIR), "-G", "Ninja",
                   "-DCMAKE_BUILD_TYPE=Release"], cwd=REPO,
                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                  bufsize=1)
    assert proc.stdout is not None
    for line in proc.stdout:
        if cancel and cancel.cancelled:
            _kill(proc)
            raise Cancelled("cancelled during configure")
        rep.console(line.rstrip())
    if proc.wait():
        raise PipelineError("cmake configure failed")

    rep.progress(SPAN_BUILD[0], "Compiling (ninja)…")
    proc = _popen(["cmake", "--build", str(BUILD_DIR), "--target",
                   "psx-runtime", "-j", str(os.cpu_count() or 8)], cwd=REPO,
                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                  bufsize=1)
    assert proc.stdout is not None
    ninja = re.compile(r"\[(\d+)/(\d+)\]")
    for line in proc.stdout:
        if cancel and cancel.cancelled:
            _kill(proc)
            raise Cancelled("cancelled during build")
        m = ninja.search(line)
        if m:
            k, n = int(m.group(1)), int(m.group(2))
            rep.progress(_lerp(SPAN_BUILD, k / n if n else 0.9),
                         f"Compiling — {k}/{n}")
        rep.console(line.rstrip())
    rc = proc.wait()
    if rc or not EXE.exists():
        raise PipelineError("build failed — read the log above")
    rep.ok(f"{EXE.name} ready ({EXE.stat().st_size // 1048576} MB)")


def write_settings(rep: Reporter) -> None:
    """Preconfigure controller/disc so a later manual double-click just works."""
    rep.progress(_lerp(SPAN_END, 0.3), "Writing settings…")
    txt = SETTINGS.read_text() if SETTINGS.exists() else ""

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
    up("[disc]", "path", f'"{DISC_CUE.resolve()}"')
    up("[launcher]", "skip_launcher", "false")
    (BUILD_DIR / "saves").mkdir(exist_ok=True)
    SETTINGS.write_text(txt)
    rep.ok("controller + disc preconfigured (build-release/settings.toml)")


def stamp_write(disc_sha1: str, rep: Reporter) -> None:
    STAMP.write_text(json.dumps(
        {"data_sha1": disc_sha1, "framework": framework_stamp(),
         "game": KNOWN["serial"], "when": time.strftime("%Y-%m-%d %H:%M")},
        indent=2) + "\n")
    rep.progress(1.0, "Done")


# ---------------------------------------------------------------- launch

def game_cmd() -> list[str]:
    return [str(EXE), "--no-launcher", "--disc", str(DISC_CUE.resolve())]


def launch_game(rep: Reporter, soak: int = 0) -> None:
    rep.banner("Play — booting the game")
    cmd = game_cmd()
    if soak:
        rep.info(f"self-test: {soak}s headless boot…")
        p = _popen(cmd + ["--headless"], cwd=BUILD_DIR,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(soak)
        alive = p.poll() is None
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        if alive:
            rep.ok("headless boot stayed alive — machine healthy")
        else:
            rep.warn(f"process exited early (code {p.returncode})")
        return
    rep.info("launching; closing this window will NOT stop the game")
    _popen(cmd, cwd=BUILD_DIR, stdout=subprocess.DEVNULL,
           stderr=subprocess.DEVNULL)
    rep.ok("have fun! 🎮")


# ---------------------------------------------------------------- orchestrator

def _ensure_build_tools(rep: Reporter) -> None:
    """Make cc / cmake / ninja resolvable — via the psxrecomp embedded
    toolchain (downloaded to ~/.local/share/retcomm on first use) when the
    system has none. Lets the AppImage (or a bare machine) compile without
    any system build tools beyond glibc."""
    have_cc = any(shutil.which(c) for c in ("cc", "gcc", "clang"))
    if have_cc and shutil.which("cmake") and shutil.which("ninja"):
        return
    rep.info("system cc/cmake/ninja incomplete — activating the embedded "
             "toolchain…")
    sys.path.insert(0, str(REPO / "psxrecomp"))
    try:
        import psxrecomp_cli as pcli
    except Exception as e:  # noqa: BLE001 — report, gate stays in step_build
        rep.warn(f"embedded toolchain unavailable ({e})")
        return

    class _P:  # minimal ProgressReporter stand-in for the framework
        def log(self, msg, **_k):
            rep.console(msg)

    if pcli.activate_embedded_toolchain(REPO):
        rep.ok("embedded toolchain active")
        return
    rep.info("downloading the build toolchain (one-time; needs network)…")
    try:
        pcli.ensure_toolchain_for_rebuild(REPO, _P(), download=True)
        if pcli.activate_embedded_toolchain(REPO):
            rep.ok("embedded toolchain ready")
    except Exception as e:  # noqa: BLE001 — step_build gives the final hint
        rep.warn(f"toolchain setup failed ({e})")


def run_pipeline(src: Path, rep: Reporter, *, cancel: CancelToken | None = None,
                 auto_launch: bool = True, soak: int = 0) -> dict:
    """Stage → verify → generate → build → (optionally) launch.

    Returns {"verified": bool, "disc_sha1": str, "already_built": bool}.
    Raises PipelineError / Cancelled.
    """
    if cancel:
        cancel.check()
    t0 = time.perf_counter()
    _ensure_build_tools(rep)
    verified = stage_input(src, rep, cancel)
    disc_sha1 = sha1_file(DISC_BIN)

    need, why = needs_rebuild(disc_sha1)
    if not need:
        rep.banner("Already built — ready to play")
        rep.progress(1.0, "Already compiled")
        if auto_launch:
            launch_game(rep, soak)
        return {"verified": verified, "disc_sha1": disc_sha1,
                "already_built": True}

    rep.info("first run: ~10 minutes of one-time work; after that, seconds"
             if why == "first run" else f"rebuilding: {why}")
    step_generate(rep, cancel)
    step_build(rep, cancel)
    write_settings(rep)
    stamp_write(disc_sha1, rep)
    rep.banner(f"One-time setup complete "
               f"({int((time.perf_counter() - t0) // 60)}m"
               f"{int((time.perf_counter() - t0) % 60):02d}s).")
    rep.ok("recompilation finished — press Play")
    if auto_launch:
        launch_game(rep, soak)
    return {"verified": verified, "disc_sha1": disc_sha1,
            "already_built": False}
