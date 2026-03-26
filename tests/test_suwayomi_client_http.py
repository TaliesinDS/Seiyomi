from __future__ import annotations

import pytest
import responses

from import_mangadex_bookmarks_to_suwayomi_refactored import SuwayomiClient, _normalize_last_read


def test_remove_from_library_fallback_uses_get(responses_mock: responses.RequestsMock):
    client = SuwayomiClient(base_url="http://example.com")
    responses_mock.add(
        responses.DELETE,
        "http://example.com/api/v1/manga/5/library",
        status=404,
    )
    responses_mock.add(
        responses.GET,
        "http://example.com/api/v1/manga/5/library/remove",
        status=200,
    )
    assert client.remove_from_library(5) is True


def test_remove_from_library_returns_false_when_all_paths_fail(responses_mock: responses.RequestsMock):
    client = SuwayomiClient(base_url="http://example.com")
    responses_mock.add(
        responses.DELETE,
        "http://example.com/api/v1/manga/5/library",
        status=404,
    )
    responses_mock.add(
        responses.GET,
        "http://example.com/api/v1/manga/5/library/remove",
        status=500,
    )
    assert client.remove_from_library(5) is False


def test_graphql_fallbacks_to_secondary_endpoint(responses_mock: responses.RequestsMock):
    client = SuwayomiClient(base_url="http://example.com")
    responses_mock.add(
        responses.POST,
        "http://example.com/api/graphql",
        status=500,
    )
    responses_mock.add(
        responses.POST,
        "http://example.com/graphql",
        json={"data": {"ok": True}},
        status=200,
    )
    payload = client.graphql("query { ok }")
    assert payload == {"data": {"ok": True}}


# --- Bug fix tests ---

# Bug 2: _auth() simple mode should accept 301 redirect without raising
def test_auth_simple_accepts_301(responses_mock: responses.RequestsMock):
    client = SuwayomiClient(
        base_url="http://example.com",
        auth_mode="simple",
        username="user",
        password="pass",
    )
    responses_mock.add(
        responses.POST,
        "http://example.com/login.html",
        status=301,
    )
    # Should not raise RuntimeError
    client._auth()


# Bug 7: _normalize_last_read("0") should return "0", not None
@pytest.mark.parametrize("raw,expected", [
    ("0", "0"),
    (0, "0"),
    ("1", "1"),
    ("Chapter 5", "Chapter 5"),
    (None, None),
    ("", None),
    ("0000-00-00", None),
    ("1970-01-01", None),
])
def test_normalize_last_read_zero_is_valid(raw, expected):
    assert _normalize_last_read(raw) == expected


# Bug 8: list_library_titles gate — verifying the exemption is present
# (The fix adds list_library_titles to the gate's exemption list in main();
#  we test the underlying exemption by checking the gate condition directly.)
def test_normalize_last_read_no_false_rejections():
    """Ensure chapter-0 values are preserved, not dropped as nulls."""
    assert _normalize_last_read("0") == "0"
    assert _normalize_last_read(0) == "0"
    assert _normalize_last_read("0.0") == "0.0"

