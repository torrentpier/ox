"""Mirror pipeline: scan `data/`, upload missing assets to R2, update JSON.

Each stage is independently idempotent — an asset with a non-empty `r2_key`
is skipped. A second `xf-mirror upload` after a clean run is a no-op.

Uploads run through a `ThreadPoolExecutor`; boto3 and httpx clients are
thread-safe under their default pools. The `Downloader._throttle` lock keeps
the global request rate at `MIRROR_RPS` regardless of worker count.

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any
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
DEFAULT_WORKERS = 8


@dataclass
class UploadTask:
    """One pending upload — enough state to write back into JSON afterwards."""

    src_url: str
    target_key: str
    asset_ref: dict[str, Any]
    json_path: Path
    field_name: str = "r2_key"
    authenticated: bool = False
    filename_hint: str | None = None
    kind: str = "asset"  # for stats keys


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


def _ensure_uploaded_one(
    task: UploadTask, r2: R2Client, dl: Downloader, *, force: bool = False
) -> tuple[UploadTask, str]:
    """Worker function: HEAD R2; download + upload otherwise.

    `force=True` skips the HEAD check and always re-downloads / re-puts.
    Returns the task plus a status string used for stats and to decide whether
    to set `r2_key` on the asset (`ok` / `skipped` mean yes; anything else
    means leave it untouched).
    """
    try:
        if not force and r2.head(task.target_key) is not None:
            return task, "skipped"
        fetched = dl.fetch(task.src_url, authenticated=task.authenticated)
        if fetched is None:
            return task, "transport_error"
        body, ct, status = fetched
        if status >= 300:
            return task, f"http_{status}"
        r2.put(
            task.target_key,
            body,
            content_type=_content_type(task.filename_hint, ct),
        )
        return task, "ok"
    except Exception as e:  # boto3 ClientError, network, etc.
        log.warning("upload error %s -> %s: %s", task.src_url, task.target_key, e)
        return task, "error"


def _run_uploads(
    tasks: list[UploadTask],
    r2: R2Client,
    dl: Downloader,
    workers: int,
    *,
    progress_every: int = 200,
    label: str = "upload",
    force: bool = False,
) -> tuple[Counter, list[tuple[UploadTask, str]]]:
    """Run uploads across `workers` threads, returning stats + per-task status."""
    stats: Counter[str] = Counter()
    results: list[tuple[UploadTask, str]] = []
    if not tasks:
        return stats, results
    log.info("%s: %d tasks, %d workers (force=%s)", label, len(tasks), workers, force)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [
            ex.submit(_ensure_uploaded_one, t, r2, dl, force=force) for t in tasks
        ]
        for i, fut in enumerate(as_completed(futures), 1):
            task, status = fut.result()
            stats[f"{task.kind}_{status}"] += 1
            results.append((task, status))
            if i % progress_every == 0 or i == len(tasks):
                log.info("%s: %d / %d %s", label, i, len(tasks), dict(stats))
    return stats, results


def _apply_and_save(
    files: dict[Path, dict[str, Any]],
    results: list[tuple[UploadTask, str]],
) -> int:
    """Set `r2_key` on each successful task, atomically rewrite dirty JSON."""
    dirty: set[Path] = set()
    for task, status in results:
        if status in ("ok", "skipped"):
            task.asset_ref[task.field_name] = task.target_key
            dirty.add(task.json_path)
    for path in dirty:
        write_json_atomic(path, files[path])
    return len(dirty)


def mirror_attachments(
    data_dir: Path,
    r2: R2Client,
    dl: Downloader,
    workers: int = DEFAULT_WORKERS,
    *,
    force: bool = False,
) -> Counter:
    paths = sorted((data_dir / "threads").glob("*.json"))
    files: dict[Path, dict[str, Any]] = {}
    tasks: list[UploadTask] = []
    pre: Counter[str] = Counter()
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        files[path] = data
        for post in data.get("posts") or []:
            for att in post.get("attachments") or []:
                if att.get("r2_key") and not force:
                    pre["attachment_already_done"] += 1
                    continue
                src = att.get("src_url")
                if not src:
                    pre["attachment_no_src"] += 1
                    continue
                tasks.append(
                    UploadTask(
                        src_url=src,
                        target_key=attachment_key(
                            att["id"], att.get("filename") or f"{att['id']}.bin"
                        ),
                        asset_ref=att,
                        json_path=path,
                        filename_hint=att.get("filename"),
                        kind="attachment",
                    )
                )
    stats, results = _run_uploads(
        tasks, r2, dl, workers, label="attachments", force=force
    )
    n_files = _apply_and_save(files, results)
    log.info("attachments: rewrote %d JSON files", n_files)
    stats.update(pre)
    return stats


# Avatar size priority — highest quality first. `h` is the hi-res (retina)
# variant XF generates from the original upload; `o` is the unmodified
# original which can be smaller than `h` for legacy users.
AVATAR_SIZE_PRIORITY = ("h", "o", "l", "m", "s")


def mirror_avatars(
    data_dir: Path,
    r2: R2Client,
    dl: Downloader,
    workers: int = DEFAULT_WORKERS,
    *,
    force: bool = False,
) -> Counter:
    paths = sorted((data_dir / "users").glob("*.json"))
    files: dict[Path, dict[str, Any]] = {}
    tasks: list[UploadTask] = []
    pre: Counter[str] = Counter()
    for path in paths:
        user = json.loads(path.read_text(encoding="utf-8"))
        files[path] = user
        if user.get("avatar_r2_key") and not force:
            pre["avatar_already_done"] += 1
            continue
        avatar_urls = user.get("avatar_urls") or {}
        src = next(
            (avatar_urls[s] for s in AVATAR_SIZE_PRIORITY if avatar_urls.get(s)),
            None,
        )
        if not src:
            pre["avatar_no_src"] += 1
            continue
        key = avatar_key(user["id"], src)
        tasks.append(
            UploadTask(
                src_url=src,
                target_key=key,
                asset_ref=user,
                json_path=path,
                field_name="avatar_r2_key",
                filename_hint=key,
                kind="avatar",
            )
        )
    stats, results = _run_uploads(
        tasks, r2, dl, workers, label="avatars", force=force
    )
    _apply_and_save(files, results)
    stats.update(pre)
    return stats


def mirror_resources(
    data_dir: Path,
    r2: R2Client,
    dl: Downloader,
    workers: int = DEFAULT_WORKERS,
    *,
    force: bool = False,
) -> Counter:
    paths = sorted((data_dir / "resources").glob("*.json"))
    files: dict[Path, dict[str, Any]] = {}
    tasks: list[UploadTask] = []
    pre: Counter[str] = Counter()
    for path in paths:
        res = json.loads(path.read_text(encoding="utf-8"))
        files[path] = res
        rid = int(res["id"])

        icon = res.get("icon_url")
        if icon:
            if res.get("icon_r2_key") and not force:
                pre["icon_already_done"] += 1
            else:
                key = resource_icon_key(rid, icon)
                tasks.append(
                    UploadTask(
                        src_url=icon,
                        target_key=key,
                        asset_ref=res,
                        json_path=path,
                        field_name="icon_r2_key",
                        filename_hint=key,
                        kind="icon",
                    )
                )

        for version in res.get("versions") or []:
            vid = int(version["id"])
            for f in version.get("files") or []:
                if f.get("r2_key") and not force:
                    pre["res_file_already_done"] += 1
                    continue
                src = f.get("src_url")
                if not src:
                    pre["res_file_no_src"] += 1
                    continue
                key = resource_file_key(
                    rid, vid, f.get("filename") or f"file-{f.get('id')}.bin"
                )
                tasks.append(
                    UploadTask(
                        src_url=src,
                        target_key=key,
                        asset_ref=f,
                        json_path=path,
                        authenticated=True,
                        filename_hint=f.get("filename"),
                        kind="res_file",
                    )
                )

    stats, results = _run_uploads(
        tasks, r2, dl, workers, label="resources", force=force
    )
    _apply_and_save(files, results)
    stats.update(pre)

    # current_files: alias the matching version file's r2_key (no upload).
    alias_dirty: set[Path] = set()
    for path, res in files.items():
        version_keys_by_id: dict[int, str] = {}
        version_keys_by_name: dict[str, str] = {}
        for version in res.get("versions") or []:
            for f in version.get("files") or []:
                k = f.get("r2_key")
                if not k:
                    continue
                if f.get("id") is not None:
                    version_keys_by_id[int(f["id"])] = k
                if f.get("filename"):
                    version_keys_by_name[f["filename"]] = k
        for cf in res.get("current_files") or []:
            if cf.get("r2_key"):
                continue
            k = None
            if cf.get("id") is not None:
                k = version_keys_by_id.get(int(cf["id"]))
            if not k and cf.get("filename"):
                k = version_keys_by_name.get(cf["filename"])
            if k:
                cf["r2_key"] = k
                stats["res_current_alias"] += 1
                alias_dirty.add(path)
    for path in alias_dirty:
        write_json_atomic(path, files[path])
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


def mirror_inline(
    data_dir: Path,
    r2: R2Client,
    dl: Downloader,
    workers: int = DEFAULT_WORKERS,
    *,
    force: bool = False,
) -> Counter:
    """Concurrent inline image mirror with sha256 dedupe.

    Two URLs that point at the same bytes share one R2 key. The persistent
    index at `data/inline_index.json` records `url -> {sha256, r2_key, size}`
    plus negative `{failed, status}` entries that suppress retry of permanent
    4xx URLs.
    """
    stats: Counter[str] = Counter()
    index = InlineIndex(data_dir / INLINE_INDEX_FILENAME)
    lock = Lock()
    urls = _collect_inline_urls(data_dir)
    pending: list[str] = []
    for url in urls:
        if not force:
            if index.is_done(url):
                stats["inline_already_done"] += 1
                continue
            if index.is_permanently_failed(url):
                stats["inline_already_4xx"] += 1
                continue
        pending.append(url)
    log.info(
        "inline: %d pending of %d unique URLs (%d workers)",
        len(pending),
        len(urls),
        workers,
    )

    def worker(url: str) -> str:
        try:
            fetched = dl.fetch(url)
        except Exception as e:
            log.warning("inline fetch error %s: %s", url, e)
            return "transport_error"
        if fetched is None:
            return "transport_error"
        body, ct, status = fetched
        if status >= 300:
            with lock:
                index.add_failed(url, status)
            return f"http_{status}"
        sha = sha256_bytes(body)
        with lock:
            existing = index.lookup_by_hash(sha)
            if existing:
                index.add(url, sha, existing, size=len(body))
                return "alias"
        key = inline_key(sha, url)
        try:
            r2.put(key, body, content_type=_content_type(url, ct))
        except Exception as e:
            log.warning("inline upload error %s: %s", url, e)
            return "upload_error"
        with lock:
            index.add(url, sha, key, size=len(body))
        return "uploaded"

    try:
        if pending:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(worker, u) for u in pending]
                for i, fut in enumerate(as_completed(futures), 1):
                    result = fut.result()
                    stats[f"inline_{result}"] += 1
                    if i % 50 == 0 or i == len(pending):
                        with lock:
                            index.save()
                        log.info(
                            "inline: %d / %d %s", i, len(pending), dict(stats)
                        )
    finally:
        with lock:
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


def verify(data_dir: Path, r2: R2Client, workers: int = DEFAULT_WORKERS) -> Counter:
    """HEAD every recorded `r2_key`. Reports missing objects."""
    stats: Counter[str] = Counter()

    def collect() -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add(key: str | None, kind: str) -> None:
            if not key or key in seen:
                return
            seen.add(key)
            items.append((key, kind))

        for path in sorted((data_dir / "threads").glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for post in data.get("posts") or []:
                for att in post.get("attachments") or []:
                    add(att.get("r2_key"), "attachment")
        for path in sorted((data_dir / "users").glob("*.json")):
            u = json.loads(path.read_text(encoding="utf-8"))
            add(u.get("avatar_r2_key"), "avatar")
        for path in sorted((data_dir / "resources").glob("*.json")):
            r = json.loads(path.read_text(encoding="utf-8"))
            add(r.get("icon_r2_key"), "resource_icon")
            for v in r.get("versions") or []:
                for f in v.get("files") or []:
                    add(f.get("r2_key"), "resource_file")
        idx_path = data_dir / INLINE_INDEX_FILENAME
        if idx_path.exists():
            index = InlineIndex(idx_path)
            for entry in index.by_url.values():
                add(entry.get("r2_key"), "inline")
        return items

    items = collect()
    log.info("verify: %d unique r2_keys, %d workers", len(items), workers)

    def check(item: tuple[str, str]) -> tuple[str, str, bool]:
        key, kind = item
        return key, kind, r2.head(key) is not None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for key, kind, present in ex.map(check, items):
            stats[f"{kind}_{'ok' if present else 'missing'}"] += 1
            if not present:
                log.warning("missing in R2: %s (%s)", key, kind)
    return stats
