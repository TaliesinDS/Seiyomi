"""Reusable tkinter widgets for the Seiyomi GUI.

All widgets here are vanilla tkinter/ttk — no third-party dependencies.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional


# ── Tooltip ────────────────────────────────────────────────────────────────

class Tooltip:
    """Simple hover tooltip."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self._widget = widget
        self._text = text
        self._win: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None) -> None:
        if self._win or not self._text:
            return
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 10
        self._win = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self._text, justify="left", relief="solid", borderwidth=1,
            background="#ffffe0", foreground="#000000", padx=6, pady=4,
            font=("Segoe UI", 9),
        ).pack()

    def _hide(self, _event=None) -> None:
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None


def attach_tip(widget: tk.Widget, text: str) -> None:
    try:
        Tooltip(widget, text)
    except Exception:
        pass


# ── LabeledEntry ──────────────────────────────────────────────────────────

class LabeledEntry(ttk.Frame):
    """Label + Entry pair, optionally with a browse button."""

    def __init__(
        self,
        parent: tk.Widget,
        label: str,
        var: tk.Variable,
        width: int = 40,
        tooltip: str = "",
        show: str = "",
    ) -> None:
        super().__init__(parent)
        ttk.Label(self, text=label, width=24, anchor="w").pack(side="left")
        self.entry = ttk.Entry(self, textvariable=var, width=width, show=show)
        self.entry.pack(side="left", fill="x", expand=True)
        if tooltip:
            attach_tip(self.entry, tooltip)


# ── LabeledDropdown ───────────────────────────────────────────────────────

class LabeledDropdown(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        label: str,
        var: tk.Variable,
        values: list,
        tooltip: str = "",
    ) -> None:
        super().__init__(parent)
        ttk.Label(self, text=label, width=24, anchor="w").pack(side="left")
        cb = ttk.Combobox(self, textvariable=var, values=values, state="readonly", width=20)
        cb.pack(side="left")
        if tooltip:
            attach_tip(cb, tooltip)


# ── StatusDot ────────────────────────────────────────────────────────────

class StatusDot(ttk.Frame):
    """Small coloured dot + label to show server connection state."""

    _GREEN = "#22c55e"
    _RED   = "#ef4444"
    _AMBER = "#f59e0b"

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent)
        self._canvas = tk.Canvas(self, width=14, height=14, highlightthickness=0,
                                 background=self.winfo_toplevel().cget("bg") if self.winfo_ismapped() else "white")
        self._canvas.pack(side="left", padx=(0, 4))
        self._label = ttk.Label(self, text="Not connected")
        self._label.pack(side="left")
        self._set_colour(self._AMBER)

    def _set_colour(self, colour: str) -> None:
        self._canvas.configure(background=colour)

    def set_ok(self, message: str = "Connected") -> None:
        self._set_colour(self._GREEN)
        self._label.configure(text=message)

    def set_error(self, message: str = "Not connected") -> None:
        self._set_colour(self._RED)
        self._label.configure(text=message)

    def set_pending(self, message: str = "Connecting…") -> None:
        self._set_colour(self._AMBER)
        self._label.configure(text=message)


# ── OutputText ────────────────────────────────────────────────────────────

class OutputText(tk.Frame):
    """Scrolled text widget for live CLI output."""

    def __init__(self, parent: tk.Widget, height: int = 18) -> None:
        super().__init__(parent)
        self._text = tk.Text(
            self, wrap="word", height=height,
            font=("Consolas", 9), state="disabled",
            background="#1e1e1e", foreground="#d4d4d4",
            insertbackground="#d4d4d4",
        )
        sb = ttk.Scrollbar(self, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._text.pack(side="left", fill="both", expand=True)

    def append(self, line: str) -> None:
        self._text.configure(state="normal")
        self._text.insert("end", line + "\n")
        self._text.see("end")
        self._text.configure(state="disabled")

    def clear(self) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")


# ── WarningBanner ─────────────────────────────────────────────────────────

class WarningBanner(ttk.Frame):
    """Yellow warning strip shown conditionally."""

    def __init__(self, parent: tk.Widget, text: str) -> None:
        super().__init__(parent, style="Warning.TFrame")
        self._label = tk.Label(
            self, text=f"⚠  {text}", background="#fef08a",
            foreground="#713f12", padx=8, pady=4,
            font=("Segoe UI", 9),
        )
        self._label.pack(fill="x")

    def show(self, text: Optional[str] = None) -> None:
        if text:
            self._label.configure(text=f"⚠  {text}")
        self.pack(fill="x")

    def hide(self) -> None:
        self.pack_forget()
