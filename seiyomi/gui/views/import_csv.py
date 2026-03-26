"""ImportCsvView — CSV bookmarks import form."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog
from typing import List

from seiyomi.gui.state import AppState
from seiyomi.gui.widgets import LabeledEntry, attach_tip


class ImportCsvView(ttk.Frame):
    def __init__(self, parent: tk.Widget, state: AppState) -> None:
        super().__init__(parent, padding=12)
        self._state = state
        self._vars: dict[str, tk.Variable] = {}
        self._file_listvar = tk.StringVar()
        self._build()

    def _build(self) -> None:
        c = self._state.csv
        self._vars = {
            "threshold":        tk.StringVar(value=str(c.threshold)),
            "strict":           tk.BooleanVar(value=c.strict),
            "status_map":       tk.StringVar(value=c.status_map),
            "apply_progress":   tk.BooleanVar(value=c.apply_progress),
            "prefer_existing":  tk.BooleanVar(value=c.prefer_existing),
        }

        ttk.Label(self, text="Import CSV", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(self, text="Import Comick or Manganato CSV exports directly into Suwayomi.",
                  foreground="#6b7280", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 10))

        # File list
        file_frame = ttk.LabelFrame(self, text="CSV files", padding=6)
        file_frame.pack(fill="x", pady=4)

        self._listbox = tk.Listbox(file_frame, selectmode="extended", height=5,
                                   listvariable=self._file_listvar)
        self._listbox.pack(side="left", fill="x", expand=True)

        btn_col = ttk.Frame(file_frame)
        btn_col.pack(side="left", padx=(6, 0), fill="y")
        ttk.Button(btn_col, text="Add…", command=self._add_files, width=8).pack(fill="x", pady=2)
        ttk.Button(btn_col, text="Remove", command=self._remove_selected, width=8).pack(fill="x", pady=2)
        ttk.Button(btn_col, text="Clear", command=self._clear, width=8).pack(fill="x", pady=2)

        # Populate from state
        for f in c.files:
            self._listbox.insert("end", f)

        ttk.Separator(self).pack(fill="x", pady=8)

        LabeledEntry(self, "Title threshold", self._vars["threshold"], width=8,
                     tooltip="Minimum similarity to accept a source match (0–1, default 0.6)").pack(fill="x", pady=2)
        LabeledEntry(self, "Status → category map", self._vars["status_map"], width=45,
                     tooltip="e.g. reading=5,completed=9,plan_to_read=2").pack(fill="x", pady=2)

        opts = ttk.Frame(self); opts.pack(fill="x", pady=4)
        ttk.Checkbutton(opts, text="Strict title match",
                        variable=self._vars["strict"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(opts, text="Apply read progress from last-read column",
                        variable=self._vars["apply_progress"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(opts, text="Skip rows not already in library",
                        variable=self._vars["prefer_existing"]).pack(side="left")

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select CSV files",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        for p in paths:
            if p not in self._listbox.get(0, "end"):
                self._listbox.insert("end", p)

    def _remove_selected(self) -> None:
        for i in reversed(self._listbox.curselection()):
            self._listbox.delete(i)

    def _clear(self) -> None:
        self._listbox.delete(0, "end")

    def get_args(self) -> List[str]:
        self.flush_to_state()
        c = self._state.csv
        args: List[str] = ["import", "csv"]
        for f in c.files:
            args += ["--file", f]
        if c.threshold != 0.6:
            args += ["--threshold", str(c.threshold)]
        if c.strict:
            args += ["--strict"]
        if c.status_map:
            args += ["--status-map", c.status_map]
        if c.apply_progress:
            args += ["--apply-progress"]
        if c.prefer_existing:
            args += ["--prefer-existing"]
        return args

    def flush_to_state(self) -> None:
        c = self._state.csv
        c.files = list(self._listbox.get(0, "end"))
        try:
            c.threshold = float(self._vars["threshold"].get())
        except ValueError:
            c.threshold = 0.6
        c.strict = bool(self._vars["strict"].get())
        c.status_map = self._vars["status_map"].get().strip()
        c.apply_progress = bool(self._vars["apply_progress"].get())
        c.prefer_existing = bool(self._vars["prefer_existing"].get())
