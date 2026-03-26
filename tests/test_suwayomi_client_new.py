"""Service contract tests for seiyomi.clients.suwayomi.SuwayomiClient.

These tests use ``responses`` to intercept HTTP calls and verify that:
- The right HTTP method + URL is used for each operation
- Response parsing is correct
- Fallback paths (REST → GQL) trigger when primary returns non-200
- The retry-with-backoff mechanism retries on ConnectionError/Timeout
- The rate limiter attribute is wired in
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests
import responses as resp_lib

from seiyomi.clients.suwayomi import SuwayomiClient

BASE = "http://suwayomi.test"


@pytest.fixture
def client() -> SuwayomiClient:
    return SuwayomiClient(base_url=BASE, rpm=0)  # rpm=0 → unlimited (no sleep in tests)


@pytest.fixture
def rsps():
    with resp_lib.RequestsMock(assert_all_requests_are_fired=False) as r:
        yield r


# ── get_library ─────────────────────────────────────────────────────────────

class TestGetLibrary:
    def test_uses_category_0_endpoint(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/category/0",
                 json=[{"id": 1, "title": "Berserk"}], status=200)
        lib = client.get_library()
        assert lib == [{"id": 1, "title": "Berserk"}]
        assert rsps.calls[0].request.url == f"{BASE}/api/v1/category/0"

    def test_returns_list_from_dict_response(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/category/0",
                 json={"manga": [{"id": 2, "title": "Vinland Saga"}]}, status=200)
        lib = client.get_library()
        assert lib == [{"id": 2, "title": "Vinland Saga"}]

    def test_falls_back_to_graphql_on_non200(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/category/0", status=404)
        rsps.add(resp_lib.POST, f"{BASE}/api/graphql",
                 json={"data": {"mangas": {"nodes": [{"id": 3, "title": "Chainsaw Man"}]}}},
                 status=200)
        lib = client.get_library()
        assert len(lib) == 1
        assert lib[0]["title"] == "Chainsaw Man"

    def test_returns_empty_when_both_fail(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/category/0", status=404)
        rsps.add(resp_lib.POST, f"{BASE}/api/graphql", status=500)
        assert client.get_library() == []


# ── get_manga ────────────────────────────────────────────────────────────────

class TestGetManga:
    def test_uses_correct_url(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/manga/42",
                 json={"id": 42, "title": "Oyasumi Punpun"}, status=200)
        result = client.get_manga(42)
        assert result["title"] == "Oyasumi Punpun"

    def test_returns_empty_dict_on_error(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/manga/99", status=500)
        assert client.get_manga(99) == {}


# ── get_chapters ─────────────────────────────────────────────────────────────

class TestGetChapters:
    def test_returns_list(self, client, rsps):
        chapters = [{"id": 1, "chapterNumber": 1.0}, {"id": 2, "chapterNumber": 2.0}]
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/manga/5/chapters",
                 json=chapters, status=200)
        result = client.get_chapters(5)
        assert len(result) == 2

    def test_returns_empty_on_non200(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/manga/5/chapters", status=404)
        assert client.get_chapters(5) == []

    def test_unwraps_dict_wrapper(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/manga/7/chapters",
                 json={"chapters": [{"id": 10}], "total": 1}, status=200)
        result = client.get_chapters(7)
        assert result == [{"id": 10}]


# ── mark_chapters_read ────────────────────────────────────────────────────────

class TestMarkChaptersRead:
    def test_posts_to_batch_endpoint_with_correct_body(self, client, rsps):
        rsps.add(resp_lib.POST, f"{BASE}/api/v1/chapter/batch", status=200)
        result = client.mark_chapters_read([21, 22])
        assert result is True
        body = json.loads(rsps.calls[0].request.body)
        assert body == {"chapterIds": [21, 22], "change": {"isRead": True}}

    def test_falls_back_to_gql_on_non200(self, client, rsps):
        rsps.add(resp_lib.POST, f"{BASE}/api/v1/chapter/batch", status=404)
        rsps.add(resp_lib.POST, f"{BASE}/api/graphql",
                 json={"data": {"updateChapters": {"chapters": {"nodes": []}}}},
                 status=200)
        assert client.mark_chapters_read([5]) is True

    def test_returns_true_for_empty_list(self, client, rsps):
        assert client.mark_chapters_read([]) is True
        assert len(rsps.calls) == 0  # no request made


# ── mark_chapter_read ─────────────────────────────────────────────────────────

class TestMarkChapterRead:
    def test_patches_correct_url_with_form_data(self, client, rsps):
        rsps.add(resp_lib.PATCH, f"{BASE}/api/v1/manga/3/chapter/7", status=200)
        result = client.mark_chapter_read(3, 7)
        assert result is True
        req = rsps.calls[0].request
        assert req.body == "read=true"
        assert "application/x-www-form-urlencoded" in req.headers.get("Content-Type", "")

    def test_returns_false_on_failure(self, client, rsps):
        rsps.add(resp_lib.PATCH, f"{BASE}/api/v1/manga/3/chapter/7", status=500)
        assert client.mark_chapter_read(3, 7) is False


# ── add_to_library / remove_from_library ──────────────────────────────────────

class TestLibraryMutation:
    def test_add_uses_get_manga_library(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/manga/10/library", status=200)
        assert client.add_to_library(10) is True
        assert rsps.calls[0].request.url == f"{BASE}/api/v1/manga/10/library"

    def test_add_returns_false_on_non200(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/manga/10/library", status=500)
        assert client.add_to_library(10) is False

    def test_remove_uses_delete(self, client, rsps):
        rsps.add(resp_lib.DELETE, f"{BASE}/api/v1/manga/10/library", status=200)
        assert client.remove_from_library(10) is True

    def test_remove_falls_back_to_get(self, client, rsps):
        rsps.add(resp_lib.DELETE, f"{BASE}/api/v1/manga/10/library", status=404)
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/manga/10/library/remove", status=200)
        assert client.remove_from_library(10) is True


# ── list_categories ───────────────────────────────────────────────────────────

class TestListCategories:
    def test_uses_correct_endpoint(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/category",
                 json=[{"id": 1, "name": "Reading"}], status=200)
        cats = client.list_categories()
        assert cats == [{"id": 1, "name": "Reading"}]
        assert rsps.calls[0].request.url == f"{BASE}/api/v1/category"

    def test_returns_empty_on_error(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/category", status=500)
        assert client.list_categories() == []


# ── get_sources ───────────────────────────────────────────────────────────────

class TestGetSources:
    def test_uses_correct_endpoint(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/source/list",
                 json=[{"id": "1", "name": "MangaSee"}], status=200)
        srcs = client.get_sources()
        assert srcs[0]["name"] == "MangaSee"


# ── search_source ─────────────────────────────────────────────────────────────

class TestSearchSource:
    def test_uses_correct_endpoint_and_params(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/source/12345/search",
                 json={"results": [{"id": 1, "title": "Berserk"}]}, status=200)
        result = client.search_source(12345, "Berserk", page=1)
        assert result is not None
        req = rsps.calls[0].request
        assert "searchTerm=Berserk" in req.url

    def test_returns_none_on_error(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/source/99/search", status=500)
        with pytest.raises(Exception):  # raises HTTPError on non-2xx
            client.search_source(99, "test", page=1)


# ── Retry-with-backoff ────────────────────────────────────────────────────────

class TestRetry:
    def test_retries_on_connection_error(self, client, rsps):
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/manga/1/library",
                 body=requests.ConnectionError("timeout"))
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/manga/1/library",
                 body=requests.ConnectionError("timeout"))
        rsps.add(resp_lib.GET, f"{BASE}/api/v1/manga/1/library", status=200)
        with patch("time.sleep"):  # don't actually sleep in tests
            result = client.add_to_library(1)
        assert result is True
        assert len(rsps.calls) == 3

    def test_raises_after_three_failures(self, client, rsps):
        for _ in range(3):
            rsps.add(resp_lib.GET, f"{BASE}/api/v1/manga/1/library",
                     body=requests.ConnectionError("down"))
        with patch("time.sleep"):
            with pytest.raises(requests.ConnectionError):
                client.add_to_library(1)


# ── Rate limiter wired in ─────────────────────────────────────────────────────

class TestRateLimiter:
    def test_rate_limiter_attribute_exists(self, client):
        from seiyomi.utils.rate_limiter import RateLimiter
        assert isinstance(client._limiter, RateLimiter)

    def test_rpm_zero_means_unlimited(self, client):
        assert client._limiter._min_interval == 0.0

    def test_rpm_60_sets_interval(self):
        c = SuwayomiClient(base_url=BASE, rpm=60)
        assert abs(c._limiter._min_interval - 1.0) < 1e-6


# ── graphql fallback ──────────────────────────────────────────────────────────

class TestGraphQL:
    def test_primary_endpoint(self, client, rsps):
        rsps.add(resp_lib.POST, f"{BASE}/api/graphql",
                 json={"data": {"ok": True}}, status=200)
        result = client.graphql("query { ok }")
        assert result == {"data": {"ok": True}}

    def test_fallback_to_secondary_endpoint(self, client, rsps):
        rsps.add(resp_lib.POST, f"{BASE}/api/graphql", status=500)
        rsps.add(resp_lib.POST, f"{BASE}/graphql",
                 json={"data": {"ok": True}}, status=200)
        result = client.graphql("query { ok }")
        assert result == {"data": {"ok": True}}

    def test_returns_none_when_both_fail(self, client, rsps):
        rsps.add(resp_lib.POST, f"{BASE}/api/graphql", status=500)
        rsps.add(resp_lib.POST, f"{BASE}/graphql", status=500)
        assert client.graphql("query { ok }") is None
