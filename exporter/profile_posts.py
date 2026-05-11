"""Stage: export profile-post wall + comments per user.

For every `data/users/{id}.json` we paginate `/api/users/{id}/profile-posts`
(10/page, server-fixed) and merge wall_posts + wall_total back into the
user JSON. When `comment_count > len(LatestComments)` we paginate
`/api/profile-posts/{id}/comments` for the full list.

Commenters' embedded `User` objects feed the shared `UserCache` so previously
unseen wall participants land in `data/users/` automatically.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

from .api import XfClient
from .io import write_json_atomic
from .users import UserCache

log = logging.getLogger(__name__)


def _url_path(view_url: str | None) -> str | None:
    if not view_url:
        return None
    return urlparse(view_url).path or None


def normalise_comment(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c["profile_post_comment_id"],
        "profile_post_id": c.get("profile_post_id"),
        "user_id": c.get("user_id"),
        "username": c.get("username"),
        "comment_date": c.get("comment_date"),
        "message_state": c.get("message_state"),
        "message_parsed": c.get("message_parsed"),
    }


def normalise_profile_post(p: dict[str, Any], comments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": p["profile_post_id"],
        "profile_user_id": p.get("profile_user_id"),
        "user_id": p.get("user_id"),
        "username": p.get("username"),
        "post_date": p.get("post_date"),
        "message_state": p.get("message_state"),
        "message_parsed": p.get("message_parsed"),
        "comment_count": p.get("comment_count", 0),
        "first_comment_date": p.get("first_comment_date"),
        "last_comment_date": p.get("last_comment_date"),
        "view_url": p.get("view_url"),
        "url_path": _url_path(p.get("view_url")),
        "comments": [normalise_comment(c) for c in comments],
    }


def iter_wall(client: XfClient, user_id: int) -> Iterable[dict[str, Any]]:
    """Yield raw profile_post objects on a user's wall, paginated."""
    page = 1
    while True:
        payload = client.get(f"/users/{user_id}/profile-posts", page=page)
        posts = payload.get("profile_posts") or []
        for p in posts:
            yield p
        pag = payload.get("pagination") or {}
        last_page = pag.get("last_page", 1)
        if page >= last_page or not posts:
            return
        page += 1


def fetch_comments(client: XfClient, profile_post_id: int) -> list[dict[str, Any]]:
    """Paginate /profile-posts/{id}/comments and return raw comment objects."""
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = client.get(f"/profile-posts/{profile_post_id}/comments", page=page)
        comments = payload.get("comments") or []
        out.extend(comments)
        pag = payload.get("pagination") or {}
        last_page = pag.get("last_page", 1)
        if page >= last_page or not comments:
            return out
        page += 1


def export_one_wall(
    client: XfClient,
    user_id: int,
    users_dir: Path,
    user_cache: UserCache,
) -> int:
    """Fetch wall+comments for one user; merge into data/users/{id}.json.

    Returns the number of profile posts written (0 if empty wall).
    """
    out = users_dir / f"{user_id}.json"
    if not out.exists():
        log.warning("user %d: %s missing, skipping", user_id, out)
        return 0

    posts: list[dict[str, Any]] = []
    access = "ok"
    try:
        for raw in iter_wall(client, user_id):
            user_cache.add(raw.get("User"))
            cc = raw.get("comment_count") or 0
            latest = raw.get("LatestComments") or []
            if cc and cc > len(latest):
                try:
                    comments = fetch_comments(client, raw["profile_post_id"])
                except httpx.HTTPStatusError as e:
                    if e.response.status_code in (403, 404):
                        log.info(
                            "profile-post %s: comments hidden (%d), using LatestComments",
                            raw["profile_post_id"], e.response.status_code,
                        )
                        comments = latest
                    else:
                        raise
            else:
                comments = latest
            for c in comments:
                user_cache.add(c.get("User"))
            posts.append(normalise_profile_post(raw, comments))
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (403, 404):
            log.info("user %d: wall hidden/missing (%d)", user_id, e.response.status_code)
            access = "hidden"
            posts = []
        else:
            raise

    existing = json.loads(out.read_text(encoding="utf-8"))
    existing["wall_posts"] = posts
    existing["wall_total"] = len(posts)
    existing["wall_access"] = access
    write_json_atomic(out, existing)
    if posts:
        log.info("user %d: wrote %d wall posts", user_id, len(posts))
    return len(posts)


def export_profile_posts(
    client: XfClient,
    data_dir: Path,
    *,
    only_user: int | None = None,
    force: bool = False,
) -> tuple[int, int]:
    """Returns (users_with_walls, total_profile_posts)."""
    users_dir = data_dir / "users"
    if not users_dir.exists():
        raise FileNotFoundError(f"{users_dir} not found — run `xf-export threads` first")
    user_cache = UserCache(users_dir)

    if only_user is not None:
        log.info("Single-user mode: %d", only_user)
        n = export_one_wall(client, only_user, users_dir, user_cache)
        user_cache.flush()
        return (1 if n else 0, n)

    uids = sorted(int(p.stem) for p in users_dir.glob("*.json"))
    log.info("Exporting walls for %d users", len(uids))

    users_with_walls = 0
    total_posts = 0
    for uid in uids:
        if not force:
            try:
                existing = json.loads((users_dir / f"{uid}.json").read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
            if "wall_total" in existing:
                continue
        n = export_one_wall(client, uid, users_dir, user_cache)
        if n:
            users_with_walls += 1
            total_posts += n

    user_cache.flush()
    log.info("Wall export complete: %d users with walls, %d posts", users_with_walls, total_posts)
    return users_with_walls, total_posts
