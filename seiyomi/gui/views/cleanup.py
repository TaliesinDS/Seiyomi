"""CleanupView — prune duplicates, non-preferred languages, and sync reads across sources."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import List

from seiyomi.gui.state import AppState
from seiyomi.gui.widgets import LabeledEntry, attach_tip


class CleanupView(ttk.Frame):
    def __init__(self, parent: tk.Widget, state: AppState) -> None:
        super().__init__(parent, padding=12)
        self._state = state
        self._vars: dict[str, tk.Variable] = {}
        self._build()

    def _build(self) -> None:
        p = self._state.prune
        sr = self._state.sync_reads
        self._vars = {
            "zero_duplicates":  tk.BooleanVar(value=p.zero_duplicates),
            "prune_threshold":  tk.StringVar(value=str(p.prune_threshold)),
            "nonpref_langs":    tk.BooleanVar(value=p.nonpreferred_langs),
            "lang_threshold":   tk.StringVar(value=str(p.lang_threshold)),
            "keep_most":        tk.BooleanVar(value=p.keep_most),
            "filter_title":     tk.StringVar(value=p.filter_title),
            "preferred_langs":  tk.StringVar(value=self._state.migrate.preferred_langs),
            # sync reads across
            "sync_reads":       tk.BooleanVar(value=sr.enabled),
            "sr_from_source":   tk.StringVar(value=sr.from_source),
            "sr_filter_title":  tk.StringVar(value=sr.filter_title),
        }

        ttk.Label(self, text="Prune Library", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(self, text="Remove duplicate or non-preferred-language entries from the library.",
                  foreground="#6b7280", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 10))

        dup = ttk.LabelFrame(self, text="Remove zero-chapter duplicates", padding=8)
        dup.pack(fill="x", pady=4)
        ttk.Checkbutton(dup, text="Enabled", variable=self._vars["zero_duplicates"]).pack(anchor="w")
        LabeledEntry(dup, "Chapter threshold", self._vars["prune_threshold"], width=8,
                     tooltip="Remove if fewer chapters than this (default: 0)").pack(fill="x", pady=4)

        lang = ttk.LabelFrame(self, text="Remove non-preferred languages", padding=8)
        lang.pack(fill="x", pady=4)
        ttk.Checkbutton(lang, text="Enabled", variable=self._vars["nonpref_langs"]).pack(anchor="w")
        LabeledEntry(lang, "Preferred languages", self._vars["preferred_langs"], width=20,
                     tooltip="Comma-separated codes to keep, e.g. en,fr").pack(fill="x", pady=4)
        LabeledEntry(lang, "Min chapter threshold", self._vars["lang_threshold"], width=8,
                     tooltip="A preferred-lang entry needs at least this many chapters to count as a keeper (default: 1)").pack(fill="x", pady=4)
        ttk.Checkbutton(lang, text="When no preferred-lang entry found, keep the source with most chapters",
                        variable=self._vars["keep_most"]).pack(anchor="w")

        ttk.Separator(self).pack(fill="x", pady=8)

        sr = ttk.LabelFrame(self, text="Sync read progress across sources", padding=8)
        sr.pack(fill="x", pady=4)
        ttk.Checkbutton(sr, text="Enabled", variable=self._vars["sync_reads"]).pack(anchor="w")
        ttk.Label(sr, text="Copy read progress from old entries to matching entries on other sources.",
                  foreground="#6b7280", font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 4))
        LabeledEntry(sr, "Donor source (--from)", self._vars["sr_from_source"], width=30,
                     tooltip="Only read progress from entries of this source (e.g. 'bato'). Leave blank to use highest across all.").pack(fill="x", pady=2)
        LabeledEntry(sr, "Filter title", self._vars["sr_filter_title"], width=40,
                     tooltip="Only sync titles containing this substring").pack(fill="x", pady=2)

        ttk.Separator(self).pack(fill="x", pady=8)

        LabeledEntry(self, "Filter title (prune)", self._vars["filter_title"], width=45,
                     tooltip="Only process entries whose title contains this substring").pack(fill="x", pady=2)

    def get_args(self) -> List[str]:
        self.flush_to_state()
        p = self._state.prune
        sr = self._state.sync_reads
        # We call the subcommands separately; the runner handles one argv at a time.
        # The view returns whichever is enabled (prefer duplicates first).
        if p.zero_duplicates:
            args = ["prune", "duplicates"]
            if p.prune_threshold != 0:
                args += ["--threshold", str(p.prune_threshold)]
            if p.filter_title:
                args += ["--filter", p.filter_title]
            return args
        if p.nonpreferred_langs:
            args = ["prune", "languages"]
            args += ["--lang", self._state.migrate.preferred_langs or "en"]
            if p.lang_threshold != 1:
                args += ["--min-chapters", str(p.lang_threshold)]
            if p.filter_title:
                args += ["--filter", p.filter_title]
            return args
        if sr.enabled:
            args = ["sync", "reads-across"]
            if sr.from_source:
                args += ["--from", sr.from_source]
            if sr.filter_title:
                args += ["--filter", sr.filter_title]
            return args
        return []

    def get_all_args(self) -> List[List[str]]:
        """Return one argv list per enabled prune operation."""
        self.flush_to_state()
        p = self._state.prune
        sr = self._state.sync_reads
        result = []
        if p.zero_duplicates:
            args = ["prune", "duplicates"]
            if p.prune_threshold != 0:
                args += ["--threshold", str(p.prune_threshold)]
            if p.filter_title:
                args += ["--filter", p.filter_title]
            result.append(args)
        if p.nonpreferred_langs:
            args = ["prune", "languages"]
            args += ["--lang", self._state.migrate.preferred_langs or "en"]
            if p.lang_threshold != 1:
                args += ["--min-chapters", str(p.lang_threshold)]
            if p.filter_title:
                args += ["--filter", p.filter_title]
            result.append(args)
        if sr.enabled:
            args = ["sync", "reads-across"]
            if sr.from_source:
                args += ["--from", sr.from_source]
            if sr.filter_title:
                args += ["--filter", sr.filter_title]
            result.append(args)
        return result

    def flush_to_state(self) -> None:
        p = self._state.prune
        p.zero_duplicates = bool(self._vars["zero_duplicates"].get())
        try:
            p.prune_threshold = int(self._vars["prune_threshold"].get())
        except ValueError:
            p.prune_threshold = 0
        p.nonpreferred_langs = bool(self._vars["nonpref_langs"].get())
        try:
            p.lang_threshold = int(self._vars["lang_threshold"].get())
        except ValueError:
            p.lang_threshold = 1
        p.keep_most = bool(self._vars["keep_most"].get())
        p.filter_title = self._vars["filter_title"].get().strip()
        self._state.migrate.preferred_langs = self._vars["preferred_langs"].get().strip()
        sr = self._state.sync_reads
        sr.enabled = bool(self._vars["sync_reads"].get())
        sr.from_source = self._vars["sr_from_source"].get().strip()
        sr.filter_title = self._vars["sr_filter_title"].get().strip()
