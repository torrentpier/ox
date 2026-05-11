"""Mirror pipeline: scan `data/`, upload missing assets to R2, update JSON.

Each stage is independently idempotent — an asset with a non-empty `r2_key`
is skipped. A second `xf-mirror upload` after a clean run is a no-op.

Stages:
- attachments      — `post.attachments[]` in `data/threads/*.json`
- avatars          — `data/users/*.json` (downloads size "l")
- resources        — icon, version files (authenticated), current_files alias
- inline           — external `<img src>` in `message_parsed` and
                     `description_parsed`. Skips torrentpier.com URLs: those
                     are handled at builder time via attachment_id lookup.
"""

from __future__ import annotations

import json
import logging
import mimetypes
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from exporter.io import write_json_atomic

from .download import Downloader, sha256_bytes
from .inline import InlineIndex
from .keys import (
    attachment_key,
    avatar_key,
    inline_key,
    resource_file_key,
    resource_icon_key,
)
from .r2 import R2Client

log = logging.getLogger(__name__)

INTERNAL_HOSTS = {"torrentpier.com", "www.torrentpier.com"}
INLINE_INDEX_FILENAME = "inline_index.json"


def _safe_urlparse(url: str):
    try:
        return urlparse(url)
    except ValueError:
        return None


def _content_type(filename_hint: str | None, fallback: str | None) -> str:
    if fallback and fallback != "application/octet-stream":
        return fallback
    if filename_hint:
        ct, _ = mimetypes.guess_type(filename_hint)
        if ct:
            return ct
    return fallback or "application/octet-stream"


def _ensure_uploaded(
    r2: R2Client,
    dl: Downloader,
    key: str,
    src_url: str,
    *,
    authenticated: bool = False,
    filename_hint: str | None = None,
) -> bool:
    """Make `key` exist in the bucket. HEAD first; download + upload otherwise.

    Returns True on success (object now present in R2), False on failure.
    """
    if r2.head(key) is not None:
        return True
    fetched = dl.fetch(src_url, authenticated=authenticated)
    if fetched is None:
        return False
    body, ct, status = fetched
    if status >= 300:
        return False
    r2.put(key, body, content_type=_content_type(filename_hint, ct))
    return True


def mirror_attachments(data_dir: Path, r2: R2Client, dl: Downloader) -> Counter:
    stats: Counter[str] = Counter()
    paths = sorted((data_dir / "threads").glob("*.json"))
    for i, path in enumerate(paths, 1):
        data = json.loads(path.read_text(encoding="utf-8"))
        dirty = False
        for post in data.get("posts") or []:
            for att in post.get("attachments") or []:
                if att.get("r2_key"):
                    stats["attachment_skipped"] += 1
                    continue
                src = att.get("src_url")
                if not src:
                    stats["attachment_no_src"] += 1
                    continue
                key = attachment_key(
                    att["id"], att.get("filename") or f"{att['id']}.bin"
                )
                if _ensure_uploaded(
                    r2, dl, key, src, filename_hint=att.get("filename")
                ):
                    att["r2_key"] = key
                    dirty = True
                    stats["attachment_ok"] += 1
                else:
                    stats["attachment_failed"] += 1
        if dirty:
            write_json_atomic(path, data)
        if i % 200 == 0:
            log.info("attachments: thread %d / %d %s", i, len(paths), dict(stats))
    return stats


def mirror_avatars(data_dir: Path, r2: R2Client, dl: Downloader) -> Counter:
    stats: Counter[str] = Counter()
    for path in sorted((data_dir / "users").glob("*.json")):
        user = json.loads(path.read_text(encoding="utf-8"))
        if user.get("avatar_r2_key"):
            stats["avatar_skipped"] += 1
            continue
        avatar_urls = user.get("avatar_urls") or {}
        src = avatar_urls.get("l") or avatar_urls.get("m") or avatar_urls.get("o")
        if not src:
            stats["avatar_no_src"] += 1
            continue
        key = avatar_key(user["id"], src)
        if _ensure_uploaded(r2, dl, key, src, filename_hint=key):
            user["avatar_r2_key"] = key
            write_json_atomic(path, user)
            stats["avatar_ok"] += 1
        else:
            stats["avatar_failed"] += 1
    return stats


def mirror_resources(data_dir: Path, r2: R2Client, dl: Downloader) -> Counter:
    stats: Counter[str] = Counter()
    for path in sorted((data_dir / "resources").glob("*.json")):
        res = json.loads(path.read_text(encoding="utf-8"))
        dirty = False
        rid = int(res["id"])

        icon = res.get("icon_url")
        if icon and not res.get("icon_r2_key"):
            key = resource_icon_key(rid, icon)
            if _ensure_uploaded(r2, dl, key, icon, filename_hint=key):
                res["icon_r2_key"] = key
                dirty = True
                stats["icon_ok"] += 1
            else:
                stats["icon_failed"] += 1

        # Version files — authenticated downloads via XF API.
        for version in res.get("versions") or []:
            vid = int(version["id"])
            for f in version.get("files") or []:
                if f.get("r2_key"):
                    stats["res_file_skipped"] += 1
                    continue
                src = f.get("src_url")
                if not src:
                    stats["res_file_no_src"] += 1
                    continue
                key = resource_file_key(
                    rid, vid, f.get("filename") or f"file-{f.get('id')}.bin"
                )
                if _ensure_uploaded(
                    r2, dl, key, src,
                    authenticated=True,
                    filename_hint=f.get("filename"),
                ):
                    f["r2_key"] = key
                    dirty = True
                    stats["res_file_ok"] += 1
                else:
                    stats["res_file_failed"] += 1

        # `current_files` is a pointer to a file inside `versions`; reuse the
        # version-file `r2_key` instead of uploading again.
        version_keys_by_id: dict[int, str] = {}
        version_keys_by_name: dict[str, str] = {}
        for version in res.get("versions") or []:
            for f in version.get("files") or []:
                key = f.get("r2_key")
                if not key:
                    continue
                if f.get("id") is not None:
                    version_keys_by_id[int(f["id"])] = key
                if f.get("filename"):
                    version_keys_by_name[f["filename"]] = key
        for cf in res.get("current_files") or []:
            if cf.get("r2_key"):
                continue
            key = None
            if cf.get("id") is not None:
                key = version_keys_by_id.get(int(cf["id"]))
            if not key and cf.get("filename"):
                key = version_keys_by_name.get(cf["filename"])
            if key:
                cf["r2_key"] = key
                dirty = True
                stats["res_current_alias"] += 1

        if dirty:
            write_json_atomic(path, res)
    return stats


def _inline_image_urls(html: str | None) -> list[str]:
    if not html or "<img" not in html:
        return []
    out: list[str] = []
    soup = BeautifulSoup(html, "lxml")
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src:
            continue
        parsed = _safe_urlparse(src)
        if parsed is None:
            continue
        host = parsed.hostname or ""
        if not host or host in INTERNAL_HOSTS:
            continue
        out.append(src)
    return out


def _collect_inline_urls(data_dir: Path) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for path in sorted((data_dir / "threads").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for post in data.get("posts") or []:
            for u in _inline_image_urls(post.get("message_parsed")):
                if u not in seen:
                    seen.add(u)
                    out.append(u)
    for path in sorted((data_dir / "resources").glob("*.json")):
        res = json.loads(path.read_text(encoding="utf-8"))
        for u in _inline_image_urls(res.get("description_parsed")):
            if u not in seen:
                seen.add(u)
                out.append(u)
    return out


def mirror_inline(data_dir: Path, r2: R2Client, dl: Downloader) -> Counter:
    stats: Counter[str] = Counter()
    index = InlineIndex(data_dir / INLINE_INDEX_FILENAME)
    urls = _collect_inline_urls(data_dir)
    log.info("inline: %d unique external image URLs", len(urls))
    try:
        for i, url in enumerate(urls, 1):
            if index.is_done(url):
                stats["inline_skipped"] += 1
                continue
            if index.is_permanently_failed(url):
                stats["inline_skip_4xx"] += 1
                continue
            fetched = dl.fetch(url)
            if fetched is None:
                stats["inline_transport_error"] += 1
                continue
            body, ct, status = fetched
            if status >= 300:
                index.add_failed(url, status)
                stats[f"inline_http_{status}"] += 1
                continue
            sha = sha256_bytes(body)
            existing_key = index.lookup_by_hash(sha)
            if existing_key:
                # Same image at a different URL — alias, no upload.
                index.add(url, sha, existing_key, size=len(body))
                stats["inline_alias"] += 1
                continue
            key = inline_key(sha, url)
            r2.put(key, body, content_type=_content_type(url, ct))
            index.add(url, sha, key, size=len(body))
            stats["inline_uploaded"] += 1
            if i % 50 == 0:
                index.save()
                log.info("inline: %d / %d %s", i, len(urls), dict(stats))
    finally:
        index.save()
    return stats


def scan_inventory(data_dir: Path) -> Counter:
    """Walk `data/` and report what `upload` would touch.

    Pure offline — no R2 / network I/O. Useful as a smoke test and a way to
    eyeball the work the next `upload` will do.
    """
    stats: Counter[str] = Counter()
    for path in sorted((data_dir / "threads").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for post in data.get("posts") or []:
            for att in post.get("attachments") or []:
                stats["attachment_total"] += 1
                stats["attachment_done" if att.get("r2_key") else "attachment_pending"] += 1
    for path in sorted((data_dir / "users").glob("*.json")):
        u = json.loads(path.read_text(encoding="utf-8"))
        avatar_urls = u.get("avatar_urls") or {}
        if not (avatar_urls.get("l") or avatar_urls.get("m") or avatar_urls.get("o")):
            continue
        stats["avatar_total"] += 1
        stats["avatar_done" if u.get("avatar_r2_key") else "avatar_pending"] += 1
    for path in sorted((data_dir / "resources").glob("*.json")):
        r = json.loads(path.read_text(encoding="utf-8"))
        if r.get("icon_url"):
            stats["icon_total"] += 1
            stats["icon_done" if r.get("icon_r2_key") else "icon_pending"] += 1
        for v in r.get("versions") or []:
            for f in v.get("files") or []:
                stats["res_file_total"] += 1
                stats["res_file_done" if f.get("r2_key") else "res_file_pending"] += 1
        for cf in r.get("current_files") or []:
            stats["res_current_total"] += 1
            stats["res_current_aliased" if cf.get("r2_key") else "res_current_pending"] += 1
    inline_urls = _collect_inline_urls(data_dir)
    stats["inline_unique_urls"] = len(inline_urls)
    idx_path = data_dir / INLINE_INDEX_FILENAME
    if idx_path.exists():
        index = InlineIndex(idx_path)
        stats["inline_index_done"] = sum(1 for v in index.by_url.values() if v.get("r2_key"))
        stats["inline_index_failed"] = sum(1 for v in index.by_url.values() if v.get("failed"))
    return stats


def verify(data_dir: Path, r2: R2Client) -> Counter:
    """HEAD every recorded `r2_key`. Report and count missing objects."""
    stats: Counter[str] = Counter()
    seen: set[str] = set()

    def check(key: str | None, kind: str) -> None:
        if not key or key in seen:
            return
        seen.add(key)
        if r2.head(key) is None:
            stats[f"{kind}_missing"] += 1
            log.warning("%s missing in R2: %s", kind, key)
        else:
            stats[f"{kind}_ok"] += 1

    for path in sorted((data_dir / "threads").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for post in data.get("posts") or []:
            for att in post.get("attachments") or []:
                check(att.get("r2_key"), "attachment")
    for path in sorted((data_dir / "users").glob("*.json")):
        u = json.loads(path.read_text(encoding="utf-8"))
        check(u.get("avatar_r2_key"), "avatar")
    for path in sorted((data_dir / "resources").glob("*.json")):
        r = json.loads(path.read_text(encoding="utf-8"))
        check(r.get("icon_r2_key"), "resource_icon")
        for v in r.get("versions") or []:
            for f in v.get("files") or []:
                check(f.get("r2_key"), "resource_file")
    idx_path = data_dir / INLINE_INDEX_FILENAME
    if idx_path.exists():
        index = InlineIndex(idx_path)
        for entry in index.by_url.values():
            check(entry.get("r2_key"), "inline")
    return stats
