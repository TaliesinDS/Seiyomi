"""AppState — centralised UI state for the Seiyomi GUI.

Replaces the 80+ raw StringVar dict that the old gui_launcher_tk.py
glued together at runtime.  Each group of settings is a namespaced
sub-dataclass; the whole thing (de)serialises to/from JSON.

Dependency direction: this module imports NOTHING from seiyomi except
standard library + tkinter's StringVar/BooleanVar/IntVar.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ── Config directory (OS-roaming) ──────────────────────────────────────────

def config_dir() -> Path:
    """Return the Seiyomi config directory, migrating old MangaDex_Suwayomi dir
    if it exists."""
    base = Path(os.getenv("APPDATA") or Path.home())
    new_dir = base / "Seiyomi"
    old_dir = base / "MangaDex_Suwayomi"
    if not new_dir.exists() and old_dir.exists():
        import shutil
        try:
            shutil.copytree(str(old_dir), str(new_dir))
        except Exception:
            pass
    return new_dir


_CONFIG_FILE = "config.json"


# ── Plain-data dataclasses (no tkinter dependency) ─────────────────────────

@dataclass
class ConnectionState:
    base_url: str = "http://127.0.0.1:4567"
    auth_mode: str = "auto"
    username: str = ""
    password: str = ""
    token: str = ""
    insecure: bool = False
    request_timeout: float = 12.0


@dataclass
class MigrateState:
    enabled: bool = False
    sources: str = ""
    exclude_sources: str = "comick,hitomi"
    from_source: str = ""
    threshold_chapters: int = 1
    remove_original: bool = False
    best_source: bool = True
    best_canonical: bool = True
    best_global: bool = False
    best_candidates: int = 5
    min_chapters_per_alt: int = 0
    preferred_langs: str = "en"
    lang_fallback: bool = False
    prefer_sources: str = ""
    prefer_boost: int = 3
    keep_both: bool = False
    keep_both_min: int = 1
    remove_if_duplicate: bool = False
    timeout: float = 20.0
    max_sources_per_site: int = 3
    try_second_page: bool = True
    workers: int = 0
    comick_prefilter: bool = False
    rejects_file: str = "rejects.csv"
    filter_title: str = ""
    title_threshold: float = 0.6
    title_strict: bool = False
    include_categories: str = ""
    exclude_categories: str = ""
    sync_reads: bool = False


@dataclass
class CsvImportState:
    enabled: bool = False
    files: List[str] = field(default_factory=list)
    threshold: float = 0.6
    strict: bool = False
    status_map: str = ""
    apply_progress: bool = False
    prefer_existing: bool = False


@dataclass
class MangaDexState:
    enabled: bool = False
    username: str = ""
    password: str = ""
    client_id: str = ""
    client_secret: str = ""
    two_fa: str = ""
    import_status: bool = False
    import_read: bool = False
    status_map: str = ""


@dataclass
class PruneState:
    zero_duplicates: bool = False
    prune_threshold: int = 0
    nonpreferred_langs: bool = False
    lang_threshold: int = 1
    keep_most: bool = False
    filter_title: str = ""


@dataclass
class SyncReadsState:
    enabled: bool = False
    from_source: str = ""
    filter_title: str = ""


@dataclass
class AppState:
    connection: ConnectionState = field(default_factory=ConnectionState)
    migrate: MigrateState = field(default_factory=MigrateState)
    csv: CsvImportState = field(default_factory=CsvImportState)
    mangadex: MangaDexState = field(default_factory=MangaDexState)
    prune: PruneState = field(default_factory=PruneState)
    sync_reads: SyncReadsState = field(default_factory=SyncReadsState)
    dry_run: bool = False
    verbose: bool = False

    # ── Persistence ────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AppState":
        s = cls()
        conn = d.get("connection", {})
        if conn:
            for k, v in conn.items():
                if hasattr(s.connection, k):
                    setattr(s.connection, k, v)
        mig = d.get("migrate", {})
        if mig:
            for k, v in mig.items():
                if hasattr(s.migrate, k):
                    setattr(s.migrate, k, v)
        csv = d.get("csv", {})
        if csv:
            for k, v in csv.items():
                if hasattr(s.csv, k):
                    setattr(s.csv, k, v)
        md = d.get("mangadex", {})
        if md:
            for k, v in md.items():
                if hasattr(s.mangadex, k):
                    setattr(s.mangadex, k, v)
        prune = d.get("prune", {})
        if prune:
            for k, v in prune.items():
                if hasattr(s.prune, k):
                    setattr(s.prune, k, v)
        s.dry_run = bool(d.get("dry_run", False))
        s.verbose = bool(d.get("verbose", False))
        return s

    def save(self) -> None:
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / _CONFIG_FILE).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "AppState":
        p = config_dir() / _CONFIG_FILE
        if p.exists():
            try:
                return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                pass
        return cls()
