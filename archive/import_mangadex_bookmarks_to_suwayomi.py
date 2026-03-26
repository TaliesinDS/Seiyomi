import re
import sys
import json
import csv
import argparse
import os
import getpass
import time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Dict, Any, Set
import csv
import time
import math

try:
    import pandas as pd  # Optional, only used for xlsx/csv convenience
except Exception:
    pd = None

import requests

# MangaDex API base (public)
MANGADEX_API = "https://api.mangadex.org"

# Global chapter sync config (set in main from CLI flags)
CHAPTER_SYNC_CONF: Dict[str, Any] = {}
# Global debug flag for read sync
READ_SYNC_DEBUG: bool = False

# Utility early so helper functions can use it
def truncate_text(t: str, limit: int = 200) -> str:
    t = (t or "").replace('\n', ' ')[:limit]
    return t + ("..." if len(t) == limit else "")

# --- Title matching helpers ---
_STOPWORDS = {
    'a','an','the','and','or','of','in','on','to','for','by','with','as','at','from','now','i','you','we','they','is','are'
}

def _normalize_title_tokens(s: str) -> List[str]:
    """Normalize title to comparable tokens.
    - lowercases
    - strips bracketed/parenthetical noise like (Official), [Color], {whatever}
    - removes punctuation
    - collapses whitespace
    - removes short/stop words
    """
    s = s or ""
    s = s.lower().strip()
    # remove bracketed content
    s = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", s)
    # drop common noise words explicitly
    s = s.replace("official", " ")
    s = s.replace("colored", " ")
    s = s.replace("colour", " ")
    # normalize punctuation to space
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = [t for t in s.split() if len(t) > 1 and t not in _STOPWORDS]
    return toks

def _title_similarity(a: str, b: str) -> float:
    """Simple token Jaccard similarity between two titles after normalization."""
    ta = set(_normalize_title_tokens(a))
    tb = set(_normalize_title_tokens(b))
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    union = ta | tb
    return len(inter) / len(union) if union else 0.0

def _is_title_match(a: str, b: str, threshold: float = 0.6, strict_exact: bool = False) -> bool:
    na = " ".join(_normalize_title_tokens(a))
    nb = " ".join(_normalize_title_tokens(b))
    if not na or not nb:
        return False
    if na == nb:
        return True
    if strict_exact:
        return False
    # allow substring containment of normalized forms as a light-weight near-exact
    if na in nb or nb in na:
        return True
    return _title_similarity(a, b) >= max(0.0, min(1.0, threshold))

# --- Helpers: detect MangaDex IDs/URLs ---
MD_ID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
MD_URL_RE = re.compile(r"https?://(www\.)?mangadex\.org/title/([0-9a-fA-F-]{36})(?:/|$)")


def extract_mangadex_ids(text: str) -> List[str]:
    ids = []
    for url_match in MD_URL_RE.finditer(text):
        ids.append(url_match.group(2))
    for id_match in MD_ID_RE.finditer(text):
        ids.append(id_match.group(0))
    # de-dup preserving order
    seen = set()
    uniq: List[str] = []
    for x in ids:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


# --- Input parsing ---

def read_any(path: Path) -> List[str]:
    suffix = path.suffix.lower()
    data: List[str] = []
    if suffix in {".txt", ".log", ".md", ".html", ".htm"}:
        text = path.read_text(encoding="utf-8", errors="ignore")
        data = extract_mangadex_ids(text)
    elif suffix in {".json"}:
        obj = json.loads(path.read_text(encoding="utf-8"))
        def walk(o: Any):
            if isinstance(o, str):
                for i in extract_mangadex_ids(o):
                    yield i
            elif isinstance(o, dict):
                for v in o.values():
                    yield from walk(v)
            elif isinstance(o, list):
                for v in o:
                    yield from walk(v)
        data = list(dict.fromkeys(walk(obj)))
    elif suffix in {".csv"}:
        # try simple pass-through first
        with path.open(newline='', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            buf: List[str] = []
            for row in reader:
                for cell in row:
                    buf.extend(extract_mangadex_ids(str(cell)))
        # unique preserve order
        data = list(dict.fromkeys(buf))
    elif suffix in {".xlsx", ".xls"}:
        if pd is None:
            raise SystemExit("pandas/openpyxl are required for Excel files. Install with: python -m pip install pandas openpyxl")
        buf: List[str] = []
        # Read all sheets
        xls = pd.read_excel(path, sheet_name=None, dtype=str)
        for _, df in xls.items():
            for val in df.astype(str).to_numpy().flatten():
                buf.extend(extract_mangadex_ids(str(val)))
        data = list(dict.fromkeys(buf))
    else:
        # Fallback: treat as text
        text = path.read_text(encoding="utf-8", errors="ignore")
        data = extract_mangadex_ids(text)
    return data


# --- Suwayomi client ---

class SuwayomiClient:
    def __init__(self, base_url: str, auth_mode: str = "auto", username: Optional[str] = None, password: Optional[str] = None, token: Optional[str] = None, verify_tls: bool = True, request_timeout: float = 12.0):
        self.base_url = base_url.rstrip('/')
        self.sess = requests.Session()
        self.headers: Dict[str, str] = {}
        self.auth_mode = auth_mode
        self.username = username
        self.password = password
        self.token = token
        self.verify = verify_tls
        self.timeout = request_timeout

    def _auth(self):
        # Modes: basic, simple, bearer, auto
        if self.auth_mode == "bearer" and self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"
        elif self.auth_mode == "basic" and self.username and self.password:
            self.sess.auth = (self.username, self.password)
        elif self.auth_mode == "simple" and self.username and self.password:
            # Perform form login to set session cookie
            # POST /login.html with user=, pass=
            resp = self.sess.post(f"{self.base_url}/login.html", data={"user": self.username, "pass": self.password}, allow_redirects=False, verify=self.verify)
            if resp.status_code not in (200, 302, 303, 303):
                raise RuntimeError(f"Simple login failed: HTTP {resp.status_code}")
        elif self.auth_mode == "auto":
            # try bearer first, then basic, then simple
            if self.token:
                self.headers["Authorization"] = f"Bearer {self.token}"
            elif self.username and self.password:
                # try basic; fallback to simple if 401
                self.sess.auth = (self.username, self.password)
            # else unauth

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}) or {})
        # Default timeout for all requests to avoid stalls
        if 'timeout' not in kwargs:
            kwargs['timeout'] = self.timeout
        resp = self.sess.request(method, url, headers=headers, verify=self.verify, **kwargs)
        # Fallback: if 401 with basic on auto, try SIMPLE login
        if resp.status_code == 401 and self.auth_mode == "auto" and self.username and self.password:
            # try simple login once
            login = self.sess.post(f"{self.base_url}/login.html", data={"user": self.username, "pass": self.password}, allow_redirects=False, verify=self.verify, timeout=self.timeout)
            if login.status_code in (200, 302, 303):
                resp = self.sess.request(method, url, headers=headers, verify=self.verify, **kwargs)
        return resp

    # API helpers
    def get_sources(self) -> List[Dict[str, Any]]:
        r = self.request("GET", "/api/v1/source/list")
        r.raise_for_status()
        return r.json()

    def search_source(self, source_id: int, query: str, page: int = 1) -> Dict[str, Any]:
        r = self.request("GET", f"/api/v1/source/{source_id}/search", params={"searchTerm": query, "pageNum": page})
        r.raise_for_status()
        return r.json()

    def add_to_library(self, manga_id: int) -> bool:
        r = self.request("GET", f"/api/v1/manga/{manga_id}/library")
        return r.status_code == 200

    def add_manga_to_category(self, manga_id: int, category_id: int) -> bool:
        # Endpoint adds manga to category via GET per server API design
        r = self.request("GET", f"/api/v1/manga/{manga_id}/category/{category_id}")
        return r.status_code == 200

    # Utilities to normalize varied server search responses
    @staticmethod
    def normalize_search_items(payload: Any) -> List[Dict[str, Any]]:
        if payload is None:
            return []
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            # Common keys across forks
            for k in (
                'mangaList','mangaListData','manga_list','results','data','list','items','entries','mangas','manga'
            ):
                v = payload.get(k)
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
            # Some APIs embed under an extra layer
            for k in ('data','result'):
                v = payload.get(k)
                if isinstance(v, dict):
                    for kk in ('items','list','results','mangaList','manga'):
                        vv = v.get(kk)
                        if isinstance(vv, list):
                            return [x for x in vv if isinstance(x, dict)]
        return []

    @staticmethod
    def extract_manga_id(item: Dict[str, Any]) -> Optional[int]:
        for k in ('id','mangaId','manga_id','manga_id_str'):
            v = item.get(k)
            if v is None:
                continue
            try:
                return int(v)
            except Exception:
                continue
        v = item.get('sourceId') or item.get('source_id') or item.get('key') or item.get('url')
        if isinstance(v, str):
            m = re.search(r"(\d{2,})", v)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    pass
        return None

    # Additional helpers for rehoming/migration
    def get_manga_details(self, manga_id: int) -> Dict[str, Any]:
        r = self.request("GET", f"/api/v1/manga/{manga_id}")
        if r.status_code != 200:
            return {}
        try:
            return r.json()
        except Exception:
            return {}

    def get_manga_chapters_count(self, manga_id: int) -> int:
        """Best-effort chapter count for a manga. Tries multiple endpoints and formats.
        Returns 0 on failure."""
        try:
            # Try common chapters endpoint variants
            for ep in (f"/api/v1/manga/{manga_id}/chapters", f"/api/v1/manga/{manga_id}/chapter"):
                r = self.request("GET", ep)
                if r.status_code != 200:
                    continue
                try:
                    js = r.json()
                except Exception:
                    continue
                if isinstance(js, list):
                    return len(js)
                if isinstance(js, dict):
                    for k in ("chapters", "data", "list"):
                        v = js.get(k)
                        if isinstance(v, list):
                            return len(v)
            # Try details with chapters included
            for ep in (f"/api/v1/manga/{manga_id}?withChapters=true", f"/api/v1/manga/{manga_id}"):
                r = self.request("GET", ep)
                if r.status_code != 200:
                    continue
                try:
                    js = r.json()
                except Exception:
                    continue
                if isinstance(js, dict):
                    for k in ("chapters", "chapterCount", "chaptersCount"):
                        v = js.get(k)
                        if isinstance(v, list):
                            return len(v)
                        if isinstance(v, int):
                            return v
        except Exception:
            pass
        # GraphQL fallback: ask for chapters length via different shapes
        try:
            # Try manga(id:Int!) first
            q1 = "query($id:Int!){ manga(id:$id){ chapters { id } } }"
            res1 = self.graphql(q1, variables={"id": int(manga_id)})
            if res1 and isinstance(res1, dict) and isinstance(res1.get('data'), dict):
                mn = res1['data'].get('manga')
                if isinstance(mn, dict):
                    chs = mn.get('chapters')
                    if isinstance(chs, list):
                        return len(chs)
            # Try chapters(mangaId:Int!) nodes/items/edges
            for q in (
                "query($id:Int!){ chapters(mangaId:$id){ nodes { id } } }",
                "query($id:Int!){ chapters(mangaId:$id){ items { id } } }",
                "query($id:Int!){ chapters(mangaId:$id){ edges { node { id } } } }",
            ):
                res2 = self.graphql(q, variables={"id": int(manga_id)})
                if res2 and isinstance(res2, dict):
                    # Use extractor to count ids
                    ids: List[str] = []
                    def visit(n: Any):
                        if isinstance(n, dict):
                            if 'id' in n and len(n) == 1:
                                ids.append(str(n['id']))
                            for v in n.values():
                                visit(v)
                        elif isinstance(n, list):
                            for it in n:
                                visit(it)
                    visit(res2.get('data'))
                    if ids:
                        return len(ids)
        except Exception:
            pass
        return 0
        return 0

    def get_manga_chapters_entries(self, manga_id: int) -> List[Dict[str, Any]]:
        """Return a best-effort list of chapter dicts using REST endpoints.
        Does not rely on GraphQL since shapes vary widely."""
        def to_list(js: Any) -> List[Dict[str, Any]]:
            if isinstance(js, list):
                return [x for x in js if isinstance(x, dict)]
            if isinstance(js, dict):
                for k in ("chapters", "data", "list", "items"):
                    v = js.get(k)
                    if isinstance(v, list):
                        return [x for x in v if isinstance(x, dict)]
            return []
        # Try chapters endpoints
        for ep in (f"/api/v1/manga/{manga_id}/chapters", f"/api/v1/manga/{manga_id}/chapter"):
            try:
                r = self.request("GET", ep)
                if r.status_code != 200:
                    continue
                try:
                    js = r.json()
                except Exception:
                    continue
                items = to_list(js)
                if items:
                    return items
            except Exception:
                pass
        # Try details with chapters included
        for ep in (f"/api/v1/manga/{manga_id}?withChapters=true", f"/api/v1/manga/{manga_id}"):
            try:
                r = self.request("GET", ep)
                if r.status_code != 200:
                    continue
                try:
                    js = r.json()
                except Exception:
                    continue
                if isinstance(js, dict):
                    items = to_list(js.get("chapters")) if isinstance(js.get("chapters"), list) else to_list(js)
                    if items:
                        return items
            except Exception:
                pass
        return []

    @staticmethod
    def _canonical_key_from_chapter(item: Dict[str, Any]) -> Optional[str]:
        """Extract canonical key from a chapter item. Convert 12.3 -> 12; handle strings like 'Ch. 12.4'.
        Returns None if no usable numeric identifier found.
        """
        # Candidate fields by common API shapes
        vals: List[str] = []
        for k in ("chapter", "chapterNumber", "number", "name", "title"):
            v = item.get(k)
            if v is None:
                continue
            if isinstance(v, (int, float)):
                # Take integer part as canonical
                try:
                    n = int(float(v))
                    return str(n)
                except Exception:
                    continue
            if isinstance(v, str):
                vals.append(v)
        for s in vals:
            # Find first numeric token
            m = re.search(r"(\d+)(?:[\.-]\d+)?", s)
            if not m:
                continue
            try:
                base = int(m.group(1))
                return str(base)
            except Exception:
                continue
        # Common labels to skip
        lab = (item.get("name") or item.get("title") or "").lower()
        if any(x in lab for x in ("oneshot", "special", "extra")):
            return None
        return None

    def get_manga_chapters_canonical_count(self, manga_id: int) -> int:
        """Count unique canonical chapter numbers, collapsing segmented releases (1.1/1.2 => 1).
        Falls back to total count if no canonical numbers could be parsed but chapters exist."""
        items = self.get_manga_chapters_entries(manga_id)
        if not items:
            return 0
        uniq: set = set()
        for it in items:
            key = self._canonical_key_from_chapter(it)
            if key is not None:
                uniq.add(key)
        if uniq:
            return len(uniq)
        # Fallback: if we couldn't parse, return total as last resort
        return len(items)

    # --- Language helpers for chapter lists ---
    @staticmethod
    def _norm_lang(v: Any) -> str:
        s = str(v or "").strip().lower().replace('_', '-')
        return s

    def _filter_items_by_lang(self, items: List[Dict[str, Any]], langs: Set[str]) -> List[Dict[str, Any]]:
        if not items or not langs:
            return items or []
        base_langs = {l.split('-')[0] for l in langs}
        out: List[Dict[str, Any]] = []
        for it in items:
            lv = it.get('language') or it.get('lang') or it.get('translatedLanguage') or it.get('languageCode') or ""
            ln = self._norm_lang(lv)
            if ln in langs:
                out.append(it)
                continue
            base = ln.split('-')[0] if ln else ''
            if base and base in base_langs:
                out.append(it)
        return out

    def get_manga_chapters_count_by_lang(self, manga_id: int, langs: Set[str], canonical: bool = False) -> int:
        items = self.get_manga_chapters_entries(manga_id)
        items = self._filter_items_by_lang(items, langs)
        if not items:
            return 0
        if canonical:
            seen: Set[str] = set()
            for it in items:
                key = self._canonical_key_from_chapter(it)
                if key:
                    seen.add(key)
            return len(seen) if seen else len(items)
        return len(items)

    def remove_from_library(self, manga_id: int) -> bool:
        # Some builds support DELETE; provide GET fallback path if needed
        r = self.request("DELETE", f"/api/v1/manga/{manga_id}/library")
        if r.status_code == 200:
            return True
        r2 = self.request("GET", f"/api/v1/manga/{manga_id}/library/remove")
        return r2.status_code == 200

    # --- GraphQL helpers ---
    def graphql(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        try:
            headers = {"Content-Type": "application/json"}
            payload = {"query": query}
            if variables is not None:
                payload["variables"] = variables
            # Try /api/graphql then /graphql
            paths = ["/api/graphql", "/graphql"]
            last_err = None
            for p in paths:
                try:
                    r = self.sess.post(f"{self.base_url}{p}", headers=headers, data=json.dumps(payload), verify=self.verify)
                except Exception as e:
                    last_err = e
                    if getattr(self, 'debug_library', False):
                        print(f"[gql-debug] Exception posting to {p}: {e}")
                    continue
                if r.status_code != 200:
                    if getattr(self, 'debug_library', False):
                        print(f"[gql-debug] HTTP {r.status_code} {p}: {truncate_text(r.text, 160)}")
                    continue
                try:
                    js = r.json()
                    if getattr(self, 'debug_library', False) and isinstance(js, dict) and js.get('errors'):
                        try:
                            print("[gql-debug] Errors:", json.dumps(js['errors'])[:400])
                        except Exception:
                            pass
                    return js
                except Exception as je:
                    if getattr(self, 'debug_library', False):
                        print(f"[gql-debug] Invalid JSON from {p}: {je}")
                    continue
            if last_err and getattr(self, 'debug_library', False):
                print(f"[gql-debug] All GraphQL paths failed: {last_err}")
            return None
        except Exception as e:
            if getattr(self, 'debug_library', False):
                print(f"[gql-debug] Unexpected GraphQL error: {e}")
            return None

    def _extract_manga_list_from_gql(self, data: Any) -> List[Dict[str, Any]]:
        found: List[Dict[str, Any]] = []
        def visit(node: Any):
            if isinstance(node, dict):
                # Derive id and title from this node considering common variants
                nid = node.get('id')
                if nid is None:
                    nid = node.get('mangaId') or node.get('manga_id') or node.get('seriesId')
                title = node.get('title') or node.get('name')
                # Also check nested 'manga' object for title/id
                if not title and isinstance(node.get('manga'), dict):
                    title = node['manga'].get('title') or node['manga'].get('name')
                if nid is None and isinstance(node.get('manga'), dict):
                    nid = node['manga'].get('id') or node['manga'].get('mangaId') or node['manga'].get('manga_id')
                if nid is not None and title:
                    found.append({'id': nid, 'title': title})
                # Traverse common container keys
                for k in ('nodes','items','edges'):
                    v = node.get(k)
                    if isinstance(v, list):
                        for it in v:
                            if k == 'edges' and isinstance(it, dict) and isinstance(it.get('node'), dict):
                                visit(it['node'])
                            else:
                                visit(it)
                for v in node.values():
                    visit(v)
            elif isinstance(node, list):
                for it in node:
                    visit(it)
        if isinstance(data, dict) and 'data' in data:
            visit(data['data'])
        else:
            visit(data)
        seen = set()
        uniq: List[Dict[str, Any]] = []
        for it in found:
            mid = it.get('id')
            if mid in seen:
                continue
            uniq.append(it)
            seen.add(mid)
        return uniq

    def get_library_graphql(self) -> List[Dict[str, Any]]:
        # Prefer category-based aggregation first (closer to actual library)
        try:
            cats_res = self.graphql("query { categories { nodes { id } edges { node { id } } } }")
            cat_ids: List[int] = []
            if isinstance(cats_res, dict) and isinstance(cats_res.get('data'), dict):
                c_root = cats_res['data'].get('categories')
                if isinstance(c_root, dict):
                    n = c_root.get('nodes') or []
                    if isinstance(n, list):
                        for it in n:
                            if isinstance(it, dict) and isinstance(it.get('id'), int):
                                cat_ids.append(it['id'])
                    e = c_root.get('edges') or []
                    if isinstance(e, list):
                        for it in e:
                            if isinstance(it, dict) and isinstance(it.get('node'), dict):
                                nid = it['node'].get('id')
                                if isinstance(nid, int):
                                    cat_ids.append(nid)
            seen_ids = set()
            out: List[Dict[str, Any]] = []
            for cid in cat_ids:
                q = "query($cid:Int!){ category(id:$cid){ mangas { nodes { id title } edges { node { id title } } } } }"
                res = self.graphql(q, variables={"cid": int(cid)})
                items = self._extract_manga_list_from_gql(res) if res else []
                for it in items:
                    mid = it.get('id')
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                    out.append(it)
            if out:
                if getattr(self, 'debug_library', False):
                    print(f"[gql-debug] Total from categories (deduped): {len(out)}")
                return out
        except Exception:
            pass

        queries = [
            # Common shapes across forks
            "query { library { entries { id mangaId title name manga { id title name } } } }",
            "query { library { id title name entries { manga { id title name } } } }",
            "query { library { mangaList { id title name } } }",
            "query { libraryEntries { manga { id title name } } }",
            "query { mangas { nodes { id title } } }",
            "query { mangas { edges { node { id title } } } }",
            "query { mangaList { id title name } }",
            "query { library { items { id title name } } }",
            "query { categories { nodes { id } } }",
            "query { categories { edges { node { id } } } }",
        ]
        # Also try parameterized 'mangas' calls with common argument shapes
        param_queries = [
            ("query($in:Boolean!){ mangas(inLibrary:$in){ id title name inLibrary } }", {"in": True}),
            ("query($f:MangaFilter){ mangas(filter:$f){ id title name inLibrary } }", {"f": {"inLibrary": True}}),
            ("query{ mangas { id title name inLibrary } }", None),
        ]
        for q in queries:
            res = self.graphql(q)
            if res is None:
                continue
            if getattr(self, 'debug_library', False):
                try:
                    data_str = json.dumps(res.get('data', {}))
                    print(f"[gql-debug] Query OK; data keys: {', '.join(list((res.get('data') or {}).keys()))}")
                    print(f"[gql-debug] Sample data: {data_str[:400]}{'...' if len(data_str)>400 else ''}")
                except Exception:
                    print("[gql-debug] Query OK, extracting manga list")
            items = self._extract_manga_list_from_gql(res)
            if items:
                return items
        for q, vars in param_queries:
            res = self.graphql(q, variables=vars)
            if res is None:
                continue
            if getattr(self, 'debug_library', False):
                try:
                    data_str = json.dumps(res.get('data', {}))
                    print(f"[gql-debug] Param query OK; data keys: {', '.join(list((res.get('data') or {}).keys()))}")
                    print(f"[gql-debug] Sample data: {data_str[:400]}{'...' if len(data_str)>400 else ''}")
                except Exception:
                    print("[gql-debug] Param query OK, extracting manga list")
            items = self._extract_manga_list_from_gql(res)
            if items:
                return items
        # As a last resort, try introspection to guide user/debugging
        intro = self.graphql("query { __schema { queryType { fields { name } } } }")
        if getattr(self, 'debug_library', False) and intro:
            try:
                fields = [f.get('name') for f in intro.get('data', {}).get('__schema', {}).get('queryType', {}).get('fields', [])]
                print("[gql-debug] Root query fields:", ", ".join(fields[:50]))
            except Exception:
                pass
        # Try fetching via categories (many schemas expose library through categories)
        try:
            cats_res = self.graphql("query { categories { id name } }")
            cat_items: List[Dict[str, Any]] = []
            if isinstance(cats_res, dict) and isinstance(cats_res.get('data'), dict):
                cats = cats_res['data'].get('categories')
                if isinstance(cats, list):
                    if getattr(self, 'debug_library', False):
                        print(f"[gql-debug] Categories found: {len(cats)}")
                    # For each category, attempt paginated fetches with common arg shapes
                    seen_ids: set = set()
                    for c in cats:
                        cid = c.get('id')
                        if cid is None:
                            continue
                        # Try several pagination argument shapes
                        arg_shapes = [
                            ("page", "size"), ("page", "limit"), ("pageNum", "pageSize"), ("offset", "limit"),
                        ]
                        for arg1, arg2 in arg_shapes:
                            page = 1
                            empty_pages = 0
                            while page <= 100:  # safety cap
                                if arg1 in ("offset",):
                                    vars = {"cid": int(cid), arg1: (page-1)*100, arg2: 100}
                                    q = f"query($cid:Int,$offset:Int,$limit:Int){{ category(id:$cid){{ mangas({arg1}:$offset, {arg2}:$limit){{ nodes {{ id title }} edges {{ node {{ id title }} }} }} }} }}"
                                elif arg1 == "pageNum" and arg2 == "pageSize":
                                    vars = {"cid": int(cid), arg1: page, arg2: 100}
                                    q = f"query($cid:Int,$pageNum:Int,$pageSize:Int){{ category(id:$cid){{ mangas({arg1}:$pageNum, {arg2}:$pageSize){{ nodes {{ id title }} edges {{ node {{ id title }} }} }} }} }}"
                                else:
                                    vars = {"cid": int(cid), arg1: page, arg2: 100}
                                    q = f"query($cid:Int,$page:Int,$size:Int){{ category(id:$cid){{ mangas({arg1}:$page, {arg2}:$size){{ nodes {{ id title }} edges {{ node {{ id title }} }} }} }} }}"
                                res = self.graphql(q, variables=vars)
                                if not res or not isinstance(res, dict):
                                    empty_pages += 1
                                    if empty_pages >= 2:
                                        break
                                    page += 1
                                    continue
                                before = len(seen_ids)
                                items = self._extract_manga_list_from_gql(res)
                                for it in items:
                                    mid = it.get('id')
                                    if mid is None or mid in seen_ids:
                                        continue
                                    seen_ids.add(mid)
                                    cat_items.append(it)
                                if getattr(self, 'debug_library', False):
                                    gained = len(seen_ids) - before
                                    print(f"[gql-debug] category {cid} page {page} +{gained} (total {len(seen_ids)})")
                                # Heuristic: stop if no new items
                                if len(seen_ids) == before:
                                    empty_pages += 1
                                else:
                                    empty_pages = 0
                                # advance page regardless
                                page += 1
                        # Move to next category
                    if cat_items:
                        return cat_items
        except Exception as e:
            if getattr(self, 'debug_library', False):
                print("[gql-debug] Category-based fetch error:", e)

        # Introspect 'mangas' field container names and try them dynamically
        try:
            introspect = self.graphql("query { __schema { queryType { fields { name type { name kind ofType { name kind ofType { name kind } } } } } } }")
            if isinstance(introspect, dict):
                fields = (introspect.get('data') or {}).get('__schema', {}).get('queryType', {}).get('fields', [])
                mangas_type = None
                for f in fields:
                    if f.get('name') == 'mangas':
                        t = f.get('type') or {}
                        # Unwrap nested ofType
                        while t and not t.get('name') and t.get('ofType'):
                            t = t['ofType']
                        mangas_type = t.get('name')
                        break
                if mangas_type:
                    type_info = self.graphql("query($n:String!){ __type(name:$n){ fields { name type { name kind ofType { name kind } } } } }", {"n": mangas_type})
                    candidates = []
                    if isinstance(type_info, dict):
                        tfields = (type_info.get('data') or {}).get('__type', {}).get('fields', [])
                        for tf in tfields:
                            fname = tf.get('name')
                            if not fname:
                                continue
                            # try common containers only
                            if fname.lower() in ('list','data','results','items','nodes','edges'):
                                candidates.append(fname)
                    if getattr(self, 'debug_library', False):
                        print("[gql-debug] mangas type:", mangas_type, "candidates:", ", ".join(candidates) or '(none)')
                    for c in candidates:
                        if c == 'edges':
                            q = f"query {{ mangas {{ edges {{ node {{ id title }} }} }} }}"
                        else:
                            q = f"query {{ mangas {{ {c} {{ id title }} }} }}"
                        res = self.graphql(q)
                        if not res:
                            continue
                        items = self._extract_manga_list_from_gql(res)
                        if items:
                            return items
        except Exception as e:
            if getattr(self, 'debug_library', False):
                print("[gql-debug] Introspection error:", e)
        return []

    

    def get_library(self) -> List[Dict[str, Any]]:
        # Try multiple known endpoints across Suwayomi builds
        endpoints = [
            "/api/v1/library",
            "/api/v1/manga/list",
            "/api/v1/manga",
            "/api/v1/library/list",
            "/api/v1/library/manga",
        ]
        for ep in endpoints:
            try:
                r = self.request("GET", ep)
            except Exception as e:
                if getattr(self, 'debug_library', False):
                    print(f"[lib-debug] Exception requesting {ep}: {e}")
                continue
            if r.status_code != 200:
                if getattr(self, 'debug_library', False):
                    print(f"[lib-debug] HTTP {r.status_code} {ep}: {truncate_text(r.text, 120)}")
                continue
            try:
                data = r.json()
            except Exception as je:
                if getattr(self, 'debug_library', False):
                    print(f"[lib-debug] Invalid JSON from {ep}: {je}")
                continue
            if getattr(self, 'debug_library', False):
                shape = type(data).__name__
                print(f"[lib-debug] {ep} -> {shape}")
            # Normalize to list of entries with id and title
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for k in ("data", "manga", "list", "mangaList", "mangaListData", "items"):
                    v = data.get(k)
                    if isinstance(v, list):
                        return v
        # Fallback to GraphQL if REST endpoints didn't yield anything
        if getattr(self, 'debug_library', False):
            print("[lib-debug] Falling back to GraphQL for library list")
        try:
            items = self.get_library_graphql()
            if items:
                return items
        except Exception as e:
            if getattr(self, 'debug_library', False):
                print(f"[lib-debug] GraphQL fallback failed: {e}")
        return []


# --- Import logic ---

def find_mangadex_source_id(sources: List[Dict[str, Any]]) -> Optional[int]:
    for s in sources:
        name = (s.get("name") or "").lower()
        apk = (s.get("apkName") or "").lower()
        # Mangadex source typically has name like "MangaDex" and package containing "mangadex"
        if "mangadex" in name or "mangadex" in apk:
            return int(s["id"]) if "id" in s else None
    return None


def search_by_mangadex_id(client: SuwayomiClient, source_id: int, md_id: str) -> Optional[int]:
    """Attempt direct UUID search in source. Returns manga_id or None."""
    try:
        resp = client.search_source(source_id, md_id, page=1)
    except Exception:
        return None
    items = resp.get("mangaList") or resp.get("mangaListData") or resp.get("manga_list") or []
    for it in items:
        url = str(it.get("url", ""))
        if md_id in url:
            return int(it.get("id"))
    for it in items:
        if str(it.get("key", "")) == md_id:
            return int(it.get("id"))
    return None


def fetch_title_from_mangadex(md_id: str) -> Optional[str]:
    """Fetch canonical English (or first available) title from MangaDex API."""
    try:
        r = requests.get(f"{MANGADEX_API}/manga/{md_id}", timeout=12)
        if r.status_code != 200:
            return None
        data = r.json().get("data") or {}
        attrs = data.get("attributes", {})
        titles = attrs.get("title") or {}
        # Prefer 'en', else first
        if "en" in titles:
            return titles["en"].strip()
        if titles:
            return next(iter(titles.values())).strip()
        alt_titles = attrs.get("altTitles") or []
        for alt in alt_titles:
            for v in alt.values():
                return v.strip()
    except Exception:
        return None
    return None


def search_by_title(client: SuwayomiClient, source_id: int, title: str) -> Optional[int]:
    """Search source by title text and attempt fuzzy containment match."""
    if not title:
        return None
    try:
        resp = client.search_source(source_id, title, page=1)
    except Exception:
        return None
    items = resp.get("mangaList") or resp.get("mangaListData") or resp.get("manga_list") or []
    # Prefer exact/normalized equality first
    exact_norm = " ".join(_normalize_title_tokens(title))
    exact_id: Optional[int] = None
    for it in items:
        cand = str(it.get("title") or it.get("name") or "")
        if not cand:
            continue
        if " ".join(_normalize_title_tokens(cand)) == exact_norm:
            try:
                return int(it.get("id"))
            except Exception:
                continue
    # Otherwise, pick the best similarity above threshold
    best_id: Optional[int] = None
    best_score = 0.0
    for it in items:
        cand = str(it.get("title") or it.get("name") or "")
        if not cand:
            continue
        try:
            score = _title_similarity(title, cand)
        except Exception:
            score = 0.0
        if score > best_score:
            best_score = score
            try:
                best_id = int(it.get("id"))
            except Exception:
                best_id = None
    # Require a reasonable similarity to avoid random top lists
    return best_id if best_score >= 0.6 else None


def import_ids(
    client: SuwayomiClient,
    ids: List[str],
    dry_run: bool = False,
    use_title_fallback: bool = True,
    show_progress: bool = True,
    throttle: float = 0.0,
    category_id: Optional[int] = None,
    reading_statuses: Optional[Dict[str, str]] = None,
    status_category_map: Optional[Dict[str, int]] = None,
    status_default_category: Optional[int] = None,
    session_token: Optional[str] = None,
    chapter_sync_conf: Optional[Dict[str, Any]] = None,
    status_map_debug: bool = False,
    assume_missing_status: Optional[str] = None,
    lists_membership: Optional[Dict[str, List[str]]] = None,
    lists_category_map: Optional[Dict[str, int]] = None,
    lists_ignore_set: Optional[set] = None,
    rehome_conf: Optional[Dict[str, Any]] = None,
) -> Tuple[int, int, List[Tuple[str, str]]]:
    client._auth()
    sources = client.get_sources()
    source_id = find_mangadex_source_id(sources)
    if not source_id:
        raise SystemExit("Could not find MangaDex source. Ensure the MangaDex extension is installed and enabled in Suwayomi.")

    added = 0
    failed = 0
    failures: List[Tuple[str, str]] = []

    total = len(ids)
    for idx, md in enumerate(ids, 1):
        prefix = f"[{idx}/{total}] " if show_progress else ""
        try:
            manga_id = search_by_mangadex_id(client, source_id, md)
            fetched_title: Optional[str] = None
            if manga_id is None and use_title_fallback:
                fetched_title = fetch_title_from_mangadex(md)
                if fetched_title:
                    manga_id = search_by_title(client, source_id, fetched_title)
            if manga_id is None:
                failures.append((md, "not found (uuid + title fallback failed)" if use_title_fallback else "not found"))
                failed += 1
                if show_progress:
                    print(f"{prefix}FAIL {md} {('- ' + fetched_title) if fetched_title else ''}".rstrip())
                continue
            if dry_run:
                # Simulate status mapping output if requested (even if status missing)
                if status_map_debug:
                    # Prefer custom list mapping if available
                    display = None
                    target_cat = None
                    via = ''
                    if lists_membership and lists_category_map:
                        names = [n for n in (lists_membership.get(md) or []) if not (lists_ignore_set and n in lists_ignore_set)]
                        for nm in names:
                            if nm in lists_category_map:
                                display = f"List:{nm}"
                                target_cat = lists_category_map[nm]
                                via = 'list-map'
                                break
                    if target_cat is None and status_category_map:
                        raw_status = (reading_statuses.get(md, '') if reading_statuses else '')
                        eff_status = (raw_status or assume_missing_status or '').lower()
                        display = raw_status or (assume_missing_status and f"(assumed {assume_missing_status})") or '(none)'
                        if eff_status:
                            target_cat = status_category_map.get(eff_status)
                            via = 'map'
                            if target_cat is None and status_default_category is not None:
                                target_cat = status_default_category
                                via = 'default'
                            if target_cat is None and raw_status == '' and assume_missing_status and status_category_map.get(assume_missing_status.lower()):
                                target_cat = status_category_map.get(assume_missing_status.lower())
                                via = 'assumed'
                        else:
                            if status_default_category is not None:
                                target_cat = status_default_category
                                via = 'default'
                    if show_progress:
                        if target_cat is not None:
                            print(f"{prefix}STATUS {display or '(none)'} -> cat {target_cat} ({via}) (dry-run)")
                        else:
                            print(f"{prefix}STATUS {(display or '(none)')} -> no mapping (dry-run)")
                added += 1
                if show_progress:
                    print(f"{prefix}OK (dry-run) {md}")
                continue
            ok = client.add_to_library(manga_id)
            if ok:
                cat_result = True
                # Apply explicit category first
                if category_id is not None:
                    cat_result = client.add_manga_to_category(manga_id, category_id)
                # Apply list-based category mapping first, then fall back to reading status
                applied = False
                if lists_membership and lists_category_map:
                    names = [n for n in (lists_membership.get(md) or []) if not (lists_ignore_set and n in lists_ignore_set)]
                    for nm in names:
                        if nm in lists_category_map:
                            try:
                                cat_ok = client.add_manga_to_category(manga_id, lists_category_map[nm])
                                applied = True
                                if status_map_debug and show_progress:
                                    print(f"{prefix}STATUS List:{nm} -> cat {lists_category_map[nm]} {'OK' if cat_ok else 'FAIL'}")
                            except Exception as sm_e:
                                if status_map_debug and show_progress:
                                    print(f"{prefix}STATUS List:{nm} ERROR {sm_e}")
                            break
                if (not applied) and (reading_statuses or assume_missing_status or status_default_category is not None) and status_category_map:
                    raw_status = (reading_statuses.get(md, '') if reading_statuses else '')
                    eff_status = (raw_status or assume_missing_status or '').lower()
                    if eff_status:
                        target_cat = status_category_map.get(eff_status)
                        resolved_via = 'map'
                        if target_cat is None and status_default_category is not None:
                            target_cat = status_default_category
                            resolved_via = 'default'
                        if target_cat is None and raw_status == '' and assume_missing_status and status_category_map.get(assume_missing_status.lower()):
                            target_cat = status_category_map.get(assume_missing_status.lower())
                            resolved_via = 'assumed'
                        if target_cat is not None:
                            try:
                                cat_ok = client.add_manga_to_category(manga_id, target_cat)
                                if status_map_debug and show_progress:
                                    display_status = raw_status or f"(assumed {assume_missing_status})"
                                    print(f"{prefix}STATUS {display_status} -> cat {target_cat} ({resolved_via}) {'OK' if cat_ok else 'FAIL'}")
                            except Exception as sm_e:
                                if status_map_debug and show_progress:
                                    print(f"{prefix}STATUS {eff_status} -> cat {target_cat} ERROR {sm_e}")
                        else:
                            if status_map_debug and show_progress:
                                display_status = raw_status or '(none)'
                                print(f"{prefix}STATUS {display_status} -> no mapping applied")
                    else:
                        # No effective status (e.g., ignored or missing): apply default if provided
                        if status_default_category is not None:
                            try:
                                cat_ok = client.add_manga_to_category(manga_id, status_default_category)
                                if status_map_debug and show_progress:
                                    print(f"{prefix}STATUS (none) -> cat {status_default_category} (default) {'OK' if cat_ok else 'FAIL'}")
                            except Exception as sm_e:
                                if status_map_debug and show_progress:
                                    print(f"{prefix}STATUS (none) -> cat {status_default_category} ERROR {sm_e}")
                # Chapter read sync (per manga) optionally delayed
                if chapter_sync_conf and chapter_sync_conf.get('enabled') and session_token:
                    delay = chapter_sync_conf.get('delay') or 0
                    if delay > 0:
                        time.sleep(delay)
                    try:
                        sync_read_chapters_for_manga(
                            client=client,
                            session_token=session_token,
                            manga_md_id=md,
                            manga_internal_id=manga_id,
                            dry_run=chapter_sync_conf.get('dry_run', False),
                            rpm=chapter_sync_conf.get('rpm', 300),
                            show_progress=show_progress,
                            prefix=prefix
                        )
                    except Exception as ce:
                        if show_progress:
                            print(f"{prefix}WARN chapters {md}: {ce}")
                # Rehoming/migration: if enabled and MangaDex has too few chapters, try alternative sources
                if rehome_conf and rehome_conf.get('enabled'):
                    try:
                        min_ch = int(rehome_conf.get('skip_if_ge', 1))
                    except Exception:
                        min_ch = 1
                    have = client.get_manga_chapters_count(manga_id)
                    if have < min_ch:
                        # We need title to search other sources
                        title = fetched_title or fetch_title_from_mangadex(md) or ''
                        if not title:
                            # last attempt: from details
                            det = client.get_manga_details(manga_id)
                            title = str(det.get('title') or det.get('name') or '')
                        if title:
                            # Prepare preferred sources
                            pref = [s.strip().lower() for s in (rehome_conf.get('sources') or []) if s.strip()]
                            # Load all sources
                            all_sources = client.get_sources()
                            # Exclude unwanted sources by name/apkName (from rehome_conf)
                            exclude_frags = [f for f in (rehome_conf.get('exclude_frags') or []) if f]
                            if exclude_frags:
                                _tmp = []
                                for _s in all_sources:
                                    _nm = (_s.get('name') or _s.get('apkName') or '').lower()
                                    if any(f in _nm for f in exclude_frags):
                                        continue
                                    _tmp.append(_s)
                                all_sources = _tmp
                            # Sort sources by preference (those matching any fragment first)
                            def score(src: Dict[str, Any]) -> int:
                                nm = (src.get('name') or src.get('apkName') or '').lower()
                                for i, frag in enumerate(pref):
                                    if frag and frag in nm:
                                        return i
                                return 9999
                            for src in sorted(all_sources, key=score):
                                nm = (src.get('name') or src.get('apkName') or '').lower()
                                if 'mangadex' in nm:
                                    continue
                                if pref and all(f not in nm for f in pref):
                                    # if preferences specified, skip non-matching sources unless we exhausted all
                                    pass
                                try:
                                    rid = int(src.get('id'))
                                except Exception:
                                    continue
                                try:
                                    search = client.search_source(rid, title, page=1)
                                except Exception:
                                    continue
                                items = SuwayomiClient.normalize_search_items(search)
                                if not items:
                                    continue
                                # Filter by title similarity to avoid unrelated "top" lists
                                def _cand_title(it: Dict[str, Any]) -> str:
                                    return str(it.get('title') or it.get('name') or it.get('label') or '')
                                threshold = float(rehome_conf.get('title_threshold') or 0.6)
                                strict = bool(rehome_conf.get('title_strict') or False)
                                filtered = [it for it in items if _is_title_match(title, _cand_title(it), threshold=threshold, strict_exact=strict)]
                                if not filtered:
                                    if show_progress:
                                        print(f"{prefix}REHOME skip '{src.get('name')}' (no title match >= {threshold}{' strict' if strict else ''})")
                                    continue
                                # pick best candidate by chapter count if enabled
                                alt_id = None
                                if rehome_conf.get('best_source'):
                                    best_count = -1
                                    limit = int(rehome_conf.get('best_candidates') or 5)
                                    for cand in filtered[:max(1, limit)]:
                                        cid = SuwayomiClient.extract_manga_id(cand)
                                        if cid is None:
                                            continue
                                        cnt = 0
                                        try:
                                            if rehome_conf.get('canonical'):
                                                cnt = client.get_manga_chapters_canonical_count(cid)
                                            else:
                                                cnt = client.get_manga_chapters_count(cid)
                                        except Exception:
                                            cnt = 0
                                        if cnt >= int(rehome_conf.get('min_chapters_per_alt') or 0) and cnt > best_count:
                                            best_count = cnt
                                            alt_id = cid
                                else:
                                    alt_id = SuwayomiClient.extract_manga_id(filtered[0])
                                if alt_id is None and int(rehome_conf.get('min_chapters_per_alt') or 0) <= 0 and filtered:
                                    alt_id = SuwayomiClient.extract_manga_id(filtered[0])
                                if alt_id is None:
                                    continue
                                added_alt = client.add_to_library(alt_id)
                                if show_progress:
                                    msg = f"{prefix}REHOME via '{src.get('name')}'"
                                    if rehome_conf.get('best_source'):
                                        msg += " (best-source)"
                                    print(f"{msg} -> {'OK' if added_alt else 'FAIL'}")
                                if added_alt and rehome_conf.get('remove_md'):
                                    try:
                                        rm_ok = client.remove_from_library(manga_id)
                                        if show_progress:
                                            print(f"{prefix}REMOVE MangaDex entry -> {'OK' if rm_ok else 'FAIL'}")
                                    except Exception as _:
                                        pass
                                # stop after first successful alt add attempt
                                break
                added += 1
                if show_progress:
                    if category_id is not None:
                        print(f"{prefix}OK added {md} (category {'ok' if cat_result else 'fail'})")
                    else:
                        print(f"{prefix}OK added {md}")
            else:
                failed += 1
                failures.append((md, f"add_to_library HTTP {ok}"))
                if show_progress:
                    print(f"{prefix}FAIL add {md}")
        except Exception as e:
            failed += 1
            failures.append((md, str(e)))
            if show_progress:
                print(f"{prefix}ERROR {md}: {e}")
        if throttle > 0:
            time.sleep(throttle)
    return added, failed, failures

# ---------------- MangaDex follows helpers (defined BEFORE main so they exist when called) ---------------- #

def login_mangadex(username: str, password: str) -> Optional[str]:
    """Return session token or None (legacy simple version kept for backward compat calls)."""
    token, _ = login_mangadex_verbose(username=username, password=password)
    return token


def login_mangadex_verbose(
    username: str,
    password: str,
    two_factor: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    debug: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    """Enhanced login returning (session_token, error_message)."""
    try:
        payload: Dict[str, Any] = {
            "username": (username or "").strip(),
            "password": (password or ""),
        }
        if two_factor:
            payload["code"] = two_factor.strip()
        # MangaDex currently does not require client id/secret for basic auth/login, but keep for future
        headers = {"Content-Type": "application/json", "User-Agent": "SuwayomiImporter/1.0"}
        r = requests.post(f"{MANGADEX_API}/auth/login", json=payload, headers=headers, timeout=20)
        if r.status_code != 200:
            msg = f"HTTP {r.status_code}: {truncate_text(r.text)}"
            if debug:
                print(f"[login debug] Login failed: {msg}")
            return None, msg
        data = r.json()
        token = ((data.get("token") or {}).get("session"))
        if not token:
            if debug:
                print(f"[login debug] No session token field in response: keys={list(data.keys())}")
            return None, "No session token in response"
        return token, None
    except Exception as e:
        if debug:
            print(f"[login debug] Exception during login: {e}")
        return None, str(e)


def fetch_all_follows(session_token: str) -> List[Dict[str, Any]]:
    # Legacy simple version kept for backward compatibility; wraps new function with defaults
    return fetch_all_follows_adv(session_token=session_token)


def fetch_all_follows_adv(session_token: str, debug: bool = False, max_follows: Optional[int] = None, pause: float = 0.2) -> List[Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {session_token}"}
    limit = 100
    offset = 0
    results: List[Dict[str, Any]] = []
    total_reported: Optional[int] = None
    consecutive_failures = 0
    while True:
        if max_follows is not None and len(results) >= max_follows:
            if debug:
                print(f"[follows debug] Reached max_follows={max_follows}, stopping early")
            break
        params = {"limit": limit, "offset": offset}
        try:
            r = requests.get(f"{MANGADEX_API}/user/follows/manga", params=params, headers=headers, timeout=25)
        except Exception as e:
            consecutive_failures += 1
            if debug:
                print(f"[follows debug] Exception offset={offset}: {e}")
            if consecutive_failures >= 3:
                break
            time.sleep(1.0 * consecutive_failures)
            continue
        if r.status_code != 200:
            consecutive_failures += 1
            if debug:
                print(f"[follows debug] HTTP {r.status_code} at offset={offset}: {truncate_text(r.text, 120)} (failure {consecutive_failures})")
            if consecutive_failures >= 3:
                break
            time.sleep(1.0 * consecutive_failures)
            continue
        consecutive_failures = 0
        js = r.json()
        data = js.get("data") or []
        limit_returned = js.get("limit") or len(data)
        total_reported = js.get("total") if total_reported is None else total_reported
        if debug:
            tr = f" total={total_reported}" if total_reported is not None else ""
            print(f"[follows debug] Page offset={offset} got={len(data)} limit={limit_returned}{tr} accum={len(results)}")
        if not data:
            # No more data
            break
        before_add = len(results)
        for entry in data:
            mid = entry.get("id")
            attrs = (entry.get("attributes") or {})
            titles = (attrs.get("title") or {})
            title = titles.get("en") or (next(iter(titles.values())) if titles else "")
            results.append({"id": mid, "title": title})
            if max_follows is not None and len(results) >= max_follows:
                break
        added_now = len(results) - before_add
        if debug:
            print(f"[follows debug] Added {added_now} this page; new_total={len(results)}")
        if total_reported is not None and len(results) >= total_reported:
            # Collected all
            break
        # Increment offset by actual number of items received to avoid gaps when a page is short
        offset += len(data)
        # Safety: if API stops increasing offset effectively
        if offset > 10000:  # arbitrary guard to avoid infinite loop
            if debug:
                print("[follows debug] Offset exceeded safety guard; stopping")
            break
        time.sleep(pause)
    if debug:
        if total_reported is not None and len(results) < total_reported:
            print(f"[follows debug] WARNING collected {len(results)} < reported total {total_reported}")
        print(f"[follows debug] Finished follows fetch: {len(results)} items")
    return results


def fetch_reading_statuses(session_token: str, manga_ids: List[str]) -> Dict[str, str]:
    """Fetch reading status for given MangaDex manga ids.
    MangaDex offers bulk endpoint: GET /manga/status?ids[]=... but to avoid very long URLs we batch.
    Returns dict md_uuid -> status (lowercase)."""
    headers = {"Authorization": f"Bearer {session_token}"}
    result: Dict[str, str] = {}
    batch = 50
    for i in range(0, len(manga_ids), batch):
        subset = manga_ids[i:i+batch]
        try:
            params = []
            for mid in subset:
                params.append(("ids[]", mid))
            r = requests.get(f"{MANGADEX_API}/manga/status", params=params, headers=headers, timeout=20)
            if r.status_code != 200:
                continue
            data = r.json().get('statuses') or {}
            for k, v in data.items():
                # API may return either a bare string or an object like {"status": "on_hold"}
                if isinstance(v, str):
                    result[k] = v.lower()
                elif isinstance(v, dict):
                    sv = v.get('status') or v.get('readingStatus') or v.get('value')
                    if isinstance(sv, str):
                        result[k] = sv.lower()
        except Exception:
            continue
        time.sleep(0.15)
    return result


def fetch_single_status(session_token: str, manga_id: str) -> Optional[str]:
    """Fetch status for a single manga via /manga/{id}/status endpoint. Returns lowercase status or None."""
    headers = {"Authorization": f"Bearer {session_token}"}
    try:
        r = requests.get(f"{MANGADEX_API}/manga/{manga_id}/status", headers=headers, timeout=12)
        if r.status_code != 200:
            return None
        js = r.json()
        # Spec shows { result: ok, status: <value|null> }
        val = js.get('status')
        if isinstance(val, str) and val:
            return val.lower()
        return None
    except Exception:
        return None


def fetch_all_statuses(session_token: str) -> Dict[str, str]:
    """Fetch all reading statuses for the authenticated user via /manga/status without ids filter.
    Returns dict md_uuid -> status (lowercase)."""
    headers = {"Authorization": f"Bearer {session_token}"}
    try:
        r = requests.get(f"{MANGADEX_API}/manga/status", headers=headers, timeout=30)
        if r.status_code != 200:
            return {}
        raw = r.json().get('statuses') or {}
        out: Dict[str, str] = {}
        for k, v in raw.items():
            if isinstance(v, str):
                out[k] = v.lower()
            elif isinstance(v, dict):
                sv = v.get('status') or v.get('readingStatus') or v.get('value')
                if isinstance(sv, str):
                    out[k] = sv.lower()
        return out
    except Exception:
        return {}


def fetch_suwayomi_chapters(client: SuwayomiClient, manga_internal_id: int) -> List[Dict[str, Any]]:
    try:
        r = client.request("GET", f"/api/v1/manga/{manga_internal_id}/chapters")
        if r.status_code != 200:
            return []
        js = r.json()
        # adaptive: look for list keys
        if isinstance(js, list):
            return js
        for key in ("chapters", "chapterList", "data"):
            if key in js and isinstance(js[key], list):
                return js[key]
        return []
    except Exception:
        return []


MD_CHAPTER_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def extract_chapter_uuid_from_item(item: Dict[str, Any]) -> Optional[str]:
    for field in ("url", "key", "chapterUrl", "sourceUrl"):
        v = item.get(field)
        if not v:
            continue
        m = MD_CHAPTER_UUID_RE.search(str(v))
        if m:
            return m.group(0)
    return None


def mark_chapter_read(client: SuwayomiClient, chapter_internal_id: int) -> bool:
    """Mark a chapter as read using several API variants. Returns True if a write-like
    endpoint reported success (200/204). Avoids treating a plain GET 200 as success.
    """
    paths_to_try = []
    # Preferred variants
    paths_to_try.append(("POST", f"/api/v1/chapter/{chapter_internal_id}/read", None))
    # Some servers use plural 'chapters'
    paths_to_try.append(("POST", f"/api/v1/chapters/{chapter_internal_id}/read", None))
    # PATCH body variant used by some builds
    paths_to_try.append(("PATCH", f"/api/v1/chapter/{chapter_internal_id}", {"read": True}))
    paths_to_try.append(("PATCH", f"/api/v1/chapters/{chapter_internal_id}", {"read": True}))
    # PUT variant
    paths_to_try.append(("PUT", f"/api/v1/chapter/{chapter_internal_id}/read", None))
    paths_to_try.append(("PUT", f"/api/v1/chapters/{chapter_internal_id}/read", None))
    # Batch fallbacks
    paths_to_try.append(("POST", "/api/v1/chapter/read", {"ids": [chapter_internal_id], "read": True}))
    paths_to_try.append(("POST", "/api/v1/chapters/read", {"ids": [chapter_internal_id], "read": True}))
    paths_to_try.append(("POST", "/api/v1/chapter/batch/read", {"ids": [chapter_internal_id], "read": True}))
    # Query-param variants
    paths_to_try.append(("GET", f"/api/v1/chapter/read?id={chapter_internal_id}", None))
    paths_to_try.append(("POST", f"/api/v1/chapter/read?id={chapter_internal_id}", None))
    # Legacy GET last (don’t treat as success unless 204/explicit body; here we require 204)
    paths_to_try.append(("GET", f"/api/v1/chapter/{chapter_internal_id}/read", None))

    for method, path, body in paths_to_try:
        try:
            kwargs = {}
            if body is not None:
                kwargs["json"] = body
            r = client.request(method, path, **kwargs)
            code = r.status_code
            if READ_SYNC_DEBUG:
                try:
                    print(f"[read-debug] mark attempt {method} {path} -> {code}")
                except Exception:
                    pass
            # Treat write-like endpoints success
            if method in ("POST", "PATCH", "PUT") and code in (200, 204):
                return True
            # For GET legacy variants, only accept 204 as a positive indicator
            if method == "GET" and code == 204:
                return True
        except Exception:
            continue
    # GraphQL fallbacks (executed only if REST variants above didn't return)
    try:
        # Prefer using the same mutations the WebUI uses
        # 1) updateChapters(ids: [Int!], patch: UpdateChapterPatchInput!)
        if READ_SYNC_DEBUG:
            try:
                print(f"[read-debug] graphql attempt: updateChapters ids=[{chapter_internal_id}] isRead=true")
            except Exception:
                pass
        mut_uc = """
        mutation UpdateChapters($ids: [Int!]!, $patch: UpdateChapterPatchInput!) {
          updateChapters(input: { ids: $ids, patch: $patch }) {
            chapters { nodes { id isRead } }
          }
        }
        """
        d_uc = client.graphql(mut_uc, {"ids": [int(chapter_internal_id)], "patch": {"isRead": True, "lastPageRead": 0}})
        if d_uc and isinstance(d_uc, dict) and (d_uc.get("data") or {}).get("updateChapters"):
            if READ_SYNC_DEBUG:
                try:
                    print(f"[read-debug] graphql updateChapters ok for {chapter_internal_id}")
                except Exception:
                    pass
            return True
        # 2) updateChapter(id: Int!, patch: UpdateChapterPatchInput!)
        if READ_SYNC_DEBUG:
            try:
                print(f"[read-debug] graphql attempt: updateChapter id={chapter_internal_id} isRead=true")
            except Exception:
                pass
        mut_uc1 = """
        mutation UpdateChapter($id: Int!, $patch: UpdateChapterPatchInput!) {
          updateChapter(input: { id: $id, patch: $patch }) {
            chapter { id isRead }
          }
        }
        """
        d_uc1 = client.graphql(mut_uc1, {"id": int(chapter_internal_id), "patch": {"isRead": True, "lastPageRead": 0}})
        if d_uc1 and isinstance(d_uc1, dict) and (d_uc1.get("data") or {}).get("updateChapter"):
            if READ_SYNC_DEBUG:
                try:
                    print(f"[read-debug] graphql updateChapter ok for {chapter_internal_id}")
                except Exception:
                    pass
            return True
    except Exception:
        if READ_SYNC_DEBUG:
            try:
                print(f"[read-debug] graphql error for {chapter_internal_id}")
            except Exception:
                pass
    return False


def fetch_mangadex_read_chapters(session_token: str, manga_md_id: str) -> List[str]:
    headers = {"Authorization": f"Bearer {session_token}"}
    try:
        r = requests.get(f"{MANGADEX_API}/manga/{manga_md_id}/read", headers=headers, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json().get('data') or []
        return [c for c in data if isinstance(c, str)]
    except Exception:
        return []


def sync_read_chapters_for_manga(
    client: SuwayomiClient,
    session_token: str,
    manga_md_id: str,
    manga_internal_id: int,
    dry_run: bool,
    rpm: int,
    show_progress: bool,
    prefix: str,
) -> None:
    md_read = fetch_mangadex_read_chapters(session_token, manga_md_id)
    if not md_read:
        return
    su_chapters = fetch_suwayomi_chapters(client, manga_internal_id)
    if not su_chapters:
        if show_progress:
            print(f"{prefix}WARN no chapters loaded yet for {manga_md_id}")
        # Live report: record unknown when chapters not loaded yet
        try:
            if MISSING_REPORT_PATH:
                title = fetch_title_from_mangadex(manga_md_id) or ""
                with MISSING_REPORT_PATH.open('a', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    w.writerow([title, manga_md_id, 0, 0, 'unknown'])
        except Exception:
            pass
        return
    uuid_to_internal: Dict[str, int] = {}
    for ch in su_chapters:
        cid = ch.get('id') or ch.get('chapterId') or ch.get('chapter_id')
        try:
            cid_int = int(cid)
        except Exception:
            continue
        md_uuid = extract_chapter_uuid_from_item(ch)
        if md_uuid:
            uuid_to_internal[md_uuid.lower()] = cid_int
    # throttle calculations
    min_interval = 60.0 / rpm if rpm > 0 else 0
    last_time = 0.0
    marked = 0
    missing = 0
    for md_uuid in md_read:
        internal = uuid_to_internal.get(md_uuid.lower())
        if not internal:
            missing += 1
            continue
        if dry_run:
            marked += 1
            continue
        now = time.time()
        if min_interval > 0 and (now - last_time) < min_interval:
            time.sleep(min_interval - (now - last_time))
        ok = mark_chapter_read(client, internal)
        last_time = time.time()
        if ok:
            marked += 1
    if show_progress:
        print(f"{prefix}Chapters sync {manga_md_id}: markable={len(md_read)} marked={marked} missing={missing}")
    # Live report: write missing rows immediately when missing>0
    try:
        if MISSING_REPORT_PATH and missing > 0:
            title = fetch_title_from_mangadex(manga_md_id) or ""
            with MISSING_REPORT_PATH.open('a', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow([title, manga_md_id, len(md_read), marked, missing])
    except Exception:
        pass


# --- MangaDex custom lists helpers ---
def fetch_user_lists(session_token: str, debug: bool = False) -> List[Dict[str, Any]]:
    """Fetch user's custom reading lists (id + name)."""
    headers = {"Authorization": f"Bearer {session_token}"}
    limit = 100
    offset = 0
    items: List[Dict[str, Any]] = []
    while True:
        try:
            r = requests.get(f"{MANGADEX_API}/user/list", params={"limit": limit, "offset": offset}, headers=headers, timeout=20)
        except Exception as e:
            if debug:
                print(f"[lists debug] Exception at offset={offset}: {e}")
            break
        if r.status_code != 200:
            if debug:
                print(f"[lists debug] HTTP {r.status_code} at offset={offset}: {truncate_text(r.text,120)}")
            break
        js = r.json()
        data = js.get("data") or []
        if not data:
            break
        for entry in data:
            lid = entry.get("id")
            name = ((entry.get("attributes") or {}).get("name")) or entry.get("name")
            if lid and name:
                items.append({"id": lid, "name": name})
        offset += len(data)
        if len(data) < limit:
            break
        time.sleep(0.15)
    if debug:
        print(f"[lists debug] Collected {len(items)} lists")
    return items


def fetch_manga_ids_in_list(session_token: str, list_id: str, debug: bool = False) -> List[str]:
    """Fetch manga IDs belonging to a specific list via /manga?list=<listId>."""
    headers = {"Authorization": f"Bearer {session_token}"}
    limit = 100
    offset = 0
    ids: List[str] = []
    while True:
        try:
            r = requests.get(f"{MANGADEX_API}/manga", params={"limit": limit, "offset": offset, "list": list_id}, headers=headers, timeout=25)
        except Exception as e:
            if debug:
                print(f"[lists debug] Exception fetching list {list_id} offset={offset}: {e}")
            break
        if r.status_code != 200:
            if debug:
                print(f"[lists debug] HTTP {r.status_code} for list {list_id} at offset={offset}: {truncate_text(r.text,120)}")
            break
        js = r.json()
        data = js.get("data") or []
        if not data:
            break
        for m in data:
            mid = m.get("id")
            if mid:
                ids.append(mid)
        offset += len(data)
        if len(data) < limit:
            break
        time.sleep(0.15)
    if debug:
        print(f"[lists debug] List {list_id}: {len(ids)} manga ids")
    return ids


# --- Cross-source read sync helpers (by chapter number) ---
def _norm_title_for_match(title: str) -> str:
    return " ".join(_normalize_title_tokens(title or ""))

def _parse_chapter_number_from_item(item: Dict[str, Any]) -> Optional[float]:
    # Try structured numeric fields first
    for k in (
        "chapterNumber", "chapter", "number",
        # additional commonly seen fields across sources
        "realChapterNumber", "chapter_index", "chapterIndex", "num", "no", "chap", "chNumber", "chNum",
        # some servers expose a sortable numeric field
        "numberSort", "sort"
    ):
        v = item.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            m = re.search(r"(\d+(?:\.\d+)?)", v)
            if m:
                try:
                    return float(m.group(1))
                except Exception:
                    pass
    # Fall back to text fields
    for k in ("name", "title"):
        v = item.get(k)
        if isinstance(v, str):
            m = re.search(r"(\d+(?:\.\d+)?)", v)
            if m:
                try:
                    return float(m.group(1))
                except Exception:
                    pass
    return None

def _build_fraction_map(numbers: List[float]) -> Dict[int, Set[int]]:
    m: Dict[int, Set[int]] = {}
    for n in numbers:
        b = int(math.floor(n + 1e-9))
        f = int(round((n - b) * 10)) if n - b > 0 else 0
        m.setdefault(b, set()).add(f)
    return m

def _is_fraction_canonical(n: float, frac_map: Dict[int, Set[int]]) -> bool:
    b = int(math.floor(n + 1e-9))
    f = int(round((n - b) * 10)) if n - b > 0 else 0
    fr = frac_map.get(b, set())
    if f == 0:
        return True
    if 1 <= f <= 4:
        return True
    if f == 5:
        # include .5 if any other split exists (1-4 or >=6)
        return any(x in fr for x in (1, 2, 3, 4)) or any(x >= 6 for x in fr)
    # .6+ present => canonical segment
    return True

def _compute_entry_progress_by_number(client: SuwayomiClient, manga_internal_id: int) -> float:
    items = fetch_suwayomi_chapters(client, manga_internal_id) or []
    nums = [n for n in (_parse_chapter_number_from_item(it) for it in items) if n is not None]
    frac_map = _build_fraction_map(nums)
    read_nums: List[float] = []
    for it in items:
        if not (it.get("read") or it.get("isRead")):
            continue
        n = _parse_chapter_number_from_item(it)
        if n is None:
            continue
        if _is_fraction_canonical(n, frac_map):
            read_nums.append(n)
    return max(read_nums) if read_nums else 0.0

def _mark_entry_up_to_number(client: SuwayomiClient, manga_internal_id: int, up_to: float, rpm: int, dry_run: bool = False) -> None:
    items = fetch_suwayomi_chapters(client, manga_internal_id) or []
    nums = [n for n in (_parse_chapter_number_from_item(it) for it in items) if n is not None]
    frac_map = _build_fraction_map(nums)
    min_interval = 60.0 / rpm if rpm > 0 else 0
    last = 0.0
    applied = 0
    attempted_ids: List[int] = []
    for it in items:
        n = _parse_chapter_number_from_item(it)
        if n is None:
            continue
        if not _is_fraction_canonical(n, frac_map):
            continue
        if n <= up_to and not (it.get("read") or it.get("isRead")):
            cid = it.get("id") or it.get("chapterId") or it.get("_id")
            if isinstance(cid, str) and cid.isdigit():
                cid = int(cid)
            if not isinstance(cid, int):
                continue
            if dry_run:
                print(f"[DRY] Mark read by number <= {up_to}: chapter {n} (id={cid})")
            else:
                if min_interval:
                    now = time.time()
                    if last and now - last < min_interval:
                        time.sleep(min_interval - (now - last))
                    last = time.time()
                try:
                    ok = mark_chapter_read(client, cid)
                    if ok:
                        applied += 1
                        print(f"Mark read: chapter {n} (id={cid})", flush=True)
                    attempted_ids.append(cid)
                except Exception:
                    pass
    if not dry_run:
        print(f"Mark summary: applied {applied} chapters on entry {manga_internal_id} up to {up_to}", flush=True)
        # Verify by refetching and counting read flags if we attempted any writes
        if attempted_ids:
            try:
                v_items = fetch_suwayomi_chapters(client, manga_internal_id) or []
                read_count = 0
                id_set = set(attempted_ids)
                for vit in v_items:
                    cid2 = vit.get("id") or vit.get("chapterId") or vit.get("_id")
                    if isinstance(cid2, str) and cid2.isdigit():
                        cid2 = int(cid2)
                    if cid2 in id_set and (vit.get("read") or vit.get("isRead")):
                        read_count += 1
                print(f"Verify summary: {read_count}/{len(attempted_ids)} marked as read now", flush=True)
            except Exception:
                pass

def _compute_md_progress_by_numbers(session_token: str, manga_md_id: str) -> Optional[float]:
    uuids = fetch_mangadex_read_chapters(session_token, manga_md_id)
    if not uuids:
        return None
    nums: List[float] = []
    for u in uuids:
        try:
            r = requests.get(f"{MANGADEX_API}/chapter/{u}", timeout=12)
            if r.status_code != 200:
                continue
            ch = (r.json() or {}).get("data", {}).get("attributes", {})
            s = str(ch.get("chapter") or "").strip()
            if not s:
                continue
            m = re.search(r"(\d+(?:\.\d+)?)", s)
            if not m:
                continue
            nums.append(float(m.group(1)))
        except Exception:
            continue
    if not nums:
        return None
    frac_map = _build_fraction_map(nums)
    canon = [n for n in nums if _is_fraction_canonical(n, frac_map)]
    return max(canon) if canon else None

def sync_cross_source_read_for_md(
    client: SuwayomiClient,
    manga_md_id: str,
    session_token: str,
    rpm: int,
    dry_run: bool = False,
    only_if_ahead: bool = False,
    title_threshold: float = 0.6,
    title_strict: bool = False,
) -> None:
    # Resolve title from MangaDex to find same-title entries
    title = fetch_title_from_mangadex(manga_md_id) or ""
    if not title:
        return
    norm = _norm_title_for_match(title)
    md_max = _compute_md_progress_by_numbers(session_token, manga_md_id)
    if md_max is None:
        return
    lib = client.get_library_graphql() or client.get_library() or []
    for it in lib:
        mid = it.get("id") or (it.get("manga") or {}).get("id") or it.get("mangaId")
        t = it.get("title") or it.get("name") or ((it.get("manga") or {}).get("title") or (it.get("manga") or {}).get("name"))
        if not (mid and t):
            continue
        try:
            mid_int = int(mid)
        except Exception:
            continue
        # Use fuzzy/containment-aware title matching to link entries across sources
        if not _is_title_match(str(t), title, threshold=max(0.0, min(1.0, float(title_threshold))), strict_exact=bool(title_strict)):
            if READ_SYNC_DEBUG:
                try:
                    print(f"[read-debug] cross-source skip: '{truncate_text(str(t),80)}' not match '{truncate_text(title,80)}' (thr={title_threshold}{' strict' if title_strict else ''})")
                except Exception:
                    pass
            continue
        cur = _compute_entry_progress_by_number(client, mid_int)
        if only_if_ahead and not (md_max > cur):
            if READ_SYNC_DEBUG:
                try:
                    print(f"[read-debug] cross-source skip id={mid_int}: md_max={md_max} <= current={cur}")
                except Exception:
                    pass
            continue
        if READ_SYNC_DEBUG:
            try:
                print(f"[read-debug] cross-source apply id={mid_int}: md_max={md_max}, current={cur}")
            except Exception:
                pass
        _mark_entry_up_to_number(client, mid_int, md_max, rpm, dry_run=dry_run)

def compute_md_missing_stats(client: SuwayomiClient, session_token: str, md_id: str) -> Optional[Dict[str, Any]]:
    """Compute markable/marked/missing for a MangaDex ID against the MangaDex source entry in Suwayomi.
    Returns dict with title, md_id, markable, marked, missing; or None if unresolved.
    """
    try:
        title = fetch_title_from_mangadex(md_id) or md_id
        # Find MangaDex source internal id
        srcs = client.get_sources()
        md_source_id = find_mangadex_source_id(srcs)
        if not md_source_id:
            return None
        # Resolve manga internal id in Suwayomi for this MD id
        internal_id = search_by_mangadex_id(client, md_source_id, md_id)
        if internal_id is None:
            # Fallback by title search
            if title:
                internal_id = search_by_title(client, md_source_id, title)
        if internal_id is None:
            return None
        # Fetch chapters in Suwayomi and build UUID map
        su_chapters = fetch_suwayomi_chapters(client, internal_id) or []
        uuid_to_item: Dict[str, Dict[str, Any]] = {}
        for it in su_chapters:
            u = extract_chapter_uuid_from_item(it)
            if u:
                uuid_to_item[u] = it
        if not uuid_to_item:
            # no chapters loaded yet
            return {
                'title': title,
                'md_id': md_id,
                'markable': 0,
                'marked': 0,
                'missing': 'unknown',
            }
        md_read = fetch_mangadex_read_chapters(session_token, md_id) or []
        markable = 0
        marked = 0
        for u in md_read:
            it = uuid_to_item.get(u)
            if it is not None:
                markable += 1
                if it.get('read') or it.get('isRead'):
                    marked += 1
        missing = max(0, len(md_read) - markable)
        return {
            'title': title,
            'md_id': md_id,
            'markable': markable,
            'marked': marked,
            'missing': missing,
        }
    except Exception:
        return None


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Import MangaDex bookmarks / follows into Suwayomi library.")
    p.add_argument("input_file", type=Path, nargs="?", help="Optional path to bookmarks file (txt/csv/xlsx/json/html). Omit when using --from-follows only.")
    p.add_argument("--base-url", required=True, help="Suwayomi base URL, e.g. http://localhost:4567")
    p.add_argument("--auth-mode", choices=["auto", "basic", "simple", "bearer"], default="auto")
    p.add_argument("--username", help="Username for BASIC or SIMPLE login (if applicable)")
    p.add_argument("--password", help="Password for BASIC or SIMPLE login (if applicable)")
    p.add_argument("--token", help="Bearer token for UI_LOGIN mode (Settings -> API Tokens)")
    p.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification")
    p.add_argument("--dry-run", action="store_true", help="Do not modify library, just simulate")
    p.add_argument("--no-title-fallback", action="store_true", help="Disable title lookup fallback via MangaDex API when direct UUID search fails")
    p.add_argument("--no-progress", action="store_true", help="Disable per-item progress output")
    p.add_argument("--throttle", type=float, default=0.0, help="Sleep seconds between items (avoid rate limits)")
    p.add_argument("--category-id", type=int, help="Optional Suwayomi category id to assign each added manga")
    # Follows fetch options
    p.add_argument("--from-follows", action="store_true", help="Fetch followed manga from MangaDex for the authenticated user and include them")
    p.add_argument("--follows-json", type=Path, help="Write fetched follows (id + title) to this JSON file")
    p.add_argument("--md-username", help="MangaDex username (or set MANGADEX_USERNAME env)")
    p.add_argument("--md-password", help="MangaDex password (or set MANGADEX_PASSWORD env). If omitted and needed, you'll be prompted.")
    p.add_argument("--md-client-id", help="MangaDex client id (optional; or env MANGADEX_CLIENT_ID)")
    p.add_argument("--md-client-secret", help="MangaDex client secret (optional; or env MANGADEX_CLIENT_SECRET)")
    p.add_argument("--md-2fa", help="MangaDex 2FA/OTP code if your account has 2FA enabled")
    p.add_argument("--debug-login", action="store_true", help="Print diagnostic details if MangaDex login fails (redacts password)")
    p.add_argument("--debug-follows", action="store_true", help="Verbose pagination diagnostics for follows fetch")
    p.add_argument("--max-follows", type=int, help="Optional cap on number of follows to fetch (diagnostics/testing)")
    p.add_argument("--md-login-only", action="store_true", help="Login to MangaDex to obtain a session for read-sync, without fetching/merging follows")
    # Reading status & chapters sync
    p.add_argument("--import-reading-status", action="store_true", help="Fetch MangaDex reading statuses and map to categories")
    p.add_argument("--status-category-map", help="Comma list mapping status=categoryId (e.g. completed=5,reading=2,on_hold=7,dropped=8,plan_to_read=9,re_reading=10)")
    p.add_argument("--status-default-category", type=int, help="Fallback category id if a status has no explicit mapping")
    p.add_argument("--import-read-chapters", action="store_true", help="Fetch MangaDex read chapter UUIDs and mark them read in Suwayomi")
    p.add_argument("--debug-read-sync", action="store_true", help="Verbose diagnostics for read sync: UUID lookup, title resolution, progress, and cross-source matches")
    p.add_argument("--read-chapters-dry-run", action="store_true", help="Simulate chapter read marking only")
    p.add_argument("--read-sync-delay", type=float, default=0.0, help="Seconds to wait after adding a manga before syncing read chapters (allow chapters to populate)")
    p.add_argument("--max-read-requests-per-minute", type=int, default=300, help="Throttle for chapter read mark requests")
    p.add_argument("--read-sync-number-fallback", action="store_true", help="When MangaDex UUIDs don't match, mark chapters by chapter number on any same-title source")
    p.add_argument("--cross-source-title-threshold", type=float, default=0.6, help="Similarity threshold (0..1) when matching titles across sources for number-based read sync (default 0.6)")
    p.add_argument("--cross-source-title-strict", action="store_true", help="Require normalized exact/containment match for cross-source title match (disables fuzzy-only matches)")
    p.add_argument("--suwayomi-manga-id", type=int, help="Force read-sync onto this Suwayomi internal manga id (bypass UUID/title lookup)")
    p.add_argument("--read-sync-only-if-ahead", action="store_true", help="Only apply read marks when MangaDex has progressed further than the target entry")
    p.add_argument("--read-sync-across-sources", action=argparse.BooleanOptionalAction, default=False, help="Also apply read marks to same-title entries under other sources (by chapter number). Use this flag to enable cross-source sync; add --no-read-sync-across-sources to force it off explicitly")
    p.add_argument("--list-categories", action="store_true", help="List Suwayomi categories (id + name) and exit")
    p.add_argument("--list-library-titles", action="store_true", help="List Suwayomi library entries with internal IDs and exit")
    p.add_argument("--filter-title", help="Optional substring filter for --list-library-titles (case-insensitive)")
    p.add_argument("--status-map-debug", action="store_true", help="Verbose output for status->category mapping decisions")
    p.add_argument("--assume-missing-status", help="If a manga has no MangaDex status, assume this status (e.g. reading)")
    p.add_argument("--print-status-summary", action="store_true", help="Print summary of fetched statuses and mapping coverage")
    p.add_argument("--debug-status", action="store_true", help="Print raw status dict sample after fetch")
    p.add_argument("--status-endpoint-raw", action="store_true", help="Dump full raw JSON from /manga/status (and per-manga fallback) for diagnostics")
    p.add_argument("--status-fallback-single", action="store_true", help="If bulk status returns empty, fetch each via /manga/{id}/status")
    p.add_argument("--status-fallback-throttle", type=float, default=0.3, help="Sleep seconds between single status fallback calls (default 0.3)")
    p.add_argument("--ignore-statuses", help="Comma-separated list of status values to ignore for category mapping (e.g. reading)")
    p.add_argument("--verify-id", action="append", dest="verify_ids", help="Repeatable. Verify this MangaDex UUID is in the final import set (after follows merge). Can be specified multiple times.")
    p.add_argument("--export-statuses", type=Path, help="Write the final fetched statuses mapping (after filters) to this JSON file")
    p.add_argument("--include-library-statuses", action="store_true", help="Include ALL manga that have a MangaDex library reading status (merge into processing set)")
    p.add_argument("--library-statuses-only", action="store_true", help="Process ONLY manga that have a MangaDex library reading status (ignore follows and file)")
    # Rehoming/migration options
    p.add_argument("--rehoming-enabled", action="store_true", help="Attempt to add an alternative source entry when MangaDex has no chapters")
    p.add_argument("--rehoming-sources", help="Comma-separated list of source name fragments in priority order (e.g. 'mangasee,comick')")
    p.add_argument("--rehoming-skip-if-chapters-ge", type=int, default=1, help="Skip rehoming if MangaDex already has at least this many chapters (default 1)")
    p.add_argument("--rehoming-remove-mangadex", action="store_true", help="After successful rehome, remove the MangaDex entry from library (if API supports it)")
    p.add_argument("--migrate-title-threshold", type=float, default=0.6, help="Similarity threshold (0..1) for matching titles when selecting migrate/rehoming candidates (default 0.6)")
    p.add_argument("--migrate-title-strict", action="store_true", help="Require normalized exact/containment title match when selecting candidates (disables fuzzy-only matches)")
    # Migrate existing library without MangaDex data
    p.add_argument("--migrate-library", action="store_true", help="Scan current Suwayomi library and add an alternative source for entries under a chapter threshold")
    p.add_argument("--migrate-threshold-chapters", type=int, default=1, help="Only migrate entries with fewer than this many chapters (default 1)")
    p.add_argument("--migrate-sources", help="Preferred alternative sources (comma-separated fragments). If omitted, uses --rehoming-sources")
    p.add_argument("--exclude-sources", default="comick,hitomi", help="Comma-separated source name fragments to always exclude (default: 'comick,hitomi')")
    p.add_argument("--migrate-remove", action=argparse.BooleanOptionalAction, default=False, help="Remove the original library entry after a successful migration (default: disabled; pass --migrate-remove to enable removal)")
    p.add_argument("--migrate-remove-if-duplicate", action="store_true", help="If the selected alternative already exists in the library and has >0 chapters, remove the original zero/low-chapter entry instead of adding a duplicate")
    p.add_argument("--debug-library", action="store_true", help="Verbose diagnostics for library and chapter listing endpoints during migration")
    p.add_argument("--request-timeout", type=float, default=12.0, help="Default HTTP request timeout in seconds (default 12)")
    p.add_argument("--migrate-timeout", type=float, default=20.0, help="Max seconds to spend trying sources for a single migration item (default 20)")
    p.add_argument("--migrate-max-sources-per-site", type=int, default=3, help="Limit attempts per site name (e.g. 'mangapark') to this many different source IDs (default 3)")
    p.add_argument("--migrate-try-second-page", action="store_true", help="Try page 2 if page 1 had no results (slower)")
    p.add_argument("--migrate-filter-title", help="Only process library entries whose title contains this substring (case-insensitive)")
    p.add_argument("--migrate-preferred-only", action="store_true", help="When set and --migrate-sources provided, restrict search to only those sources (by name fragments)")
    p.add_argument("--preferred-langs", help="Comma-separated language codes to prefer when counting chapters (e.g. 'en,en-us,id'). If set, candidates are scored by chapters in these languages")
    p.add_argument("--lang-fallback", action="store_true", help="If no chapters match preferred languages for a candidate, allow non-preferred counts as fallback")
    # Source preference (quality bias)
    p.add_argument("--prefer-sources", help="Comma-separated source name fragments to bias as higher-quality (e.g. 'asura,flame,genz,utoons')")
    p.add_argument("--prefer-boost", type=int, default=3, help="Add this many points to the candidate score when its source matches --prefer-sources (default 3)")
    p.add_argument("--migrate-keep-both", action="store_true", help="When using global best, also add the raw max-chapters candidate if different from the preferred boosted winner (helps keep quality + completeness)")
    p.add_argument("--keep-both-min-preferred", type=int, default=1, help="Minimum preferred-language chapters required on the second candidate to keep it as well (set 0 to allow non-preferred) (default 1)")
    p.add_argument("--migrate-include-categories", help="Comma-separated category IDs or names; only entries in at least one of these categories will be migrated")
    p.add_argument("--migrate-exclude-categories", help="Comma-separated category IDs or names; entries in any of these categories will be skipped")
    # Best source selection
    p.add_argument("--best-source", action="store_true", help="Evaluate a few candidate sources and pick the one with the most chapters (opt-in)")
    p.add_argument("--best-source-candidates", type=int, default=5, help="Max number of candidate manga entries to score per title when --best-source is enabled (default 5)")
    p.add_argument("--min-chapters-per-alt", type=int, default=0, help="Require chosen alternative to have at least this many chapters; if not, try next candidate/result (default 0)")
    p.add_argument("--best-source-canonical", action="store_true", help="Score by unique canonical chapter numbers (collapse 1.1/1.2 to 1)")
    p.add_argument("--best-source-global", action="store_true", help="When set, consider all preferred sources and pick the single best candidate overall instead of stopping at the first site that qualifies")
    # Custom lists support
    p.add_argument("--import-lists", action="store_true", help="Fetch MangaDex custom lists and map list names to categories")
    p.add_argument("--list-lists", action="store_true", help="List your MangaDex custom lists (id + name) and exit")
    p.add_argument("--lists-category-map", help="Comma list mapping ListName=categoryId (e.g. Dropped=7,On Hold=5,Plan to Read=8,Completed=9,Reading=4)")
    p.add_argument("--lists-ignore", help="Comma-separated list names to ignore when importing lists (e.g. Reading)")
    p.add_argument("--debug-lists", action="store_true", help="Verbose output for custom lists fetching and mapping decisions")
    # Reports
    p.add_argument("--missing-report", type=Path, help="Write a CSV of titles where read-chapter sync found missing chapters (title, md_id, markable, marked, missing)")
    p.add_argument("--no-add-library", action="store_true", help="Do not add missing titles to Suwayomi; only run reporting and (if enabled) cross-source read sync against existing library entries")

    # Prune-only mode (hard prune duplicates without searching)
    p.add_argument("--prune-zero-duplicates", action="store_true", help="Remove zero/low-chapter entries when another entry with the same title already exists with >= --prune-threshold-chapters chapters (no searching)")
    p.add_argument("--prune-threshold-chapters", type=int, default=1, help="Threshold for considering an entry 'kept'. Entries with chapters < this value are pruned if a matching-title entry has >= this value (default 1, i.e., keep entries with >=1 chapter)")
    p.add_argument("--prune-filter-title", help="Only consider titles containing this substring (case-insensitive) during prune")
    p.add_argument("--prune-nonpreferred-langs", action="store_true", help="Remove entries whose chapters don't match --preferred-langs when another same-title entry has chapters in the preferred language(s)")
    p.add_argument("--prune-lang-threshold", type=int, default=1, help="Minimum number of preferred-language chapters required to consider an entry a keeper (default 1)")
    p.add_argument("--prune-lang-fallback-keep-most", action="store_true", help="If no entries have preferred-language chapters in a title group, keep only the entry with the highest total chapter count and prune the rest")

    args = p.parse_args(argv)

    # Enable early debug traces as soon as possible
    try:
        global READ_SYNC_DEBUG
        READ_SYNC_DEBUG = bool(getattr(args, 'debug_read_sync', False))
    except Exception:
        READ_SYNC_DEBUG = False
    if READ_SYNC_DEBUG:
        try:
            print("[read-debug] start; base_url=", args.base_url, "file=", str(args.input_file or ''), "from_follows=", bool(args.from_follows))
        except Exception:
            pass

    # Ensure session_token always defined to avoid UnboundLocalError when using --import-reading-status without --from-follows
    session_token: Optional[str] = None

    ids: List[str] = []
    if args.input_file:
        ids = read_any(args.input_file)
        if READ_SYNC_DEBUG:
            try:
                print(f"[read-debug] ids from file: {len(ids)}")
            except Exception:
                pass

    # --- MangaDex follows fetch ---
    follows_meta: List[Dict[str, Any]] = []
    if args.from_follows:
        md_user = args.md_username or os.environ.get("MANGADEX_USERNAME")
        md_pass = args.md_password or os.environ.get("MANGADEX_PASSWORD")
        if not md_user:
            print("MangaDex username required for --from-follows (flag --md-username or env MANGADEX_USERNAME)")
            return 2
        if not md_pass:
            md_pass = getpass.getpass("MangaDex password: ")
        session_token, login_err = login_mangadex_verbose(
            username=md_user,
            password=md_pass,
            two_factor=args.md_2fa,
            client_id=args.md_client_id or os.environ.get("MANGADEX_CLIENT_ID"),
            client_secret=args.md_client_secret or os.environ.get("MANGADEX_CLIENT_SECRET"),
            debug=args.debug_login,
        )
        if not session_token:
            print("Failed to authenticate with MangaDex." + (f" Reason: {login_err}" if login_err else ""))
            return 3
        follows_meta = fetch_all_follows_adv(
            session_token=session_token,
            debug=args.debug_follows,
            max_follows=args.max_follows,
        )
        if READ_SYNC_DEBUG:
            try:
                print(f"[read-debug] follows fetched: {len(follows_meta)} (max={args.max_follows})")
            except Exception:
                pass
        follow_ids = [m["id"] for m in follows_meta]
        # Merge with file IDs preserving order preference: file first, then new
        seen = set(ids)
        for fid in follow_ids:
            if fid not in seen:
                ids.append(fid)
                seen.add(fid)
        if args.follows_json:
            try:
                args.follows_json.write_text(json.dumps(follows_meta, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"Warning: failed to write follows JSON: {e}")
    elif args.md_login_only:
        # Login to MangaDex to obtain a session token without merging follows
        md_user = args.md_username or os.environ.get("MANGADEX_USERNAME")
        md_pass = args.md_password or os.environ.get("MANGADEX_PASSWORD")
        if not md_user or not md_pass:
            print("--md-login-only requires --md-username and --md-password (or env MANGADEX_USERNAME/MANGADEX_PASSWORD)")
            return 2
        session_token, login_err = login_mangadex_verbose(
            username=md_user,
            password=md_pass,
            two_factor=args.md_2fa,
            client_id=args.md_client_id or os.environ.get("MANGADEX_CLIENT_ID"),
            client_secret=args.md_client_secret or os.environ.get("MANGADEX_CLIENT_SECRET"),
            debug=args.debug_login,
        )
        if not session_token:
            print("Failed to authenticate with MangaDex." + (f" Reason: {login_err}" if login_err else ""))
            return 3

    # Optionally merge or replace with all-statuses library set
    library_statuses_all: Dict[str, str] = {}
    if (args.include_library_statuses or args.library_statuses_only):
        # Ensure we have a session
        if not session_token:
            md_user = args.md_username or os.environ.get("MANGADEX_USERNAME")
            md_pass = args.md_password or os.environ.get("MANGADEX_PASSWORD")
            if md_user and md_pass:
                session_token, _ = login_mangadex_verbose(username=md_user, password=md_pass, two_factor=args.md_2fa)
            else:
                print("--include-library-statuses/--library-statuses-only requires MangaDex credentials (use --md-username/--md-password)")
                return 2
        library_statuses_all = fetch_all_statuses(session_token) if session_token else {}
        lib_ids = list(library_statuses_all.keys())
        if args.library_statuses_only:
            ids = lib_ids
        else:
            seen = set(ids)
            for mid in lib_ids:
                if mid not in seen:
                    ids.append(mid)
                    seen.add(mid)

    if READ_SYNC_DEBUG:
        try:
            print(f"[read-debug] merged ids total: {len(ids)}")
        except Exception:
            pass
    if not ids and not args.list_categories and not args.migrate_library and not getattr(args, 'prune_zero_duplicates', False) and not getattr(args, 'prune_nonpreferred_langs', False):
        print("No MangaDex IDs to process (empty file and no follows fetched). Use --migrate-library or a prune mode to operate only on Suwayomi.")
        return 1

    # Optional presence verification of specific IDs
    if args.verify_ids:
        print("ID presence verification (after merge):")
        id_set = set(ids)
        for vid in args.verify_ids:
            if vid in id_set:
                print(f"  {vid} : PRESENT")
            else:
                print(f"  {vid} : MISSING (not in file nor follows)" )

    # --- Reading status + Lists mapping (optional) ---
    status_map: Dict[str, int] = {}
    if args.status_category_map:
        for part in args.status_category_map.split(','):
            part = part.strip()
            if not part:
                continue
            if '=' not in part:
                print(f"Warning: ignoring malformed status map entry '{part}'")
                continue
            k, v = part.split('=', 1)
            try:
                status_map[k.strip().lower()] = int(v)
            except ValueError:
                print(f"Warning: invalid category id in map entry '{part}'")
    reading_statuses: Dict[str, str] = {}
    lists_membership: Dict[str, List[str]] = {}
    lists_category_map: Dict[str, int] = {}
    lists_ignore_set: set = set()
    status_fetch_note = ""
    if args.import_reading_status:
        # We can reuse session_token from follows, or login solely for status fetch.
        if not session_token:
            # Attempt standalone login if credentials provided and from-follows not used.
            md_user = args.md_username or os.environ.get("MANGADEX_USERNAME")
            md_pass = args.md_password or os.environ.get("MANGADEX_PASSWORD")
            if md_user and md_pass:
                session_token, login_err = login_mangadex_verbose(username=md_user, password=md_pass, two_factor=args.md_2fa)
                if not session_token:
                    print("Failed MangaDex login for status fetch." + (f" Reason: {login_err}" if login_err else ""))
                    status_fetch_note = "login failed"
            else:
                print("No session (need --from-follows or MangaDex credentials) to fetch statuses.")
                status_fetch_note = "no credentials"
        if session_token:
            # If raw dump requested, capture raw JSON pages by temporarily wrapping fetch_reading_statuses batching
            if args.status_endpoint_raw:
                print("[status-raw] Fetching statuses for", len(ids), "ids")
            # Prefer using the pre-fetched all-statuses map when available
            if library_statuses_all:
                reading_statuses = {k: v for k, v in library_statuses_all.items() if k in set(ids)}
            else:
                reading_statuses = fetch_reading_statuses(session_token, ids)
            if not reading_statuses:
                status_fetch_note = "0 statuses fetched"
                if args.debug_status:
                    print("[debug-status] No statuses returned. If you just set one on MangaDex, wait a few seconds or toggle it again.")
                if args.status_endpoint_raw and ids:
                    # Try single-item fallback endpoint described in docs: GET /manga/{id}/status
                    test_id = ids[0]
                    try:
                        import requests as _rq
                        r2 = _rq.get(f"{MANGADEX_API}/manga/{test_id}/status", headers={"Authorization": f"Bearer {session_token}"}, timeout=15)
                        print(f"[status-raw] Single /manga/{{id}}/status HTTP {r2.status_code}")
                        try:
                            print("[status-raw] Body:", truncate_text(r2.text, 400))
                        except Exception:
                            pass
                    except Exception as se:
                        print(f"[status-raw] Single status fetch error: {se}")
                # Automatic or explicit fallback to single fetch per id
                if args.status_fallback_single or (not reading_statuses and args.import_reading_status):
                    if args.debug_status:
                        print(f"[debug-status] Starting single-status fallback for {len(ids)} ids")
                    fetched_any = False
                    for mid in ids:
                        st = fetch_single_status(session_token, mid)
                        if st:
                            reading_statuses[mid] = st
                            fetched_any = True
                        time.sleep(max(0.0, args.status_fallback_throttle))
                    if args.debug_status:
                        print(f"[debug-status] Single-status fallback {'found some' if fetched_any else 'found none'}.")
                    if reading_statuses and status_fetch_note.startswith('0 statuses'):
                        status_fetch_note = f"{len(reading_statuses)} statuses fetched (fallback)"
            else:
                status_fetch_note = f"{len(reading_statuses)} statuses fetched"

            # If bulk returned some, still fill in any missing IDs when fallback is requested
            if args.status_fallback_single and ids:
                missing_ids = [mid for mid in ids if mid not in reading_statuses]
                if missing_ids:
                    if args.debug_status:
                        print(f"[debug-status] Fallback for missing {len(missing_ids)} ids after bulk")
                    filled = 0
                    for mid in missing_ids:
                        st = fetch_single_status(session_token, mid)
                        if st:
                            reading_statuses[mid] = st
                            filled += 1
                        time.sleep(max(0.0, args.status_fallback_throttle))
                    if args.debug_status:
                        print(f"[debug-status] Fallback filled {filled} additional statuses")
            if args.debug_status:
                sample_items = list(reading_statuses.items())[:10]
                print("[debug-status] Sample:")
                for k,v in sample_items:
                    print(f"  {k}: {v}")
                if len(reading_statuses) > 10:
                    print(f"  ... {len(reading_statuses)-10} more")
            if args.status_endpoint_raw and reading_statuses:
                # Dump full mapping (may be large) truncated
                try:
                    js_dump = json.dumps(reading_statuses)
                    print("[status-raw] Full statuses JSON (truncated 800 chars):", js_dump[:800] + ("..." if len(js_dump) > 800 else ""))
                except Exception as je:
                    print(f"[status-raw] Could not dump statuses JSON: {je}")

            # Print raw summary before ignore if requested
            if args.print_status_summary and reading_statuses:
                raw_counts: Dict[str, int] = {}
                for s in reading_statuses.values():
                    raw_counts[s] = raw_counts.get(s, 0) + 1
                print("Raw status summary:", ", ".join(f"{k}={v}" for k,v in sorted(raw_counts.items())))

            # Filter out ignored statuses from mapping phase (still appear in raw summary before removal)
            if args.ignore_statuses:
                ignore_set = {s.strip().lower() for s in args.ignore_statuses.split(',') if s.strip()}
                if ignore_set:
                    removed = 0
                    for k in list(reading_statuses.keys()):
                        if reading_statuses[k] in ignore_set:
                            del reading_statuses[k]
                            removed += 1
                    if args.debug_status:
                        print(f"[debug-status] Removed {removed} entries due to ignore-statuses filter {sorted(ignore_set)}")

    # Optionally export the final statuses used for mapping (after ignore filters)
    if args.export_statuses:
        try:
            args.export_statuses.write_text(json.dumps(reading_statuses, indent=2), encoding="utf-8")
            print(f"Wrote {len(reading_statuses)} statuses to {args.export_statuses}")
        except Exception as e:
            print(f"Warning: failed to write --export-statuses: {e}")

    # Parse lists mapping
    if args.lists_category_map:
        for part in args.lists_category_map.split(','):
            part = part.strip()
            if not part:
                continue
            if '=' not in part:
                print(f"Warning: ignoring malformed lists map entry '{part}'")
                continue
            k, v = part.split('=', 1)
            try:
                lists_category_map[k.strip()] = int(v)
            except ValueError:
                print(f"Warning: invalid category id in lists map entry '{part}'")
    if args.lists_ignore:
        lists_ignore_set = {s.strip() for s in args.lists_ignore.split(',') if s.strip()}

    # Fetch and list user lists if requested
    if (args.import_lists or args.list_lists) and not session_token:
        # Need a session; try logging in if not already
        md_user = args.md_username or os.environ.get("MANGADEX_USERNAME")
        md_pass = args.md_password or os.environ.get("MANGADEX_PASSWORD")
        if md_user and md_pass:
            session_token, login_err = login_mangadex_verbose(username=md_user, password=md_pass, two_factor=args.md_2fa)
        else:
            print("Cannot fetch lists without MangaDex credentials/session.")
    if args.list_lists and session_token:
        lists = fetch_user_lists(session_token, debug=args.debug_lists)
        if not lists:
            print("No lists found or fetch failed.")
        else:
            print("MangaDex Lists:")
            for it in lists:
                print(f"  {it['id']}: {it['name']}")
        return 0

    # Load list memberships for current ids if requested
    if args.import_lists and session_token:
        lists = fetch_user_lists(session_token, debug=args.debug_lists)
        name_by_id = {it['id']: it['name'] for it in lists}
        for lid, lname in name_by_id.items():
            ids_in = fetch_manga_ids_in_list(session_token, lid, debug=args.debug_lists)
            for mid in ids_in:
                if mid not in ids:
                    # include if not already
                    ids.append(mid)
                lists_membership.setdefault(mid, []).append(lname)

    if args.print_status_summary and args.import_reading_status:
        if reading_statuses:
            counts: Dict[str, int] = {}
            for s in reading_statuses.values():
                counts[s] = counts.get(s, 0) + 1
            mapped = sum(1 for s in reading_statuses.values() if s in status_map)
            coverage = (mapped / len(reading_statuses)) * 100 if reading_statuses else 0.0
            print("Status summary:", ", ".join(f"{k}={v}" for k,v in sorted(counts.items())))
            print(f"Status mapping coverage: {mapped}/{len(reading_statuses)} ({coverage:.1f}%)")
        else:
            print(f"Status summary: NONE ({status_fetch_note or 'no data'})")
        if args.assume_missing_status:
            print(f"Assuming missing status = '{args.assume_missing_status.lower()}'")

    # --- Chapter read marker sync configuration ---
    chapter_sync_conf = {
        'enabled': args.import_read_chapters,
        'dry_run': args.read_chapters_dry_run,
        'delay': args.read_sync_delay,
        'rpm': args.max_read_requests_per_minute,
        'number_fallback': args.read_sync_number_fallback,
        'only_if_ahead': args.read_sync_only_if_ahead,
        'across_sources': args.read_sync_across_sources,
        'xsrc_title_threshold': float(args.cross_source_title_threshold),
        'xsrc_title_strict': bool(args.cross_source_title_strict),
    }
    # Publish chapter sync config globally for helpers
    try:
        global CHAPTER_SYNC_CONF
        CHAPTER_SYNC_CONF = dict(chapter_sync_conf)
    except Exception:
        pass
    # Global debug flag already set earlier for early traces
    if args.import_read_chapters and not session_token:
        print("--import-read-chapters requires a MangaDex session (use --from-follows or --md-login-only). Disabling.")
        chapter_sync_conf['enabled'] = False

    client = SuwayomiClient(
        base_url=args.base_url,
        auth_mode=args.auth_mode,
        username=args.username,
        password=args.password,
        token=args.token,
        verify_tls=not args.insecure,
        request_timeout=args.request_timeout,
    )
    if READ_SYNC_DEBUG:
        try:
            print("[read-debug] client constructed", flush=True)
        except Exception:
            pass

    # If a missing report is requested, ensure the file exists with header now (helps live tailing)
    pre_open_live_file: Optional[Path] = None
    if args.missing_report:
        try:
            outp = args.missing_report
            outp.parent.mkdir(parents=True, exist_ok=True)
            # Create file with header if empty/non-existent
            if not outp.exists() or outp.stat().st_size == 0:
                with outp.open('w', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    w.writerow(["title", "md_id", "markable", "marked", "missing"])
            pre_open_live_file = outp
        except Exception:
            pre_open_live_file = None
    # Publish the report path globally for live appends in helpers
    try:
        global MISSING_REPORT_PATH
        MISSING_REPORT_PATH = pre_open_live_file
    except Exception:
        pass
    if READ_SYNC_DEBUG:
        try:
            print(f"[read-debug] missing_report path set: {bool(MISSING_REPORT_PATH)} -> {str(MISSING_REPORT_PATH) if MISSING_REPORT_PATH else ''}", flush=True)
        except Exception:
            pass
    # Unconditional progress marker to confirm flow
    try:
        print("[read-debug] marker: after missing_report setup", flush=True)
    except Exception:
        pass

    # Continue with reporting/sync path (esp. when --no-add-library)
    if READ_SYNC_DEBUG:
        try:
            print("[read-debug] passed option gates (categories/prune/migrate checks)", flush=True)
        except Exception:
            pass

    # Collect per-id sync stats for optional report
    # Unconditional marker to confirm reach of report/sync phase
    try:
        print("[read-debug] marker: entering report/sync prelude", flush=True)
    except Exception:
        pass
    if READ_SYNC_DEBUG:
        try:
            print("[read-debug] entering report/sync phase", flush=True)
        except Exception:
            pass

    added = 0
    failed = 0
    failures: List[Tuple[str, str]] = []

    # Unconditional marker for no_add_library branch check
    try:
        print(f"[read-debug] marker: no_add_library={bool(args.no_add_library)}", flush=True)
    except Exception:
        pass
    if READ_SYNC_DEBUG:
        try:
            print(f"[read-debug] about to branch on no_add_library={bool(args.no_add_library)}", flush=True)
        except Exception:
            pass

    if args.no_add_library:
        if READ_SYNC_DEBUG:
            try:
                print("[read-debug] --no-add-library path: will skip adds and proceed to reporting+sync", flush=True)
            except Exception:
                pass
        if not args.no_progress:
            print("Skipping add-to-library because --no-add-library is set; proceeding to reporting and read sync only.")
    else:
        # In this trimmed path, we won't implement full add logic; users can run without --no-add-library for full import
        pass

    # Summary prelude
    print(f"Found {len(ids)} MangaDex IDs; Added: {added}, Failed: {failed}")

    # Per-ID reporting and optional cross-source read sync
    if READ_SYNC_DEBUG:
        try:
            print(f"[read-debug] session_token present: {bool(session_token)}; starting reporting+sync if True", flush=True)
        except Exception:
            pass
    if session_token:
        # Resolve MangaDex source id once (for possible per-id stats)
        try:
            md_source_id = find_mangadex_source_id(SuwayomiClient(args.base_url).get_sources())
        except Exception:
            md_source_id = None
        if READ_SYNC_DEBUG:
            try:
                print(f"[read-debug] MangaDex source id: {md_source_id}", flush=True)
            except Exception:
                pass
        for md in ids:
            # Compute and append missing report row if requested
            try:
                stats = compute_md_missing_stats(client, session_token, md)
            except Exception as _e:
                stats = None
            if stats and MISSING_REPORT_PATH:
                try:
                    with MISSING_REPORT_PATH.open('a', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        w.writerow([stats.get('title') or '', md, stats.get('markable') or 0, stats.get('marked') or 0, stats.get('missing') or 0])
                except Exception:
                    pass
            # If user explicitly targets a Suwayomi entry, mark it directly by number using MD progress
            if getattr(args, 'suwayomi_manga_id', None):
                try:
                    target_id = int(args.suwayomi_manga_id)
                except Exception:
                    target_id = None
                if target_id:
                    try:
                        md_max = _compute_md_progress_by_numbers(session_token, md)
                    except Exception:
                        md_max = None
                    if md_max is not None:
                        if READ_SYNC_DEBUG:
                            try:
                                cur = _compute_entry_progress_by_number(client, target_id)
                                print(f"[read-debug] direct apply id={target_id}: md_max={md_max}, current={cur}")
                            except Exception:
                                pass
                        try:
                            _mark_entry_up_to_number(
                                client=client,
                                manga_internal_id=target_id,
                                up_to=md_max,
                                rpm=chapter_sync_conf.get('rpm', 300),
                                dry_run=bool(chapter_sync_conf.get('dry_run')),
                            )
                        except Exception as _e:
                            if READ_SYNC_DEBUG:
                                try:
                                    print(f"[read-debug] direct apply error for {target_id}: {_e}")
                                except Exception:
                                    pass
                        # Move to next md id after direct marking
                        continue
            # Cross-source by-number sync when enabled and requested
            try:
                if chapter_sync_conf.get('enabled') and chapter_sync_conf.get('across_sources') and chapter_sync_conf.get('number_fallback'):
                    sync_cross_source_read_for_md(
                        client=client,
                        manga_md_id=md,
                        session_token=session_token,
                        rpm=chapter_sync_conf.get('rpm', 300),
                        dry_run=bool(chapter_sync_conf.get('dry_run')),
                        only_if_ahead=bool(chapter_sync_conf.get('only_if_ahead')),
                        title_threshold=float(chapter_sync_conf.get('xsrc_title_threshold', 0.6)),
                        title_strict=bool(chapter_sync_conf.get('xsrc_title_strict', False)),
                    )
            except Exception as _e:
                if READ_SYNC_DEBUG:
                    try:
                        print(f"[read-debug] cross-source sync error for {md}: {_e}")
                    except Exception:
                        pass

    # Done
    return 0 if failed == 0 else 2

def _extract_int(v: Any) -> Optional[int]:
    try:
        if isinstance(v, bool) or v is None:
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip():
            return int(v.strip())
    except Exception:
        return None
    return None

def _extract_entry_props(it: Dict[str, Any]) -> Tuple[Optional[int], Optional[str], Optional[int]]:
    """Best-effort extract (internal_id, title, source_id) from a library entry with varied shapes."""
    mid: Optional[int] = None
    title: Optional[str] = None
    sid: Optional[int] = None
    # Direct fields
    mid = mid or _extract_int(it.get('id') or it.get('mangaId') or it.get('manga_id'))
    title = it.get('title') or it.get('name') or it.get('mangaTitle') or it.get('manga_title')
    sid = sid or _extract_int(it.get('sourceId') or it.get('source_id'))
    # Nested common containers
    m = it.get('manga') or {}
    if isinstance(m, dict):
        mid = mid or _extract_int(m.get('id'))
        title = title or m.get('title') or m.get('name')
        sid = sid or _extract_int(m.get('sourceId') or m.get('source_id'))
        src = m.get('source') or {}
        if isinstance(src, dict):
            sid = sid or _extract_int(src.get('id') or src.get('sourceId'))
    src2 = it.get('source') or {}
    if isinstance(src2, dict):
        sid = sid or _extract_int(src2.get('id') or src2.get('sourceId'))
    return mid, title, sid

    if args.list_categories:
        try:
            cat_endpoints = [
                "/api/v1/category/list",  # common
                "/api/v1/category",       # alternative
                "/api/v1/categories",     # plural variant
            ]
            last_err: Optional[str] = None
            for ep in cat_endpoints:
                r = client.request("GET", ep)
                if r.status_code == 200:
                    try:
                        data = r.json()
                    except Exception as je:
                        last_err = f"Invalid JSON from {ep}: {je}"
                        continue
                    # Some APIs wrap list inside a key
                    if isinstance(data, dict):
                        for k in ("data", "categories", "list"):
                            if k in data and isinstance(data[k], list):
                                data = data[k]
                                break
                    if not isinstance(data, list):
                        last_err = f"Unexpected format from {ep} (type {type(data)})"
                        continue
                    print("Available Categories (from", ep, "):")
                    for cat in data:
                        if not isinstance(cat, dict):
                            continue
                        cid = cat.get('id') or cat.get('categoryId')
                        name = cat.get('name') or cat.get('label') or ''
                        print(f"  {cid}: {name}")
                    return 0
                else:
                    last_err = f"HTTP {r.status_code} {truncate_text(r.text,120)} at {ep}"
            print(f"Failed to fetch categories. Tried endpoints: {', '.join(cat_endpoints)}")
            if last_err:
                print("Last error:", last_err)
            return 4
        except Exception as ce:
            print(f"Error retrieving categories: {ce}")
            return 4

    # Hard prune mode: remove zero/low-chapter duplicates without searching
    if args.prune_zero_duplicates:
        client_auth = SuwayomiClient(
            base_url=args.base_url,
            auth_mode=args.auth_mode,
            username=args.username,
            password=args.password,
            token=args.token,
            verify_tls=not args.insecure,
            request_timeout=args.request_timeout,
        )
        client_auth._auth()
        library = client_auth.get_library()
        if not library:
            print("Could not fetch library or library is empty.")
            return 5
        # Normalize titles
        def norm(s: str) -> str:
            s = (s or '').lower()
            s = re.sub(r"[\(\[\{].*?[\)\]\}]", "", s)
            s = re.sub(r"[^a-z0-9\s]", "", s)
            return ' '.join(s.split())
        # Group entries by normalized title
        groups: Dict[str, list] = {}
        for e in library:
            title = str(e.get('title') or e.get('name') or '').strip()
            if args.prune_filter_title and args.prune_filter_title.lower() not in title.lower():
                continue
            nid = norm(title)
            groups.setdefault(nid, []).append(e)
        removed = 0
        kept = 0
        threshold = max(0, int(args.prune_threshold_chapters))
        for nid, items in groups.items():
            # Get counts
            with_counts = []
            for e in items:
                mid = e.get('id') or e.get('mangaId') or e.get('manga_id')
                try:
                    mid_int = int(mid)
                except Exception:
                    continue
                try:
                    cnt = client_auth.get_manga_chapters_count(mid_int)
                except Exception:
                    cnt = 0
                with_counts.append((mid_int, cnt, e))
            # Decide keeper(s): any with count >= threshold
            keepers = [t for t in with_counts if (t[1] or 0) >= threshold]
            if not keepers:
                # Nothing to prune in this group
                kept += len(with_counts)
                continue
            # Prefer the one with most chapters; keep ties
            max_cnt = max(t[1] or 0 for t in keepers)
            keep_set = {t[0] for t in keepers if (t[1] or 0) == max_cnt}
            for mid_int, cnt, e in with_counts:
                title = str(e.get('title') or e.get('name') or '').strip()
                if mid_int in keep_set:
                    kept += 1
                    if not args.no_progress:
                        print(f"KEEP '{title}' (chapters={cnt})")
                else:
                    if args.dry_run:
                        removed += 1
                        if not args.no_progress:
                            print(f"PRUNE (dry-run) '{title}' (chapters={cnt})")
                    else:
                        ok = client_auth.remove_from_library(mid_int)
                        removed += 1 if ok else 0
                        if not args.no_progress:
                            print(f"PRUNE '{title}' (chapters={cnt}) -> {'OK' if ok else 'FAIL'}")
        print(f"Prune summary: kept={kept} removed={removed}")
        return 0

    # List library entries (id, source, title) and exit
    if args.list_library_titles:
        try:
            srcs = client.get_sources()
            src_name_by_id = {}
            for s in srcs:
                try:
                    sid = s.get('id') or s.get('sourceId')
                    name = s.get('name') or s.get('sourceName') or s.get('lang') or ''
                    if sid is not None:
                        src_name_by_id[int(sid)] = str(name)
                except Exception:
                    pass
        except Exception:
            src_name_by_id = {}
        lib = client.get_library_graphql() or client.get_library() or []
        q = (args.filter_title or '').lower().strip()
        print("Suwayomi library entries:")
        shown = 0
        for it in lib:
            try:
                mid, title, sid = _extract_entry_props(it)
                if title is None:
                    continue
                if q and q not in title.lower():
                    continue
                src_name = src_name_by_id.get(sid or -1, str(sid) if sid is not None else "?")
                print(f"  id={mid}  source={src_name}  title={title}")
                shown += 1
            except Exception:
                continue
        print(f"Total shown: {shown}")
        return 0

    # Prune non-preferred language entries when a preferred-language entry exists for the same title
    if args.prune_nonpreferred_langs:
        if not args.preferred_langs:
            print("--prune-nonpreferred-langs requires --preferred-langs")
            return 2
        pref_langs = {s.strip().lower().replace('_','-') for s in args.preferred_langs.split(',') if s.strip()}
        client_auth = SuwayomiClient(
            base_url=args.base_url,
            auth_mode=args.auth_mode,
            username=args.username,
            password=args.password,
            token=args.token,
            verify_tls=not args.insecure,
            request_timeout=args.request_timeout,
        )
        client_auth._auth()
        library = client_auth.get_library()
        if not library:
            print("Could not fetch library or library is empty.")
            return 5
        def norm(s: str) -> str:
            s = (s or '').lower()
            s = re.sub(r"[\(\[\{].*?[\)\]\}]", "", s)
            s = re.sub(r"[^a-z0-9\s]", "", s)
            return ' '.join(s.split())
        groups: Dict[str, list] = {}
        for e in library:
            title = str(e.get('title') or e.get('name') or '').strip()
            if args.prune_filter_title and args.prune_filter_title.lower() not in title.lower():
                continue
            nid = norm(title)
            groups.setdefault(nid, []).append(e)
        removed = 0
        kept = 0
        min_pref = max(1, int(args.prune_lang_threshold))
        for nid, items in groups.items():
            scored: List[Tuple[int, int, int, Dict[str, Any]]] = []  # (pref_count, total_count, id, entry)
            for e in items:
                mid = e.get('id') or e.get('mangaId') or e.get('manga_id')
                try:
                    mid_int = int(mid)
                except Exception:
                    continue
                try:
                    pref_count = client_auth.get_manga_chapters_count_by_lang(mid_int, pref_langs, canonical=False)
                except Exception:
                    pref_count = 0
                try:
                    total_count = client_auth.get_manga_chapters_count(mid_int)
                except Exception:
                    total_count = 0
                scored.append((pref_count, total_count, mid_int, e))
            # Keeper set: entries that meet preferred minimum; if none, keep the one with highest total
            keep_set: Set[int] = set()
            best_pref = max((p for (p, _, _, _) in scored), default=0)
            if best_pref >= min_pref:
                # Keep all that achieve the max preferred count (avoid deleting the top preferred variant if split)
                keep_set = {mid for (p, _, mid, _) in ((p, t, m, e) for (p, t, m, e) in scored) if p == best_pref}
            else:
                # No preferred-language chapters found; optionally keep only the entry with most total
                if args.prune_lang_fallback_keep_most and scored:
                    max_total = max((t for (_, t, _, _) in scored), default=0)
                    keep_set = {mid for (_, t, mid, _) in scored if t == max_total}
                else:
                    # Nothing to prune in this group
                    keep_set = {mid for (_, _, mid, _) in scored}
            for pref_count, total_count, mid_int, e in scored:
                title = str(e.get('title') or e.get('name') or '').strip()
                if mid_int in keep_set:
                    kept += 1
                    if not args.no_progress:
                        print(f"KEEP '{title}' (pref={pref_count}, total={total_count})")
                else:
                    if args.dry_run:
                        removed += 1
                        if not args.no_progress:
                            print(f"PRUNE (dry-run) '{title}' (pref={pref_count}, total={total_count})")
                    else:
                        ok = client_auth.remove_from_library(mid_int)
                        removed += 1 if ok else 0
                        if not args.no_progress:
                            print(f"PRUNE '{title}' (pref={pref_count}, total={total_count}) -> {'OK' if ok else 'FAIL'}")
        print(f"Prune by language summary: kept={kept} removed={removed}")
        return 0

    # Standalone library migration flow (no MangaDex needed)
    if args.migrate_library:
        client_auth = SuwayomiClient(
            base_url=args.base_url,
            auth_mode=args.auth_mode,
            username=args.username,
            password=args.password,
            token=args.token,
            verify_tls=not args.insecure,
            request_timeout=args.request_timeout,
        )
        client_auth._auth()
        # Attach debug flag
        setattr(client_auth, 'debug_library', bool(args.debug_library))
        library = client_auth.get_library()
        if not library:
            print("Could not fetch library or library is empty. Try --debug-library to see endpoint attempts.")
            return 5
        if not args.no_progress:
            print(f"Library entries discovered: {len(library)}")
        # Resolve category include/exclude filters
        include_cat_tokens = [s.strip() for s in (args.migrate_include_categories.split(',') if args.migrate_include_categories else []) if s.strip()]
        exclude_cat_tokens = [s.strip() for s in (args.migrate_exclude_categories.split(',') if args.migrate_exclude_categories else []) if s.strip()]
        cat_name_by_id: Dict[int, str] = {}
        cat_id_by_name: Dict[str, int] = {}
        membership: Dict[int, Set[int]] = {}
        if include_cat_tokens or exclude_cat_tokens:
            # Fetch categories and build membership via GraphQL
            try:
                cats_res = client_auth.graphql("query { categories { nodes { id name } edges { node { id name } } } }")
            except Exception:
                cats_res = None
            cat_ids: List[int] = []
            if isinstance(cats_res, dict) and isinstance(cats_res.get('data'), dict):
                root = cats_res['data'].get('categories') or {}
                nodes = []
                if isinstance(root, dict):
                    nodes += [n for n in (root.get('nodes') or []) if isinstance(n, dict)]
                    nodes += [e.get('node') for e in (root.get('edges') or []) if isinstance(e, dict) and isinstance(e.get('node'), dict)]
                for n in nodes:
                    try:
                        cid = int(n.get('id'))
                        nm = str(n.get('name') or '')
                        cat_ids.append(cid)
                        cat_name_by_id[cid] = nm
                        if nm:
                            cat_id_by_name[nm.strip().lower()] = cid
                    except Exception:
                        pass
            # Build membership per category with basic pagination attempts
            for cid in cat_ids:
                # Use a few common pagination shapes
                arg_shapes = [("page", "size"), ("page", "limit"), ("pageNum", "pageSize"), ("offset", "limit")]
                page = 1
                empty_pages = 0
                while page <= 200:
                    if arg_shapes[0][0] == "offset":
                        vars = {"cid": int(cid), "offset": (page-1)*200, "limit": 200}
                        q = "query($cid:Int,$offset:Int,$limit:Int){ category(id:$cid){ mangas(offset:$offset, limit:$limit){ nodes { id } edges { node { id } } } } }"
                    elif arg_shapes[0][0] == "pageNum":
                        vars = {"cid": int(cid), "pageNum": page, "pageSize": 200}
                        q = "query($cid:Int,$pageNum:Int,$pageSize:Int){ category(id:$cid){ mangas(pageNum:$pageNum, pageSize:$pageSize){ nodes { id } edges { node { id } } } } }"
                    else:
                        vars = {"cid": int(cid), "page": page, "size": 200}
                        q = "query($cid:Int,$page:Int,$size:Int){ category(id:$cid){ mangas(page:$page, size:$size){ nodes { id } edges { node { id } } } } }"
                    res = client_auth.graphql(q, variables=vars)
                    ids_this_page: List[int] = []
                    try:
                        nodes = (((res or {}).get('data') or {}).get('category') or {}).get('mangas') or {}
                        raw = []
                        if isinstance(nodes, dict):
                            raw += [n for n in (nodes.get('nodes') or []) if isinstance(n, dict)]
                            raw += [e.get('node') for e in (nodes.get('edges') or []) if isinstance(e, dict) and isinstance(e.get('node'), dict)]
                        for it in raw:
                            mid = it.get('id')
                            if mid is None:
                                continue
                            try:
                                mid_int = int(mid)
                                membership.setdefault(mid_int, set()).add(int(cid))
                                ids_this_page.append(mid_int)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    if not ids_this_page:
                        empty_pages += 1
                        if empty_pages >= 2:
                            break
                    else:
                        empty_pages = 0
                    page += 1
            # Build include/exclude sets of IDs
            def tokens_to_ids(tokens: List[str]) -> Set[int]:
                out: Set[int] = set()
                for t in tokens:
                    tl = t.strip().lower()
                    if not tl:
                        continue
                    if tl.isdigit():
                        out.add(int(tl))
                    elif tl in cat_id_by_name:
                        out.add(cat_id_by_name[tl])
                return out
            include_cat_ids = tokens_to_ids(include_cat_tokens)
            exclude_cat_ids = tokens_to_ids(exclude_cat_tokens)
        # Build a quick lookup of existing library internal IDs for duplicate detection
        lib_ids: Set[int] = set()
        for _e in library:
            try:
                _idv = int(_e.get('id') or _e.get('mangaId') or _e.get('manga_id'))
                lib_ids.add(_idv)
            except Exception:
                pass
        # Prepare preferred sources
        pref_str = args.migrate_sources or args.rehoming_sources or ""
        pref = [s.strip().lower() for s in pref_str.split(',') if s.strip()]
        # Find all sources and sort by preference
        sources = client_auth.get_sources()
        # Exclude unwanted sources by name/apkName
        exclude_frags = [s.strip().lower() for s in (args.exclude_sources.split(',') if args.exclude_sources else []) if s.strip()]
        if exclude_frags:
            def not_excluded(src: Dict[str, Any]) -> bool:
                nm = (src.get('name') or src.get('apkName') or '').lower()
                return all(frag not in nm for frag in exclude_frags)
            sources = [s for s in sources if not_excluded(s)]
        def score(src: Dict[str, Any]) -> int:
            nm = (src.get('name') or src.get('apkName') or '').lower()
            for i, frag in enumerate(pref):
                if frag and frag in nm:
                    return i
            return 9999
        # If requested, restrict to preferred list only
        if args.migrate_preferred_only and pref:
            sources = [s for s in sources if any(f in (s.get('name') or s.get('apkName') or '').lower() for f in pref)]
        sorted_sources = sorted(sources, key=score)
        # Helper: normalize site key from name/apkName
        def site_key(src: Dict[str, Any]) -> str:
            nm = (src.get('name') or src.get('apkName') or '').lower()
            return re.sub(r"[^a-z]+", "", nm)[:32]
        # Helper: generate conservative title variants
        def title_variants(full: str) -> List[str]:
            vars: List[str] = []
            def add(s: str):
                s = ' '.join(s.split())
                if s and s not in vars:
                    vars.append(s)
            add(full)
            # Strip after common separators
            m = re.split(r"\s*[~:\-–—]\s*", full)
            if m:
                add(m[0])
            # Remove bracketed segments
            add(re.sub(r"[\(\[\{].*?[\)\]\}]", "", full))
            # Remove punctuation
            add(re.sub(r"[^0-9A-Za-z\s]", "", full))
            # Truncate
            if len(full) > 64:
                add(full[:64])
            return vars[:4]
        migrated = 0
        skipped = 0
        failed = 0
        threshold = max(0, args.migrate_threshold_chapters)
        filter_sub = (args.migrate_filter_title or "").strip().lower()
        # Parse preferred languages once
        pref_langs: Set[str] = set()
        if args.preferred_langs:
            pref_langs = {s.strip().lower().replace('_','-') for s in args.preferred_langs.split(',') if s.strip()}
        for idx, entry in enumerate(library, 1):
            mid = entry.get('id') or entry.get('mangaId') or entry.get('manga_id')
            try:
                mid_int = int(mid)
            except Exception:
                continue
            # Apply category filters if provided
            if include_cat_tokens or exclude_cat_tokens:
                cats_for = membership.get(mid_int, set())
                if include_cat_tokens and not (cats_for & include_cat_ids):
                    if args.debug_library and not args.no_progress:
                        print(f"[{idx}] SKIP by include-categories")
                    continue
                if exclude_cat_tokens and (cats_for & exclude_cat_ids):
                    if args.debug_library and not args.no_progress:
                        print(f"[{idx}] SKIP by exclude-categories")
                    continue
            title = str(entry.get('title') or entry.get('name') or '').strip()
            ch_count = client_auth.get_manga_chapters_count(mid_int)
            if ch_count >= threshold:
                skipped += 1
                if not args.no_progress:
                    reason = f">={threshold} chapters" if ch_count is not None else "unknown chapter count"
                    print(f"[{idx}] SKIP '{title or mid_int}' ({reason})")
                continue
            if not title:
                # Try fetching details for title
                det = client_auth.get_manga_details(mid_int)
                title = str(det.get('title') or det.get('name') or '').strip()
            if not title:
                failed += 1
                if not args.no_progress:
                    print(f"[{idx}] MIGRATE skip (no title)")
                continue
            if not args.no_progress:
                print(f"[{idx}] MIGRATE '{title}' (chapters={ch_count})")
            # If filter requested, enforce title contains substring
            if filter_sub and filter_sub not in (title or '').lower():
                if args.debug_library and not args.no_progress:
                    print(f"[{idx}]   filter-title skip (no match)")
                continue
            added_any = False
            start_ts = time.time()
            per_site_counts: Dict[str, int] = {}
            cap_announced: Dict[str, bool] = {}
            # If global best is requested, accumulate candidates across sites first
            global_best: Optional[Tuple[int, int, Dict[str, Any]]] = None  # (score,alt_id,source)
            global_raw_max: Optional[Tuple[int, int, Dict[str, Any]]] = None  # (raw_count,alt_id,source)
            # Parse quality-preferred sources
            prefer_frags = [s.strip().lower() for s in (args.prefer_sources.split(',') if args.prefer_sources else []) if s.strip()]
            for src in sorted_sources:
                nm = (src.get('name') or src.get('apkName') or '').lower()
                try:
                    sid = int(src.get('id'))
                except Exception:
                    continue
                skey = site_key(src)
                cnt = per_site_counts.get(skey, 0)
                if args.migrate_max_sources_per_site and cnt >= max(1, int(args.migrate_max_sources_per_site)):
                    if args.debug_library and not args.no_progress and not cap_announced.get(skey):
                        print(f"[{idx}]   skip remaining '{nm}' sources (cap {args.migrate_max_sources_per_site})")
                        cap_announced[skey] = True
                    continue
                if args.migrate_timeout and (time.time() - start_ts) > args.migrate_timeout:
                    if not args.no_progress:
                        print(f"[{idx}] MIGRATE timeout after {args.migrate_timeout:.0f}s; giving up on this title")
                    break
                got_items: List[Dict[str, Any]] = []
                # Try small set of title variants for this source
                for qtitle in title_variants(title):
                    try:
                        if args.debug_library and not args.no_progress:
                            print(f"[{idx}]   search '{qtitle}' in source id={sid} ({nm})")
                        res = client_auth.search_source(sid, qtitle, page=1)
                    except Exception as e:
                        if args.debug_library and not args.no_progress:
                            print(f"[{idx}]   search error on source id={sid}: {e}")
                        res = None
                    items = SuwayomiClient.normalize_search_items(res)
                    if items:
                        got_items = items
                        break
                    if args.migrate_try_second_page:
                        try:
                            res2 = client_auth.search_source(sid, qtitle, page=2)
                        except Exception:
                            res2 = None
                        items2 = SuwayomiClient.normalize_search_items(res2)
                        if items2:
                            got_items = items2
                            break
                if not got_items:
                    if args.debug_library and not args.no_progress:
                        print(f"[{idx}]   no results")
                    per_site_counts[skey] = cnt + 1
                    continue
                # Score candidates
                alt_id = None
                if args.best_source:
                    best_count = -1
                    limit = max(1, int(args.best_source_candidates))
                    for cand in got_items[:limit]:
                        cid = SuwayomiClient.extract_manga_id(cand)
                        if cid is None:
                            continue
                        ccount = 0
                        try:
                            if pref_langs:
                                if args.best_source_canonical:
                                    ccount = client_auth.get_manga_chapters_count_by_lang(cid, pref_langs, canonical=True)
                                else:
                                    ccount = client_auth.get_manga_chapters_count_by_lang(cid, pref_langs, canonical=False)
                                if ccount == 0 and args.lang_fallback:
                                    # fallback to non-filtered count
                                    ccount = client_auth.get_manga_chapters_canonical_count(cid) if args.best_source_canonical else client_auth.get_manga_chapters_count(cid)
                            else:
                                ccount = client_auth.get_manga_chapters_canonical_count(cid) if args.best_source_canonical else client_auth.get_manga_chapters_count(cid)
                            # Apply quality boost for preferred sources
                            if prefer_frags and any(f in nm for f in prefer_frags):
                                ccount += int(args.prefer_boost)
                            # Track raw (unboosted, non-language-fallback) max for optional keep-both
                            try:
                                # Raw = total chapters (canonical if requested), no language filter, no source boost
                                raw = client_auth.get_manga_chapters_canonical_count(cid) if args.best_source_canonical else client_auth.get_manga_chapters_count(cid)
                            except Exception:
                                raw = 0
                        except Exception:
                            ccount = 0
                            raw = 0
                        if args.debug_library and not args.no_progress:
                            ctitle = str(cand.get('title') or cand.get('name') or '')
                            print(f"[{idx}]     cand id={cid} site='{nm}' score={ccount} title='{ctitle[:60]}'")
                        if ccount >= max(0, int(args.min_chapters_per_alt)) and ccount > best_count:
                            best_count = ccount
                            alt_id = cid
                            if not args.best_source_global:
                                # non-global: choose per-site immediately
                                pass
                        # Track global raw max by raw count
                        if args.best_source_global and (global_raw_max is None or raw > global_raw_max[0]):
                            global_raw_max = (raw, cid, src)
                    if args.best_source_global and alt_id is not None:
                        score_val = best_count
                        if global_best is None or score_val > global_best[0]:
                            global_best = (score_val, alt_id, src)
                        per_site_counts[skey] = cnt + 1
                        continue
                else:
                    alt_id = SuwayomiClient.extract_manga_id(got_items[0])
                # Fallback: if no candidate met min, take first if allowed and min=0 (only when not global)
                if not args.best_source_global and alt_id is None and int(args.min_chapters_per_alt) <= 0 and got_items:
                    alt_id = SuwayomiClient.extract_manga_id(got_items[0])
                if args.best_source_global:
                    # In global mode we don't add yet; continue scanning other sources
                    per_site_counts[skey] = cnt + 1
                    continue
                if alt_id is None:
                    if args.debug_library and not args.no_progress:
                        print(f"[{idx}]   unexpected search payload shape")
                    per_site_counts[skey] = cnt + 1
                    continue
                # If the chosen alt already exists and user wants to remove the original instead of duplicating
                if not args.dry_run and args.migrate_remove_if_duplicate and alt_id and alt_id in lib_ids and alt_id != mid_int:
                    try:
                        alt_ch = client_auth.get_manga_chapters_count(alt_id)
                    except Exception:
                        alt_ch = None
                    if (alt_ch or 0) > 0:
                        try:
                            rm_ok = client_auth.remove_from_library(mid_int)
                        except Exception:
                            rm_ok = False
                        if not args.no_progress:
                            print(f"[{idx}] DUPLICATE already in library with chapters; REMOVE original -> {'OK' if rm_ok else 'FAIL'}")
                        if rm_ok:
                            migrated += 1
                            added_any = True
                            break
                if args.dry_run:
                    added_any = True
                    if not args.no_progress:
                        print(f"[{idx}] MIGRATE '{title}' via '{src.get('name')}' -> OK (dry-run)")
                else:
                    try:
                        added_any = client_auth.add_to_library(alt_id)
                    except Exception as e:
                        if args.debug_library and not args.no_progress:
                            print(f"[{idx}]   add_to_library error for id={alt_id}: {e}")
                        added_any = False
                    if not args.no_progress:
                        print(f"[{idx}] MIGRATE '{title}' via '{src.get('name')}' -> {'OK' if added_any else 'FAIL'}")
                per_site_counts[skey] = cnt + 1
                if added_any and args.migrate_remove and not args.dry_run:
                    try:
                        rm_ok = client_auth.remove_from_library(mid_int)
                        if not args.no_progress:
                            print(f"[{idx}] REMOVE original -> {'OK' if rm_ok else 'FAIL'}")
                    except Exception:
                        pass
                if added_any:
                    migrated += 1
                    break
            # If global-best was requested, add the single winner now
            if not added_any and args.best_source_global and global_best is not None:
                best_score, best_alt_id, src_best = global_best
                # If the best alternative already exists and user wants to remove the original instead of duplicating
                if not args.dry_run and args.migrate_remove_if_duplicate and best_alt_id and best_alt_id in lib_ids and best_alt_id != mid_int:
                    try:
                        best_ch = client_auth.get_manga_chapters_count(best_alt_id)
                    except Exception:
                        best_ch = None
                    if (best_ch or 0) > 0:
                        try:
                            rm_ok = client_auth.remove_from_library(mid_int)
                        except Exception:
                            rm_ok = False
                        if not args.no_progress:
                            print(f"[{idx}] DUPLICATE already in library with chapters; REMOVE original -> {'OK' if rm_ok else 'FAIL'}")
                        if rm_ok:
                            migrated += 1
                            added_any = True
                if added_any:
                    pass
                elif args.dry_run:
                    added_any = True
                    if not args.no_progress:
                        print(f"[{idx}] MIGRATE '{title}' via '{src_best.get('name')}' (global-best) -> OK (dry-run)")
                else:
                    try:
                        added_any = client_auth.add_to_library(best_alt_id)
                    except Exception as e:
                        if args.debug_library and not args.no_progress:
                            print(f"[{idx}]   add_to_library error for id={best_alt_id}: {e}")
                        added_any = False
                    if not args.no_progress:
                        print(f"[{idx}] MIGRATE '{title}' via '{src_best.get('name')}' (global-best) -> {'OK' if added_any else 'FAIL'}")
                if added_any and args.migrate_remove and not args.dry_run:
                    try:
                        rm_ok = client_auth.remove_from_library(mid_int)
                        if not args.no_progress:
                            print(f"[{idx}] REMOVE original -> {'OK' if rm_ok else 'FAIL'}")
                    except Exception:
                        pass
                if added_any:
                    migrated += 1
                    # Optionally also add the raw-max candidate for completeness if different
                    if args.migrate_keep_both and global_raw_max is not None:
                        raw_count, raw_alt_id, raw_src = global_raw_max
                        if raw_alt_id and raw_alt_id != best_alt_id:
                            # If user requires the second candidate to also have preferred-language chapters, enforce it
                            if args.keep_both_min_preferred > 0:
                                try:
                                    pref_cnt_second = client_auth.get_manga_chapters_count_by_lang(raw_alt_id, pref_langs, canonical=args.best_source_canonical) if pref_langs else 0
                                except Exception:
                                    pref_cnt_second = 0
                                if pref_cnt_second < int(args.keep_both_min_preferred):
                                    if args.debug_library and not args.no_progress:
                                        print(f"[{idx}]   skip raw-max keep (preferred-lang chapters {pref_cnt_second} < {args.keep_both_min_preferred})")
                                    return migrated  # skip second add
                            if args.dry_run:
                                if not args.no_progress:
                                    print(f"[{idx}] ALSO KEEP '{title}' via '{raw_src.get('name')}' (raw-max) -> OK (dry-run)")
                            else:
                                try:
                                    ok2 = client_auth.add_to_library(raw_alt_id)
                                except Exception as e:
                                    if args.debug_library and not args.no_progress:
                                        print(f"[{idx}]   add_to_library error for id={raw_alt_id}: {e}")
                                    ok2 = False
                                if not args.no_progress:
                                    print(f"[{idx}] ALSO KEEP '{title}' via '{raw_src.get('name')}' (raw-max) -> {'OK' if ok2 else 'FAIL'}")
            if not added_any:
                failed += 1
            # Optional light throttle between items if --throttle set
            if args.throttle:
                time.sleep(max(0.0, float(args.throttle)))
        print(f"Migrate summary: migrated={migrated} skipped={skipped} failed={failed}")
        return 0 if failed == 0 else 6

    # After option gates, continue
    if READ_SYNC_DEBUG:
        try:
            print("[read-debug] passed option gates (categories/prune/migrate checks)", flush=True)
        except Exception:
            pass
    # Collect per-id sync stats for optional report
    if READ_SYNC_DEBUG:
        try:
            print("[read-debug] entering report/sync phase", flush=True)
        except Exception:
            pass
    sync_stats: List[Dict[str, Any]] = []

    if READ_SYNC_DEBUG:
        try:
            print(f"[read-debug] about to branch on no_add_library={bool(args.no_add_library)}", flush=True)
        except Exception:
            pass
    if args.no_add_library:
        added, failed, failures = (0, 0, [])
        if READ_SYNC_DEBUG:
            try:
                print("[read-debug] --no-add-library path: will skip adds and proceed to reporting+sync")
            except Exception:
                pass
        if not args.no_progress:
            print("Skipping add-to-library because --no-add-library is set; proceeding to reporting and read sync only.")
    else:
        added, failed, failures = import_ids(
            client,
            ids,
            dry_run=args.dry_run,
            use_title_fallback=not args.no_title_fallback,
            show_progress=not args.no_progress,
            throttle=args.throttle,
            category_id=args.category_id,
            reading_statuses=reading_statuses,
            status_category_map=status_map,
            status_default_category=args.status_default_category,
            session_token=session_token if args.from_follows else None,
            chapter_sync_conf=chapter_sync_conf,
        status_map_debug=args.status_map_debug,
        assume_missing_status=(args.assume_missing_status.lower() if args.assume_missing_status else None),
        lists_membership=lists_membership if args.import_lists else None,
        lists_category_map=lists_category_map if args.import_lists else None,
        lists_ignore_set=lists_ignore_set if args.import_lists else None,
        rehome_conf={
            'enabled': args.rehoming_enabled,
            'sources': [s.strip() for s in (args.rehoming_sources.split(',') if args.rehoming_sources else []) if s.strip()],
            'skip_if_ge': args.rehoming_skip_if_chapters_ge,
            'remove_md': args.rehoming_remove_mangadex,
            'exclude_frags': [s.strip().lower() for s in (args.exclude_sources.split(',') if args.exclude_sources else []) if s.strip()],
            'best_source': bool(args.best_source),
            'best_candidates': int(args.best_source_candidates),
            'min_chapters_per_alt': int(args.min_chapters_per_alt),
            'canonical': bool(args.best_source_canonical),
            'title_threshold': float(args.migrate_title_threshold),
            'title_strict': bool(args.migrate_title_strict),
        } if args.rehoming_enabled else None,
        )

    print(f"Found {len(ids)} MangaDex IDs; Added: {added}, Failed: {failed}")
    if failures:
        print("Failures:")
        for md, reason in failures[:50]:  # cap output
            print(f"  {md}: {reason}")
        if len(failures) > 50:
            print(f"  ... and {len(failures) - 50} more")

    # Per-ID reporting and optional cross-source read sync (append rows atomically per write)
    if READ_SYNC_DEBUG:
        try:
            print(f"[read-debug] session_token present: {bool(session_token)}; starting reporting+sync if True")
        except Exception:
            pass
    if session_token:
        # Resolve MangaDex source id once for UUID-based marking against existing entries
        md_source_id: Optional[int] = None
        try:
            srcs = client.get_sources()
            md_source_id = find_mangadex_source_id(srcs)
        except Exception:
            md_source_id = None
        if READ_SYNC_DEBUG:
            print(f"[read-debug] MangaDex source id: {md_source_id}")
        outp = args.missing_report if args.missing_report else None
        if outp:
            try:
                outp.parent.mkdir(parents=True, exist_ok=True)
                # Ensure header exists (pre-created above; safeguard here too)
                if not outp.exists() or outp.stat().st_size == 0:
                    with outp.open('w', newline='', encoding='utf-8') as f:
                        csv.writer(f).writerow(["title", "md_id", "markable", "marked", "missing"])
            except Exception:
                pass

        appended_count = 0
        written_ids: Set[str] = set()

        def _append_row(row: Dict[str, Any]):
            m = row.get('missing')
            is_missing = (isinstance(m, int) and m > 0) or (isinstance(m, str) and m.strip().lower() == 'unknown')
            if not is_missing:
                return
            mdv = str(row.get('md_id','') or '')
            if mdv in written_ids:
                return
            written_ids.add(mdv)
            sync_stats.append(row)
            if outp:
                try:
                    with outp.open('a', newline='', encoding='utf-8') as f:
                        w = csv.writer(f)
                        w.writerow([row.get('title',''), row.get('md_id',''), row.get('markable',''), row.get('marked',''), row.get('missing','')])
                    # Heartbeat output to reassure progress
                    nonlocal appended_count
                    appended_count += 1
                    if not args.no_progress:
                        print(f"[report] appended {appended_count}: {row.get('md_id','')} missing={row.get('missing','')}")
                except Exception:
                    # Ignore file write errors (e.g., file locked); continue processing
                    pass

        for md in ids:
            if not MD_ID_RE.match(md):
                continue
            try:
                # If requested, mark reads on an explicitly provided Suwayomi manga id first
                if args.import_read_chapters and args.no_add_library and getattr(args, 'suwayomi_manga_id', None):
                    forced_id = int(args.suwayomi_manga_id)
                    if READ_SYNC_DEBUG:
                        print(f"[read-debug] Forcing read-sync onto Suwayomi manga id={forced_id} for MD {md}")
                    if chapter_sync_conf.get('delay', 0) and chapter_sync_conf.get('delay', 0) > 0:
                        time.sleep(float(chapter_sync_conf.get('delay', 0)))
                    sync_read_chapters_for_manga(
                        client,
                        session_token,
                        md,
                        forced_id,
                        dry_run=bool(chapter_sync_conf.get('dry_run')),
                        rpm=int(chapter_sync_conf.get('rpm', 300)),
                        show_progress=not args.no_progress,
                        prefix=f"[read-sync] ",
                    )
                # Otherwise, mark reads on existing MangaDex entries without adding new ones
                elif args.import_read_chapters and args.no_add_library and md_source_id is not None:
                    try:
                        internal_id = search_by_mangadex_id(client, md_source_id, md)
                        if READ_SYNC_DEBUG:
                            print(f"[read-debug] UUID lookup for {md}: internal_id={internal_id}")
                        if internal_id:
                            if chapter_sync_conf.get('delay', 0) and chapter_sync_conf.get('delay', 0) > 0:
                                time.sleep(float(chapter_sync_conf.get('delay', 0)))
                            sync_read_chapters_for_manga(
                                client,
                                session_token,
                                md,
                                internal_id,
                                dry_run=bool(chapter_sync_conf.get('dry_run')),
                                rpm=int(chapter_sync_conf.get('rpm', 300)),
                                show_progress=not args.no_progress,
                                prefix=f"[read-sync] ",
                            )
                        else:
                            # Fallback: find MD entry by title in library (same source) and mark UUIDs on it
                            title = fetch_title_from_mangadex(md) or ""
                            if READ_SYNC_DEBUG:
                                print(f"[read-debug] Fallback by title for {md}: '{truncate_text(title, 120)}'")
                            if title:
                                norm_target = _norm_title_for_match(title)
                                lib = client.get_library_graphql() or client.get_library() or []
                                chosen_id: Optional[int] = None
                                for it in lib:
                                    mid2, t2, sid2 = _extract_entry_props(it)
                                    if sid2 is None or sid2 != md_source_id:
                                        continue
                                    if not t2:
                                        continue
                                    if _is_title_match(t2, title, threshold=0.6, strict_exact=False):
                                        chosen_id = mid2
                                        if READ_SYNC_DEBUG:
                                            print(f"[read-debug] Matched library MD entry by title: id={mid2} title='{truncate_text(t2, 80)}'")
                                        break
                                if chosen_id:
                                    if chapter_sync_conf.get('delay', 0) and chapter_sync_conf.get('delay', 0) > 0:
                                        time.sleep(float(chapter_sync_conf.get('delay', 0)))
                                    sync_read_chapters_for_manga(
                                        client,
                                        session_token,
                                        md,
                                        chosen_id,
                                        dry_run=bool(chapter_sync_conf.get('dry_run')),
                                        rpm=int(chapter_sync_conf.get('rpm', 300)),
                                        show_progress=not args.no_progress,
                                        prefix=f"[read-sync] ",
                                    )
                                else:
                                    if READ_SYNC_DEBUG:
                                        print(f"[read-debug] No MD-source library match by title for {md}; will rely on cross-source fallback if enabled.")
                    except Exception:
                        pass
                # Compute MD vs Suwayomi (MD source) stats first
                st = compute_md_missing_stats(client, session_token, md)
                if st:
                    _append_row(st)
                # Cross-source sync by numbers if enabled (for any ID source)
                # Only run cross-source number-based sync when user opted-in via --read-sync-number-fallback
                if chapter_sync_conf.get('enabled') and chapter_sync_conf.get('across_sources') and chapter_sync_conf.get('number_fallback'):
                    sync_cross_source_read_for_md(
                        client,
                        md,
                        session_token=session_token,
                        rpm=chapter_sync_conf.get('rpm', 300),
                        dry_run=bool(chapter_sync_conf.get('dry_run')),
                        only_if_ahead=bool(chapter_sync_conf.get('only_if_ahead')),
                        title_threshold=float(chapter_sync_conf.get('xsrc_title_threshold', 0.6)),
                        title_strict=bool(chapter_sync_conf.get('xsrc_title_strict', False)),
                    )
            except Exception as _e:
                # Keep going even if one ID fails during reporting
                if READ_SYNC_DEBUG:
                    try:
                        print(f"[read-debug] Exception during per-id processing for {md}: {_e}")
                    except Exception:
                        pass
                continue

    # Write missing report if requested
    if args.missing_report:
        try:
            outp = args.missing_report
            # Ensure parent directory exists
            try:
                outp.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            # Filter to only entries with missing > 0 or unknown
            def _is_missing(row: Dict[str, Any]) -> bool:
                m = row.get('missing')
                if isinstance(m, int):
                    return m > 0
                if isinstance(m, str):
                    return m.strip().lower() == 'unknown'
                return False
            rows = [r for r in sync_stats if _is_missing(r)]
            with outp.open('w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["title", "md_id", "markable", "marked", "missing"])
                for row in rows:
                    w.writerow([row.get('title',''), row.get('md_id',''), row.get('markable',''), row.get('marked',''), row.get('missing','')])
            print(f"Missing-chapters report written to {outp} ({len(rows)} rows)")
        except Exception as e:
            print(f"Failed to write --missing-report: {e}")

    return 0 if failed == 0 else 2

if __name__ == "__main__":
    sys.exit(main())
