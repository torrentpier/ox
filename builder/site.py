"""Render the static site from `data/` into `dist/`.

Current scope:
- /index.html — top-level categories with their child forums
- /categories/{slug?}.{id}/ — single category page
- /forums/{slug?}.{id}/ — single forum page with all its threads
- /threads/{slug}.{id}/ — single thread, all posts on one page (no pagination)
- /resources/categories/{slug?}.{id}/ — list resources in a category
- /resources/{slug}.{id}/ — resource detail page
- copies static/ as-is

TODO: pagination, message_parsed rewrite, member pages, search, sitemap.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from .render import context_globals, make_env

log = logging.getLogger(__name__)


SLUG_FALLBACK_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """Used only when a node has no slug-bearing view_url."""
    s = SLUG_FALLBACK_RE.sub("-", (text or "").lower()).strip("-")
    return s or "node"


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


def load_resources(data_dir: Path) -> list[dict[str, Any]]:
    res_dir = data_dir / "resources"
    if not res_dir.exists():
        return []
    return sorted(
        (_read_json(p) for p in res_dir.glob("*.json")),
        key=lambda r: r["id"],
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


def node_url(node: dict[str, Any]) -> str:
    """Build the canonical URL path for a category or forum node.

    XF view_urls (e.g. `/forums/general.5/`) keep the slug. We reconstruct
    the same shape from `node_name` if available, falling back to slugified
    title, then to the bare id.
    """
    nid = node["node_id"]
    slug = node.get("node_name") or _slugify(node.get("title", ""))
    type_path = "categories" if node.get("node_type_id") == "Category" else "forums"
    return f"/{type_path}/{slug}.{nid}/"


def _write(out: Path, html: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


def _build_indexes(meta: dict[str, Any], threads: list[dict[str, Any]], resources: list[dict[str, Any]]) -> dict[str, Any]:
    nodes_by_id: dict[int, dict[str, Any]] = {n["node_id"]: n for n in meta.get("nodes", [])}
    forums = [n for n in nodes_by_id.values() if n.get("node_type_id") == "Forum"]
    categories = [n for n in nodes_by_id.values() if n.get("node_type_id") == "Category"]
    tree_map = {int(k): list(v) for k, v in (meta.get("tree_map") or {}).items()}

    threads_by_forum: dict[int, list[dict[str, Any]]] = {}
    for t in threads:
        fid = (t.get("forum") or {}).get("id") or t.get("node_id")
        if fid:
            threads_by_forum.setdefault(int(fid), []).append(t)
    for ts in threads_by_forum.values():
        ts.sort(key=lambda t: -(t.get("last_post_date") or t.get("post_date") or 0))

    resources_by_cat: dict[int, list[dict[str, Any]]] = {}
    for r in resources:
        cid = (r.get("category") or {}).get("id")
        if cid:
            resources_by_cat.setdefault(int(cid), []).append(r)
    for rs in resources_by_cat.values():
        rs.sort(key=lambda r: -(r.get("last_update") or r.get("resource_date") or 0))

    return {
        "nodes_by_id": nodes_by_id,
        "forums": sorted(forums, key=lambda n: (n.get("display_order", 0), n.get("title") or "")),
        "categories": sorted(categories, key=lambda n: (n.get("display_order", 0), n.get("title") or "")),
        "tree_map": tree_map,
        "threads_by_forum": threads_by_forum,
        "resources_by_cat": resources_by_cat,
    }


def build(data_dir: Path, out_dir: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    template_dir = repo_root / "templates"
    static_dir = repo_root / "static"

    env = make_env(template_dir)
    env.globals.update(context_globals())

    meta = load_meta(data_dir)
    threads = load_threads(data_dir)
    resources = load_resources(data_dir)
    users = load_users(data_dir)
    log.info(
        "Loaded data: %d nodes, %d threads, %d resources, %d users",
        len(meta.get("nodes", [])),
        len(threads),
        len(resources),
        len(users),
    )

    idx = _build_indexes(meta, threads, resources)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    n_static = _copy_static(static_dir, out_dir)
    log.info("Copied %d static files", n_static)

    # Helpers exposed to all templates
    env.globals["node_url"] = node_url
    env.globals["users"] = users
    env.globals["nodes_by_id"] = idx["nodes_by_id"]

    # /
    index_tmpl = env.get_template("index.html")
    _write(
        out_dir / "index.html",
        index_tmpl.render(
            categories=idx["categories"],
            forums=idx["forums"],
            tree_map=idx["tree_map"],
            threads_by_forum=idx["threads_by_forum"],
            thread_count=len(threads),
            resource_count=len(resources),
        ),
    )

    # /categories/{slug}.{id}/
    cat_tmpl = env.get_template("category.html")
    for cat in idx["categories"]:
        child_ids = idx["tree_map"].get(cat["node_id"], [])
        child_forums = [
            idx["nodes_by_id"][cid]
            for cid in child_ids
            if cid in idx["nodes_by_id"] and idx["nodes_by_id"][cid].get("node_type_id") == "Forum"
        ]
        path = (out_dir / node_url(cat).lstrip("/") / "index.html")
        _write(path, cat_tmpl.render(category=cat, forums=child_forums, threads_by_forum=idx["threads_by_forum"]))

    # /forums/{slug}.{id}/
    forum_tmpl = env.get_template("forum.html")
    for forum in idx["forums"]:
        path = (out_dir / node_url(forum).lstrip("/") / "index.html")
        _write(
            path,
            forum_tmpl.render(
                forum=forum,
                threads=idx["threads_by_forum"].get(forum["node_id"], []),
            ),
        )

    # /threads/{slug}.{id}/
    thread_tmpl = env.get_template("thread.html")
    for thread in threads:
        url_path = thread.get("url_path") or f"/threads/thread-{thread['id']}/"
        path = out_dir / url_path.lstrip("/") / "index.html"
        _write(path, thread_tmpl.render(thread=thread))
    log.info("Rendered %d thread pages", len(threads))

    # /resources/{slug}.{id}/
    resource_tmpl = env.get_template("resource.html")
    for resource in resources:
        url_path = resource.get("url_path") or f"/resources/resource-{resource['id']}/"
        path = out_dir / url_path.lstrip("/") / "index.html"
        _write(path, resource_tmpl.render(resource=resource))
    log.info("Rendered %d resource pages", len(resources))

    # /resources/categories/{slug?}.{id}/
    rcat_tmpl = env.get_template("rcategory.html")
    seen_cats: dict[int, dict[str, Any]] = {}
    for r in resources:
        cat = r.get("category") or {}
        cid = cat.get("id")
        if cid and cid not in seen_cats:
            seen_cats[cid] = cat
    for cid, cat in seen_cats.items():
        url = cat.get("view_url") or ""
        # extract path part if absolute URL
        from urllib.parse import urlparse

        url_path = urlparse(url).path or f"/resources/categories/cat-{cid}/"
        path = out_dir / url_path.lstrip("/") / "index.html"
        _write(
            path,
            rcat_tmpl.render(
                category=cat,
                resources=idx["resources_by_cat"].get(cid, []),
            ),
        )

    # /resources/ — listing of resource categories
    resources_index_tmpl = env.get_template("resources_index.html")
    _write(
        out_dir / "resources" / "index.html",
        resources_index_tmpl.render(
            categories=sorted(seen_cats.values(), key=lambda c: c.get("display_order") or 0),
            resources_by_cat=idx["resources_by_cat"],
            resource_count=len(resources),
        ),
    )

    # /search/ — placeholder until the Cloudflare Worker is wired up
    search_tmpl = env.get_template("search.html")
    _write(out_dir / "search" / "index.html", search_tmpl.render())

    # /robots.txt
    _write(
        out_dir / "robots.txt",
        "User-agent: *\nAllow: /\nSitemap: https://ox.torrentpier.com/sitemap.xml\n",
    )

    # /sitemap.xml
    _write(out_dir / "sitemap.xml", _render_sitemap(threads, resources, idx))

    log.info("Build complete: %s", out_dir)


def _render_sitemap(
    threads: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    idx: dict[str, Any],
) -> str:
    base = "https://ox.torrentpier.com"
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    def _entry(path: str, lastmod_ts: int | None = None) -> str:
        loc = f"{base}{path}"
        if lastmod_ts:
            from datetime import datetime, timezone
            iso = datetime.fromtimestamp(int(lastmod_ts), tz=timezone.utc).date().isoformat()
            return f"  <url><loc>{loc}</loc><lastmod>{iso}</lastmod></url>"
        return f"  <url><loc>{loc}</loc></url>"

    parts.append(_entry("/"))
    for cat in idx["categories"]:
        parts.append(_entry(node_url(cat)))
    for forum in idx["forums"]:
        threads_in_forum = idx["threads_by_forum"].get(forum["node_id"], [])
        lastmod = (
            threads_in_forum[0].get("last_post_date") if threads_in_forum else None
        )
        parts.append(_entry(node_url(forum), lastmod))
    for t in threads:
        parts.append(
            _entry(
                t.get("url_path") or f"/threads/thread-{t['id']}/",
                t.get("last_post_date") or t.get("post_date"),
            )
        )
    for r in resources:
        parts.append(
            _entry(
                r.get("url_path") or f"/resources/resource-{r['id']}/",
                r.get("last_update") or r.get("resource_date"),
            )
        )
    parts.append("</urlset>")
    return "\n".join(parts) + "\n"
