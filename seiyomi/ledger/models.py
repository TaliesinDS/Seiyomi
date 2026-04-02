"""Ledger data models — plain dataclasses, no I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class LedgerTitle:
    """A canonical title entry in the ledger."""
    id: int = 0
    normalized_key: str = ""
    display_title: str = ""
    mal_id: Optional[int] = None
    mu_id: Optional[int] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class AltTitle:
    """An alternative name for a ledger title."""
    id: int = 0
    title_id: int = 0
    alt_name: str = ""
    source: str = ""  # suwayomi / mal / mu / comick


@dataclass
class ReadProgress:
    """Core progress record — one per title."""
    id: int = 0
    title_id: int = 0
    max_chapter: float = 0.0
    max_volume: Optional[int] = None
    status: str = "reading"
    last_synced_suwa: str = ""
    last_synced_mal: str = ""
    last_synced_mu: str = ""
    updated_at: str = ""


@dataclass
class SuwayomiEntry:
    """Maps a Suwayomi manga ID to a ledger title."""
    id: int = 0
    title_id: int = 0
    suwayomi_id: int = 0
    source_id: str = ""
    source_name: str = ""
    in_library: bool = True
    chapter_count: int = 0
