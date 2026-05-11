"""Stage: export resource reviews (XF Resource Manager).

Walks `/api/resource-reviews` (paginated, 30/page) and merges each review
into the matching `data/resources/{id}.json` under `reviews[]`. Review
authors feed the shared `UserCache`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable

from .api import XfClient
from .io import write_json_atomic
from .users import UserCache

log = logging.getLogger(__name__)


def normalise_review(rev: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": rev.get("resource_rating_id") or rev.get("rating_id"),
        "resource_id": (rev.get("Resource") or {}).get("resource_id"),
        "user_id": (rev.get("User") or {}).get("user_id"),
        "username": (rev.get("User") or {}).get("username"),
        "rating": rev.get("rating"),
        "rating_date": rev.get("rating_date"),
        "rating_state": rev.get("rating_state"),
        "is_anonymous": bool(rev.get("is_anonymous", False)),
        "message": rev.get("message"),
        "author_response": rev.get("author_response") or "",
    }


def iter_reviews(client: XfClient) -> Iterable[dict[str, Any]]:
    page = 1
    while True:
        payload = client.get("/resource-reviews", page=page)
        reviews = payload.get("reviews") or []
        for r in reviews:
            yield r
        pag = payload.get("pagination") or {}
        last_page = pag.get("last_page", 1)
        if page >= last_page or not reviews:
            return
        page += 1


def export_resource_reviews(
    client: XfClient,
    data_dir: Path,
) -> tuple[int, int]:
    """Returns (reviews_imported, resources_touched)."""
    resources_dir = data_dir / "resources"
    if not resources_dir.exists():
        raise FileNotFoundError(f"{resources_dir} not found — run `xf-export resources` first")
    user_cache = UserCache(data_dir / "users")

    # Bucket reviews by resource_id so we can write each resource JSON once.
    by_resource: dict[int, list[dict[str, Any]]] = {}
    for raw in iter_reviews(client):
        user_cache.add(raw.get("User"))
        rid = (raw.get("Resource") or {}).get("resource_id")
        if rid is None:
            continue
        by_resource.setdefault(int(rid), []).append(normalise_review(raw))

    # Clear reviews on every resource (so previously-removed reviews drop).
    for path in resources_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        new_reviews = by_resource.get(int(data["id"]), [])
        # Sort by rating_date ascending so identical exports stay deterministic.
        new_reviews.sort(key=lambda r: (r.get("rating_date") or 0, r.get("id") or 0))
        data["reviews"] = new_reviews
        write_json_atomic(path, data)

    total_reviews = sum(len(v) for v in by_resource.values())
    log.info(
        "Reviews export: %d reviews across %d resources",
        total_reviews, len(by_resource),
    )
    user_cache.flush()
    return total_reviews, len(by_resource)
