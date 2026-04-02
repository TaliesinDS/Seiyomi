"""Ledger display and export helpers."""
from __future__ import annotations

import csv
import io
import logging
from pathlib import Path
from typing import Optional

from seiyomi.ledger.db import LedgerDB

logger = logging.getLogger("seiyomi.ledger.show")


def show_stats(db: LedgerDB) -> str:
    """Return a formatted stats summary string."""
    s = db.stats()
    lines = [
        f"Titles:           {s['titles']}",
        f"With progress:    {s['with_progress']}",
        f"Suwayomi entries: {s['suwayomi_entries']}",
        f"Alt titles:       {s['alt_titles']}",
    ]
    return "\n".join(lines)


def show_title(db: LedgerDB, query: str) -> str:
    """Search for a title and return formatted detail."""
    query_lower = query.lower()
    results = []
    for title, prog in db.all_progress():
        if query_lower in title.display_title.lower() or query_lower in title.normalized_key:
            entries = db.get_suwayomi_entries(title.id)
            alts = db.get_alt_titles(title.id)
            lines = [
                f"  Title:    {title.display_title}",
                f"  Key:      {title.normalized_key}",
                f"  Chapter:  {prog.max_chapter:.1f}",
                f"  Status:   {prog.status}",
                f"  MAL ID:   {title.mal_id or '-'}",
                f"  MU ID:    {title.mu_id or '-'}",
                f"  Updated:  {prog.updated_at}",
            ]
            if alts:
                alt_strs = [a.alt_name for a in alts[:5]]
                lines.append(f"  Alts:     {'; '.join(alt_strs)}")
            if entries:
                for e in entries:
                    lib_tag = "library" if e.in_library else "orphan"
                    lines.append(
                        f"  Suwayomi: id={e.suwayomi_id} source={e.source_name} "
                        f"ch={e.chapter_count} [{lib_tag}]"
                    )
            results.append("\n".join(lines))

    if not results:
        return f"No ledger entries matching '{query}'."
    return f"\nFound {len(results)} match(es):\n\n" + "\n\n".join(results)


def export_csv(db: LedgerDB, output_path: Optional[Path] = None) -> str:
    """Export ledger to CSV.  Returns the output path used."""
    path = output_path or Path("ledger_export.csv")
    rows = db.all_progress()

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "title", "normalized_key", "max_chapter", "status",
            "mal_id", "mu_id", "updated_at",
        ])
        for title, prog in rows:
            writer.writerow([
                title.display_title, title.normalized_key,
                prog.max_chapter, prog.status,
                title.mal_id or "", title.mu_id or "",
                prog.updated_at,
            ])

    logger.info("Exported %d entries to %s", len(rows), path)
    return str(path)
