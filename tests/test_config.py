"""Smoke tests for seiyomi.config dataclasses.

These tests verify that:
1. All dataclasses can be instantiated with defaults.
2. ``from_args`` extracts the correct fields from a mock argparse.Namespace.
"""
from __future__ import annotations

import argparse
import pytest

from seiyomi.config import (
    ConnectionConfig,
    MigrateConfig,
    ReadSyncConfig,
    CsvImportConfig,
    PruneConfig,
    RehomeConfig,
    MangaDexImportConfig,
)


def _ns(**kwargs) -> argparse.Namespace:
    """Build a minimal argparse.Namespace for testing."""
    defaults = dict(
        base_url="http://localhost:4567",
        auth_mode="none",
        username="",
        password="",
        token="",
        insecure=False,
        request_timeout=30,
        migrate_threshold_chapters=1,
        migrate_sources="",
        rehoming_sources="",
        exclude_sources="",
        preferred_langs="en",
        migrate_remove=False,
        best_source=False,
        best_source_canonical=False,
        best_source_global=False,
        best_source_candidates=5,
        min_chapters_per_alt=0,
        migrate_timeout=0,
        dry_run=False,
        migrate_preferred_only=False,
        migrate_try_second_page=False,
        migrate_filter_title="",
        migrate_include_categories="",
        migrate_exclude_categories="",
        migrate_max_sources_per_site=0,
        debug_library=False,
        no_progress=False,
        migrate_keep_both=False,
        keep_both_min_preferred=0,
        prefer_sources="",
        prefer_boost=0,
        lang_fallback=False,
        migrate_remove_if_duplicate=False,
        import_read_chapters=False,
        read_sync_number_fallback=True,
        read_sync_across_sources=True,
        read_sync_only_if_ahead=False,
        read_sync_delay=1.0,
        read_sync_rpm=300,
        read_sync_canonical=False,
        title_threshold=0.6,
        title_strict=False,
        csv_apply_read_progress=False,
        status_category_map_resolved={},
        status_default_category=None,
        status_map_debug=False,
        prefer_existing=False,
        no_add_library=False,
        prune_threshold_chapters=0,
        prune_lang_threshold=1,
        prune_lang_fallback_keep_most=False,
        prune_filter_title="",
        rehome=False,
        rehome_skip_if_ge=1,
        rehome_remove_md=False,
        rehome_best_source=False,
        rehome_best_candidates=5,
        rehome_min_chapters_per_alt=0,
        rehome_title_threshold=0.6,
        rehome_title_strict=False,
        rehome_canonical=False,
        from_follows=False,
        import_statuses=False,
        ignore_statuses="",
        assume_missing_status=None,
        no_title_fallback=False,
        throttle=0.0,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---- ConnectionConfig ----

def test_connection_config_defaults():
    ns = _ns()
    cfg = ConnectionConfig.from_args(ns)
    assert cfg.base_url == "http://localhost:4567"
    assert cfg.auth_mode == "none"
    assert cfg.verify_tls is True
    assert cfg.request_timeout == 30


def test_connection_config_insecure():
    ns = _ns(insecure=True)
    cfg = ConnectionConfig.from_args(ns)
    assert cfg.verify_tls is False


# ---- MigrateConfig ----

def test_migrate_config_defaults():
    ns = _ns()
    cfg = MigrateConfig.from_args(ns)
    assert cfg.dry_run is False
    assert cfg.preferred_sources == []


def test_migrate_config_sources_parsed():
    ns = _ns(migrate_sources="Mangafire, Comick")
    cfg = MigrateConfig.from_args(ns)
    assert cfg.preferred_sources == ["mangafire", "comick"]


def test_migrate_config_threshold_clamped():
    ns = _ns(migrate_threshold_chapters=-5)
    cfg = MigrateConfig.from_args(ns)
    assert cfg.threshold_chapters == 0


# ---- ReadSyncConfig ----

def test_read_sync_config_defaults():
    ns = _ns()
    cfg = ReadSyncConfig.from_args(ns)
    assert cfg.enabled is False
    assert cfg.max_rpm == 300


def test_read_sync_config_enabled():
    ns = _ns(import_read_chapters=True)
    cfg = ReadSyncConfig.from_args(ns)
    assert cfg.enabled is True


# ---- CsvImportConfig ----

def test_csv_import_config_defaults():
    ns = _ns()
    cfg = CsvImportConfig.from_args(ns)
    assert cfg.title_threshold == pytest.approx(0.6)
    assert cfg.apply_read_progress is False


def test_csv_import_config_status_map():
    ns = _ns(status_category_map_resolved={"reading": 1, "completed": 2})
    cfg = CsvImportConfig.from_args(ns)
    assert cfg.status_to_category["reading"] == 1
    assert cfg.status_to_category["completed"] == 2


# ---- PruneConfig ----

def test_prune_config_duplicates_mode():
    ns = _ns()
    cfg = PruneConfig.from_args(ns, mode="duplicates")
    assert cfg.mode == "duplicates"


def test_prune_config_langs_parsed():
    ns = _ns(preferred_langs="en,ja")
    cfg = PruneConfig.from_args(ns, mode="languages")
    assert cfg.preferred_langs == ["en", "ja"]


# ---- RehomeConfig ----

def test_rehome_config_defaults():
    ns = _ns()
    cfg = RehomeConfig.from_args(ns)
    assert cfg.enabled is False
    assert cfg.skip_if_chapters_ge == 1


def test_rehome_config_enabled():
    ns = _ns(rehome=True, rehoming_sources="comick,mangafire")
    cfg = RehomeConfig.from_args(ns)
    assert cfg.enabled is True
    assert cfg.preferred_sources == ["comick", "mangafire"]


# ---- MangaDexImportConfig ----

def test_mangadex_import_config_defaults():
    ns = _ns()
    cfg = MangaDexImportConfig.from_args(ns)
    assert cfg.from_follows is False
    assert cfg.use_title_fallback is True


def test_mangadex_import_config_ignore_statuses():
    ns = _ns(ignore_statuses="dropped, on_hold")
    cfg = MangaDexImportConfig.from_args(ns)
    assert "dropped" in cfg.ignore_statuses
    assert "on_hold" in cfg.ignore_statuses


# ---- Dataclass instantiation with pure defaults (no args) ----

@pytest.mark.parametrize("cls", [
    ConnectionConfig,
    MigrateConfig,
    ReadSyncConfig,
    CsvImportConfig,
    PruneConfig,
    RehomeConfig,
    MangaDexImportConfig,
])
def test_all_configs_have_sensible_defaults(cls):
    """Each config should be instantiable with keyword args only for required fields."""
    if cls is ConnectionConfig:
        obj = cls(base_url="http://localhost:4567")
    else:
        obj = cls()
    assert obj is not None
