"""Render the static site from `data/` into `dist/`."""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .render import context_globals, make_env
from .rewrite import rewrite_html

log = logging.getLogger(__name__)


POSTS_PER_PAGE = 10  # XF default for this forum
THREADS_PER_PAGE = 30  # XF default for this forum
MEMBERS_PER_PAGE = 30

SITE_HOST = "ox.torrentpier.com"
R2_PUBLIC_BASE = "https://files-ox.torrentpier.com"


SLUG_FALLBACK_RE = re.compile(r"[^a-z0-9]+")
MEMBER_URL_RE = re.compile(r"^/members/([^/.]+)\.(\d+)/?$")


def r2_url(key: str | None) -> str | None:
    """Build a public URL for an R2 key. Returns None if `key` is falsy."""
    if not key:
        return None
    from urllib.parse import quote
    return f"{R2_PUBLIC_BASE}/{quote(key, safe='/')}"


def _load_inline_index(data_dir: Path) -> dict[str, str]:
    """`source_url -> R2 public URL` for inline images mirror successfully shipped."""
    path = data_dir / "inline_index.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8")).get("by_url") or {}
    return {src: r2_url(entry["r2_key"]) for src, entry in raw.items() if entry.get("r2_key")}


def _paginate(items: list[Any], per_page: int) -> list[tuple[int, list[Any], str, int]]:
    """Return list of (page_no, page_items, url_suffix, total_pages).

    `url_suffix` is "" for page 1 (so the canonical URL is the bare base path)
    and "page-N/" for further pages — matching XF.
    """
    if not items:
        return [(1, [], "", 1)]
    total = (len(items) + per_page - 1) // per_page
    out: list[tuple[int, list[Any], str, int]] = []
    for i in range(total):
        start = i * per_page
        end = start + per_page
        page_no = i + 1
        suffix = "" if page_no == 1 else f"page-{page_no}/"
        out.append((page_no, items[start:end], suffix, total))
    return out


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


def _member_slug(user: dict[str, Any]) -> str:
    view_url = user.get("view_url") or ""
    try:
        path = urlparse(view_url).path or ""
    except ValueError:
        path = ""
    m = MEMBER_URL_RE.match(path)
    if m:
        return m.group(1)
    return _slugify(user.get("username") or f"user-{user['id']}")


def member_url(user: dict[str, Any]) -> str:
    return f"/members/{_member_slug(user)}.{user['id']}/"


def _post_page_no(position: int | None, per_page: int = POSTS_PER_PAGE) -> int:
    """Return 1-based page number that contains a post with given position."""
    pos = int(position or 0)
    return (pos // per_page) + 1


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

    # Recursive thread count: own threads + threads in every descendant forum.
    # Mirrors what XF shows on its forum index — a parent container reports
    # the total across its subtree, not just its own immediate posts.
    thread_count_recursive: dict[int, int] = {}

    def _visit(node_id: int) -> int:
        if node_id in thread_count_recursive:
            return thread_count_recursive[node_id]
        node = nodes_by_id.get(node_id)
        total = 0
        if node and node.get("node_type_id") == "Forum":
            total += len(threads_by_forum.get(node_id, []))
        for child_id in tree_map.get(node_id, []):
            total += _visit(int(child_id))
        thread_count_recursive[node_id] = total
        return total

    for nid in nodes_by_id:
        _visit(nid)

    return {
        "nodes_by_id": nodes_by_id,
        "forums": sorted(forums, key=lambda n: (n.get("display_order", 0), n.get("title") or "")),
        "categories": sorted(categories, key=lambda n: (n.get("display_order", 0), n.get("title") or "")),
        "tree_map": tree_map,
        "threads_by_forum": threads_by_forum,
        "thread_count_recursive": thread_count_recursive,
        "resources_by_cat": resources_by_cat,
    }


def build(data_dir: Path, out_dir: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    template_dir = repo_root / "templates"
    static_dir = repo_root / "static"

    env = make_env(template_dir)

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

    # Pin the build timestamp to the export so identical `data/` -> identical `dist/`.
    env.globals.update(context_globals(exported_at=meta.get("exported_at")))

    idx = _build_indexes(meta, threads, resources)

    thread_url_map: dict[int, str] = {
        int(t["id"]): t["url_path"] for t in threads if t.get("url_path")
    }
    forum_url_map: dict[int, str] = {
        int(f["node_id"]): node_url(f) for f in idx["forums"]
    }
    member_url_map: dict[int, str] = {
        int(uid): member_url(u) for uid, u in users.items()
    }
    inline_url_map = _load_inline_index(data_dir)
    attachment_url_map: dict[int, str] = {}
    for t in threads:
        for p in t.get("posts") or []:
            for a in p.get("attachments") or []:
                key = a.get("r2_key")
                if key:
                    attachment_url_map[int(a["id"])] = r2_url(key)
    log.info(
        "asset maps: %d attachments, %d inline external",
        len(attachment_url_map),
        len(inline_url_map),
    )

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    n_static = _copy_static(static_dir, out_dir)
    log.info("Copied %d static files", n_static)

    # Helpers exposed to all templates
    env.globals["node_url"] = node_url
    env.globals["member_url"] = member_url
    env.globals["r2_url"] = r2_url
    env.globals["users"] = users
    env.globals["nodes_by_id"] = idx["nodes_by_id"]
    env.globals["thread_count_recursive"] = idx["thread_count_recursive"]

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

    # /forums/{slug}.{id}/page-N/
    forum_tmpl = env.get_template("forum.html")
    forum_pages = 0
    for forum in idx["forums"]:
        base_url = node_url(forum)
        threads_in_forum = idx["threads_by_forum"].get(forum["node_id"], [])
        child_ids = idx["tree_map"].get(forum["node_id"], [])
        child_forums = [
            idx["nodes_by_id"][cid]
            for cid in child_ids
            if cid in idx["nodes_by_id"]
            and idx["nodes_by_id"][cid].get("node_type_id") == "Forum"
        ]
        for page_no, page_threads, suffix, total_pages in _paginate(threads_in_forum, THREADS_PER_PAGE):
            page_url = f"{base_url}{suffix}"
            path = out_dir / page_url.lstrip("/") / "index.html"
            _write(
                path,
                forum_tmpl.render(
                    forum=forum,
                    threads=page_threads,
                    child_forums=child_forums if page_no == 1 else [],
                    page_no=page_no,
                    total_pages=total_pages,
                    base_url=base_url,
                ),
            )
            forum_pages += 1
    log.info("Rendered %d forum pages", forum_pages)

    # /threads/{slug}.{id}/page-N/
    thread_tmpl = env.get_template("thread.html")
    thread_pages = 0
    for thread in threads:
        # Sanitise once before pagination — same content on every page
        for post in thread.get("posts", []):
            post["message_parsed"] = rewrite_html(
                post.get("message_parsed"),
                thread_url_map=thread_url_map,
                forum_url_map=forum_url_map,
                member_url_map=member_url_map,
                attachment_url_map=attachment_url_map,
                inline_url_map=inline_url_map,
            )
        base_url = thread.get("url_path") or f"/threads/thread-{thread['id']}/"
        posts_list = thread.get("posts", [])
        for page_no, page_posts, suffix, total_pages in _paginate(posts_list, POSTS_PER_PAGE):
            page_url = f"{base_url}{suffix}"
            path = out_dir / page_url.lstrip("/") / "index.html"
            _write(
                path,
                thread_tmpl.render(
                    thread=thread,
                    page_posts=page_posts,
                    page_no=page_no,
                    total_pages=total_pages,
                    base_url=base_url,
                ),
            )
            thread_pages += 1
    log.info("Rendered %d thread pages (across %d threads)", thread_pages, len(threads))

    # /posts/{id}/ → meta-refresh redirect into the right thread page + anchor.
    # Old XF deep-links land here regardless of which page they belonged to.
    redirect_tmpl = env.get_template("redirect.html")
    redirect_count = 0
    for thread in threads:
        base_url = thread.get("url_path") or f"/threads/thread-{thread['id']}/"
        for post in thread.get("posts", []):
            pid = post.get("id")
            if not pid:
                continue
            page_no = _post_page_no(post.get("position"))
            suffix = "" if page_no == 1 else f"page-{page_no}/"
            target = f"{base_url}{suffix}#post-{pid}"
            _write(
                out_dir / "posts" / str(pid) / "index.html",
                redirect_tmpl.render(
                    target=target,
                    title=f"Post #{pid} in “{thread.get('title', '')}”",
                ),
            )
            redirect_count += 1
    log.info("Rendered %d post redirects", redirect_count)

    # /resources/{slug}.{id}/
    resource_tmpl = env.get_template("resource.html")
    for resource in resources:
        resource["description_parsed"] = rewrite_html(
            resource.get("description_parsed"),
            thread_url_map=thread_url_map,
            forum_url_map=forum_url_map,
            member_url_map=member_url_map,
            attachment_url_map=attachment_url_map,
            inline_url_map=inline_url_map,
        )
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

    # /members/ — paginated index, /members/{slug}.{id}/ — per-user page
    member_tmpl = env.get_template("member.html")
    members_index_tmpl = env.get_template("members_index.html")
    members_sorted = sorted(
        users.values(),
        key=lambda u: (-(u.get("message_count") or 0), (u.get("username") or "").lower()),
    )
    for u in members_sorted:
        url = member_url(u)
        _write(out_dir / url.lstrip("/") / "index.html", member_tmpl.render(user=u))
    for page_no, page_users, suffix, total_pages in _paginate(members_sorted, MEMBERS_PER_PAGE):
        page_url = f"/members/{suffix}"
        _write(
            out_dir / page_url.lstrip("/") / "index.html",
            members_index_tmpl.render(
                members=page_users,
                page_no=page_no,
                total_pages=total_pages,
                base_url="/members/",
                total=len(members_sorted),
            ),
        )
    log.info("Rendered %d member pages", len(members_sorted))

    # /search/ — placeholder until the Cloudflare Worker is wired up
    search_tmpl = env.get_template("search.html")
    _write(out_dir / "search" / "index.html", search_tmpl.render())

    # /robots.txt
    _write(
        out_dir / "robots.txt",
        f"User-agent: *\nAllow: /\nSitemap: https://{SITE_HOST}/sitemap.xml\n",
    )

    # /sitemap.xml
    _write(out_dir / "sitemap.xml", _render_sitemap(threads, resources, idx, members_sorted))

    # GitHub Pages custom-domain marker
    _write(out_dir / "CNAME", f"{SITE_HOST}\n")

    log.info("Build complete: %s", out_dir)


def _render_sitemap(
    threads: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    idx: dict[str, Any],
    members: list[dict[str, Any]],
) -> str:
    base = f"https://{SITE_HOST}"
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
    for u in members:
        parts.append(_entry(member_url(u), u.get("last_activity")))
    parts.append("</urlset>")
    return "\n".join(parts) + "\n"
