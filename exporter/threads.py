"""Stage: export threads + posts.

For each forum (from `data/meta.json`):
1. Paginate `/api/forums/{id}/threads` (server-fixed `per_page=30`).
2. For each thread, paginate `/api/threads/{id}/?with_posts=1&page=N`
   (server-fixed `per_page=10`) until `current_page == last_page`.
3. Merge pages into a single `data/threads/{thread_id}.json` written
   atomically. Existing files are skipped unless `--force`.
4. As a side effect, every embedded `post.User` object is captured into
   the shared `UserCache`, so a separate users pass is rarely needed.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable

from .api import XfClient
from .io import write_json_atomic
from .users import UserCache

log = logging.getLogger(__name__)

SLUG_RE = re.compile(r"/(?:threads|forums|resources)/([^/]+?)\.\d+/?$")


def extract_slug(view_url: str | None) -> str | None:
    if not view_url:
        return None
    m = SLUG_RE.search(view_url)
    return m.group(1) if m else None


def url_path(view_url: str | None) -> str | None:
    if not view_url:
        return None
    # strip scheme+host, keep path: /threads/foo.123/
    from urllib.parse import urlparse

    p = urlparse(view_url)
    return p.path or None


def normalise_attachment(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": a["attachment_id"],
        "filename": a.get("filename"),
        "file_size": a.get("file_size"),
        "width": a.get("width"),
        "height": a.get("height"),
        "is_audio": bool(a.get("is_audio", False)),
        "is_video": bool(a.get("is_video", False)),
        "attach_date": a.get("attach_date"),
        "src_url": a.get("direct_url"),
        "thumbnail_url": a.get("thumbnail_url"),
        "local_path": None,
        "r2_key": None,
    }


def normalise_post(post: dict[str, Any]) -> dict[str, Any]:
    user = post.get("User") or {}
    return {
        "id": post["post_id"],
        "position": post.get("position"),
        "user_id": post.get("user_id"),
        "username": post.get("username"),
        "user_title": user.get("user_title", ""),
        "is_staff": bool(user.get("is_staff", False)),
        "is_admin": bool(user.get("is_admin", False)),
        "is_moderator": bool(user.get("is_moderator", False)),
        "post_date": post.get("post_date"),
        "last_edit_date": post.get("last_edit_date"),
        "message_state": post.get("message_state"),
        "message_parsed": post.get("message_parsed"),
        "attach_count": post.get("attach_count", 0),
        "attachments": [normalise_attachment(a) for a in (post.get("Attachments") or [])],
    }


def normalise_forum(forum: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": forum.get("node_id"),
        "title": forum.get("title"),
        "breadcrumbs": [
            {"id": b.get("node_id"), "title": b.get("title"), "type": b.get("node_type_id")}
            for b in (forum.get("breadcrumbs") or [])
        ],
    }


def normalise_thread(thread: dict[str, Any], posts: list[dict[str, Any]]) -> dict[str, Any]:
    view_url = thread.get("view_url")
    return {
        "id": thread["thread_id"],
        "title": thread.get("title"),
        "slug": extract_slug(view_url),
        "url_path": url_path(view_url),
        "forum": normalise_forum(thread.get("Forum") or {}),
        "node_id": thread.get("node_id"),
        "tags": thread.get("tags") or [],
        "prefix_id": thread.get("prefix_id"),
        "discussion_state": thread.get("discussion_state"),
        "discussion_open": thread.get("discussion_open"),
        "discussion_type": thread.get("discussion_type"),
        "sticky": bool(thread.get("sticky", False)),
        "post_date": thread.get("post_date"),
        "last_post_date": thread.get("last_post_date"),
        "view_count": thread.get("view_count"),
        "reply_count": thread.get("reply_count"),
        "first_post_id": thread.get("first_post_id"),
        "user_id": thread.get("user_id"),
        "username": thread.get("username"),
        "custom_fields": thread.get("custom_fields") or {},
        "posts": [normalise_post(p) for p in posts],
    }


def load_meta(data_dir: Path) -> dict[str, Any]:
    meta = data_dir / "meta.json"
    if not meta.exists():
        raise FileNotFoundError(
            f"{meta} not found — run `xf-export nodes` first"
        )
    return json.loads(meta.read_text(encoding="utf-8"))


def iter_forum_threads(
    client: XfClient, forum_id: int
) -> Iterable[dict[str, Any]]:
    """Yield every thread in a forum, paginated."""
    page = 1
    while True:
        payload = client.get(f"/forums/{forum_id}/threads", page=page)
        threads = payload.get("threads") or []
        for t in threads:
            yield t
        pag = payload.get("pagination") or {}
        last_page = pag.get("last_page", 1)
        if page >= last_page or not threads:
            return
        page += 1


def export_one_thread(
    client: XfClient,
    thread_id: int,
    threads_dir: Path,
    user_cache: UserCache,
    *,
    force: bool = False,
) -> bool:
    """Returns True if the thread was (re-)written, False if skipped."""
    out = threads_dir / f"{thread_id}.json"
    if out.exists() and not force:
        log.debug("skip %s (exists)", out)
        return False

    thread_meta: dict[str, Any] | None = None
    all_posts: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = client.get(
            f"/threads/{thread_id}/", with_posts=1, page=page
        )
        thread_meta = payload.get("thread") or thread_meta
        posts = payload.get("posts") or []
        for p in posts:
            user_cache.add(p.get("User"))
        all_posts.extend(posts)
        pag = payload.get("pagination") or {}
        last_page = pag.get("last_page", 1)
        if page >= last_page:
            break
        page += 1

    if thread_meta is None:
        log.warning("thread %s: no thread metadata returned", thread_id)
        return False

    write_json_atomic(out, normalise_thread(thread_meta, all_posts))
    log.info("Wrote %s (%d posts)", out, len(all_posts))
    return True


def export_threads(
    client: XfClient,
    data_dir: Path,
    *,
    forum_ids: list[int] | None = None,
    only_thread: int | None = None,
    force: bool = False,
) -> tuple[int, int]:
    """Returns (threads_written, users_flushed)."""
    threads_dir = data_dir / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    user_cache = UserCache(data_dir / "users")

    if only_thread is not None:
        log.info("Single-thread mode: %d", only_thread)
        wrote = export_one_thread(
            client, only_thread, threads_dir, user_cache, force=force
        )
        users_flushed = user_cache.flush()
        return (1 if wrote else 0, users_flushed)

    if not forum_ids:
        forum_ids = list(load_meta(data_dir)["forum_ids"])
    log.info("Exporting %d forum(s): %s", len(forum_ids), forum_ids)

    written = 0
    seen_thread_ids: set[int] = set()
    for fid in forum_ids:
        log.info("==> forum %d", fid)
        forum_count = 0
        for t in iter_forum_threads(client, fid):
            tid = t["thread_id"]
            if tid in seen_thread_ids:
                continue
            seen_thread_ids.add(tid)
            forum_count += 1
            if export_one_thread(client, tid, threads_dir, user_cache, force=force):
                written += 1
        log.info("    forum %d: %d threads listed", fid, forum_count)

    users_flushed = user_cache.flush()
    log.info("Total: %d threads written, %d users cached", written, users_flushed)
    return written, users_flushed
