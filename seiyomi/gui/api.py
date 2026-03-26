"""Async data-fetch helpers for the Seiyomi GUI (read-only).

GUI rules:
- This module may import SuwayomiClient for READ-ONLY calls only.
- ALL mutations (migrate, import, prune, sync) go through ProcessRunner (CLI).
- Callbacks are always called on the worker thread; callers must schedule
  onto the tkinter main thread via widget.after(0, lambda: callback(result)).
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional


def _make_client(base_url: str, auth_mode: str, username: str, password: str, token: str):
    from seiyomi.clients.suwayomi import SuwayomiClient
    return SuwayomiClient(
        base_url=base_url,
        auth_mode=auth_mode,
        username=username,
        password=password,
        token=token,
    )


def fetch_categories_async(
    base_url: str,
    auth_mode: str,
    username: str,
    password: str,
    token: str,
    callback: Callable[[Optional[List[Dict[str, Any]]]], None],
) -> None:
    """Fetch category list in a daemon thread and call callback(result)."""
    def _work():
        try:
            client = _make_client(base_url, auth_mode, username, password, token)
            result = client.list_categories()
        except Exception:
            result = None
        callback(result)
    threading.Thread(target=_work, daemon=True).start()


def fetch_sources_async(
    base_url: str,
    auth_mode: str,
    username: str,
    password: str,
    token: str,
    callback: Callable[[Optional[List[Dict[str, Any]]]], None],
) -> None:
    """Fetch installed source list in a daemon thread."""
    def _work():
        try:
            client = _make_client(base_url, auth_mode, username, password, token)
            result = client.get_sources()
        except Exception:
            result = None
        callback(result)
    threading.Thread(target=_work, daemon=True).start()


def fetch_library_async(
    base_url: str,
    auth_mode: str,
    username: str,
    password: str,
    token: str,
    callback: Callable[[Optional[List[Dict[str, Any]]]], None],
) -> None:
    """Fetch library in a daemon thread."""
    def _work():
        try:
            client = _make_client(base_url, auth_mode, username, password, token)
            result = client.get_library_graphql() or client.get_library()
        except Exception:
            result = None
        callback(result)
    threading.Thread(target=_work, daemon=True).start()


def test_connection_async(
    base_url: str,
    auth_mode: str,
    username: str,
    password: str,
    token: str,
    callback: Callable[[bool, str], Any],
) -> None:
    """Test server reachability; callback(ok: bool, message: str)."""
    def _work():
        try:
            client = _make_client(base_url, auth_mode, username, password, token)
            cats = client.list_categories()
            if cats is not None:
                callback(True, f"Connected — {len(cats)} categories")
            else:
                callback(False, "Server responded but returned no data")
        except Exception as exc:
            callback(False, str(exc))
    threading.Thread(target=_work, daemon=True).start()
