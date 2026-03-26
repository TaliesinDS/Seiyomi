"""Operations — high-level Suwayomi library operations.

Each sub-module owns one operation. The monolith delegates to these modules;
main() will eventually be rewritten to call them directly (Phase 1.6).
"""
# Explicit re-exports so callers can do:
#   from seiyomi.operations import migrate_library, prune_zero_duplicates, …
from seiyomi.operations.migrate import migrate_library
from seiyomi.operations.prune import prune_zero_duplicates, prune_nonpreferred_langs
from seiyomi.operations.rehome import rehome_entry
from seiyomi.operations.read_sync import (
    fetch_suwayomi_chapters,
    extract_chapter_uuid_from_item,
    mark_chapter_read,
    sync_read_chapters_by_uuid,
)

__all__ = [
    "migrate_library",
    "prune_zero_duplicates",
    "prune_nonpreferred_langs",
    "rehome_entry",
    "fetch_suwayomi_chapters",
    "extract_chapter_uuid_from_item",
    "mark_chapter_read",
    "sync_read_chapters_by_uuid",
]
