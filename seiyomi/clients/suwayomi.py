"""
seiyomi/clients/suwayomi.py
Clean SuwayomiClient using authoritative REST endpoints.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set

import requests

from seiyomi.utils.rate_limiter import RateLimiter

logger = logging.getLogger("seiyomi")


class SuwayomiClient:
    """Suwayomi REST/GQL client with correct, minimal endpoint usage.

    Auth modes: "none" (default), "basic", "bearer", "simple", "auto".
    """

    def __init__(
        self,
        base_url: str,
        auth_mode: str = "none",
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        verify_tls: bool = True,
        request_timeout: float = 12.0,
        rpm: int = 0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_mode = auth_mode
        self.username = username or ""
        self.password = password or ""
        self.token = token or ""
        self.verify = verify_tls
        self.timeout = request_timeout
        self._sess = requests.Session()
        self._extra_headers: Dict[str, str] = {}
        self._server_version: Optional[str] = None
        self._limiter = RateLimiter(rpm=rpm)

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _auth(self) -> None:
        if self.auth_mode == "bearer" and self.token:
            self._extra_headers["Authorization"] = f"Bearer {self.token}"
        elif self.auth_mode == "basic" and self.username and self.password:
            self._sess.auth = (self.username, self.password)
        elif self.auth_mode == "simple" and self.username and self.password:
            resp = self._sess.post(
                f"{self.base_url}/login.html",
                data={"user": self.username, "pass": self.password},
                allow_redirects=False,
                verify=self.verify,
                timeout=self.timeout,
            )
            if resp.status_code not in (200, 301, 302, 303):
                raise RuntimeError(f"Simple login failed: HTTP {resp.status_code}")
        elif self.auth_mode == "auto":
            if self.token:
                self._extra_headers["Authorization"] = f"Bearer {self.token}"
            elif self.username and self.password:
                self._sess.auth = (self.username, self.password)

    # ── Core HTTP ─────────────────────────────────────────────────────────────

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("GET", path, **kwargs)

    def _delete(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("DELETE", path, **kwargs)

    def _post(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("POST", path, **kwargs)

    def _patch(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("PATCH", path, **kwargs)

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = dict(self._extra_headers)
        headers.update(kwargs.pop("headers", {}) or {})
        kwargs.setdefault("timeout", self.timeout)
        # Rate limit: honour configured rpm before every request
        self._limiter.wait()
        # Retry-with-backoff for transient failures (3 attempts, exponential backoff)
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                resp = self._sess.request(method, url, headers=headers, verify=self.verify, **kwargs)
                break
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(2.0 ** attempt)
                continue
        else:
            raise last_exc  # type: ignore[misc]
        # Auto-retry on 401 in "auto" mode with simple login
        if resp.status_code == 401 and self.auth_mode == "auto" and self.username and self.password:
            login = self._sess.post(
                f"{self.base_url}/login.html",
                data={"user": self.username, "pass": self.password},
                allow_redirects=False,
                verify=self.verify,
                timeout=self.timeout,
            )
            if login.status_code in (200, 302, 303):
                resp = self._sess.request(method, url, headers=headers, verify=self.verify, **kwargs)
        return resp

    # ── Server info ───────────────────────────────────────────────────────────

    @property
    def server_version(self) -> Optional[str]:
        if self._server_version is None:
            try:
                r = self._get("/api/v1/settings/about")
                if r.status_code == 200:
                    data = r.json()
                    self._server_version = str(
                        data.get("buildVersion") or data.get("version") or ""
                    )
            except Exception:
                pass
        return self._server_version

    # ── Library ───────────────────────────────────────────────────────────────

    def get_library(self) -> List[Dict[str, Any]]:
        """Return all manga in library via GET /api/v1/category/0.

        Falls back to GQL ``mangas(condition:{inLibrary:true})`` on non-200.
        """
        try:
            r = self._get("/api/v1/category/0")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    for k in ("manga", "mangas", "data", "items"):
                        v = data.get(k)
                        if isinstance(v, list):
                            return v
        except Exception as exc:
            logger.debug("get_library REST error: %s", exc)

        return self._get_library_graphql()

    def _get_library_graphql(self) -> List[Dict[str, Any]]:
        q = """
        query {
          mangas(condition: { inLibrary: true }) {
            nodes { id title }
          }
        }
        """
        resp = self.graphql(q.strip())
        if not resp or not isinstance(resp.get("data"), dict):
            return []
        nodes = (resp["data"].get("mangas") or {}).get("nodes") or []
        return [n for n in nodes if isinstance(n, dict)]

    # ── Manga ─────────────────────────────────────────────────────────────────

    def get_manga(self, manga_id: int) -> Dict[str, Any]:
        """GET /api/v1/manga/{manga_id}"""
        r = self._get(f"/api/v1/manga/{manga_id}")
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                pass
        return {}

    # ── Chapters ──────────────────────────────────────────────────────────────

    def get_chapters(self, manga_id: int) -> List[Dict[str, Any]]:
        """GET /api/v1/manga/{manga_id}/chapters — list all chapters."""
        r = self._get(f"/api/v1/manga/{manga_id}/chapters")
        if r.status_code == 200:
            try:
                data = r.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    for k in ("chapters", "data", "items"):
                        v = data.get(k)
                        if isinstance(v, list):
                            return v
            except Exception:
                pass
        return []

    def get_chapter_count(self, manga_id: int) -> int:
        """Return chapter count via GQL ``manga(id:N) { chapters { totalCount } }``."""
        q = "query($id:Int!){ manga(id:$id){ chapters { totalCount } } }"
        try:
            resp = self.graphql(q, variables={"id": manga_id})
            if resp and isinstance(resp.get("data"), dict):
                manga_node = resp["data"].get("manga") or {}
                total = (manga_node.get("chapters") or {}).get("totalCount")
                if isinstance(total, int):
                    return total
        except Exception as exc:
            logger.debug("get_chapter_count gql error: %s", exc)
        # Fallback: count from REST list
        return len(self.get_chapters(manga_id))

    def mark_chapters_read(self, chapter_ids: List[int]) -> bool:
        """POST /api/v1/chapter/batch — mark chapter database IDs as read.

        Falls back to GQL ``updateChapters`` mutation on non-200.
        """
        if not chapter_ids:
            return True
        try:
            r = self._post(
                "/api/v1/chapter/batch",
                json={"chapterIds": chapter_ids, "change": {"isRead": True}},
            )
            if r.status_code == 200:
                return True
        except Exception as exc:
            logger.debug("mark_chapters_read REST error: %s", exc)

        # GQL fallback
        mutation = """
        mutation updateChapters($input: UpdateChaptersInput!) {
          updateChapters(input: $input) {
            chapters { nodes { id isRead } }
          }
        }
        """
        resp = self.graphql(
            mutation.strip(),
            variables={"input": {"ids": chapter_ids, "patch": {"isRead": True, "lastPageRead": 0}}},
        )
        return resp is not None and "errors" not in resp

    def mark_chapter_read(self, manga_id: int, chapter_index: int) -> bool:
        """PATCH /api/v1/manga/{manga_id}/chapter/{chapter_index} with form-encoded read=true.

        Note: ``chapter_index`` is the 1-based positional index, NOT the database chapter ID.
        """
        r = self._patch(
            f"/api/v1/manga/{manga_id}/chapter/{chapter_index}",
            data="read=true",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return r.status_code == 200

    # ── Library mutation ──────────────────────────────────────────────────────

    def add_to_library(self, manga_id: int) -> bool:
        """GET /api/v1/manga/{manga_id}/library"""
        r = self._get(f"/api/v1/manga/{manga_id}/library")
        return r.status_code == 200

    def remove_from_library(self, manga_id: int) -> bool:
        """DELETE /api/v1/manga/{manga_id}/library"""
        r = self._delete(f"/api/v1/manga/{manga_id}/library")
        if r.status_code == 200:
            return True
        # Old server builds may only have GET-based removal
        r2 = self._get(f"/api/v1/manga/{manga_id}/library/remove")
        return r2.status_code == 200

    # ── Categories ────────────────────────────────────────────────────────────

    def list_categories(self) -> List[Dict[str, Any]]:
        """GET /api/v1/category"""
        r = self._get("/api/v1/category")
        if r.status_code == 200:
            try:
                data = r.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    for k in ("categories", "data", "items"):
                        v = data.get(k)
                        if isinstance(v, list):
                            return v
            except Exception:
                pass
        return []

    def get_category_manga(self, category_id: int) -> List[Dict[str, Any]]:
        """GET /api/v1/category/{category_id} — category 0 = full library."""
        r = self._get(f"/api/v1/category/{category_id}")
        if r.status_code == 200:
            try:
                data = r.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    for k in ("manga", "mangas", "data", "items"):
                        v = data.get(k)
                        if isinstance(v, list):
                            return v
            except Exception:
                pass
        return []

    def add_to_category(self, manga_id: int, category_id: int) -> bool:
        """GET /api/v1/manga/{manga_id}/category/{category_id}"""
        r = self._get(f"/api/v1/manga/{manga_id}/category/{category_id}")
        return r.status_code == 200

    def remove_from_category(self, manga_id: int, category_id: int) -> bool:
        """DELETE /api/v1/manga/{manga_id}/category/{category_id}"""
        r = self._delete(f"/api/v1/manga/{manga_id}/category/{category_id}")
        return r.status_code == 200

    # ── Sources ───────────────────────────────────────────────────────────────

    def get_sources(self) -> List[Dict[str, Any]]:
        """GET /api/v1/source/list"""
        r = self._get("/api/v1/source/list")
        r.raise_for_status()
        return r.json()

    def search_source(self, source_id: int, term: str, page: int = 1) -> Dict[str, Any]:
        """GET /api/v1/source/{source_id}/search?searchTerm=...&pageNum=..."""
        r = self._get(
            f"/api/v1/source/{source_id}/search",
            params={"searchTerm": term, "pageNum": page},
        )
        r.raise_for_status()
        return r.json()

    # ── GraphQL ───────────────────────────────────────────────────────────────

    def graphql(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """POST /api/graphql (falls back to /graphql) with error handling."""
        payload: Dict[str, Any] = {"query": query}
        if variables is not None:
            payload["variables"] = variables
        body = json.dumps(payload)
        for path in ("/api/graphql", "/graphql"):
            try:
                r = self._sess.post(
                    f"{self.base_url}{path}",
                    headers={"Content-Type": "application/json", **self._extra_headers},
                    data=body,
                    verify=self.verify,
                    timeout=self.timeout,
                )
                if r.status_code != 200:
                    continue
                return r.json()
            except Exception as exc:
                logger.debug("graphql %s error: %s", path, exc)
        return None

    # ── Static helpers (shared with monolith during migration) ────────────────

    @staticmethod
    def normalize_search_items(payload: Any) -> List[Dict[str, Any]]:
        """Normalize varied Suwayomi search response shapes to a flat list."""
        if payload is None:
            return []
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            for k in ("mangaList", "mangaListData", "manga_list", "results", "data",
                      "list", "items", "entries", "mangas", "manga"):
                v = payload.get(k)
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
            for k in ("data", "result"):
                v = payload.get(k)
                if isinstance(v, dict):
                    for kk in ("items", "list", "results", "mangaList", "manga"):
                        vv = v.get(kk)
                        if isinstance(vv, list):
                            return [x for x in vv if isinstance(x, dict)]
        return []

    @staticmethod
    def extract_manga_id(item: Dict[str, Any]) -> Optional[int]:
        """Extract integer manga ID from a search result dict."""
        for k in ("id", "mangaId", "manga_id", "manga_id_str"):
            v = item.get(k)
            if v is None:
                continue
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
        # Last resort: extract first run of 2+ digits from a URL-like field
        for k in ("sourceId", "source_id", "key", "url"):
            v = item.get(k)
            if isinstance(v, str):
                m = re.search(r"(\d{2,})", v)
                if m:
                    try:
                        return int(m.group(1))
                    except (TypeError, ValueError):
                        pass
        return None

    # ── Chapter key helpers (for read-sync / canonical counting) ─────────────

    @staticmethod
    def _canonical_key_from_chapter(item: Dict[str, Any]) -> Optional[str]:
        """Extract canonical chapter number string from a chapter dict.

        E.g. chapterNumber=12.4 → "12";  title="Ch. 5.2" → "5".
        Returns None for specials/extras/unparseable entries.
        """
        for k in ("chapter", "chapterNumber", "number"):
            v = item.get(k)
            if v is None:
                continue
            if isinstance(v, (int, float)):
                try:
                    return str(int(float(v)))
                except (TypeError, ValueError):
                    continue
            if isinstance(v, str):
                m = re.search(r"(\d+)", v)
                if m:
                    return str(int(m.group(1)))

        for k in ("name", "title"):
            s = str(item.get(k) or "")
            if any(x in s.lower() for x in ("oneshot", "special", "extra")):
                return None
            m = re.search(r"(\d+)(?:[.\-]\d+)?", s)
            if m:
                try:
                    return str(int(m.group(1)))
                except (TypeError, ValueError):
                    pass
        return None

    @staticmethod
    def _norm_lang(v: Any) -> str:
        return str(v or "").strip().lower().replace("_", "-")

    def _filter_items_by_lang(
        self, items: List[Dict[str, Any]], langs: Set[str]
    ) -> List[Dict[str, Any]]:
        if not items or not langs:
            return items or []
        base_langs = {lang.split("-")[0] for lang in langs}
        out: List[Dict[str, Any]] = []
        for it in items:
            raw = (
                it.get("language")
                or it.get("lang")
                or it.get("translatedLanguage")
                or it.get("languageCode")
                or ""
            )
            ln = self._norm_lang(raw)
            if ln in langs or ln.split("-")[0] in base_langs:
                out.append(it)
        return out

    # ── Backward-compat aliases (used by monolith call sites) ─────────────────

    def get_manga_details(self, manga_id: int) -> Dict[str, Any]:
        return self.get_manga(manga_id)

    def add_manga_to_category(self, manga_id: int, category_id: int) -> bool:
        return self.add_to_category(manga_id, category_id)

    def get_manga_chapters_entries(self, manga_id: int) -> List[Dict[str, Any]]:
        return self.get_chapters(manga_id)

    def get_manga_chapters_count(self, manga_id: int) -> int:
        return len(self.get_chapters(manga_id))

    def get_manga_chapters_canonical_count(self, manga_id: int) -> int:
        items = self.get_chapters(manga_id)
        if not items:
            return 0
        uniq: Set[str] = set()
        for it in items:
            key = self._canonical_key_from_chapter(it)
            if key is not None:
                uniq.add(key)
        return len(uniq) if uniq else len(items)

    def get_manga_chapters_count_by_lang(
        self, manga_id: int, langs: Set[str], canonical: bool = False
    ) -> int:
        items = self._filter_items_by_lang(self.get_chapters(manga_id), langs)
        if not items:
            return 0
        if canonical:
            uniq: Set[str] = set()
            for it in items:
                key = self._canonical_key_from_chapter(it)
                if key:
                    uniq.add(key)
            return len(uniq) if uniq else len(items)
        return len(items)

    # request() alias so monolith code using client.request() still works
    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        return self._request(method, path, **kwargs)

    def get_library_graphql(self) -> List[Dict[str, Any]]:
        """Public alias for GQL library fetch (backward compat). Delegates to get_library()."""
        return self._get_library_graphql()
