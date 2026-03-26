"""HomeView — landing screen with workflow summary cards."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


_CARDS = [
    {
        "title": "Import CSV",
        "desc": "Import a Comick or Manganato bookmarks export directly into Suwayomi.",
        "tab": "import_csv",
        "emoji": "📄",
    },
    {
        "title": "Import Follows",
        "desc": "Fetch your MangaDex followed titles and add them to Suwayomi.",
        "tab": "import_md",
        "emoji": "🔖",
    },
    {
        "title": "Migrate Library",
        "desc": "Move library entries from sources with no chapters to better alternatives.",
        "tab": "migrate",
        "emoji": "🔄",
    },
    {
        "title": "Prune Library",
        "desc": "Remove duplicate or non-preferred-language entries.",
        "tab": "cleanup",
        "emoji": "🗑",
    },
    {
        "title": "Advanced",
        "desc": "Full flag access — all CLI options in one form.",
        "tab": "advanced",
        "emoji": "⚙",
    },
    {
        "title": "Settings",
        "desc": "Configure the Suwayomi server URL and authentication.",
        "tab": "settings",
        "emoji": "🔌",
    },
]


class HomeView(ttk.Frame):
    def __init__(self, parent: tk.Widget,
                 on_navigate: Optional[Callable[[str], None]] = None) -> None:
        super().__init__(parent, padding=16)
        self._on_navigate = on_navigate
        self._build()

    def _build(self) -> None:
        ttk.Label(
            self, text="Seiyomi", font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            self, text="Suwayomi library manager",
            font=("Segoe UI", 10), foreground="#6b7280",
        ).pack(anchor="w", pady=(0, 16))

        grid = ttk.Frame(self)
        grid.pack(fill="both", expand=True)

        cols = 3
        for i, card in enumerate(_CARDS):
            row, col = divmod(i, cols)
            self._make_card(grid, card).grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

        for c in range(cols):
            grid.columnconfigure(c, weight=1)

    def _make_card(self, parent: tk.Widget, card: dict) -> tk.Widget:
        tab = card["tab"]
        frame = ttk.LabelFrame(parent, text=f"{card['emoji']}  {card['title']}", padding=10)
        ttk.Label(frame, text=card["desc"], wraplength=220,
                  font=("Segoe UI", 9), justify="left").pack(anchor="w", pady=(0, 8))
        ttk.Button(frame, text="Open →",
                   command=lambda t=tab: self._on_navigate and self._on_navigate(t)
                   ).pack(anchor="w")
        return frame
