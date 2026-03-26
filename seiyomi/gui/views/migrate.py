"""MigrateView — library migration form."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import List

from seiyomi.gui.state import AppState
from seiyomi.gui.widgets import LabeledEntry, attach_tip


class MigrateView(ttk.Frame):
    def __init__(self, parent: tk.Widget, state: AppState) -> None:
        super().__init__(parent, padding=12)
        self._state = state
        self._vars: dict[str, tk.Variable] = {}
        self._build()

    def _build(self) -> None:
        m = self._state.migrate
        self._vars = {
            "sources":         tk.StringVar(value=m.sources),
            "exclude_sources": tk.StringVar(value=m.exclude_sources),
            "threshold":       tk.StringVar(value=str(m.threshold_chapters)),
            "preferred_langs": tk.StringVar(value=m.preferred_langs),
            "filter_title":    tk.StringVar(value=m.filter_title),
            "timeout":         tk.StringVar(value=str(m.timeout)),
            "candidates":      tk.StringVar(value=str(m.best_candidates)),
            "include_cat":     tk.StringVar(value=m.include_categories),
            "exclude_cat":     tk.StringVar(value=m.exclude_categories),
            "title_threshold": tk.StringVar(value=str(m.title_threshold)),
            # booleans
            "remove_original": tk.BooleanVar(value=m.remove_original),
            "best_source":     tk.BooleanVar(value=m.best_source),
            "best_canonical":  tk.BooleanVar(value=m.best_canonical),
            "best_global":     tk.BooleanVar(value=m.best_global),
            "lang_fallback":   tk.BooleanVar(value=m.lang_fallback),
            "try_second_page": tk.BooleanVar(value=m.try_second_page),
            "title_strict":    tk.BooleanVar(value=m.title_strict),
            "keep_both":       tk.BooleanVar(value=m.keep_both),
            "remove_if_dup":   tk.BooleanVar(value=m.remove_if_duplicate),
        }

        ttk.Label(self, text="Migrate Library", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(self, text="Find library entries with few chapters and move them to a better source.",
                  foreground="#6b7280", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 10))

        LabeledEntry(self, "Preferred sources", self._vars["sources"], width=45,
                     tooltip="Comma-separated source name fragments to prefer (leave blank = any)").pack(fill="x", pady=2)
        LabeledEntry(self, "Exclude sources", self._vars["exclude_sources"], width=45,
                     tooltip="Comma-separated source fragments to always skip (default: comick,hitomi)").pack(fill="x", pady=2)
        LabeledEntry(self, "Chapter threshold", self._vars["threshold"], width=8,
                     tooltip="Migrate entries with fewer chapters than this (default: 1)").pack(fill="x", pady=2)
        LabeledEntry(self, "Preferred languages", self._vars["preferred_langs"], width=20,
                     tooltip="Comma-separated language codes, e.g. en,fr").pack(fill="x", pady=2)
        LabeledEntry(self, "Filter title", self._vars["filter_title"], width=40,
                     tooltip="Only process titles containing this substring").pack(fill="x", pady=2)
        LabeledEntry(self, "Timeout per title (s)", self._vars["timeout"], width=8).pack(fill="x", pady=2)
        LabeledEntry(self, "Max candidates", self._vars["candidates"], width=8,
                     tooltip="Max source candidates to score per title (default: 5)").pack(fill="x", pady=2)
        LabeledEntry(self, "Title threshold", self._vars["title_threshold"], width=8,
                     tooltip="Minimum title similarity score 0..1 (default: 0.6)").pack(fill="x", pady=2)
        LabeledEntry(self, "Include categories", self._vars["include_cat"], width=40,
                     tooltip="Only migrate entries in these category IDs or names (comma-separated)").pack(fill="x", pady=2)
        LabeledEntry(self, "Exclude categories", self._vars["exclude_cat"], width=40,
                     tooltip="Skip entries in these category IDs or names (comma-separated)").pack(fill="x", pady=2)

        ttk.Separator(self).pack(fill="x", pady=8)

        flags = ttk.LabelFrame(self, text="Options", padding=6)
        flags.pack(fill="x", pady=4)

        r1 = ttk.Frame(flags); r1.pack(fill="x")
        ttk.Checkbutton(r1, text="Best source (score by chapter count)",
                        variable=self._vars["best_source"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(r1, text="Canonical chapters",
                        variable=self._vars["best_canonical"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(r1, text="Global best",
                        variable=self._vars["best_global"]).pack(side="left")

        r2 = ttk.Frame(flags); r2.pack(fill="x", pady=4)
        ttk.Checkbutton(r2, text="Try second page",
                        variable=self._vars["try_second_page"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(r2, text="Language fallback",
                        variable=self._vars["lang_fallback"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(r2, text="Strict title match",
                        variable=self._vars["title_strict"]).pack(side="left")

        r3 = ttk.Frame(flags); r3.pack(fill="x", pady=4)
        ttk.Checkbutton(r3, text="Remove original after migration",
                        variable=self._vars["remove_original"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(r3, text="Remove if duplicate already exists",
                        variable=self._vars["remove_if_dup"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(r3, text="Keep both (add new, don't remove old)",
                        variable=self._vars["keep_both"]).pack(side="left")

    def get_args(self) -> List[str]:
        self.flush_to_state()
        m = self._state.migrate
        args: List[str] = ["migrate"]
        if m.sources:
            args += ["--to", m.sources]
        if m.exclude_sources:
            args += ["--exclude", m.exclude_sources]
        if m.threshold_chapters != 1:
            args += ["--threshold", str(m.threshold_chapters)]
        if m.preferred_langs and m.preferred_langs != "en":
            args += ["--lang", m.preferred_langs]
        if m.filter_title:
            args += ["--filter", m.filter_title]
        if m.timeout != 20.0:
            args += ["--timeout", str(m.timeout)]
        if m.best_candidates != 5:
            args += ["--candidates", str(m.best_candidates)]
        if m.remove_original:
            args += ["--remove-old"]
        return args

    def flush_to_state(self) -> None:
        m = self._state.migrate
        m.sources = self._vars["sources"].get().strip()
        m.exclude_sources = self._vars["exclude_sources"].get().strip()
        try:
            m.threshold_chapters = int(self._vars["threshold"].get())
        except ValueError:
            m.threshold_chapters = 1
        m.preferred_langs = self._vars["preferred_langs"].get().strip()
        m.filter_title = self._vars["filter_title"].get().strip()
        try:
            m.timeout = float(self._vars["timeout"].get())
        except ValueError:
            m.timeout = 20.0
        try:
            m.best_candidates = int(self._vars["candidates"].get())
        except ValueError:
            m.best_candidates = 5
        try:
            m.title_threshold = float(self._vars["title_threshold"].get())
        except ValueError:
            m.title_threshold = 0.6
        m.include_categories = self._vars["include_cat"].get().strip()
        m.exclude_categories = self._vars["exclude_cat"].get().strip()
        m.remove_original = bool(self._vars["remove_original"].get())
        m.best_source = bool(self._vars["best_source"].get())
        m.best_canonical = bool(self._vars["best_canonical"].get())
        m.best_global = bool(self._vars["best_global"].get())
        m.lang_fallback = bool(self._vars["lang_fallback"].get())
        m.try_second_page = bool(self._vars["try_second_page"].get())
        m.title_strict = bool(self._vars["title_strict"].get())
        m.keep_both = bool(self._vars["keep_both"].get())
        m.remove_if_duplicate = bool(self._vars["remove_if_dup"].get())
