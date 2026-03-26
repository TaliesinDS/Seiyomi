"""Seiyomi configuration dataclasses.

Each dataclass maps to a group of related CLI flags. The ``from_args()``
classmethod on each class extracts the relevant fields from an
``argparse.Namespace`` so the operations modules never need to import
``argparse`` or reference the raw namespace.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ConnectionConfig:
    base_url: str
    auth_mode: str = "none"
    username: str = ""
    password: str = ""
    token: str = ""
    verify_tls: bool = True
    request_timeout: int = 30

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "ConnectionConfig":
        return cls(
            base_url=args.base_url,
            auth_mode=getattr(args, "auth_mode", "none") or "none",
            username=getattr(args, "username", "") or "",
            password=getattr(args, "password", "") or "",
            token=getattr(args, "token", "") or "",
            verify_tls=not getattr(args, "insecure", False),
            request_timeout=getattr(args, "request_timeout", 30) or 30,
        )


@dataclass
class MigrateConfig:
    threshold_chapters: int = 1
    preferred_sources: List[str] = field(default_factory=list)
    exclude_sources: List[str] = field(default_factory=list)
    preferred_langs: List[str] = field(default_factory=lambda: ["en"])
    remove_original: bool = False
    best_source: bool = True
    best_source_canonical: bool = False
    best_source_global: bool = False
    max_candidates: int = 5
    min_chapters_per_alt: int = 0
    timeout: float = 0.0
    dry_run: bool = False
    preferred_only: bool = False
    try_second_page: bool = False
    filter_title: str = ""
    include_categories: str = ""
    exclude_categories: str = ""
    max_sources_per_site: int = 0
    debug: bool = False
    no_progress: bool = False
    keep_both: bool = False
    keep_both_min_preferred: int = 0
    prefer_sources: str = ""
    prefer_boost: int = 0
    lang_fallback: bool = False
    remove_if_duplicate: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "MigrateConfig":
        pref_str = getattr(args, "migrate_sources", None) or getattr(args, "rehoming_sources", "") or ""
        pref_langs_str = getattr(args, "preferred_langs", "") or ""
        return cls(
            threshold_chapters=max(0, getattr(args, "migrate_threshold_chapters", 1)),
            preferred_sources=[s.strip().lower() for s in pref_str.split(",") if s.strip()],
            exclude_sources=[
                s.strip().lower()
                for s in (getattr(args, "exclude_sources", "") or "").split(",")
                if s.strip()
            ],
            preferred_langs=[
                s.strip().lower().replace("_", "-")
                for s in pref_langs_str.split(",")
                if s.strip()
            ],
            remove_original=getattr(args, "migrate_remove", False),
            best_source=getattr(args, "best_source", False),
            best_source_canonical=getattr(args, "best_source_canonical", False),
            best_source_global=getattr(args, "best_source_global", False),
            max_candidates=max(1, int(getattr(args, "best_source_candidates", 5) or 5)),
            min_chapters_per_alt=max(0, int(getattr(args, "min_chapters_per_alt", 0) or 0)),
            timeout=float(getattr(args, "migrate_timeout", 0) or 0),
            dry_run=getattr(args, "dry_run", False),
            preferred_only=getattr(args, "migrate_preferred_only", False),
            try_second_page=getattr(args, "migrate_try_second_page", False),
            filter_title=(getattr(args, "migrate_filter_title", "") or "").strip(),
            include_categories=getattr(args, "migrate_include_categories", "") or "",
            exclude_categories=getattr(args, "migrate_exclude_categories", "") or "",
            max_sources_per_site=int(getattr(args, "migrate_max_sources_per_site", 0) or 0),
            debug=getattr(args, "debug_library", False),
            no_progress=getattr(args, "no_progress", False),
            keep_both=getattr(args, "migrate_keep_both", False),
            keep_both_min_preferred=int(getattr(args, "keep_both_min_preferred", 0) or 0),
            prefer_sources=getattr(args, "prefer_sources", "") or "",
            prefer_boost=int(getattr(args, "prefer_boost", 0) or 0),
            lang_fallback=getattr(args, "lang_fallback", False),
            remove_if_duplicate=getattr(args, "migrate_remove_if_duplicate", False),
        )


@dataclass
class ReadSyncConfig:
    enabled: bool = False
    number_fallback: bool = True
    across_sources: bool = True
    only_if_ahead: bool = True
    delay: float = 1.0
    max_rpm: int = 300
    dry_run: bool = False
    canonical: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace, prefix: str = "chapter_sync_") -> "ReadSyncConfig":
        """Build from the chapter_sync_* flags on the argparse namespace."""
        return cls(
            enabled=getattr(args, "import_read_chapters", False),
            number_fallback=getattr(args, "read_sync_number_fallback", True),
            across_sources=getattr(args, "read_sync_across_sources", True),
            only_if_ahead=getattr(args, "read_sync_only_if_ahead", False),
            delay=float(getattr(args, "read_sync_delay", 1.0) or 1.0),
            max_rpm=int(getattr(args, "read_sync_rpm", 300) or 300),
            dry_run=getattr(args, "dry_run", False),
            canonical=getattr(args, "read_sync_canonical", False),
        )


@dataclass
class CsvImportConfig:
    title_threshold: float = 0.6
    strict_match: bool = False
    apply_read_progress: bool = False
    status_to_category: Dict[str, int] = field(default_factory=dict)
    default_category: Optional[int] = None
    status_map_debug: bool = False
    prefer_existing: bool = False
    no_add_library: bool = False
    dry_run: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "CsvImportConfig":
        return cls(
            title_threshold=float(getattr(args, "title_threshold", 0.6) or 0.6),
            strict_match=getattr(args, "title_strict", False),
            apply_read_progress=getattr(args, "csv_apply_read_progress", False),
            status_to_category=getattr(args, "status_category_map_resolved", {}) or {},
            default_category=getattr(args, "status_default_category", None),
            status_map_debug=getattr(args, "status_map_debug", False),
            prefer_existing=getattr(args, "prefer_existing", False),
            no_add_library=getattr(args, "no_add_library", False),
            dry_run=getattr(args, "dry_run", False),
        )


@dataclass
class PruneConfig:
    mode: str = "duplicates"  # "duplicates" or "languages"
    threshold_chapters: int = 0
    preferred_langs: List[str] = field(default_factory=lambda: ["en"])
    lang_threshold: int = 1
    lang_fallback_keep_most: bool = False
    filter_title: str = ""
    dry_run: bool = False
    no_progress: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace, mode: str = "duplicates") -> "PruneConfig":
        pref_langs_str = getattr(args, "preferred_langs", "") or ""
        return cls(
            mode=mode,
            threshold_chapters=max(0, int(getattr(args, "prune_threshold_chapters", 0) or 0)),
            preferred_langs=[
                s.strip().lower().replace("_", "-")
                for s in pref_langs_str.split(",")
                if s.strip()
            ],
            lang_threshold=max(1, int(getattr(args, "prune_lang_threshold", 1) or 1)),
            lang_fallback_keep_most=getattr(args, "prune_lang_fallback_keep_most", False),
            filter_title=(getattr(args, "prune_filter_title", "") or "").strip(),
            dry_run=getattr(args, "dry_run", False),
            no_progress=getattr(args, "no_progress", False),
        )


@dataclass
class RehomeConfig:
    enabled: bool = False
    preferred_sources: List[str] = field(default_factory=list)
    exclude_sources: List[str] = field(default_factory=list)
    skip_if_chapters_ge: int = 1
    remove_source_entry: bool = False
    best_source: bool = False
    best_candidates: int = 5
    min_chapters_per_alt: int = 0
    title_threshold: float = 0.6
    title_strict: bool = False
    canonical: bool = False
    dry_run: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "RehomeConfig":
        pref_str = getattr(args, "rehoming_sources", "") or ""
        return cls(
            enabled=getattr(args, "rehome", False),
            preferred_sources=[s.strip().lower() for s in pref_str.split(",") if s.strip()],
            exclude_sources=[
                s.strip().lower()
                for s in (getattr(args, "exclude_sources", "") or "").split(",")
                if s.strip()
            ],
            skip_if_chapters_ge=max(1, int(getattr(args, "rehome_skip_if_ge", 1) or 1)),
            remove_source_entry=getattr(args, "rehome_remove_md", False),
            best_source=getattr(args, "rehome_best_source", False),
            best_candidates=max(1, int(getattr(args, "rehome_best_candidates", 5) or 5)),
            min_chapters_per_alt=max(0, int(getattr(args, "rehome_min_chapters_per_alt", 0) or 0)),
            title_threshold=float(getattr(args, "rehome_title_threshold", 0.6) or 0.6),
            title_strict=getattr(args, "rehome_title_strict", False),
            canonical=getattr(args, "rehome_canonical", False),
            dry_run=getattr(args, "dry_run", False),
        )


@dataclass
class MangaDexImportConfig:
    from_follows: bool = False
    import_statuses: bool = False
    import_read_chapters: bool = False
    status_category_map: Dict[str, int] = field(default_factory=dict)
    default_category: Optional[int] = None
    ignore_statuses: List[str] = field(default_factory=list)
    assume_missing_status: Optional[str] = None
    use_title_fallback: bool = True
    throttle: float = 0.0
    dry_run: bool = False
    status_map_debug: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "MangaDexImportConfig":
        return cls(
            from_follows=getattr(args, "from_follows", False),
            import_statuses=getattr(args, "import_statuses", False),
            import_read_chapters=getattr(args, "import_read_chapters", False),
            status_category_map=getattr(args, "status_category_map_resolved", {}) or {},
            default_category=getattr(args, "status_default_category", None),
            ignore_statuses=[
                s.strip().lower()
                for s in (getattr(args, "ignore_statuses", "") or "").split(",")
                if s.strip()
            ],
            assume_missing_status=getattr(args, "assume_missing_status", None),
            use_title_fallback=not getattr(args, "no_title_fallback", False),
            throttle=float(getattr(args, "throttle", 0.0) or 0.0),
            dry_run=getattr(args, "dry_run", False),
            status_map_debug=getattr(args, "status_map_debug", False),
        )
