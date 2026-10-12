#!/usr/bin/env python3
"""Battle Hunter — Recomp Launcher (GUI).

A tiny desktop launcher that turns the Drop & Play pipeline into three
buttons:

  1. INSERT  — pick your Battle Hunter disc image (.ecm / .bin / .cue)
               (or just drag the file onto this window)
  2. RECOMPILE — unsqueeze → verify → translate to C → compile, with a
               live progress bar and a scrolling console of everything
               the pipeline does
  3. PLAY    — boots the recompiled game (enabled once a build exists)

The heavy lifting lives in tools/bh_pipeline.py (shared with the terminal
Drop & Play tool); this file is only the GTK front-end. Nothing game-derived
ships in this repository — recompiling rebuilds it locally, from your file.

Usage:
  python3 tools/launcher_gui.py [PATH]     # PATH pre-selects the game file
  python3 tools/launcher_gui.py --smoke    # show the window briefly and exit
                                           # (used by self-tests)

Requires GTK3 via PyGObject (python3-gi). On Debian/Ubuntu:
  sudo apt install python3-gi gir1.2-gtk-3.0
On Arch: sudo pacman -S gtk3 python-gobject
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bh_pipeline as bh  # noqa: E402

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gio, GLib, Gtk
except (ImportError, ValueError) as exc:  # pragma: no cover — env dependent
    print("Battle Hunter launcher needs GTK3 via PyGObject (python3-gi).\n"
          f"  details: {exc}\n"
          "  Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-3.0\n"
          "  Arch/CachyOS:  sudo pacman -S gtk3 python-gobject\n"
          "The terminal tool still works without it:\n"
          "  python3 tools/drop_and_play.py <your.ecm>", file=sys.stderr)
    sys.exit(2)

GLib.set_prgname("bh-recomp-launcher")

ICON = bh.REPO / "assets/psxrecomp.png"
CSS = b"""
textview.view { background-color: #16181d; color: #cfd6e4; caret-color: #cfd6e4;
                font-family: monospace; font-size: 9pt; }
label.hint  { opacity: 0.65; font-size: 0.9em; }
label.step  { font-weight: 700; }
label.state-ok    { color: #33d17a; }
label.state-warn  { color: #f6d32d; }
label.state-error { color: #ff7b63; }
"""

MAX_CONSOLE_LINES = 4000  # trim the log beyond this (keeps the UI snappy)


# ============================================================ reporter (worker side)

class GuiReporter(bh.Reporter):
    """Marshals pipeline output into queues the GTK main loop drains."""

    def __init__(self, gui: "LauncherWindow"):
        self._gui = gui

    def banner(self, msg):
        self._gui.console_line(f"\n── {msg} {'─' * max(0, 52 - len(msg))}")

    def info(self, msg):
        self._gui.console_line(f"    {msg}")

    def ok(self, msg="done"):
        self._gui.console_line(f" ✓ {msg}")

    def warn(self, msg):
        self._gui.console_line(f" ⚠ {msg}")

    def console(self, line):
        self._gui.console_line(line)

    def progress(self, pct, message=""):
        self._gui.progress(pct, message)


# ============================================================ main window

class LauncherWindow(Gtk.Window):
    def __init__(self, preset: Path | None):
        super().__init__(title="Battle Hunter — Recomp Launcher")
        self.set_default_size(820, 600)
        try:
            self.set_icon_from_file(str(ICON))
        except (GLib.Error, OSError):
            pass

        # ---- state
        self._console_q: queue.Queue[str] = queue.Queue()
        self._progress_q: queue.Queue[tuple] = queue.Queue()
        self._state_q: queue.Queue[tuple] = queue.Queue()
        self._cancel: bh.CancelToken | None = None
        self._worker: threading.Thread | None = None
        self._running = False
        self._pulse = False
        self._max_pct = 0.0

        self._build_ui()
        self._wire_dnd()

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        GLib.timeout_add(80, self._tick)
        threading.Thread(target=self._probe_state, daemon=True).start()
        if preset is not None:
            self._file_entry.set_text(str(preset))

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        hb = Gtk.HeaderBar.new()
        hb.set_show_close_button(True)
        hb.props.title = "Battle Hunter"
        hb.props.subtitle = "static recompilation launcher (SLUS-01335, USA)"
        self.set_titlebar(hb)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(14)
        root.set_margin_end(14)
        self.add(root)

        # -- step 1: insert the game file
        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lbl = Gtk.Label()
        lbl.set_markup("<b>1 · Insert your game</b>")
        lbl.get_style_context().add_class("step")
        lbl.set_valign(Gtk.Align.CENTER)
        self._browse_btn = Gtk.Button.new_with_mnemonic("_Browse…")
        self._browse_btn.connect("clicked", self._on_browse)
        self._file_entry = Gtk.Entry()
        self._file_entry.set_placeholder_text(
            "Pick BATTLE HUNTER.iso.ecm (or a .bin/.cue dump) — or drag it here")
        self._file_entry.set_hexpand(True)
        self._file_entry.connect("changed", lambda *_: self._refresh_sensitivity())
        row1.pack_start(lbl, False, False, 0)
        row1.pack_start(self._file_entry, True, True, 0)
        row1.pack_start(self._browse_btn, False, False, 0)
        root.add(row1)

        hint = Gtk.Label(label="Your disc image is never uploaded anywhere — it is "
                          "unsqueezed, verified, translated to C and compiled "
                          "on this machine.")
        hint.set_halign(Gtk.Align.START)
        hint.get_style_context().add_class("hint")
        hint.set_xalign(0)
        root.add(hint)

        # -- step 2: recompile  /  step 3: play
        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._recompile_btn = Gtk.Button.new_with_mnemonic("_2 · Recompile")
        self._recompile_btn.get_style_context().add_class("suggested-action")
        self._recompile_btn.connect("clicked", self._on_recompile)
        self._cancel_btn = Gtk.Button.new_with_mnemonic("_Cancel")
        self._cancel_btn.connect("clicked", self._on_cancel)
        self._play_btn = Gtk.Button.new_with_label("3 · Play  ▶")
        self._play_btn.get_style_context().add_class("suggested-action")
        self._play_btn.connect("clicked", self._on_play)
        size = Gtk.IconSize.BUTTON
        try:
            self._recompile_btn.set_image(Gtk.Image.new_from_icon_name(
                "view-refresh-symbolic", size))
            self._recompile_btn.set_always_show_image(True)
            self._play_btn.set_image(Gtk.Image.new_from_icon_name(
                "media-playback-start-symbolic", size))
            self._play_btn.set_always_show_image(True)
        except Exception:
            pass
        row2.pack_start(self._recompile_btn, False, False, 0)
        row2.pack_start(self._cancel_btn, False, False, 0)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        row2.pack_start(spacer, True, True, 0)
        row2.pack_start(self._play_btn, False, False, 0)
        root.add(row2)

        # -- progress + status
        self._bar = Gtk.ProgressBar()
        self._bar.set_show_text(True)
        self._bar.set_text("idle")
        root.add(self._bar)
        self._status = Gtk.Label(label="Checking this machine…")
        self._status.set_halign(Gtk.Align.START)
        self._status.set_xalign(0)
        self._status.get_style_context().add_class("hint")
        root.add(self._status)

        root.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # -- console
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.IN)
        frame.set_vexpand(True)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self._view = Gtk.TextView()
        self._view.set_editable(False)
        self._view.set_cursor_visible(False)
        self._view.set_wrap_mode(Gtk.WrapMode.NONE)
        self._view.set_monospace(True)
        self._tbuf = self._view.get_buffer()
        self._end_mark = self._tbuf.create_mark("end", self._tbuf.get_end_iter(),
                                                False)
        scrolled.add(self._view)
        frame.add(scrolled)
        root.add(frame)
        self._file_entry.grab_focus()

    def _wire_dnd(self) -> None:
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect("drag-data-received", self._on_drop)

    def _on_drop(self, _w, ctx, _x, _y, data, _info, t):
        path = None
        if data:
            for uri in data.get_uris():
                if uri.startswith("file:"):
                    path = Gio.File.new_for_uri(uri).get_path()
                    if path:
                        break
        ok = path is not None and Path(path).exists()
        if ok:
            self._file_entry.set_text(path)
            self.console_line(f"dropped: {path}")
        try:
            Gtk.drag_finish(ctx, ok, False, t)
        except (TypeError, ValueError):
            pass  # synthetic/degenerate contexts only

    # ---------------------------------------------------------------- helpers

    def console_line(self, line: str) -> None:
        self._console_q.put(line)

    def progress(self, pct, message: str) -> None:
        self._progress_q.put((pct, message))

    def _set_state(self, state: str, detail: str = "") -> None:
        """idle | running | done | error | cancelled (call from any thread)."""
        self._state_q.put((state, detail))

    # ---- everything below runs on the GTK main thread ----

    def _tick(self) -> bool:
        try:
            while True:
                self._append_console(self._console_q.get_nowait() + "\n")
        except queue.Empty:
            pass
        try:
            while True:
                pct, message = self._progress_q.get_nowait()
                if pct is None:
                    self._pulse = True
                else:
                    self._pulse = False
                    self._max_pct = max(self._max_pct, pct)
                    self._bar.set_fraction(self._max_pct)
                    self._bar.set_text(
                        f"{message} — {int(round(self._max_pct * 100))}%"
                        if message else f"{int(round(self._max_pct * 100))}%")
                if message:
                    self._status.set_text(message)
        except queue.Empty:
            pass
        try:
            while True:
                state, detail = self._state_q.get_nowait()
                self._apply_state(state, detail)
        except queue.Empty:
            pass
        if self._pulse:
            self._bar.pulse()
        return True  # keep the tick alive

    def _append_console(self, text: str) -> None:
        buf = self._tbuf
        buf.insert(buf.get_end_iter(), text)
        n = buf.get_line_count()
        if n > MAX_CONSOLE_LINES:
            buf.delete(buf.get_start_iter(),
                       buf.get_iter_at_line(n - MAX_CONSOLE_LINES))
        self._view.scroll_mark_onscreen(self._end_mark)

    def _apply_state(self, state: str, detail: str) -> None:
        cls = self._status.get_style_context()
        for c in ("state-ok", "state-warn", "state-error"):
            cls.remove_class(c)
        running = state == "running"
        self._running = running
        self._browse_btn.set_sensitive(not running)
        self._file_entry.set_sensitive(not running)
        self._recompile_btn.set_sensitive(not running)
        self._cancel_btn.set_sensitive(running and self._cancel is not None)
        can_play = (not running) and bh.EXE.exists()
        self._play_btn.set_sensitive(can_play)
        if state == "running":
            self._status.set_text(detail or "Recompiling…")
        elif state == "done":
            cls.add_class("state-ok")
            self._status.set_text(detail or "Recompilation complete — press Play")
            self._pulse = False
            self._max_pct = 1.0
            self._bar.set_fraction(1.0)
            self._bar.set_text("100%")
        elif state == "error":
            cls.add_class("state-error")
            self._status.set_text(detail or "Recompilation failed — see the log")
        elif state == "cancelled":
            cls.add_class("state-warn")
            self._status.set_text(detail or "Cancelled")
        else:  # idle
            if detail:
                self._status.set_text(detail)
        self._refresh_sensitivity()

    def _refresh_sensitivity(self, *_):
        if self._running:
            return  # while running, _apply_state governs the buttons
        has = bool(self._file_entry.get_text().strip()) or bh.DISC_BIN.exists()
        self._recompile_btn.set_sensitive(has)

    # ---------------------------------------------------------------- actions

    def _on_browse(self, *_):
        filt = Gtk.FileFilter()
        filt.set_name("Battle Hunter disc images")
        for pat in ("*.ecm", "*.bin", "*.cue"):
            filt.add_pattern(pat)
        try:
            dlg = Gtk.FileChooserNative.new(
                "Pick your Battle Hunter disc image", self,
                Gtk.FileChooserAction.OPEN, "_Open", "_Cancel")
            dlg.add_filter(filt)
        except Exception:
            dlg = Gtk.FileChooserDialog(
                title="Pick your Battle Hunter disc image", transient_for=self,
                action=Gtk.FileChooserAction.OPEN)
            dlg.add_buttons("_Cancel", Gtk.ResponseType.CANCEL,
                            "_Open", Gtk.ResponseType.ACCEPT)
            dlg.add_filter(filt)

        def chosen(d, resp):
            if resp == Gtk.ResponseType.ACCEPT:
                fn = d.get_filename()
                if fn:
                    self._file_entry.set_text(fn)
                    self._max_pct = 0.0
                    self._bar.set_fraction(0.0)
                    self._status.set_text(f"selected: {fn}")
            d.destroy()

        dlg.connect("response", chosen)
        dlg.show()

    def _probe_state(self):
        """Background startup probe: is there already a playable build?"""
        try:
            st = bh.pipeline_state()
        except Exception as e:  # pragma: no cover — defensive
            self._set_state("idle", f"startup check failed: {e}")
            return
        if not st["needs_rebuild"] and st["exe_ready"]:
            self._set_state("idle", "Already compiled — press Play "
                                    "(or pick a new file and Recompile)")
        elif st["exe_ready"]:
            self._set_state("idle", f"Built earlier, but a rebuild is needed "
                                    f"({st['why']}) — press Recompile")
        elif st["disc_staged"]:
            self._set_state("idle", "No build yet — press Recompile to make one")
        else:
            self._set_state("idle", "Welcome! Insert your game file to begin")

    def _on_recompile(self, *_):
        text = self._file_entry.get_text().strip()
        if text:
            src = Path(text).expanduser()
            if not src.exists():
                self._warn_dialog("File not found",
                                  f"{src} does not exist — pick your game file "
                                  "with Browse…")
                return
        elif bh.DISC_BIN.exists():
            src = bh.DISC_BIN
            self.console_line(f"(no file picked — using staged {bh.DISC_BIN})")
        else:
            self._warn_dialog("No game file",
                              "Pick your Battle Hunter .ecm/.bin/.cue first "
                              "(Browse… or drag it onto this window).")
            return

        self._cancel = bh.CancelToken()
        self._max_pct = 0.0
        self._bar.set_fraction(0.0)
        self.console_line(f"\n══ recompile run · {src} "
                          + "═" * max(0, 30 - min(30, len(str(src)))))
        self._apply_state("running", f"Recompiling from {src.name}…")
        self._worker = threading.Thread(
            target=self._run_pipeline, args=(src, self._cancel), daemon=True)
        self._worker.start()

    def _run_pipeline(self, src: Path, cancel: bh.CancelToken):
        rep = GuiReporter(self)
        try:
            bh.run_pipeline(src, rep, cancel=cancel, auto_launch=False)
            self._set_state("done")
        except bh.Cancelled:
            self._set_state("cancelled")
        except bh.PipelineError as e:
            self._set_state("error", str(e))
        except Exception as e:  # pragma: no cover — defensive
            self._set_state("error", f"unexpected error: {e!r}")

    def _on_cancel(self, *_):
        if self._cancel:
            self._cancel.cancel()
            self._cancel_btn.set_sensitive(False)
            self._status.set_text("Cancelling…")

    def _on_play(self, *_):
        if not bh.DISC_CUE.exists():
            self._warn_dialog("No disc staged",
                              "The game needs disc/BattleHunter.cue — run "
                              "Recompile first.")
            return
        if not bh.EXE.exists():
            self._warn_dialog("Not compiled yet",
                              "Press Recompile first — Play needs the "
                              "compiled game.")
            return
        cmd = bh.game_cmd()
        try:
            subprocess.Popen(cmd, cwd=bh.BUILD_DIR, start_new_session=True,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError as e:
            self._set_state("error", f"could not launch the game: {e}")
            return
        self.console_line(f" ✓ launched: {Path(cmd[0]).name} "
                          "(closing this window will NOT stop the game)")
        cls = self._status.get_style_context()
        cls.remove_class("state-warn")
        cls.remove_class("state-error")
        cls.add_class("state-ok")
        self._status.set_text("Game launched — have fun! 🎮")

    def _warn_dialog(self, title, message):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.CLOSE,
                                text=title)
        dlg.format_secondary_text(message)
        dlg.run()
        dlg.destroy()


# ============================================================ entry point

def _render_png(widget, path: str) -> None:
    """Draw a widget (and children) to a PNG — used by --shot self-tests."""
    import cairo
    alloc = widget.get_allocation()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, alloc.width, alloc.height)
    ctx = cairo.Context(surface)
    widget.draw(ctx)
    surface.write_to_png(path)


def main() -> int:
    args = [a for a in sys.argv[1:]]
    smoke = "--smoke" in args
    args = [a for a in args if a != "--smoke"]
    shot = None
    if any(a.startswith("--shot=") for a in args):
        shot = next(a.split("=", 1)[1] for a in args if a.startswith("--shot="))
        args = [a for a in args if not a.startswith("--shot=")]
        smoke = True
    preset = None
    if args:
        p = Path(args[0]).expanduser()
        if p.exists():
            preset = p
    win = LauncherWindow(preset)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    if shot:
        GLib.timeout_add(700, lambda: (_render_png(win, shot), Gtk.main_quit()) and False)
    elif smoke:
        GLib.timeout_add(900, Gtk.main_quit)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
