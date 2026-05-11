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


def iter_reviews_for(client: XfClient, resource_id: int) -> Iterable[dict[str, Any]]:
    """Paginate /api/resources/{id}/reviews/ and yield raw review objects."""
    page = 1
    while True:
        payload = client.get(f"/resources/{resource_id}/reviews/", page=page)
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
    """Returns (reviews_imported, resources_touched).

    The global /api/resource-reviews/ feed only shows the most recent few; we
    have to walk each resource individually to get every review.
    """
    resources_dir = data_dir / "resources"
    if not resources_dir.exists():
        raise FileNotFoundError(f"{resources_dir} not found — run `xf-export resources` first")
    user_cache = UserCache(data_dir / "users")

    total = 0
    touched = 0
    for path in sorted(resources_dir.glob("*.json"), key=lambda p: int(p.stem)):
        data = json.loads(path.read_text(encoding="utf-8"))
        rid = int(data["id"])
        reviews: list[dict[str, Any]] = []
        for raw in iter_reviews_for(client, rid):
            user_cache.add(raw.get("User"))
            reviews.append(normalise_review(raw))
        reviews.sort(key=lambda r: (r.get("rating_date") or 0, r.get("id") or 0))
        data["reviews"] = reviews
        write_json_atomic(path, data)
        if reviews:
            touched += 1
            total += len(reviews)
            log.info("resource %d: %d reviews", rid, len(reviews))

    user_cache.flush()
    log.info("Reviews export: %d total across %d resources", total, touched)
    return total, touched
