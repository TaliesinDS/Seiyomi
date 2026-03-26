"""CSV direct import operation.

Resolves CSV items (CsvItem) against Suwayomi sources and adds them to the library.
Currently delegates to the monolith implementation; will be moved here in Phase 2
once the library-lookup helpers are also extracted.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from seiyomi.clients.suwayomi import SuwayomiClient


def process_csv_direct_items(
    client: SuwayomiClient,
    items: list,
    *,
    dry_run: bool,
    prefer_existing: bool,
    no_add_library: bool,
    status_category_map: Dict[str, int],
    status_default_category: Optional[int],
    status_map_debug: bool,
    show_progress: bool,
    apply_read_progress: bool,
    chapter_sync_conf: Optional[Dict[str, Any]],
    title_threshold: float,
    title_strict: bool,
) -> Tuple[list, list, list, int, int]:
    """Add CSV items to the Suwayomi library.

    For now this delegates to the monolith function while the library-lookup
    helpers have not yet been extracted to the seiyomi package.
    """
    from import_mangadex_bookmarks_to_suwayomi_refactored import (
        process_csv_direct_items as _process_csv_direct_items,
    )
    return _process_csv_direct_items(
        client=client,
        items=items,
        dry_run=dry_run,
        prefer_existing=prefer_existing,
        no_add_library=no_add_library,
        status_category_map=status_category_map,
        status_default_category=status_default_category,
        status_map_debug=status_map_debug,
        show_progress=show_progress,
        apply_read_progress=apply_read_progress,
        chapter_sync_conf=chapter_sync_conf,
        title_threshold=title_threshold,
        title_strict=title_strict,
    )
