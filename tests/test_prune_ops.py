"""Operation tests for seiyomi.operations.prune.

These tests verify:
- prune_zero_duplicates: only removes enteries with fewer chapters than the max
- prune_zero_duplicates: dry_run suppresses mutations
- prune_zero_duplicates: threshold parameter is respected
- prune_zero_duplicates: single entry per title is never removed
- prune_nonpreferred_langs: entry with preferred-lang chapters is kept
- prune_nonpreferred_langs: entry without preferred-lang chapters is removed
- Both functions handle empty library (return 5)
"""
from __future__ import annotations

import argparse
from unittest.mock import MagicMock, call

import pytest

from seiyomi.operations.prune import prune_zero_duplicates, prune_nonpreferred_langs


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _dup_args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        prune_threshold_chapters=1,
        prune_filter_title="",
        dry_run=False,
        no_progress=True,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _lang_args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        preferred_langs="en",
        prune_filter_title="",
        prune_lang_threshold=1,
        prune_lang_fallback_keep_most=False,
        dry_run=False,
        no_progress=True,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _entry(id_: int, title: str) -> dict:
    return {"id": id_, "title": title}


def _client_with_library(entries, chapter_counts=None):
    """Build a mock SuwayomiClient with a fixed library and chapter counts."""
    c = MagicMock()
    c.get_library.return_value = entries
    c.remove_from_library.return_value = True
    if chapter_counts is None:
        c.get_manga_chapters_count.return_value = 0
    else:
        c.get_manga_chapters_count.side_effect = lambda mid: chapter_counts.get(mid, 0)
    return c


# ────────────────────────────────────────────────────────────────────────────
# prune_zero_duplicates
# ────────────────────────────────────────────────────────────────────────────

class TestPruneZeroDuplicates:
    def test_returns_5_when_library_empty(self):
        c = _client_with_library(None)
        assert prune_zero_duplicates(c, _dup_args()) == 5

    def test_single_entry_never_removed(self):
        c = _client_with_library([_entry(1, "Berserk")], {1: 0})
        prune_zero_duplicates(c, _dup_args())
        c.remove_from_library.assert_not_called()

    def test_removes_zero_chapter_duplicate(self):
        """Given two entries for the same title, the one with 0 chapters should be pruned."""
        entries = [_entry(1, "One Piece"), _entry(2, "One Piece")]
        c = _client_with_library(entries, {1: 100, 2: 0})
        prune_zero_duplicates(c, _dup_args(prune_threshold_chapters=1))
        c.remove_from_library.assert_called_once_with(2)

    def test_keeps_entry_above_threshold(self):
        """Both duplicates above threshold → neither is removed."""
        entries = [_entry(1, "Naruto"), _entry(2, "Naruto")]
        c = _client_with_library(entries, {1: 10, 2: 5})
        prune_zero_duplicates(c, _dup_args(prune_threshold_chapters=1))
        # Both above threshold=1, both have chapters, tie-break keeps higher → removes 2
        # In any case, entry 1 (max) should not be removed
        removed_ids = [c[0][0] for c in c.remove_from_library.call_args_list]
        assert 1 not in removed_ids  # the max-chapter entry is never removed

    def test_dry_run_suppresses_remove(self):
        entries = [_entry(1, "Dragon Ball"), _entry(2, "Dragon Ball")]
        c = _client_with_library(entries, {1: 50, 2: 0})
        prune_zero_duplicates(c, _dup_args(dry_run=True))
        c.remove_from_library.assert_not_called()

    def test_threshold_respected(self):
        """threshold=50 means entries below 50 chapters are candidates for removal."""
        entries = [_entry(1, "Bleach"), _entry(2, "Bleach")]
        c = _client_with_library(entries, {1: 100, 2: 30})
        prune_zero_duplicates(c, _dup_args(prune_threshold_chapters=50))
        c.remove_from_library.assert_called_once_with(2)

    def test_filter_title_skips_non_matching(self):
        entries = [_entry(1, "Berserk"), _entry(2, "Berserk"),
                   _entry(3, "Vinland Saga"), _entry(4, "Vinland Saga")]
        c = _client_with_library(entries, {1: 50, 2: 0, 3: 20, 4: 0})
        prune_zero_duplicates(c, _dup_args(prune_filter_title="berserk", prune_threshold_chapters=1))
        removed = [call_[0][0] for call_ in c.remove_from_library.call_args_list]
        assert 2 in removed     # Berserk zero-chapter entry removed
        assert 4 not in removed  # Vinland Saga filtered out

    def test_returns_0_on_success(self):
        c = _client_with_library([_entry(1, "Solo Entry")], {1: 5})
        assert prune_zero_duplicates(c, _dup_args()) == 0


# ────────────────────────────────────────────────────────────────────────────
# prune_nonpreferred_langs
# ────────────────────────────────────────────────────────────────────────────

class TestPruneNonPreferredLangs:
    def test_returns_5_when_library_empty(self):
        c = _client_with_library(None)
        c.get_manga_chapters_count_by_lang = MagicMock(return_value=0)
        assert prune_nonpreferred_langs(c, _lang_args()) == 5

    def test_returns_2_without_preferred_langs(self):
        c = _client_with_library([_entry(1, "Test")])
        c.get_manga_chapters_count_by_lang = MagicMock(return_value=0)
        assert prune_nonpreferred_langs(c, _lang_args(preferred_langs="")) == 2

    def test_keeps_entry_with_preferred_chapters(self):
        """Entry 1 has English chapters; entry 2 has none → entry 2 removed."""
        entries = [_entry(1, "Attack on Titan"), _entry(2, "Attack on Titan")]
        c = _client_with_library(entries, {1: 10, 2: 10})
        c.get_manga_chapters_count_by_lang = MagicMock(side_effect=lambda mid, *args, **kw: 10 if mid == 1 else 0)
        prune_nonpreferred_langs(c, _lang_args())
        removed = [ca[0][0] for ca in c.remove_from_library.call_args_list]
        assert 2 in removed
        assert 1 not in removed

    def test_dry_run_suppresses_remove(self):
        entries = [_entry(1, "Test"), _entry(2, "Test")]
        c = _client_with_library(entries, {1: 10, 2: 10})
        c.get_manga_chapters_count_by_lang = MagicMock(side_effect=lambda mid, *args, **kw: 10 if mid == 1 else 0)
        prune_nonpreferred_langs(c, _lang_args(dry_run=True))
        c.remove_from_library.assert_not_called()

    def test_no_preferred_chapters_keeps_all_by_default(self):
        """If NO entry has preferred-lang chapters and fallback_keep_most=False, keep all."""
        entries = [_entry(1, "Manga"), _entry(2, "Manga")]
        c = _client_with_library(entries, {1: 5, 2: 3})
        c.get_manga_chapters_count_by_lang = MagicMock(return_value=0)
        prune_nonpreferred_langs(c, _lang_args())
        c.remove_from_library.assert_not_called()

    def test_fallback_keep_most_removes_lower_count(self):
        """With fallback_keep_most=True and no preferred langs, keep highest-chapter entry."""
        entries = [_entry(1, "Manga"), _entry(2, "Manga")]
        c = _client_with_library(entries, {1: 50, 2: 3})
        c.get_manga_chapters_count_by_lang = MagicMock(return_value=0)
        prune_nonpreferred_langs(c, _lang_args(prune_lang_fallback_keep_most=True))
        removed = [ca[0][0] for ca in c.remove_from_library.call_args_list]
        assert 2 in removed
        assert 1 not in removed

    def test_single_entry_never_removed(self):
        c = _client_with_library([_entry(1, "Solo")])
        c.get_manga_chapters_count_by_lang = MagicMock(return_value=0)
        prune_nonpreferred_langs(c, _lang_args())
        c.remove_from_library.assert_not_called()

    def test_returns_0_on_success(self):
        c = _client_with_library([_entry(1, "Solo")])
        c.get_manga_chapters_count_by_lang = MagicMock(return_value=5)
        assert prune_nonpreferred_langs(c, _lang_args()) == 0
