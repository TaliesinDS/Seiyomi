"""CSV import parsing — pure I/O layer, no network calls, no MangaDex."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CSV_KIND_COMICK = "comick"
CSV_KIND_MANGANATO = "manganato"
CSV_KIND_AUTO = "auto"


@dataclass
class CsvItem:
    title: str
    synonyms: List[str] = field(default_factory=list)
    external_ids: Dict[str, str] = field(default_factory=dict)
    status: Optional[str] = None
    last_read_chapter: Optional[str] = None
    last_read_at: Optional[str] = None
    rating: Optional[str] = None
    source: str = "unknown"
    raw: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split_synonyms(raw: str) -> List[str]:
    vals: List[str] = []
    for token in re.split(r"[,;]", raw or ""):
        token = token.strip()
        if token and token not in vals:
            vals.append(token)
    return vals


def _normalize_chapter_hint(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    lowered = text.lower().replace("chapter", "").replace("chap", "").replace("#", "").strip()
    return lowered or text


def _normalize_last_read(raw: Any) -> Optional[str]:
    """Return None for zero-epoch dates; otherwise return string as-is."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in {"0000:00:00", "0000-00-00", "1970-01-01"}:
        return None
    return text


def _parse_chapter_hint_to_float(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", raw)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Schema detection
# ---------------------------------------------------------------------------

def detect_csv_kind(path: Path, forced: str = CSV_KIND_AUTO) -> str:
    if forced and forced.lower() != CSV_KIND_AUTO:
        return forced.lower()
    header: List[str] = []
    sample: List[str] = []
    try:
        with path.open(newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            header = next(reader, [])
            sample = next(reader, [])
    except Exception:
        pass
    lower = [h.strip().lower() for h in header if h]
    if "hid" in lower and "title" in lower and "synonyms" in lower:
        return CSV_KIND_COMICK
    if "title" in lower and "url" in lower:
        return CSV_KIND_MANGANATO
    if "manganato" in " ".join(sample).lower():
        return CSV_KIND_MANGANATO
    if "hid" in lower:
        return CSV_KIND_COMICK
    return CSV_KIND_AUTO


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_comick_csv(path: Path) -> List[CsvItem]:
    items: List[CsvItem] = []
    with path.open(newline="", encoding="utf-8", errors="ignore") as f:
        for row in csv.DictReader(f):
            title = (row.get("title") or "").strip()
            if not title:
                continue
            synonyms = _split_synonyms(row.get("synonyms") or "")
            external_ids: Dict[str, str] = {}
            hid = (row.get("hid") or "").strip()
            if hid:
                external_ids["comick"] = hid
            for key in ("mal", "anilist", "mangaupdates"):
                val = (row.get(key) or "").strip()
                if val:
                    external_ids[key] = val
            status = (row.get("type") or row.get("status") or "").strip() or None
            items.append(
                CsvItem(
                    title=title,
                    synonyms=synonyms,
                    external_ids=external_ids,
                    status=status.lower() if status else None,
                    last_read_chapter=_normalize_chapter_hint(row.get("read")),
                    last_read_at=_normalize_last_read(row.get("last_read")),
                    rating=(row.get("rating") or "").strip() or None,
                    source=CSV_KIND_COMICK,
                    raw=dict(row),
                )
            )
    return items


def parse_manganato_csv(
    path: Path,
    column_map: Optional[Dict[str, str]] = None,
) -> List[CsvItem]:
    items: List[CsvItem] = []
    col = {"title": "Title", "url": "URL", "viewed": "Viewed"}
    if column_map:
        col.update({k: v for k, v in column_map.items() if k in {"title", "url", "viewed"}})
    with path.open(newline="", encoding="utf-8", errors="ignore") as f:
        for row in csv.DictReader(f):
            title = (row.get(col["title"]) or "").strip()
            if not title:
                continue
            url_val = (row.get(col["url"]) or "").strip()
            external_ids: Dict[str, str] = {}
            if url_val:
                external_ids["manganato"] = url_val
            viewed = (row.get(col["viewed"]) or "").strip()
            items.append(
                CsvItem(
                    title=title,
                    external_ids=external_ids,
                    status=None,
                    last_read_chapter=_normalize_chapter_hint(viewed),
                    last_read_at=None,
                    rating=None,
                    source=CSV_KIND_MANGANATO,
                    raw=dict(row),
                )
            )
    return items


def load_csv_items(
    path: Path,
    forced_kind: str = CSV_KIND_AUTO,
    column_map: Optional[Dict[str, str]] = None,
) -> Tuple[str, List[CsvItem]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")
    detected = detect_csv_kind(path, forced_kind)
    if detected == CSV_KIND_COMICK:
        return CSV_KIND_COMICK, parse_comick_csv(path)
    if detected == CSV_KIND_MANGANATO:
        return CSV_KIND_MANGANATO, parse_manganato_csv(path, column_map)
    # Default: try Comick, fallback to Manganato
    try:
        return CSV_KIND_COMICK, parse_comick_csv(path)
    except Exception:
        return CSV_KIND_MANGANATO, parse_manganato_csv(path, column_map)


def parse_csv_column_map(overrides: Optional[List[str]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not overrides:
        return result
    for spec in overrides:
        if not spec:
            continue
        for part in (p for p in spec.split(",") if p.strip()):
            if "=" not in part:
                raise ValueError(f"Invalid column map entry '{part}', expected key=value")
            key, value = part.split("=", 1)
            key, value = key.strip().lower(), value.strip()
            if not key or not value:
                raise ValueError(f"Invalid column map entry '{part}', missing key or value")
            result[key] = value
    return result
