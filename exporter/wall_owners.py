"""One-off helper: fetch users who *own* a wall but never authored a forum
post or wall comment, so they're not in `data/users/` from the threads or
profile-posts stages.

Called as `xf-export wall-owners --add UID1,UID2,...`. For each given id we
fetch `/api/users/{id}` and write a normalised file via UserCache. After
this, `xf-export profile-posts --force` will pick them up.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from .api import XfClient
from .users import UserCache, normalise_user

log = logging.getLogger(__name__)


def add_wall_owners(client: XfClient, data_dir: Path, user_ids: list[int]) -> int:
    """Returns the number of user JSONs written."""
    users_dir = data_dir / "users"
    cache = UserCache(users_dir)
    added = 0
    for uid in user_ids:
        try:
            payload = client.get(f"/users/{uid}")
        except httpx.HTTPStatusError as e:
            log.warning("user %d: %d %s", uid, e.response.status_code, e.response.text[:120])
            continue
        user = payload.get("user")
        if user:
            cache.add(user)
            added += 1
    flushed = cache.flush()
    log.info("Wall-owners stage: %d fetched, %d flushed", added, flushed)
    return flushed
