"""User normalisation + cache.

Users are collected as a side-effect of the threads stage: every post in
`/api/threads/{id}/?with_posts=1` carries a fully embedded `User` object,
so the exporter rarely needs to call `/api/users/{id}` directly.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .api import XfClient
from .io import write_json_atomic

log = logging.getLogger(__name__)

# Fields that downstream stages (mirror, builder) write onto users; the
# exporter must preserve them when re-flushing a known user.
PRESERVED_USER_FIELDS = ("avatar_r2_key",)


def normalise_user(u: dict[str, Any]) -> dict[str, Any]:
    """Pick the fields we want to archive; drop viewer-dependent flags."""
    return {
        "id": u["user_id"],
        "username": u["username"],
        "user_title": u.get("user_title", ""),
        "is_admin": bool(u.get("is_admin", False)),
        "is_moderator": bool(u.get("is_moderator", False)),
        "is_staff": bool(u.get("is_staff", False)),
        "user_group_id": u.get("user_group_id"),
        "secondary_group_ids": list(u.get("secondary_group_ids") or []),
        "avatar_urls": u.get("avatar_urls") or {},
        "register_date": u.get("register_date"),
        "last_activity": u.get("last_activity"),
        "message_count": u.get("message_count"),
        "view_url": u.get("view_url"),
    }


class UserCache:
    """Accumulate seen User objects in memory; flush to data/users/{id}.json."""

    def __init__(self, users_dir: Path) -> None:
        self.dir = users_dir
        self._by_id: dict[int, dict[str, Any]] = {}

    def add(self, user: dict[str, Any] | None) -> None:
        if not user:
            return
        uid = user.get("user_id")
        if not uid:
            return
        if uid not in self._by_id:
            self._by_id[uid] = normalise_user(user)

    def flush(self) -> int:
        if not self._by_id:
            return 0
        self.dir.mkdir(parents=True, exist_ok=True)
        for uid, user in self._by_id.items():
            path = self.dir / f"{uid}.json"
            if path.exists():
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    existing = {}
                for field in PRESERVED_USER_FIELDS:
                    if field in existing and field not in user:
                        user[field] = existing[field]
            write_json_atomic(path, user)
        log.info("Flushed %d users to %s", len(self._by_id), self.dir)
        return len(self._by_id)


def fetch_user(client: XfClient, user_id: int) -> dict[str, Any] | None:
    """Fallback fetch for users referenced via mentions but never seen as authors."""
    try:
        payload = client.get(f"/users/{user_id}")
    except Exception as e:
        log.warning("Failed to fetch user %s: %s", user_id, e)
        return None
    return payload.get("user")
