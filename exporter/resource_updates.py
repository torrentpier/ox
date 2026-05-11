"""Stage: export resource update announcements.

For each resource we paginate `/api/resources/{id}/updates/` and inline
the result into `data/resources/{id}.json` under `updates[]`. These are
the "post-an-update" entries authors write between version releases
(separate from `versions[]`).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .api import XfClient
from .io import write_json_atomic
from .threads import normalise_attachment
from .users import UserCache

log = logging.getLogger(__name__)


def _url_path(view_url: str | None) -> str | None:
    if not view_url:
        return None
    return urlparse(view_url).path or None


def normalise_update(u: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": u["resource_update_id"],
        "resource_id": u.get("resource_id"),
        "title": u.get("title"),
        "post_date": u.get("post_date"),
        "last_edit_date": u.get("last_edit_date"),
        "message_state": u.get("message_state"),
        "message_parsed": u.get("message_parsed"),
        "attach_count": u.get("attach_count", 0),
        "view_url": u.get("view_url"),
        "url_path": _url_path(u.get("view_url")),
        "attachments": [normalise_attachment(a) for a in (u.get("Attachments") or [])],
    }


def iter_updates(client: XfClient, resource_id: int) -> Iterable[dict[str, Any]]:
    page = 1
    while True:
        payload = client.get(f"/resources/{resource_id}/updates/", page=page)
        items = payload.get("updates") or []
        for u in items:
            yield u
        pag = payload.get("pagination") or {}
        last_page = pag.get("last_page", 1)
        if page >= last_page or not items:
            return
        page += 1


def export_resource_updates(client: XfClient, data_dir: Path) -> tuple[int, int]:
    """Returns (updates_imported, resources_touched)."""
    resources_dir = data_dir / "resources"
    if not resources_dir.exists():
        raise FileNotFoundError(f"{resources_dir} not found — run `xf-export resources` first")
    user_cache = UserCache(data_dir / "users")

    total = 0
    touched = 0
    for path in sorted(resources_dir.glob("*.json"), key=lambda p: int(p.stem)):
        data = json.loads(path.read_text(encoding="utf-8"))
        rid = int(data["id"])
        updates: list[dict[str, Any]] = []
        for raw in iter_updates(client, rid):
            user_cache.add(raw.get("User"))
            updates.append(normalise_update(raw))
        updates.sort(key=lambda u: (u.get("post_date") or 0, u.get("id") or 0))
        data["updates"] = updates
        write_json_atomic(path, data)
        if updates:
            touched += 1
            total += len(updates)
            log.info("resource %d: %d updates", rid, len(updates))

    user_cache.flush()
    log.info("Updates export: %d total across %d resources", total, touched)
    return total, touched
