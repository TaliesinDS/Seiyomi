"""SettingsView — connection config and profile management."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from seiyomi.gui.widgets import LabeledEntry, LabeledDropdown, StatusDot, attach_tip
from seiyomi.gui.state import AppState, ConnectionState


class SettingsView(ttk.Frame):
    """Connection settings pane — embedded in the main notebook."""

    def __init__(self, parent: tk.Widget, state: AppState,
                 on_test: Optional[Callable] = None) -> None:
        super().__init__(parent, padding=12)
        self._state = state
        self._on_test = on_test
        self._vars: dict[str, tk.Variable] = {}
        self._build()

    def _build(self) -> None:
        c = self._state.connection
        self._vars = {
            "base_url":       tk.StringVar(value=c.base_url),
            "auth_mode":      tk.StringVar(value=c.auth_mode),
            "username":       tk.StringVar(value=c.username),
            "password":       tk.StringVar(value=c.password),
            "token":          tk.StringVar(value=c.token),
            "insecure":       tk.BooleanVar(value=c.insecure),
            "request_timeout":tk.StringVar(value=str(c.request_timeout)),
        }

        ttk.Label(self, text="Connection", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))

        LabeledEntry(self, "Server URL", self._vars["base_url"], width=45,
                     tooltip="Suwayomi base URL, e.g. http://127.0.0.1:4567").pack(fill="x", pady=2)

        LabeledDropdown(self, "Auth mode", self._vars["auth_mode"],
                        values=["auto", "none", "basic", "bearer", "simple"],
                        tooltip="auto = detect from server response").pack(fill="x", pady=2)

        LabeledEntry(self, "Username", self._vars["username"],
                     tooltip="For basic/simple auth").pack(fill="x", pady=2)

        LabeledEntry(self, "Password", self._vars["password"], show="•",
                     tooltip="For basic/simple auth").pack(fill="x", pady=2)

        LabeledEntry(self, "Bearer token", self._vars["token"], show="•",
                     tooltip="Settings → API Tokens in Suwayomi").pack(fill="x", pady=2)

        row = ttk.Frame(self)
        row.pack(fill="x", pady=2)
        ttk.Checkbutton(row, text="Disable TLS verification (insecure)",
                        variable=self._vars["insecure"]).pack(side="left")

        LabeledEntry(self, "Request timeout (s)", self._vars["request_timeout"],
                     width=8, tooltip="HTTP timeout per request (default 12)").pack(fill="x", pady=2)

        ttk.Separator(self).pack(fill="x", pady=10)

        # Connection test
        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Test connection", command=self._test).pack(side="left")
        self._status = StatusDot(btn_row)
        self._status.pack(side="left", padx=10)

    def _test(self) -> None:
        self.flush_to_state()
        if self._on_test:
            self._on_test(self._status)

    def flush_to_state(self) -> None:
        c = self._state.connection
        c.base_url = self._vars["base_url"].get().strip()
        c.auth_mode = self._vars["auth_mode"].get().strip()
        c.username = self._vars["username"].get().strip()
        c.password = self._vars["password"].get().strip()
        c.token = self._vars["token"].get().strip()
        c.insecure = bool(self._vars["insecure"].get())
        try:
            c.request_timeout = float(self._vars["request_timeout"].get())
        except ValueError:
            c.request_timeout = 12.0

    def update_status(self, ok: bool, message: str) -> None:
        if ok:
            self._status.set_ok(message)
        else:
            self._status.set_error(message)
