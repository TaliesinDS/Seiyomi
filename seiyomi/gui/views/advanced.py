"""AdvancedView — full flag access (power-user safety net).

This view allows constructing arbitrary CLI invocations. It's the
"escape hatch" for users who need flags not exposed in the other views.
It directly mirrors what the old gui_launcher_tk.py exposed.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog
from typing import List

from seiyomi.gui.state import AppState
from seiyomi.gui.widgets import LabeledEntry, LabeledDropdown, attach_tip, WarningBanner


class AdvancedView(ttk.Frame):
    """Raw CLI argument builder — direct port of the old GUI."""

    def __init__(self, parent: tk.Widget, state: AppState) -> None:
        super().__init__(parent, padding=12)
        self._state = state
        self._vars: dict[str, tk.Variable] = {}
        self._csv_files: List[str] = list(state.csv.files)
        self._build()

    def _build(self) -> None:
        WarningBanner(self, "Advanced mode — use the dedicated tabs for most operations.").pack(fill="x", pady=(0, 8))

        canvas = tk.Canvas(self, highlightthickness=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _resize(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(win_id, width=canvas.winfo_width())
        inner.bind("<Configure>", _resize)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=canvas.winfo_width()))

        self._inner = inner
        self._build_inner(inner)

    def _build_inner(self, p: ttk.Frame) -> None:
        a = self._state
        m = a.migrate
        c = a.csv
        md = a.mangadex
        pr = a.prune

        self._vars = {
            # Execution
            "dry_run":           tk.BooleanVar(value=a.dry_run),
            "verbose":           tk.BooleanVar(value=a.verbose),
            "no_progress":       tk.BooleanVar(value=False),
            # CSV
            "csv_threshold":     tk.StringVar(value=str(c.threshold)),
            "csv_strict":        tk.BooleanVar(value=c.strict),
            "csv_status_map":    tk.StringVar(value=c.status_map),
            "csv_apply_prog":    tk.BooleanVar(value=c.apply_progress),
            "csv_prefer_exist":  tk.BooleanVar(value=c.prefer_existing),
            # MangaDex
            "md_user":           tk.StringVar(value=md.username),
            "md_pass":           tk.StringVar(value=md.password),
            "md_client_id":      tk.StringVar(value=md.client_id),
            "md_client_secret":  tk.StringVar(value=md.client_secret),
            "md_2fa":            tk.StringVar(value=md.two_fa),
            "import_status":     tk.BooleanVar(value=md.import_status),
            "import_read":       tk.BooleanVar(value=md.import_read),
            "status_map":        tk.StringVar(value=md.status_map),
            # Migrate
            "migrate_enabled":   tk.BooleanVar(value=m.enabled),
            "migrate_sources":   tk.StringVar(value=m.sources),
            "exclude_sources":   tk.StringVar(value=m.exclude_sources),
            "migrate_thresh":    tk.StringVar(value=str(m.threshold_chapters)),
            "pref_langs":        tk.StringVar(value=m.preferred_langs),
            "remove_orig":       tk.BooleanVar(value=m.remove_original),
            "best_source":       tk.BooleanVar(value=m.best_source),
            "best_canon":        tk.BooleanVar(value=m.best_canonical),
            "best_global":       tk.BooleanVar(value=m.best_global),
            "filter_title":      tk.StringVar(value=m.filter_title),
            "migrate_timeout":   tk.StringVar(value=str(m.timeout)),
            # Prune
            "prune_zero":        tk.BooleanVar(value=pr.zero_duplicates),
            "prune_thresh":      tk.StringVar(value=str(pr.prune_threshold)),
            "prune_nonpref":     tk.BooleanVar(value=pr.nonpreferred_langs),
            "prune_lang_thresh": tk.StringVar(value=str(pr.lang_threshold)),
            "prune_keep_most":   tk.BooleanVar(value=pr.keep_most),
            "prune_filter":      tk.StringVar(value=pr.filter_title),
        }

        def _section(text):
            ttk.Separator(p).pack(fill="x", pady=6)
            ttk.Label(p, text=text, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))

        # ── Execution ──
        row = ttk.Frame(p); row.pack(fill="x", pady=2)
        ttk.Checkbutton(row, text="Dry run", variable=self._vars["dry_run"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row, text="Verbose", variable=self._vars["verbose"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row, text="No progress", variable=self._vars["no_progress"]).pack(side="left")

        # ── CSV ──
        _section("CSV import")
        lf = ttk.LabelFrame(p, text="CSV files", padding=4); lf.pack(fill="x", pady=2)
        self._csv_lb = tk.Listbox(lf, height=4)
        self._csv_lb.pack(side="left", fill="x", expand=True)
        for f in self._csv_files:
            self._csv_lb.insert("end", f)
        btn = ttk.Frame(lf); btn.pack(side="left", padx=4)
        ttk.Button(btn, text="Add…", command=self._csv_add, width=7).pack(fill="x", pady=1)
        ttk.Button(btn, text="Remove", command=self._csv_remove, width=7).pack(fill="x", pady=1)
        LabeledEntry(p, "Title threshold", self._vars["csv_threshold"], width=8).pack(fill="x", pady=2)
        LabeledEntry(p, "Status map", self._vars["csv_status_map"], width=45,
                     tooltip="e.g. reading=5,completed=9").pack(fill="x", pady=2)
        row2 = ttk.Frame(p); row2.pack(fill="x", pady=2)
        ttk.Checkbutton(row2, text="Strict match", variable=self._vars["csv_strict"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row2, text="Apply read progress", variable=self._vars["csv_apply_prog"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row2, text="Prefer existing", variable=self._vars["csv_prefer_exist"]).pack(side="left")

        # ── MangaDex ──
        _section("MangaDex import")
        LabeledEntry(p, "MD username", self._vars["md_user"]).pack(fill="x", pady=2)
        LabeledEntry(p, "MD password", self._vars["md_pass"], show="•").pack(fill="x", pady=2)
        LabeledEntry(p, "Client ID", self._vars["md_client_id"]).pack(fill="x", pady=2)
        LabeledEntry(p, "Client secret", self._vars["md_client_secret"], show="•").pack(fill="x", pady=2)
        LabeledEntry(p, "2FA code", self._vars["md_2fa"]).pack(fill="x", pady=2)
        row3 = ttk.Frame(p); row3.pack(fill="x", pady=2)
        ttk.Checkbutton(row3, text="Import status", variable=self._vars["import_status"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row3, text="Import read progress", variable=self._vars["import_read"]).pack(side="left")
        LabeledEntry(p, "Reading status map", self._vars["status_map"], width=45,
                     tooltip="e.g. reading=5,completed=9").pack(fill="x", pady=2)

        # ── Migrate ──
        _section("Migrate library")
        ttk.Checkbutton(p, text="Enable migration", variable=self._vars["migrate_enabled"]).pack(anchor="w", pady=2)
        LabeledEntry(p, "Preferred sources", self._vars["migrate_sources"], width=45).pack(fill="x", pady=2)
        LabeledEntry(p, "Exclude sources", self._vars["exclude_sources"], width=45).pack(fill="x", pady=2)
        LabeledEntry(p, "Chapter threshold", self._vars["migrate_thresh"], width=8).pack(fill="x", pady=2)
        LabeledEntry(p, "Preferred langs", self._vars["pref_langs"], width=20).pack(fill="x", pady=2)
        LabeledEntry(p, "Filter title", self._vars["filter_title"], width=40).pack(fill="x", pady=2)
        LabeledEntry(p, "Timeout", self._vars["migrate_timeout"], width=8).pack(fill="x", pady=2)
        row4 = ttk.Frame(p); row4.pack(fill="x", pady=2)
        ttk.Checkbutton(row4, text="Remove original", variable=self._vars["remove_orig"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row4, text="Best source", variable=self._vars["best_source"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row4, text="Canonical", variable=self._vars["best_canon"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row4, text="Global best", variable=self._vars["best_global"]).pack(side="left")

        # ── Prune ──
        _section("Prune")
        row5 = ttk.Frame(p); row5.pack(fill="x", pady=2)
        ttk.Checkbutton(row5, text="Prune zero duplicates", variable=self._vars["prune_zero"]).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row5, text="Prune non-preferred langs", variable=self._vars["prune_nonpref"]).pack(side="left")
        LabeledEntry(p, "Prune threshold", self._vars["prune_thresh"], width=8).pack(fill="x", pady=2)
        LabeledEntry(p, "Lang threshold", self._vars["prune_lang_thresh"], width=8).pack(fill="x", pady=2)
        LabeledEntry(p, "Prune filter title", self._vars["prune_filter"], width=40).pack(fill="x", pady=2)
        ttk.Checkbutton(p, text="Keep most-chapters source when no preferred-lang found",
                        variable=self._vars["prune_keep_most"]).pack(anchor="w", pady=2)

    def _csv_add(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select CSV files", filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        for p in paths:
            if p not in self._csv_lb.get(0, "end"):
                self._csv_lb.insert("end", p)

    def _csv_remove(self) -> None:
        for i in reversed(self._csv_lb.curselection()):
            self._csv_lb.delete(i)

    def get_args(self) -> List[str]:
        """Build a flat old-style argv from the current form state.

        The compat layer in cli.py will translate this to the correct subcommand.
        This view uses the OLD flat-flag interface intentionally — it's the
        escape hatch for power users who know the flags.
        """
        self.flush_to_state()
        a = self._state
        m = a.migrate
        c = a.csv
        md = a.mangadex
        pr = a.prune
        args: List[str] = []

        if a.dry_run:
            args += ["--dry-run"]
        if a.verbose:
            args += ["--verbose"]
        if self._vars["no_progress"].get():
            args += ["--no-progress"]

        # CSV
        for f in list(self._csv_lb.get(0, "end")):
            args += ["--from-csv", f]
        if c.threshold != 0.6:
            args += ["--csv-title-threshold", str(c.threshold)]
        if c.strict:
            args += ["--csv-title-strict"]
        if c.status_map:
            args += ["--csv-status-to-category", c.status_map]
        if c.apply_progress:
            args += ["--csv-apply-read-progress"]
        if c.prefer_existing:
            args += ["--csv-prefer-existing"]
        if list(self._csv_lb.get(0, "end")):
            args += ["--csv-no-mangadex"]

        # MangaDex
        if md.username:
            args += ["--from-follows", "--md-username", md.username]
            if md.password:   args += ["--md-password", md.password]
            if md.client_id:   args += ["--md-client-id", md.client_id]
            if md.client_secret: args += ["--md-client-secret", md.client_secret]
            if md.two_fa:     args += ["--md-2fa", md.two_fa]
        if md.import_status:
            args += ["--import-reading-status"]
        if md.import_read:
            args += ["--import-read-chapters"]
        if md.status_map:
            args += ["--status-category-map", md.status_map]

        # Migrate
        if m.enabled:
            args += ["--migrate-library"]
            if m.sources:           args += ["--migrate-sources", m.sources]
            if m.exclude_sources:   args += ["--exclude-sources", m.exclude_sources]
            if m.threshold_chapters != 1: args += ["--migrate-threshold-chapters", str(m.threshold_chapters)]
            if m.preferred_langs:    args += ["--preferred-langs", m.preferred_langs]
            if m.remove_original:   args += ["--migrate-remove"]
            if m.best_source:       args += ["--best-source"]
            if m.best_canonical:    args += ["--best-source-canonical"]
            if m.best_global:       args += ["--best-source-global"]
            if m.filter_title:      args += ["--migrate-filter-title", m.filter_title]
            if m.timeout != 20.0:   args += ["--migrate-timeout", str(m.timeout)]

        # Prune
        if pr.zero_duplicates:
            args += ["--prune-zero-duplicates"]
            if pr.prune_threshold != 0: args += ["--prune-threshold-chapters", str(pr.prune_threshold)]
        if pr.nonpreferred_langs:
            args += ["--prune-nonpreferred-langs"]
            if m.preferred_langs: args += ["--preferred-langs", m.preferred_langs]
            if pr.lang_threshold != 1: args += ["--prune-lang-threshold", str(pr.lang_threshold)]
        if pr.filter_title:
            args += ["--prune-filter-title", pr.filter_title]

        return args

    def flush_to_state(self) -> None:
        a = self._state
        a.dry_run = bool(self._vars["dry_run"].get())
        a.verbose = bool(self._vars["verbose"].get())
        m = a.migrate
        m.enabled = bool(self._vars["migrate_enabled"].get())
        m.sources = self._vars["migrate_sources"].get().strip()
        m.exclude_sources = self._vars["exclude_sources"].get().strip()
        try: m.threshold_chapters = int(self._vars["migrate_thresh"].get())
        except ValueError: m.threshold_chapters = 1
        m.preferred_langs = self._vars["pref_langs"].get().strip()
        m.remove_original = bool(self._vars["remove_orig"].get())
        m.best_source = bool(self._vars["best_source"].get())
        m.best_canonical = bool(self._vars["best_canon"].get())
        m.best_global = bool(self._vars["best_global"].get())
        m.filter_title = self._vars["filter_title"].get().strip()
        try: m.timeout = float(self._vars["migrate_timeout"].get())
        except ValueError: m.timeout = 20.0

        c = a.csv
        c.files = list(self._csv_lb.get(0, "end"))
        try: c.threshold = float(self._vars["csv_threshold"].get())
        except ValueError: c.threshold = 0.6
        c.strict = bool(self._vars["csv_strict"].get())
        c.status_map = self._vars["csv_status_map"].get().strip()
        c.apply_progress = bool(self._vars["csv_apply_prog"].get())
        c.prefer_existing = bool(self._vars["csv_prefer_exist"].get())

        md = a.mangadex
        md.username = self._vars["md_user"].get().strip()
        md.password = self._vars["md_pass"].get().strip()
        md.client_id = self._vars["md_client_id"].get().strip()
        md.client_secret = self._vars["md_client_secret"].get().strip()
        md.two_fa = self._vars["md_2fa"].get().strip()
        md.import_status = bool(self._vars["import_status"].get())
        md.import_read = bool(self._vars["import_read"].get())
        md.status_map = self._vars["status_map"].get().strip()

        pr = a.prune
        pr.zero_duplicates = bool(self._vars["prune_zero"].get())
        try: pr.prune_threshold = int(self._vars["prune_thresh"].get())
        except ValueError: pr.prune_threshold = 0
        pr.nonpreferred_langs = bool(self._vars["prune_nonpref"].get())
        try: pr.lang_threshold = int(self._vars["prune_lang_thresh"].get())
        except ValueError: pr.lang_threshold = 1
        pr.keep_most = bool(self._vars["prune_keep_most"].get())
        pr.filter_title = self._vars["prune_filter"].get().strip()
