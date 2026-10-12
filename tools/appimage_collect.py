#!/usr/bin/env python3
"""appimage_collect.py — bundle a portable Python + GTK3 runtime into an AppDir.

Used by tools/make_appimage.sh. Discovers everything via introspection on the
build machine (works on both Arch-style and Debian/Ubuntu-style layouts), so
the same script builds a working launcher bundle on a distro of your choice:

  usr/bin/python3                    the interpreter itself
  usr/bin/gdk-pixbuf-query-loaders   regenerates the loader cache at runtime
  usr/lib/pythonX.Y/                 the standard library (test/tkinter trimmed)
  usr/python-packages/gi/            PyGObject (+ pycairo if present)
  usr/lib/*.so                       every NEEDED library, transitively
  usr/lib/girepository-1.0/          GObject typelibs
  usr/lib/gdk-pixbuf-2.0/.../loaders/  image loaders (window icon, PNGs)

A static AppRun then points PYTHONHOME / GI_TYPELIB_PATH / LD_LIBRARY_PATH at
these copies. Host fontconfig/icons/themes are used as-is (present on any
desktop), keeping the bundle small.

Usage: python3 tools/appimage_collect.py /path/to/AppDir
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

SKIP_STDLIB_DIRS = {"test", "idlelib", "tkinter", "lib2to3", "__pycache__",
                    "ensurepip", "venv"}
SKIP_STDLIB_SO = re.compile(r"(_tkinter|nis|ossaudiodev|audiodev)\b.*\.so")
SKIP_LIB = re.compile(r"(^|/)(ld-linux|libanl|libBrokenLocale|libcidn|libcrypt"
                      r"|libdl|libm\.|libm-|libmemusage|libnsl|libnss_"
                      r"|libresolv|librt|libthread_db|libutil)\.so")


def log(msg: str) -> None:
    print(f"[collect] {msg}", flush=True)


def ldd_libs(elf: Path) -> list[Path]:
    """All NEEDED shared objects (transitively) for one ELF file."""
    try:
        out = subprocess.run(["ldd", str(elf)], capture_output=True, text=True,
                             check=True).stdout
    except (subprocess.CalledProcessError, OSError):
        return []
    libs = []
    for m in re.finditer(r"\s(?:/[\w./+-]+)\s+\((?:0x[0-9a-f]+)\)?", out):
        p = Path(m.group(0).strip())
        if p.exists():
            libs.append(p)
    # also the "=> /path (addr)" form
    for m in re.finditer(r"=>\s(/[\w./+-]+)\s+\(", out):
        p = Path(m.group(1))
        if p.exists():
            libs.append(p)
    return libs


def copy_to(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if src.is_symlink():
        real = src.resolve()
        # copy the real file under the soname we were asked for
        shutil.copy2(real, dst)
    else:
        shutil.copy2(src, dst)


def copy_tree(src: Path, dst: Path, skip_dirs=(), skip_so=None) -> int:
    n = 0
    for p in src.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(src)
        if any(part in skip_dirs for part in rel.parts):
            continue
        if skip_so and p.suffix == ".so" and skip_so.search(p.name):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        n += 1
    return n


def main() -> int:
    appdir = Path(sys.argv[1]).resolve()
    usr = appdir / "usr"
    lib = usr / "lib"
    for d in (usr / "bin", lib, usr / "python-packages"):
        d.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- python itself
    py = Path(sys.executable).resolve()
    copy_to(py, usr / "bin" / "python3")
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}"
    stdlib = Path(sysconfig.get_paths()["stdlib"])
    log(f"python {pyver}: {py} (stdlib {stdlib})")
    n = copy_tree(stdlib, lib / f"python{pyver}",
                  skip_dirs=SKIP_STDLIB_DIRS, skip_so=SKIP_STDLIB_SO)
    log(f"stdlib: {n} files (trimmed test/tkinter/idle)")

    # ---------------------------------------------------------- PyGObject
    import gi  # noqa: E402 — must succeed on the build machine
    gi_dir = Path(gi.__file__).resolve().parent          # .../gi
    gi_parent = gi_dir.parent                            # site/dist-packages
    pkgs = usr / "python-packages"
    n = copy_tree(gi_dir, pkgs / "gi")
    log(f"gi package: {n} files from {gi_parent}")
    cairo = gi_parent / "cairo"                          # pycairo, if present
    if cairo.is_dir():
        n = copy_tree(cairo, pkgs / "cairo")
        log(f"pycairo: {n} files")

    # ---------------------------------------------------------- typelibs
    ti_dirs = [Path("/usr/lib/x86_64-linux-gnu/girepository-1.0"),
               Path("/usr/lib/girepository-1.0"),
               Path("/usr/lib64/girepository-1.0")]
    ti_src = next((d for d in ti_dirs if d.is_dir()), None)
    if ti_src is None:
        log("ERROR: no girepository-1.0 typelib dir found")
        return 1
    n = copy_tree(ti_src, lib / "girepository-1.0")
    log(f"typelibs: {n} files from {ti_src}")

    # ---------------------------------------------------------- gdk-pixbuf loaders
    q = shutil.which("gdk-pixbuf-query-loaders")
    if not q:  # Debian/Ubuntu keeps it out of PATH
        for cand in ("/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders",
                     "/usr/lib/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders",
                     "/usr/lib64/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders"):
            if Path(cand).exists():
                q = cand
                break
    if q:
        copy_to(Path(q).resolve(), usr / "bin" / "gdk-pixbuf-query-loaders")
    loader_roots = list(Path("/usr/lib").glob("gdk-pixbuf-2.0/*/loaders")) + \
        list(Path("/usr/lib/x86_64-linux-gnu").glob("gdk-pixbuf-2.0/*/loaders"))
    for root in loader_roots:
        n = copy_tree(root, lib / root.relative_to(Path("/usr/lib")))
        log(f"pixbuf loaders: {n} from {root}")

    # ---------------------------------------------------------- ELF closure
    roots: list[Path] = [usr / "bin" / "python3"]
    roots += [p for p in (lib / f"python{pyver}").rglob("*.so")]
    roots += [p for p in pkgs.rglob("*.so")]
    roots += [p for p in (lib / "gdk-pixbuf-2.0").rglob("*.so")] if \
        (lib / "gdk-pixbuf-2.0").exists() else []
    # the GTK stack itself (python only dlopens it via typelibs)
    for soname in ("libgtk-3.so.0", "libgdk-3.so.0", "libgirepository-1.0.so.1",
                   "libgirepository-2.0.so.1"):
        found = shutil.which(soname)  # not usually on PATH…
        if not found:
            out = subprocess.run(["ldconfig", "-p"], capture_output=True,
                                 text=True).stdout
            m = re.search(rf"{soname}\s+\(.*\)\s+=>\s+(/\S+)", out)
            found = m.group(1) if m else None
        if found and Path(found).exists():
            roots.append(Path(found))

    seen: set[Path] = set()
    todo = [r for r in roots if r.exists()]
    while todo:
        elf = todo.pop()
        if elf in seen:
            continue
        seen.add(elf)
        for dep in ldd_libs(elf):
            if dep in seen:
                continue
            if SKIP_LIB.search(dep.name) or "python" in dep.name:
                continue  # glibc pieces stay on the host; libpython comes later
            copy_to(dep, lib / dep.name)
            todo.append(dep)
    log(f"shared libs: {len(seen)} roots walked, "
        f"{len(list(lib.glob('*.so*')))} libs bundled")

    # libpython is special: keep it findable right next to the bundle libs
    for dep in ldd_libs(usr / "bin" / "python3"):
        if "libpython" in dep.name:
            copy_to(dep, lib / dep.name)
            log(f"libpython: {dep.name}")

    (appdir / "runtime.env").write_text(f"PYVER={pyver}\n")
    log(f"done → {appdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
