"""LedgerView — manage the local read-progress ledger from the GUI."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import List

from seiyomi.gui.state import AppState
from seiyomi.gui.widgets import LabeledEntry, attach_tip


class LedgerView(ttk.Frame):
    def __init__(self, parent: tk.Widget, state: AppState) -> None:
        super().__init__(parent, padding=12)
        self._state = state
        self._vars: dict[str, tk.Variable] = {}
        self._build()

    def _build(self) -> None:
        ls = self._state.ledger
        self._vars = {
            "action":         tk.StringVar(value=ls.action),
            "include_orphans": tk.BooleanVar(value=ls.include_orphans),
            "full_scan":      tk.BooleanVar(value=ls.full_scan),
            "filter_title":   tk.StringVar(value=ls.filter_title),
            "ledger_db":      tk.StringVar(value=ls.ledger_db),
            "show_query":     tk.StringVar(value=ls.show_query),
            "export_output":  tk.StringVar(value=ls.export_output),
        }

        ttk.Label(self, text="Read Ledger", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
        ttk.Label(self, text="Persistent local database of your read progress — survives extension churn.",
                  foreground="#6b7280", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 10))

        # ── Action selector ──
        action_frame = ttk.LabelFrame(self, text="Action", padding=8)
        action_frame.pack(fill="x", pady=4)

        actions = [
            ("auto",     "Auto (snapshot + apply)",
             "Scan Suwayomi for progress, then apply to entries that are behind."),
            ("snapshot", "Snapshot only",
             "Record current read progress from Suwayomi into the ledger."),
            ("apply",    "Apply only",
             "Push ledger progress to Suwayomi entries that are behind."),
            ("show",     "Show / Search",
             "Display ledger stats or search for a title."),
            ("export",   "Export to CSV",
             "Dump the entire ledger to a CSV file."),
        ]
        for value, label, tip in actions:
            rb = ttk.Radiobutton(action_frame, text=label,
                                 variable=self._vars["action"], value=value)
            rb.pack(anchor="w", pady=1)
            attach_tip(rb, tip)

        # ── Options ──
        opts = ttk.LabelFrame(self, text="Options", padding=8)
        opts.pack(fill="x", pady=4)

        orphan_cb = ttk.Checkbutton(opts, text="Include orphaned entries (dead extensions)",
                                     variable=self._vars["include_orphans"])
        orphan_cb.pack(anchor="w")
        attach_tip(orphan_cb,
                   "Also scan entries no longer in the library but still in Suwayomi's DB.")

        full_cb = ttk.Checkbutton(opts, text="Full rescan (ignore last-snapshot time)",
                                  variable=self._vars["full_scan"])
        full_cb.pack(anchor="w")
        attach_tip(full_cb,
                   "By default, only entries read since the last snapshot are scanned. "
                   "Check this to force a full rescan.")

        LabeledEntry(opts, "Filter title", self._vars["filter_title"], width=45,
                     tooltip="Only process titles containing this substring (apply/show)").pack(fill="x", pady=4)

        # ── Show / Export options ──
        extra = ttk.LabelFrame(self, text="Show / Export", padding=8)
        extra.pack(fill="x", pady=4)

        LabeledEntry(extra, "Search query (show)", self._vars["show_query"], width=45,
                     tooltip="Title to search for. Leave blank for overall stats.").pack(fill="x", pady=2)
        LabeledEntry(extra, "Export output path", self._vars["export_output"], width=45,
                     tooltip="File path for the CSV export (default: ledger_export.csv)").pack(fill="x", pady=2)

        # ── Advanced ──
        adv = ttk.LabelFrame(self, text="Advanced", padding=8)
        adv.pack(fill="x", pady=4)

        LabeledEntry(adv, "Ledger DB path", self._vars["ledger_db"], width=50,
                     tooltip="Override the default DB location (~/.seiyomi/read_ledger.db). "
                             "Leave blank for default.").pack(fill="x", pady=2)

    def get_args(self) -> List[str]:
        self.flush_to_state()
        ls = self._state.ledger
        action = ls.action or "auto"

        if action == "show":
            args = ["ledger", "show"]
            if ls.show_query:
                args.append(ls.show_query)
            if ls.ledger_db:
                args += ["--ledger-db", ls.ledger_db]
            return args

        if action == "export":
            args = ["ledger", "export"]
            if ls.export_output:
                args += ["--output", ls.export_output]
            if ls.ledger_db:
                args += ["--ledger-db", ls.ledger_db]
            return args

        # snapshot / apply / auto
        args = ["ledger", action]
        if action in ("snapshot", "auto"):
            if not ls.include_orphans:
                args.append("--no-include-orphans")
            if ls.full_scan:
                args.append("--full")
        if action in ("apply", "auto") and ls.filter_title:
            args += ["--filter", ls.filter_title]
        if ls.ledger_db:
            args += ["--ledger-db", ls.ledger_db]
        return args

    def flush_to_state(self) -> None:
        ls = self._state.ledger
        ls.action = self._vars["action"].get()
        ls.include_orphans = bool(self._vars["include_orphans"].get())
        ls.full_scan = bool(self._vars["full_scan"].get())
        ls.filter_title = self._vars["filter_title"].get().strip()
        ls.ledger_db = self._vars["ledger_db"].get().strip()
        ls.show_query = self._vars["show_query"].get().strip()
        ls.export_output = self._vars["export_output"].get().strip()
