"""Stage: export resources (XenForo Resource Manager).

For each resource:
1. Paginate `/api/resources` (server-fixed `per_page=30`).
2. For each resource, fetch `/api/resources/{id}` (full detail with embedded
   `Category`) and `/api/resources/{id}/versions` (all versions, each with
   `files[]` carrying `download_url` and `size`).
3. Merge into one `data/resources/{resource_id}.json` written atomically.
4. As a side effect, capture the resource author's `User` (if embedded) into
   the shared UserCache.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterable

import httpx

from .api import XfClient
from .io import write_json_atomic
from .threads import extract_slug, normalise_attachment, url_path
from .users import UserCache

log = logging.getLogger(__name__)


def normalise_category(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c.get("resource_category_id"),
        "title": c.get("title"),
        "description": c.get("description"),
        "parent_id": c.get("parent_category_id"),
        "view_url": c.get("view_url"),
        "slug": extract_slug(c.get("view_url")),
    }


def normalise_file(f: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f["id"],
        "filename": f.get("filename"),
        "size": f.get("size"),
        "src_url": f.get("download_url"),
        "local_path": None,
        "r2_key": None,
    }


def normalise_version(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": v["resource_version_id"],
        "version_string": v.get("version_string"),
        "release_date": v.get("release_date"),
        "download_count": v.get("download_count"),
        "rating_avg": v.get("rating_avg"),
        "rating_count": v.get("rating_count"),
        "version_state": v.get("version_state"),
        "view_url": v.get("view_url"),
        "files": [normalise_file(f) for f in (v.get("files") or [])],
    }


def normalise_resource(r: dict[str, Any], versions: list[dict[str, Any]]) -> dict[str, Any]:
    view_url = r.get("view_url")
    return {
        "id": r["resource_id"],
        "title": r.get("title"),
        "tag_line": r.get("tag_line"),
        "slug": extract_slug(view_url),
        "url_path": url_path(view_url),
        "category": normalise_category(r.get("Category") or {}),
        "user_id": r.get("user_id"),
        "username": r.get("username"),
        "version": r.get("version"),
        "view_count": r.get("view_count"),
        "download_count": r.get("download_count"),
        "rating_avg": r.get("rating_avg"),
        "rating_count": r.get("rating_count"),
        "resource_state": r.get("resource_state"),
        "resource_date": r.get("resource_date"),
        "last_update": r.get("last_update"),
        "icon_url": r.get("icon_url"),
        "external_url": r.get("external_url") or None,
        "is_fileless": r.get("is_fileless"),
        "tags": r.get("tags") or [],
        "custom_fields": r.get("custom_fields") or {},
        "description_parsed": r.get("description_parsed"),
        "description_attachments": [
            normalise_attachment(a) for a in (r.get("DescriptionAttachments") or [])
        ],
        "current_files": [normalise_file(f) for f in (r.get("current_files") or [])],
        "versions": [normalise_version(v) for v in versions],
    }


def iter_resources(client: XfClient) -> Iterable[dict[str, Any]]:
    page = 1
    while True:
        payload = client.get("/resources", page=page)
        items = payload.get("resources") or []
        for r in items:
            yield r
        pag = payload.get("pagination") or {}
        last_page = pag.get("last_page", 1)
        if page >= last_page or not items:
            return
        page += 1


def export_one_resource(
    client: XfClient,
    resource_id: int,
    out_dir: Path,
    user_cache: UserCache,
    *,
    force: bool = False,
) -> bool:
    out = out_dir / f"{resource_id}.json"
    if out.exists() and not force:
        log.debug("skip %s (exists)", out)
        return False

    detail = client.get(f"/resources/{resource_id}").get("resource") or {}
    versions: list[dict[str, Any]] = []
    if (detail.get("Category") or {}).get("enable_versioning", True):
        try:
            versions_payload = client.get(f"/resources/{resource_id}/versions")
            versions = versions_payload.get("versions") or []
        except httpx.HTTPStatusError as e:
            # XF returns 400 'xfrm_this_resource_is_not_versioned' for single-file
            # releases living in a versioned category; treat as zero versions.
            if e.response.status_code == 400:
                log.info("Resource %s: not versioned (using current_files)", resource_id)
            else:
                raise

    user_cache.add(detail.get("User"))

    write_json_atomic(out, normalise_resource(detail, versions))
    log.info("Wrote %s (%d versions)", out, len(versions))
    return True


def export_resources(
    client: XfClient,
    data_dir: Path,
    *,
    only_resource: int | None = None,
    force: bool = False,
) -> int:
    out_dir = data_dir / "resources"
    out_dir.mkdir(parents=True, exist_ok=True)
    user_cache = UserCache(data_dir / "users")

    if only_resource is not None:
        log.info("Single-resource mode: %d", only_resource)
        wrote = export_one_resource(
            client, only_resource, out_dir, user_cache, force=force
        )
        user_cache.flush()
        return 1 if wrote else 0

    written = 0
    for r in iter_resources(client):
        rid = r["resource_id"]
        if export_one_resource(client, rid, out_dir, user_cache, force=force):
            written += 1
    user_cache.flush()
    log.info("Total resources written: %d", written)
    return written
