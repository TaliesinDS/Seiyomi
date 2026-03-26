"""Tests for seiyomi.importers.csv_import — CSV parsing layer."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import List

import pytest

from seiyomi.importers.csv_import import (
    CsvItem,
    CSV_KIND_COMICK,
    CSV_KIND_MANGANATO,
    CSV_KIND_AUTO,
    _normalize_last_read,
    _normalize_chapter_hint,
    detect_csv_kind,
    parse_comick_csv,
    parse_manganato_csv,
    load_csv_items,
    parse_csv_column_map,
)


# ---------------------------------------------------------------------------
# _normalize_last_read
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("0", "0"),
    (0, "0"),
    ("1", "1"),
    ("Chapter 5", "Chapter 5"),
    (None, None),
    ("", None),
    ("0000-00-00", None),
    ("0000:00:00", None),
    ("1970-01-01", None),
])
def test_normalize_last_read(raw, expected):
    assert _normalize_last_read(raw) == expected


# ---------------------------------------------------------------------------
# _normalize_chapter_hint
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Chapter 5", "5"),
    ("chap 12", "12"),
    ("#3", "3"),
    ("5.5", "5.5"),
    ("0", "0"),
    (None, None),
    ("", None),
])
def test_normalize_chapter_hint(raw, expected):
    assert _normalize_chapter_hint(raw) == expected


# ---------------------------------------------------------------------------
# parse_comick_csv
# ---------------------------------------------------------------------------

def _write_comick_csv(path: Path, rows: List[dict]) -> None:
    fieldnames = ["hid", "title", "synonyms", "type", "status", "read", "last_read", "rating", "mal"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_parse_comick_csv_basic(tmp_path: Path):
    p = tmp_path / "test.csv"
    _write_comick_csv(p, [
        {"hid": "abc123", "title": "Blue Lock", "synonyms": "Blue Lock;BL", "type": "manga",
         "status": "", "read": "Chapter 5", "last_read": "2024-01-01", "rating": "9", "mal": ""},
    ])
    items = parse_comick_csv(p)
    assert len(items) == 1
    item = items[0]
    assert item.title == "Blue Lock"
    assert item.external_ids["comick"] == "abc123"
    assert "Blue Lock" in item.synonyms
    assert "BL" in item.synonyms
    assert item.status == "manga"
    assert item.last_read_chapter == "5"
    assert item.last_read_at == "2024-01-01"
    assert item.rating == "9"
    assert item.source == CSV_KIND_COMICK


def test_parse_comick_csv_skips_blank_titles(tmp_path: Path):
    p = tmp_path / "test.csv"
    _write_comick_csv(p, [
        {"hid": "x", "title": "", "synonyms": "", "type": "", "status": "", "read": "", "last_read": "", "rating": "", "mal": ""},
        {"hid": "y", "title": "Solo Leveling", "synonyms": "", "type": "", "status": "", "read": "", "last_read": "", "rating": "", "mal": ""},
    ])
    items = parse_comick_csv(p)
    assert len(items) == 1
    assert items[0].title == "Solo Leveling"


def test_parse_comick_csv_zero_chapter_preserved(tmp_path: Path):
    p = tmp_path / "test.csv"
    _write_comick_csv(p, [
        {"hid": "z", "title": "Test Manga", "synonyms": "", "type": "", "status": "",
         "read": "0", "last_read": "0", "rating": "", "mal": ""},
    ])
    items = parse_comick_csv(p)
    assert items[0].last_read_chapter == "0"
    # last_read "0" is not a zero-epoch date, so it should be preserved
    assert items[0].last_read_at == "0"


# ---------------------------------------------------------------------------
# parse_manganato_csv
# ---------------------------------------------------------------------------

def _write_manganato_csv(path: Path, rows: List[dict]) -> None:
    fieldnames = ["Title", "URL", "Viewed"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_parse_manganato_csv_basic(tmp_path: Path):
    p = tmp_path / "test.csv"
    _write_manganato_csv(p, [
        {"Title": "Attack on Titan", "URL": "https://manganato.com/manga-123", "Viewed": "Chapter 10"},
    ])
    items = parse_manganato_csv(p)
    assert len(items) == 1
    item = items[0]
    assert item.title == "Attack on Titan"
    assert item.external_ids["manganato"] == "https://manganato.com/manga-123"
    assert item.last_read_chapter == "10"
    assert item.source == CSV_KIND_MANGANATO


def test_parse_manganato_csv_column_map_override(tmp_path: Path):
    p = tmp_path / "test.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Name", "Link", "Read"])
        writer.writeheader()
        writer.writerow({"Name": "Solo Leveling", "Link": "https://example.com", "Read": "5"})
    items = parse_manganato_csv(p, column_map={"title": "Name", "url": "Link", "viewed": "Read"})
    assert len(items) == 1
    assert items[0].title == "Solo Leveling"
    assert items[0].last_read_chapter == "5"


# ---------------------------------------------------------------------------
# detect_csv_kind
# ---------------------------------------------------------------------------

def test_detect_csv_kind_comick(tmp_path: Path):
    p = tmp_path / "comick.csv"
    p.write_text("hid,title,synonyms\nabc,Blue Lock,BL\n", encoding="utf-8")
    assert detect_csv_kind(p) == CSV_KIND_COMICK


def test_detect_csv_kind_manganato(tmp_path: Path):
    p = tmp_path / "manganato.csv"
    p.write_text("Title,URL\nBlue Lock,https://manganato.com/x\n", encoding="utf-8")
    assert detect_csv_kind(p) == CSV_KIND_MANGANATO


def test_detect_csv_kind_forced(tmp_path: Path):
    p = tmp_path / "any.csv"
    p.write_text("Title,URL\nBlue Lock,https://manganato.com/x\n", encoding="utf-8")
    assert detect_csv_kind(p, forced="comick") == CSV_KIND_COMICK


def test_detect_csv_kind_auto_falls_back(tmp_path: Path):
    p = tmp_path / "unknown.csv"
    p.write_text("col1,col2\nval1,val2\n", encoding="utf-8")
    assert detect_csv_kind(p) == CSV_KIND_AUTO


# ---------------------------------------------------------------------------
# load_csv_items
# ---------------------------------------------------------------------------

def test_load_csv_items_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_csv_items(tmp_path / "nonexistent.csv")


def test_load_csv_items_detects_comick(tmp_path: Path):
    p = tmp_path / "comick.csv"
    p.write_text("hid,title,synonyms\nabc,Blue Lock,BL\n", encoding="utf-8")
    kind, items = load_csv_items(p)
    assert kind == CSV_KIND_COMICK
    assert items[0].title == "Blue Lock"


# ---------------------------------------------------------------------------
# parse_csv_column_map
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("overrides,expected", [
    (["title=Name,url=Link"], {"title": "Name", "url": "Link"}),
    (["title=Name", "url=Link"], {"title": "Name", "url": "Link"}),
    (None, {}),
    ([], {}),
])
def test_parse_csv_column_map(overrides, expected):
    assert parse_csv_column_map(overrides) == expected


def test_parse_csv_column_map_invalid_raises():
    with pytest.raises(ValueError):
        parse_csv_column_map(["titleName"])  # missing =
