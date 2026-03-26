"""Tests for seiyomi.operations.read_sync — chapter sync operations."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from seiyomi.operations.read_sync import (
    _parse_chapter_number,
    _build_fraction_map,
    _is_fraction_canonical,
    compute_entry_progress_by_number,
    mark_entry_up_to_number,
    fetch_suwayomi_chapters,
    extract_chapter_uuid_from_item,
    sync_read_chapters_by_uuid,
)


# ---------------------------------------------------------------------------
# _parse_chapter_number
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("item,expected", [
    ({"chapterNumber": 5}, 5.0),
    ({"chapter": "12"}, 12.0),
    ({"chapter": "12.5"}, 12.5),
    ({"name": "Chapter 7"}, 7.0),
    ({"title": "Vol.3 Ch.15"}, 3.0),   # first number found
    ({}, None),
    ({"name": "Prologue"}, None),
])
def test_parse_chapter_number(item, expected):
    assert _parse_chapter_number(item) == expected


# ---------------------------------------------------------------------------
# _build_fraction_map / _is_fraction_canonical
# ---------------------------------------------------------------------------

def test_build_fraction_map_integers_only():
    nums = [1.0, 2.0, 3.0]
    fmap = _build_fraction_map(nums)
    assert 0 in fmap[1]
    assert 0 in fmap[2]
    assert 0 in fmap[3]


def test_is_fraction_canonical_integer():
    fmap = _build_fraction_map([1.0, 1.5, 2.0])
    assert _is_fraction_canonical(1.0, fmap) is True
    assert _is_fraction_canonical(2.0, fmap) is True


def test_is_fraction_canonical_half():
    fmap = _build_fraction_map([1.0, 1.5])
    # 1.5: f=5, need other fractions or >=6 — only 0 present → False
    assert _is_fraction_canonical(1.5, fmap) is False


def test_is_fraction_canonical_quarter():
    fmap = _build_fraction_map([1.0, 1.1])
    # 1.1: f=1, in range 1-4 → True
    assert _is_fraction_canonical(1.1, fmap) is True


# ---------------------------------------------------------------------------
# fetch_suwayomi_chapters
# ---------------------------------------------------------------------------

def _make_client(chapters_response: Any) -> MagicMock:
    client = MagicMock()
    resp = MagicMock()
    resp.json.return_value = chapters_response
    client.request.return_value = resp
    return client


def test_fetch_suwayomi_chapters_chapters_key():
    client = _make_client({"chapters": [{"id": 1}, {"id": 2}]})
    result = fetch_suwayomi_chapters(client, 42)
    assert len(result) == 2
    client.request.assert_called_once_with("GET", "/api/v1/manga/42/chapters")


def test_fetch_suwayomi_chapters_data_key():
    client = _make_client({"data": [{"id": 3}]})
    result = fetch_suwayomi_chapters(client, 7)
    assert result == [{"id": 3}]


def test_fetch_suwayomi_chapters_empty_on_exception():
    client = MagicMock()
    client.request.side_effect = ConnectionError("nope")
    result = fetch_suwayomi_chapters(client, 1)
    assert result == []


# ---------------------------------------------------------------------------
# extract_chapter_uuid_from_item
# ---------------------------------------------------------------------------

_VALID_UUID = "12345678-1234-1234-1234-123456789abc"


@pytest.mark.parametrize("item,expected", [
    ({"url": f"https://mangadex.org/chapter/{_VALID_UUID}"}, _VALID_UUID),
    ({"chapterUrl": _VALID_UUID}, _VALID_UUID),
    ({"sourceUrl": f"/path/{_VALID_UUID}/data"}, _VALID_UUID),
    ({"title": "no uuid here"}, None),
    ({}, None),
])
def test_extract_chapter_uuid(item, expected):
    assert extract_chapter_uuid_from_item(item) == expected


# ---------------------------------------------------------------------------
# compute_entry_progress_by_number
# ---------------------------------------------------------------------------

def test_compute_entry_progress_no_chapters():
    client = _make_client({"chapters": []})
    assert compute_entry_progress_by_number(client, 1) == 0.0


def test_compute_entry_progress_some_read():
    chapters = [
        {"id": 1, "chapterNumber": 1.0, "isRead": True},
        {"id": 2, "chapterNumber": 2.0, "isRead": True},
        {"id": 3, "chapterNumber": 3.0, "isRead": False},
    ]
    client = _make_client({"chapters": chapters})
    assert compute_entry_progress_by_number(client, 1) == 2.0


def test_compute_entry_progress_none_read():
    chapters = [
        {"id": 1, "chapterNumber": 5.0, "isRead": False},
    ]
    client = _make_client({"chapters": chapters})
    assert compute_entry_progress_by_number(client, 1) == 0.0


# ---------------------------------------------------------------------------
# mark_entry_up_to_number
# ---------------------------------------------------------------------------

def test_mark_entry_up_to_number_dry_run(caplog):
    chapters = [
        {"id": 10, "chapterNumber": 1.0, "isRead": False},
        {"id": 11, "chapterNumber": 2.0, "isRead": False},
        {"id": 12, "chapterNumber": 5.0, "isRead": False},
    ]
    client = _make_client({"chapters": chapters})
    mark_entry_up_to_number(client, 1, up_to=2.0, rpm=300, dry_run=True)
    # Should NOT call request for mark_chapter_read
    assert not any(
        call[0][0] in ("POST", "PATCH", "PUT")
        for call in client.request.call_args_list
    )


def test_mark_entry_up_to_number_skips_already_read():
    chapters = [
        {"id": 10, "chapterNumber": 1.0, "isRead": True},   # already read
        {"id": 11, "chapterNumber": 2.0, "isRead": False},  # to mark
    ]
    client = MagicMock()
    # First call: get chapters; subsequent calls: mark_chapter_read responses
    resp_chapters = MagicMock()
    resp_chapters.json.return_value = {"chapters": chapters}
    resp_mark = MagicMock()
    resp_mark.status_code = 200
    resp_verify = MagicMock()
    resp_verify.json.return_value = {"chapters": [{"id": 11, "isRead": True}]}
    client.request.side_effect = [resp_chapters, resp_mark, resp_verify]
    mark_entry_up_to_number(client, 1, up_to=2.0, rpm=600, dry_run=False)
    # mark_chapter_read tries POST for chapter 11 only
    post_calls = [
        c for c in client.request.call_args_list
        if c[0][0] == "POST"
    ]
    assert len(post_calls) >= 1
    assert "/11/" in post_calls[0][0][1] or "11" in str(post_calls[0])


# ---------------------------------------------------------------------------
# sync_read_chapters_by_uuid
# ---------------------------------------------------------------------------

def test_sync_read_by_uuid_dry_run():
    _UUID_1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    _UUID_2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    chapters = [
        {"id": 10, "chapterNumber": 1.0, "url": f"https://mangadex.org/chapter/{_UUID_1}"},
        {"id": 11, "chapterNumber": 2.0, "url": f"https://mangadex.org/chapter/{_UUID_2}"},
    ]
    client = _make_client({"chapters": chapters})
    # dry_run=True → should not call mark_chapter_read
    sync_read_chapters_by_uuid(
        client=client,
        manga_internal_id=1,
        md_read_uuids=[_UUID_1, _UUID_2],
        dry_run=True,
        rpm=300,
    )
    # Only one call: GET chapters
    assert client.request.call_count == 1


def test_sync_read_by_uuid_empty_uuids():
    client = MagicMock()
    sync_read_chapters_by_uuid(
        client=client,
        manga_internal_id=1,
        md_read_uuids=[],
        dry_run=False,
        rpm=300,
    )
    # Should still fetch chapters; missing=0, nothing to mark
    # No error


def test_sync_read_by_uuid_no_chapters():
    client = _make_client({"chapters": []})
    # Should warn but not crash
    sync_read_chapters_by_uuid(
        client=client,
        manga_internal_id=1,
        md_read_uuids=["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
        dry_run=False,
        rpm=300,
        show_progress=False,
    )


def test_sync_read_by_uuid_missing_report_path(tmp_path):
    """Chapters not found in Suwayomi are reported to missing_report_path."""
    _UUID_MISSING = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    client = _make_client({"chapters": []})
    report = tmp_path / "missing.csv"
    sync_read_chapters_by_uuid(
        client=client,
        manga_internal_id=1,
        md_read_uuids=[_UUID_MISSING],
        dry_run=False,
        rpm=300,
        show_progress=False,
        missing_report_path=report,
        manga_md_id="test-md-id",
        fetch_title_fn=lambda _: "Test Title",
    )
    assert report.exists()
