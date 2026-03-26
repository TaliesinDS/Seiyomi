"""MangaDex API client — authentication, follows, statuses, read chapters, lists."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import requests

MANGADEX_API = "https://api.mangadex.org"


def _truncate(text: str, limit: int = 200) -> str:
    t = (text or "").replace("\n", " ")[:limit]
    return t + ("..." if len(t) == limit else "")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def login_mangadex(username: str, password: str) -> Optional[str]:
    """Return session token or None."""
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
    """Return (session_token, error_message)."""
    import logging
    log = logging.getLogger("seiyomi.mangadex")
    try:
        payload: Dict[str, Any] = {
            "username": (username or "").strip(),
            "password": (password or ""),
        }
        if two_factor:
            payload["code"] = two_factor.strip()
        headers = {"Content-Type": "application/json", "User-Agent": "SuwayomiImporter/1.0"}
        r = requests.post(
            f"{MANGADEX_API}/auth/login",
            json=payload,
            headers=headers,
            timeout=20,
        )
        if r.status_code != 200:
            msg = f"HTTP {r.status_code}: {_truncate(r.text)}"
            if debug:
                log.debug(f"[login debug] Login failed: {msg}")
            return None, msg
        data = r.json()
        token = ((data.get("token") or {}).get("session"))
        if not token:
            if debug:
                log.debug(f"[login debug] No session token in response: keys={list(data.keys())}")
            return None, "No session token in response"
        return token, None
    except Exception as e:
        if debug:
            log.debug(f"[login debug] Exception during login: {e}")
        return None, str(e)


# ---------------------------------------------------------------------------
# Follows
# ---------------------------------------------------------------------------

def fetch_all_follows(session_token: str) -> List[Dict[str, Any]]:
    return fetch_all_follows_adv(session_token=session_token)


def fetch_all_follows_adv(
    session_token: str,
    debug: bool = False,
    max_follows: Optional[int] = None,
    pause: float = 0.2,
) -> List[Dict[str, Any]]:
    import logging
    log = logging.getLogger("seiyomi.mangadex")
    headers = {"Authorization": f"Bearer {session_token}"}
    limit = 100
    offset = 0
    results: List[Dict[str, Any]] = []
    total_reported: Optional[int] = None
    consecutive_failures = 0
    while True:
        if max_follows is not None and len(results) >= max_follows:
            if debug:
                log.debug(f"[follows debug] Reached max_follows={max_follows}, stopping early")
            break
        params = {"limit": limit, "offset": offset}
        try:
            r = requests.get(
                f"{MANGADEX_API}/user/follows/manga",
                params=params,
                headers=headers,
                timeout=25,
            )
        except Exception as e:
            consecutive_failures += 1
            if debug:
                log.debug(f"[follows debug] Exception offset={offset}: {e}")
            if consecutive_failures >= 3:
                break
            time.sleep(1.0 * consecutive_failures)
            continue
        if r.status_code != 200:
            consecutive_failures += 1
            if debug:
                log.debug(
                    f"[follows debug] HTTP {r.status_code} at offset={offset}: "
                    f"{_truncate(r.text, 120)} (failure {consecutive_failures})"
                )
            if consecutive_failures >= 3:
                break
            time.sleep(1.0 * consecutive_failures)
            continue
        consecutive_failures = 0
        js = r.json()
        data = js.get("data") or []
        limit_returned = js.get("limit") or len(data)
        if total_reported is None:
            total_reported = js.get("total")
        if debug:
            tr = f" total={total_reported}" if total_reported is not None else ""
            log.debug(
                f"[follows debug] Page offset={offset} got={len(data)} "
                f"limit={limit_returned}{tr} accum={len(results)}"
            )
        if not data:
            break
        before_add = len(results)
        for entry in data:
            mid = entry.get("id")
            attrs = entry.get("attributes") or {}
            titles = attrs.get("title") or {}
            title = titles.get("en") or (next(iter(titles.values())) if titles else "")
            results.append({"id": mid, "title": title})
            if max_follows is not None and len(results) >= max_follows:
                break
        if debug:
            log.debug(
                f"[follows debug] Added {len(results) - before_add} this page; new_total={len(results)}"
            )
        if total_reported is not None and len(results) >= total_reported:
            break
        offset += len(data)
        if offset > 10_000:
            if debug:
                log.debug("[follows debug] Offset exceeded safety guard; stopping")
            break
        time.sleep(pause)
    if debug:
        if total_reported is not None and len(results) < total_reported:
            log.debug(f"[follows debug] WARNING collected {len(results)} < reported total {total_reported}")
        log.debug(f"[follows debug] Finished follows fetch: {len(results)} items")
    return results


# ---------------------------------------------------------------------------
# Reading statuses
# ---------------------------------------------------------------------------

def fetch_reading_statuses(session_token: str, manga_ids: List[str]) -> Dict[str, str]:
    """Bulk-fetch reading statuses for the given manga IDs. Returns {md_uuid: status}."""
    headers = {"Authorization": f"Bearer {session_token}"}
    result: Dict[str, str] = {}
    batch = 50
    for i in range(0, len(manga_ids), batch):
        subset = manga_ids[i : i + batch]
        try:
            r = requests.get(
                f"{MANGADEX_API}/manga/status",
                params=[("ids[]", mid) for mid in subset],
                headers=headers,
                timeout=20,
            )
            if r.status_code != 200:
                continue
            for k, v in (r.json().get("statuses") or {}).items():
                if isinstance(v, str):
                    result[k] = v.lower()
                elif isinstance(v, dict):
                    sv = v.get("status") or v.get("readingStatus") or v.get("value")
                    if isinstance(sv, str):
                        result[k] = sv.lower()
        except Exception:
            continue
        time.sleep(0.15)
    return result


def fetch_single_status(session_token: str, manga_id: str) -> Optional[str]:
    """Fetch status for one manga via /manga/{id}/status. Returns lowercase or None."""
    headers = {"Authorization": f"Bearer {session_token}"}
    try:
        r = requests.get(
            f"{MANGADEX_API}/manga/{manga_id}/status",
            headers=headers,
            timeout=12,
        )
        if r.status_code != 200:
            return None
        val = r.json().get("status")
        return val.lower() if isinstance(val, str) and val else None
    except Exception:
        return None


def fetch_all_statuses(session_token: str) -> Dict[str, str]:
    """Fetch all reading statuses for the authenticated user. Returns {md_uuid: status}."""
    headers = {"Authorization": f"Bearer {session_token}"}
    try:
        r = requests.get(f"{MANGADEX_API}/manga/status", headers=headers, timeout=30)
        if r.status_code != 200:
            return {}
        return r.json().get("statuses") or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Read chapters
# ---------------------------------------------------------------------------

def fetch_mangadex_read_chapters(session_token: str, manga_md_id: str) -> List[str]:
    """Return list of chapter UUIDs the user has marked read on MangaDex."""
    headers = {"Authorization": f"Bearer {session_token}"}
    try:
        r = requests.get(
            f"{MANGADEX_API}/manga/{manga_md_id}/read",
            headers=headers,
            timeout=20,
        )
        if r.status_code != 200:
            return []
        return [c for c in (r.json().get("data") or []) if isinstance(c, str)]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Title lookup
# ---------------------------------------------------------------------------

def fetch_title_from_mangadex(md_id: str) -> Optional[str]:
    """Return the canonical English (or first available) title for a manga UUID."""
    try:
        r = requests.get(f"{MANGADEX_API}/manga/{md_id}", timeout=12)
        if r.status_code != 200:
            return None
        data = r.json().get("data") or {}
        attrs = data.get("attributes", {})
        titles = attrs.get("title") or {}
        if "en" in titles:
            return titles["en"].strip()
        if titles:
            return next(iter(titles.values())).strip()
        for alt in (attrs.get("altTitles") or []):
            for v in alt.values():
                return v.strip()
    except Exception:
        return None
    return None


def _search_mangadex_titles(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    params = {
        "title": query,
        "limit": max(1, min(limit, 20)),
        "order[relevance]": "desc",
    }
    try:
        resp = requests.get(f"{MANGADEX_API}/manga", params=params, timeout=20)
        if resp.status_code != 200:
            return []
        data = resp.json().get("data")
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except Exception:
        return []
    return []


# ---------------------------------------------------------------------------
# Custom lists
# ---------------------------------------------------------------------------

def fetch_user_lists(session_token: str, debug: bool = False) -> List[Dict[str, Any]]:
    """Fetch user's custom reading lists. Returns list of {id, name}."""
    import logging
    log = logging.getLogger("seiyomi.mangadex")
    headers = {"Authorization": f"Bearer {session_token}"}
    limit = 100
    offset = 0
    items: List[Dict[str, Any]] = []
    while True:
        try:
            r = requests.get(
                f"{MANGADEX_API}/user/list",
                params={"limit": limit, "offset": offset},
                headers=headers,
                timeout=20,
            )
        except Exception as e:
            if debug:
                log.debug(f"[lists debug] Exception at offset={offset}: {e}")
            break
        if r.status_code != 200:
            if debug:
                log.debug(f"[lists debug] HTTP {r.status_code} at offset={offset}: {_truncate(r.text, 120)}")
            break
        js = r.json()
        data = js.get("data") or []
        if not data:
            break
        for entry in data:
            lid = entry.get("id")
            name = (entry.get("attributes") or {}).get("name") or entry.get("name")
            if lid and name:
                items.append({"id": lid, "name": name})
        offset += len(data)
        if len(data) < limit:
            break
        time.sleep(0.15)
    if debug:
        log.debug(f"[lists debug] Collected {len(items)} lists")
    return items


def fetch_manga_ids_in_list(session_token: str, list_id: str, debug: bool = False) -> List[str]:
    """Return manga IDs belonging to a custom list via /manga?list=<listId>."""
    import logging
    log = logging.getLogger("seiyomi.mangadex")
    headers = {"Authorization": f"Bearer {session_token}"}
    limit = 100
    offset = 0
    ids: List[str] = []
    while True:
        try:
            r = requests.get(
                f"{MANGADEX_API}/manga",
                params={"limit": limit, "offset": offset, "list": list_id},
                headers=headers,
                timeout=25,
            )
        except Exception as e:
            if debug:
                log.debug(f"[lists debug] Exception fetching list {list_id} offset={offset}: {e}")
            break
        if r.status_code != 200:
            if debug:
                log.debug(
                    f"[lists debug] HTTP {r.status_code} for list {list_id} "
                    f"at offset={offset}: {_truncate(r.text, 120)}"
                )
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
        log.debug(f"[lists debug] List {list_id}: {len(ids)} manga ids")
    return ids
