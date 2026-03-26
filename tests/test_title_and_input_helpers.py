from __future__ import annotations

import json
from pathlib import Path

import pytest

from seiyomi.matching.titles import (
    normalize_title_tokens as _normalize_title_tokens,
    title_similarity as _title_similarity,
    is_title_match as _is_title_match,
)
from import_mangadex_bookmarks_to_suwayomi_refactored import (
    SuwayomiClient,
    extract_mangadex_ids,
    read_any,
)


@pytest.mark.parametrize(
    "title,expected",
    [
        ("The Official Guide (Color Edition)", ["guide"]),
        ("{Special} My Hero Academia", ["my", "hero", "academia"]),
        ("A Tale of Two Cities", ["tale", "two", "cities"]),
    ],
)
def test_normalize_title_tokens(title: str, expected: list[str]):
    assert _normalize_title_tokens(title) == expected


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("Blue Lock", "Blue Lock", 1.0),
        ("Blue Lock", "Lock Blue", 1.0),
    ("Attack on Titan", "Attack of Titan", 1.0),
    ("My Dress-Up Darling", "Dress Up Darling", 0.75),
    ],
)
def test_title_similarity(a: str, b: str, expected: float):
    assert _title_similarity(a, b) == pytest.approx(expected)


@pytest.mark.parametrize(
    "a,b,threshold,strict,expected",
    [
        ("Blue Lock", "Blue Lock", 0.6, False, True),
        ("Blue Lock", "Lock Blue", 0.6, True, False),
        ("Attack on Titan", "Titan Attack", 0.5, False, True),
        ("Attack on Titan", "Titanfall", 0.5, False, False),
    ],
)
def test_is_title_match(a: str, b: str, threshold: float, strict: bool, expected: bool):
    assert _is_title_match(a, b, threshold=threshold, strict_exact=strict) is expected


def test_extract_mangadex_ids_dedupes_and_preserves_order():
    text = (
        "https://mangadex.org/title/11111111-1111-1111-1111-111111111111/example "
        "some extra text 22222222-2222-2222-2222-222222222222 "
        "https://mangadex.org/title/11111111-1111-1111-1111-111111111111"
    )
    ids = extract_mangadex_ids(text)
    assert ids == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]


@pytest.mark.parametrize("suffix", [".txt", ".json", ".csv"])
def test_read_any_supports_multiple_formats(tmp_path: Path, suffix: str):
    ids = [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
    ]
    target = tmp_path / f"sample{suffix}"
    if suffix == ".txt":
        target.write_text("\n".join(ids + [ids[0]]), encoding="utf-8")
    elif suffix == ".json":
        content = {
            "items": ids,
            "nested": {"also": ids[1]},
        }
        target.write_text(json.dumps(content), encoding="utf-8")
    else:
        target.write_text(
            "id\n" + "\n".join(ids[:2]) + f"\nhttps://mangadex.org/title/{ids[2]}",
            encoding="utf-8",
        )
    extracted = read_any(target)
    assert extracted == ids


def test_canonical_key_from_chapter_numeric_and_string():
    client = SuwayomiClient(base_url="http://dummy")
    assert client._canonical_key_from_chapter({"chapterNumber": 12.4}) == "12"
    assert client._canonical_key_from_chapter({"title": "Ch. 5.2", "name": "Chapter 5.2"}) == "5"


def test_canonical_key_from_chapter_skips_special_labels():
    client = SuwayomiClient(base_url="http://dummy")
    assert client._canonical_key_from_chapter({"title": "Special Extra"}) is None


def test_filter_items_by_lang_matches_variants():
    client = SuwayomiClient(base_url="http://dummy")
    items = [
        {"id": 1, "language": "en"},
        {"id": 2, "translatedLanguage": "en-us"},
        {"id": 3, "lang": "fr"},
    ]
    result = client._filter_items_by_lang(items, {"en-us"})
    assert [it["id"] for it in result] == [1, 2]


class DummyClient(SuwayomiClient):
    def __init__(self, items):
        super().__init__(base_url="http://dummy")
        self._items = list(items)

    def get_chapters(self, manga_id: int):  # type: ignore[override]
        return list(self._items)

    # Keep old override name so any legacy callers also work
    def get_manga_chapters_entries(self, manga_id: int):  # type: ignore[override]
        return list(self._items)


def test_get_manga_chapters_count_by_lang_canonical_unique():
    chapters = [
        {"id": 1, "language": "en", "chapter": "1"},
        {"id": 2, "language": "en-us", "chapter": "1.1"},
        {"id": 3, "language": "en", "chapter": "2"},
        {"id": 4, "language": "ja", "chapter": "4"},
    ]
    client = DummyClient(chapters)
    count = client.get_manga_chapters_count_by_lang(101, {"en", "en-us"}, canonical=True)
    assert count == 2


def test_get_manga_chapters_count_by_lang_no_matches_returns_zero():
    chapters = [
        {"id": 1, "language": "ja", "chapter": "1"},
    ]
    client = DummyClient(chapters)
    assert client.get_manga_chapters_count_by_lang(101, {"en"}) == 0
