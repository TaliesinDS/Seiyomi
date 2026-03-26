"""ImportMangaDexView — MangaDex follows import form."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import List

from seiyomi.gui.state import AppState
from seiyomi.gui.widgets import LabeledEntry, attach_tip


class ImportMangaDexView(ttk.Frame):
    def __init__(self, parent: tk.Widget, state: AppState) -> None:
        super().__init__(parent, padding=12)
        self._state = state
        self._vars: dict[str, tk.Variable] = {}
        self._build()

    def _build(self) -> None:
        m = self._state.mangadex
        self._vars = {
            "username":       tk.StringVar(value=m.username),
            "password":       tk.StringVar(value=m.password),
            "client_id":      tk.StringVar(value=m.client_id),
            "client_secret":  tk.StringVar(value=m.client_secret),
            "two_fa":         tk.StringVar(value=m.two_fa),
            "import_status":  tk.BooleanVar(value=m.import_status),
            "import_read":    tk.BooleanVar(value=m.import_read),
            "status_map":     tk.StringVar(value=m.status_map),
        }

        ttk.Label(self, text="Import MangaDex Follows", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(self, text="Log in to MangaDex and import your followed titles into Suwayomi.",
                  foreground="#6b7280", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 10))

        creds = ttk.LabelFrame(self, text="MangaDex credentials", padding=8)
        creds.pack(fill="x", pady=4)

        LabeledEntry(creds, "Username", self._vars["username"]).pack(fill="x", pady=2)
        LabeledEntry(creds, "Password", self._vars["password"], show="•").pack(fill="x", pady=2)
        LabeledEntry(creds, "Client ID (optional)", self._vars["client_id"],
                     tooltip="Personal API client ID — leave blank to use the public client").pack(fill="x", pady=2)
        LabeledEntry(creds, "Client secret (optional)", self._vars["client_secret"], show="•").pack(fill="x", pady=2)
        LabeledEntry(creds, "2FA code (optional)", self._vars["two_fa"],
                     tooltip="Time-based one-time code if your account uses 2FA").pack(fill="x", pady=2)

        ttk.Separator(self).pack(fill="x", pady=8)

        opts = ttk.LabelFrame(self, text="Options", padding=8)
        opts.pack(fill="x", pady=4)

        ttk.Checkbutton(opts, text="Import reading statuses (reading/completed/etc.)",
                        variable=self._vars["import_status"]).pack(anchor="w", pady=2)
        ttk.Checkbutton(opts, text="Sync read progress (marks individual chapters read)",
                        variable=self._vars["import_read"]).pack(anchor="w", pady=2)

        LabeledEntry(opts, "Status → category map", self._vars["status_map"], width=45,
                     tooltip="e.g. reading=5,completed=9,plan_to_read=2").pack(fill="x", pady=4)

    def get_args(self) -> List[str]:
        self.flush_to_state()
        m = self._state.mangadex
        args: List[str] = ["import", "follows"]
        if m.username:
            args += ["--md-user", m.username]
        if m.password:
            args += ["--md-pass", m.password]
        if m.client_id:
            args += ["--md-client-id", m.client_id]
        if m.client_secret:
            args += ["--md-client-secret", m.client_secret]
        if m.two_fa:
            args += ["--md-2fa", m.two_fa]
        if m.import_status:
            args += ["--import-status"]
        if m.import_read:
            args += ["--import-read"]
        if m.status_map:
            args += ["--status-map", m.status_map]
        return args

    def flush_to_state(self) -> None:
        m = self._state.mangadex
        m.username = self._vars["username"].get().strip()
        m.password = self._vars["password"].get().strip()
        m.client_id = self._vars["client_id"].get().strip()
        m.client_secret = self._vars["client_secret"].get().strip()
        m.two_fa = self._vars["two_fa"].get().strip()
        m.import_status = bool(self._vars["import_status"].get())
        m.import_read = bool(self._vars["import_read"].get())
        m.status_map = self._vars["status_map"].get().strip()
