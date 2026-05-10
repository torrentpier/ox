"""Render the static site from `data/` into `dist/`.

This first slice is intentionally minimal:
- /index.html with a flat list of forums (categories will follow)
- /threads/{slug}.{id}/index.html for every exported thread (no pagination yet)
- copies static/ as-is to the output root

Pagination, forum listings, resources, member pages and the `message_parsed`
rewrite pass are TODO — see PLAN.md.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from .render import context_globals, make_env

log = logging.getLogger(__name__)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_meta(data_dir: Path) -> dict[str, Any]:
    meta_path = data_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"{meta_path} missing — run `xf-export nodes` first")
    return _read_json(meta_path)


def load_threads(data_dir: Path) -> list[dict[str, Any]]:
    threads_dir = data_dir / "threads"
    if not threads_dir.exists():
        return []
    return sorted(
        (_read_json(p) for p in threads_dir.glob("*.json")),
        key=lambda t: t["id"],
    )


def load_users(data_dir: Path) -> dict[int, dict[str, Any]]:
    users_dir = data_dir / "users"
    if not users_dir.exists():
        return {}
    out: dict[int, dict[str, Any]] = {}
    for p in users_dir.glob("*.json"):
        u = _read_json(p)
        out[int(u["id"])] = u
    return out


def _copy_static(static_dir: Path, out_dir: Path) -> int:
    if not static_dir.exists():
        return 0
    n = 0
    for src in static_dir.rglob("*"):
        if src.is_file() and src.name != ".gitkeep":
            rel = src.relative_to(static_dir)
            dst = out_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    return n


def _index_forums(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Flat list of forums sorted by display_order then title."""
    return sorted(
        (n for n in meta.get("nodes", []) if n.get("node_type_id") == "Forum"),
        key=lambda n: (n.get("display_order", 0), n.get("title") or ""),
    )


def build(data_dir: Path, out_dir: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    template_dir = repo_root / "templates"
    static_dir = repo_root / "static"

    env = make_env(template_dir)
    env.globals.update(context_globals())

    meta = load_meta(data_dir)
    threads = load_threads(data_dir)
    users = load_users(data_dir)
    log.info(
        "Loaded data: %d nodes, %d threads, %d users",
        len(meta.get("nodes", [])),
        len(threads),
        len(users),
    )

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    n_static = _copy_static(static_dir, out_dir)
    log.info("Copied %d static files", n_static)

    index_tmpl = env.get_template("index.html")
    (out_dir / "index.html").write_text(
        index_tmpl.render(meta=meta, forums=_index_forums(meta), thread_count=len(threads)),
        encoding="utf-8",
    )

    thread_tmpl = env.get_template("thread.html")
    rendered = 0
    for thread in threads:
        url_path = thread.get("url_path") or f"/threads/thread-{thread['id']}/"
        out_path = out_dir / url_path.lstrip("/") / "index.html"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            thread_tmpl.render(thread=thread, users=users, meta=meta),
            encoding="utf-8",
        )
        rendered += 1
    log.info("Rendered %d thread pages", rendered)
