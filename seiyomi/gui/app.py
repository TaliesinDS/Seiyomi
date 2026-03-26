"""SeiyomiApp — main application window.

Architecture:
- Central notebook with one tab per view.
- A persistent status bar showing connection state.
- A shared output panel at the bottom for live CLI output.
- "Run" / "Cancel" / "Dry Run" controls.
- Config auto-save on close.
"""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import List, Optional

from typing import Any, cast

from seiyomi.gui.api import test_connection_async
from seiyomi.gui.runner import ProcessRunner
from seiyomi.gui.state import AppState
from seiyomi.gui.widgets import OutputText, StatusDot, attach_tip

# Views — imported lazily in _build() so GUI launches even if a view has a bug.


_APP_TITLE = "Seiyomi — Suwayomi Library Manager"
_APP_VERSION = "dev"


class SeiyomiApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(_APP_TITLE)
        self.minsize(900, 640)
        self._state = AppState.load()
        self._runner: Optional[ProcessRunner] = None
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._auto_test_connection()

    # ── Builder ────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Top-level layout: paned window (tabs | output)
        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True)

        # ── Notebook (top) ──
        nb_frame = ttk.Frame(paned)
        paned.add(nb_frame, weight=3)

        self._nb = ttk.Notebook(nb_frame)
        self._nb.pack(fill="both", expand=True)

        self._views: dict[str, tk.Widget] = {}
        self._build_tabs()

        # ── Output panel (bottom) ──
        out_frame = ttk.LabelFrame(paned, text="Output", padding=4)
        paned.add(out_frame, weight=1)

        self._output = OutputText(out_frame, height=12)
        self._output.pack(fill="both", expand=True)

        # ── Control bar ──
        ctrl = ttk.Frame(self)
        ctrl.pack(fill="x", padx=8, pady=4)

        self._dry_run_var = tk.BooleanVar(value=self._state.dry_run)
        ttk.Checkbutton(ctrl, text="Dry run", variable=self._dry_run_var).pack(side="left", padx=(0, 8))

        self._verbose_var = tk.BooleanVar(value=self._state.verbose)
        ttk.Checkbutton(ctrl, text="Verbose", variable=self._verbose_var).pack(side="left", padx=(0, 16))

        self._run_btn = ttk.Button(ctrl, text="▶  Run", command=self._on_run, width=10)
        self._run_btn.pack(side="left", padx=(0, 6))

        self._cancel_btn = ttk.Button(ctrl, text="✕  Cancel", command=self._on_cancel,
                                      state="disabled", width=10)
        self._cancel_btn.pack(side="left", padx=(0, 16))

        ttk.Button(ctrl, text="Clear output", command=self._output.clear).pack(side="left")

        # ── Status bar ──
        status_bar = ttk.Frame(self, relief="sunken")
        status_bar.pack(fill="x", side="bottom")
        self._status_dot = StatusDot(status_bar)
        self._status_dot.pack(side="left", padx=8, pady=2)

    def _build_tabs(self) -> None:
        from seiyomi.gui.views.home import HomeView
        from seiyomi.gui.views.settings import SettingsView
        from seiyomi.gui.views.migrate import MigrateView
        from seiyomi.gui.views.import_csv import ImportCsvView
        from seiyomi.gui.views.import_md import ImportMangaDexView
        from seiyomi.gui.views.cleanup import CleanupView
        from seiyomi.gui.views.advanced import AdvancedView

        _tabs = [
            ("home",        "Home",            HomeView(self._nb, on_navigate=self._navigate)),
            ("migrate",     "Migrate",         MigrateView(self._nb, self._state)),
            ("import_csv",  "Import CSV",      ImportCsvView(self._nb, self._state)),
            ("import_md",   "Import MangaDex", ImportMangaDexView(self._nb, self._state)),
            ("cleanup",     "Prune",           CleanupView(self._nb, self._state)),
            ("advanced",    "Advanced",        AdvancedView(self._nb, self._state)),
            ("settings",    "Settings",        SettingsView(
                self._nb, self._state, on_test=self._test_connection_from_settings
            )),
        ]

        for key, label, view in _tabs:
            self._nb.add(view, text=label)
            self._views[key] = view
            view.pack_propagate(True)

        self._tab_keys = [t[0] for t in _tabs]

    # ── Navigation ─────────────────────────────────────────────────────────

    def _navigate(self, tab_key: str) -> None:
        if tab_key in self._tab_keys:
            idx = self._tab_keys.index(tab_key)
            self._nb.select(idx)

    # ── Run / Cancel ───────────────────────────────────────────────────────

    def _current_view(self) -> Optional[tk.Widget]:
        try:
            idx = self._nb.index("current")
            key = self._tab_keys[idx]
            return self._views.get(key)
        except Exception:
            return None

    def _build_argv(self) -> List[str]:
        """Gather CLI argv from the currently selected view."""
        self._state.dry_run = bool(self._dry_run_var.get())
        self._state.verbose = bool(self._verbose_var.get())

        view = self._current_view()
        if view is None:
            return []

        # Views expose get_args() → List[str]
        if hasattr(view, "get_args"):
            args: List[str] = cast(Any, view).get_args()
        else:
            return []

        # Inject shared flags
        conn = self._state.connection
        base: List[str] = [
            "--base-url", conn.base_url,
            "--auth", conn.auth_mode,
        ]
        if conn.username:
            base += ["--user", conn.username]
        if conn.password:
            base += ["--password", conn.password]
        if conn.token:
            base += ["--token", conn.token]
        if self._state.dry_run:
            base += ["--dry-run"]
        if self._state.verbose:
            base += ["--verbose"]

        # Shared flags go after the subcommand word(s); before the subcommand-
        # specific ones.  For compound subcommands (e.g. ["import", "csv", ...])
        # we need to insert after the subcommand words.
        # Simple heuristic: if the first non-flag word in args already contains
        # the subcommand, prepend base before the subcommand-specific flags.
        # Actually, argparse accepts flags anywhere, so we can just append.
        return args + base

    def _on_run(self) -> None:
        if self._runner is not None:
            messagebox.showwarning("Already running", "An operation is already in progress.")
            return

        argv = self._build_argv()
        if not argv:
            messagebox.showwarning("Nothing to run", "No operation selected in the current tab.")
            return

        self._output.clear()
        self._output.append(f"$ seiyomi {' '.join(argv)}")
        self._output.append("")

        self._run_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")

        def _on_line(line: str) -> None:
            self.after(0, lambda: self._output.append(line))

        def _on_done(rc: int) -> None:
            def _finish():
                self._runner = None
                self._run_btn.configure(state="normal")
                self._cancel_btn.configure(state="disabled")
                colour = "#22c55e" if rc == 0 else "#ef4444"
                self._output.append(f"\n[Exit code: {rc}]")
            self.after(0, _finish)

        self._runner = ProcessRunner(argv, _on_line, _on_done)
        self._runner.start()

    def _on_cancel(self) -> None:
        if self._runner:
            self._runner.cancel()
            self._runner = None
        self._run_btn.configure(state="normal")
        self._cancel_btn.configure(state="disabled")
        self._output.append("\n[Cancelled]")

    # ── Connection test ────────────────────────────────────────────────────

    def _auto_test_connection(self) -> None:
        self._status_dot.set_pending("Connecting…")
        conn = self._state.connection
        test_connection_async(
            conn.base_url, conn.auth_mode, conn.username, conn.password, conn.token,
            callback=lambda ok, msg: self.after(0, lambda: self._status_dot.set_ok(msg) if ok else self._status_dot.set_error(msg)),
        )

    def _test_connection_from_settings(self, dot: StatusDot) -> None:
        dot.set_pending("Connecting…")
        conn = self._state.connection
        test_connection_async(
            conn.base_url, conn.auth_mode, conn.username, conn.password, conn.token,
            callback=lambda ok, msg: self.after(0, lambda: dot.set_ok(msg) if ok else dot.set_error(msg)),
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        self._state.dry_run = bool(self._dry_run_var.get())
        self._state.verbose = bool(self._verbose_var.get())
        # Flush all views that support it
        for view in self._views.values():
            if hasattr(view, "flush_to_state"):
                try:
                    cast(Any, view).flush_to_state()
                except Exception:
                    pass
        self._state.save()
        if self._runner:
            self._runner.cancel()
        self.destroy()


# ── Entry point ────────────────────────────────────────────────────────────

def launch() -> None:
    app = SeiyomiApp()
    app.mainloop()
