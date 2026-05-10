# Development plan: torrentpier.com static archive

This document is the single source of truth for the project. It must be
detailed enough that work can be paused and resumed at any point — by the
same or a different operator — without losing context. Update it after every
meaningful decision or completed step.

## Status snapshot (2026-05-11)

| # | Item                                                       | State |
|---|------------------------------------------------------------|-------|
|   | Branch                                                     | `feat/archive` (14 commits, **not pushed yet**) |
|   | Repo skeleton (dirs + meta files)                          | Done (`c12ba69`) |
|   | API surface verified (probed live)                         | Done — see "API surface" below |
|   | Wrangler installed (Homebrew)                              | Done — 4.90.0 |
|   | Cloudflare auth (`wrangler login`)                         | **Pending — must be run interactively by user** |
|   | Python venv + deps (`uv venv`, py3.13)                     | Done — `.venv/` in repo (gitignored) |
| 1 | Exporter — `nodes` stage                                   | Done — 34 nodes (7 categories, 27 forums) |
| 1 | Exporter — `threads` stage                                 | Done — 3,280 threads, 42,623 posts (matches `Σ reply_count + 1` exactly) |
| 1 | Exporter — `users` stage (incidental from `post.User`)     | Done — 1,085 unique authors |
| 1 | Exporter — `resources` stage                               | Done — 230 resources, 548 versions, 511 files (62.83 MiB binary) |
| 2 | Mirror — R2 bucket + custom domain                         | Not started — needs `wrangler login` |
| 2 | Mirror — Python uploader (boto3, atomic JSON update)       | Not started |
| 2 | Mirror — rewrite asset URLs in `data/*.json` to `r2_key`   | Not started |
| 3 | Builder — index + category + forum (paginated 30/page)     | Done |
| 3 | Builder — thread (paginated 10/page) with avatars + badges | Done |
| 3 | Builder — resource pages with version table                | Done |
| 3 | Builder — `message_parsed` sanitiser + URL canonicaliser   | Done (sans R2 — attachments still point at torrentpier.com) |
| 3 | Builder — `/resources/`, `/search/`, `sitemap.xml`, `robots.txt` | Done |
| 3 | Builder — wire R2 URLs after mirror stage runs             | Not started |
| 3 | Builder — `/posts/{id}/` redirect to thread anchor         | Not started |
| 3 | Builder — `/members/{slug}.{id}/` minimal pages            | Not started |
| 4 | Search — Python indexer (lemmatised plain text → SQL)      | Not started |
| 4 | Search — Cloudflare D1 schema + import                     | Not started — needs `wrangler login` |
| 4 | Search — TypeScript Worker exposing `/search?q=`           | Not started |
| 4 | Search — frontend on `/search/` page                       | Not started (placeholder lives) |
| 5 | Deploy — GitHub Actions build + Pages deploy               | Not started |
| 5 | Deploy — DNS: `ox.torrentpier.com` CNAME → Pages           | Not started |
| 5 | Deploy — Bulk Redirect from `torrentpier.com/*` → archive  | Not started |
| 5 | Cutover — confirm archive live, revoke super-user API key  | Not started |

## Source forum

- URL: `https://torrentpier.com`
- Engine: XenForo 2 with the Resource Manager add-on
- Currently in read-only / maintenance mode — snapshot is consistent
- Volume: 3,280 visible threads, 42,623 forum posts, 1,085 posting users
  (5,194 registered total; the rest are lurkers and don't appear in the
  archive), 230 resources

## Target hosts

- Site: **`ox.torrentpier.com`** (CNAME → GitHub Pages)
- Files: **`files-ox.torrentpier.com`** (Cloudflare R2 custom domain)
  - Hyphenated, not `files.ox.torrentpier.com`, because Cloudflare's
    universal SSL doesn't cover 4th-level subdomains.
- Search API: **`search-ox.torrentpier.com`** (Cloudflare Worker)

## Decisions log

| #  | Decision                                                                                          | Reasoning                                                                                                  |
|----|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------|
| 1  | Intermediate format = JSON (one file per thread / resource), checked into git                     | Source of truth, diffable, trivially editable, easy GDPR-style deletes                                     |
| 2  | Final format = pre-rendered HTML on GitHub Pages                                                  | Longevity, $0 cost, archive is read-only forever                                                           |
| 3  | Files (attachments, avatars, inline images) on Cloudflare R2 with custom domain                   | GitHub Pages 1 GB repo limit; R2 has 10 GB free tier and zero egress                                       |
| 4  | Search = Cloudflare Worker + D1 (SQLite FTS5), not Pagefind                                       | FTS5 + Russian lemmatisation gives meaningful search; Pagefind is literal-only for Russian                 |
| 5  | Exporter / builder language = Python (3.11+, currently running 3.13)                              | Faster iteration on JSON munging + Jinja2 + BS4                                                            |
| 6  | URL scheme = identical to XenForo (`/threads/{slug}.{id}/page-N/`, `/forums/{slug}.{id}/page-N/`) | Old links from search engines / chats keep working without redirect rules                                  |
| 7  | Don't carry: deleted/hidden posts, private conversations, reactions                               | Per user                                                                                                   |
| 8  | Carry: text + attachments + avatars + per-post username/title/group + resources + all resource versions | Per user                                                                                              |
| 9  | API auth via super-user key + dotenv (`XF_API_KEY`, `XF_API_USER`)                                | Forum is being shut down; key will be revoked post-export                                                  |
| 10 | Subdomain via CNAME, redirects from old hostname handled via Cloudflare (out of scope for repo)   | Per user                                                                                                   |
| 11 | Hostnames: `ox.torrentpier.com` for site, `files-ox.torrentpier.com` for R2                       | Cloudflare universal SSL doesn't cover 4th-level                                                           |
| 12 | Carry resource binaries: **all versions of all 230 resources**                                    | Total size measured at 62.83 MiB — negligible relative to forum attachments                                |
| 13 | Pagination is server-fixed and per-endpoint: `per_page=30` for forum/thread listings, `per_page=10` for thread post pagination. The `per_page` query param is ignored. | Confirmed by probing `per_page=20/30/50/100/200` against forum 17 (47 threads) and observing `pagination.per_page` in thread 37048 detail page. |
| 14 | R2 provisioning via `wrangler` from this machine; `wrangler login` runs interactively by the user | Avoids handling a Cloudflare API token in the repo or in dotenv                                            |
| 15 | In `/api/threads/{id}/?with_posts=1`: `posts` and `pagination` are top-level keys; attachments are named `Attachments` (capital A). | Verified against thread 37048; embedded resource conventions in XF API |
| 16 | `User` object is embedded in every post under `post.User` — bulk `/api/users/{id}` calls are unnecessary in the common case | Saves ~5,000 requests; only fetch `/api/users/{id}` for users referenced via `[USER=N]` mentions / quotes who never authored a post |
| 17 | `/api/resources/{id}/versions` may return `400 xfrm_this_resource_is_not_versioned` for single-file or fileless resources living in a versioned category. Treat as zero versions and rely on `current_files`. | Discovered against resource 254 ("Мод noindex,nofollow"); silently skipping kept the run going. |
| 18 | Resource description: store `description_parsed` (rendered HTML) alongside `DescriptionAttachments` so the builder renders it the same way as posts. | Mirrors the post schema (`message_parsed` + `Attachments`); avoids re-parsing BBCode. |
| 19 | Builder URL canonicaliser rewrites every internal link in `message_parsed` to use the **current** slug for that thread/forum id. | XF in old posts often has Cyrillic slugs (e.g. `/threads/Открытие-форума.2/`) that don't match the static files we render (`/threads/otkrytie-foruma.2/`). |
| 20 | Builder pagination: 30 threads/page on forums, 10 posts/page on threads. Page 1 lives at the bare base URL; later pages at `/page-N/`. | Matches XF defaults exactly so XF's own internal links continue to land on the right page. |

## API surface (verified against torrentpier.com on 2026-05-11)

Probed with a super-user key. Endpoints not listed were not checked.

| Endpoint                                                | Status | Notes                                                                                                  |
|---------------------------------------------------------|--------|--------------------------------------------------------------------------------------------------------|
| `GET /api/`                                             | 200    | Returns `version_id`, `site_title`, key info                                                           |
| `GET /api/me`                                           | 200    | Acting user                                                                                            |
| `GET /api/nodes`                                        | 200    | Categories + forums + pages + links — full tree via `tree_map` + flat `nodes[]` array                  |
| `GET /api/nodes/flattened`                              | 200    | Alternative flat form                                                                                  |
| `GET /api/forums/{node_id}`                             | 200    | Single forum incl. breadcrumbs and `view_url` with slug                                                |
| `GET /api/forums/{node_id}/threads?page=N`              | 200    | Threads in forum, paginated. **Server-fixed `per_page=30`** (query param ignored).                     |
| `GET /api/threads/{id}/?with_posts=1&page=N`            | 200    | Returns `{thread, posts, pagination}` at top level. **Server-fixed `per_page=10` for posts.** Each post has `User` embedded |
| `GET /api/threads/{id}/posts?page=N`                    | 200    | Posts-only listing if needed                                                                           |
| `GET /api/users/{id}`                                   | 200    | Full user object incl. `avatar_urls`, `user_title`, `is_admin/moderator/staff`. Rarely needed         |
| `GET /api/resources?page=N`                             | 200    | Resource Manager content with embedded `Category` per resource. Server-fixed `per_page=30`.            |
| `GET /api/resources/{id}`                               | 200    | Single resource detail; includes `current_files[]` and `Category`                                      |
| `GET /api/resources/{id}/versions`                      | 200/400 | All versions with `files[].size` and `download_url`. **400 `xfrm_this_resource_is_not_versioned`** for single-file resources |
| Attachment download                                     | —      | Each attachment object carries `direct_url` (e.g. `https://torrentpier.com/attachments/123-webp.508/`). No need for `/api/attachments/{id}/data`. |
| Resource version file download                          | —      | `download_url` in `versions[].files[]` is `https://torrentpier.com/api/resource-versions/{vid}/download?file={fid}` — **requires `XF-Api-Key` header**, mirror stage must download via authenticated client and rehost on R2 |
| `GET /api/categories`                                   | 404    | Categories live under `/api/nodes`                                                                     |
| `GET /api/forums` (collection)                          | 404    | Use `/api/nodes`                                                                                       |
| `GET /api/tags`                                         | 404    | No bulk tag listing; tags appear inline on threads                                                     |
| `GET /api/rm`, `/api/rm/*`                              | 404    | Resource Manager API root is `/api/resources`                                                          |
| `GET /api/resources/categories`                         | 404    | Categories only appear embedded inside resource objects                                                |
| `GET /api/resources/{id}/icon`                          | 404    | Icon URL lives on the `resource` object                                                                |
| `GET /api/resources/{id}/files`                         | 404    | Files are inside `versions[].files[]`                                                                  |
| `GET /api/profile-posts/`                               | TBD    | Not yet probed — may be how to capture the missing 2,850 messages                                      |

### Schema highlights

**Thread response envelope** (`/api/threads/{id}/?with_posts=1&page=N`):
```jsonc
{
  "thread":     { /* metadata, see below */ },
  "posts":      [ /* this page's posts, max 10 */ ],
  "pagination": {"current_page": N, "last_page": M, "per_page": 10, "shown": 10, "total": 198}
}
```

**Post**: `post_id`, `position`, `thread_id`, `message_parsed` (rendered HTML — **always use this**), `last_edit_date`, `Attachments` (capital A), `User` (full embedded object). Drop `can_*`, `is_first/last_post`, `is_reacted_to`, `is_unread`, `reaction_score`, `view_url`, `warning_message`.

**Attachment** (per-post `Attachments[]`):
```jsonc
{
  "attachment_id": 508, "content_id": 9435, "content_type": "post",
  "filename": "123.webp", "file_size": 8614,
  "width": 416, "height": 160, "is_audio": false, "is_video": false,
  "attach_date": 1326481417, "view_count": 1091,
  "direct_url": "https://torrentpier.com/attachments/123-webp.508/",
  "thumbnail_url": "https://torrentpier.com/data/attachments/0/508-...jpg?hash=..."
}
```

**User** (embedded under `post.User` and `resource.User`): `user_id`, `username`, `user_title`, `user_group_id`, `secondary_group_ids[]`, `is_admin`, `is_moderator`, `is_staff`, `avatar_urls.{o,h,l,m,s}`, `view_url`, `register_date`, `message_count`, `last_activity`.

**Resource version**: `resource_version_id`, `version_string`, `release_date`, `download_count`, `version_state`, `files[]` with `id`, `filename`, `size`, `download_url`.

**Pagination envelope** (every listing endpoint): `current_page`, `last_page`, `per_page`, `shown`, `total`. `per_page` is **server-fixed**.

## Pipeline overview

```
XenForo REST API
        |
        v
  [1] exporter/    --> data/threads/*.json (3280)
                       data/resources/*.json (230)
                       data/users/*.json (1085)
                       data/meta.json
        |
        +----> [2] mirror/        --> Cloudflare R2 (attachments, avatars,
        |                              inline images, resource files)
        v
  [3] builder/     --> dist/  (HTML + CSS + JS, sitemap, canonical URLs)
        |
        +----> [4] search/        --> Cloudflare D1 (FTS5 over lemmatised post bodies)
        |                            + Worker exposing /search?q=...
        v
  [5] deploy via GitHub Actions --> GitHub Pages --> ox.torrentpier.com
```

Verified request budget for the exporter: ~5,300 calls at 3 rps ≈ **30 min**
clean run (matches what was actually observed).

## Stage 1 — Exporter (Done)

Code in `exporter/`:
- `api.py` — `XfClient` wrapper (`httpx`, `tenacity` retry, token-bucket rate
  limiter; `XF_API_RPS` env var, default 3 rps).
- `io.py` — atomic JSON writer (`tempfile` + `os.replace`).
- `nodes.py` — exports `/api/nodes` to `data/meta.json`.
- `threads.py` — paginates `/api/forums/{id}/threads` then per-thread
  `/api/threads/{id}/?with_posts=1&page=N`; merges all pages into one
  `data/threads/{id}.json`. Captures embedded `post.User` into a shared
  `UserCache`.
- `users.py` — `UserCache` flushes one normalised user JSON per id.
- `resources.py` — paginates `/api/resources`, fetches detail + versions
  per resource. Handles `400 xfrm_this_resource_is_not_versioned` and
  falls back to `current_files`.
- `main.py` — argparse CLI: `xf-export {nodes,threads,resources}` with
  `--data`, `--force`, `--only-thread`, `--only-resource`, `--forum N`.

To re-run any stage:
```bash
.venv/bin/python -m exporter --data data nodes
.venv/bin/python -m exporter --data data threads        # idempotent: skips existing /threads/{id}.json
.venv/bin/python -m exporter --data data resources --force
```

`.env` must contain `XF_API_URL`, `XF_API_KEY`, `XF_API_USER`.

### Output schema

`data/meta.json`: `tree_map`, full `nodes[]`, `by_type` index, `forum_ids` shortcut.

`data/threads/{id}.json` (per-thread):
```jsonc
{
  "id": 2, "title": "...", "slug": "otkrytie-foruma",
  "url_path": "/threads/otkrytie-foruma.2/",
  "forum": {"id": 110, "title": "News archive",
            "breadcrumbs": [{"id": 1, "title": "TorrentPier.com", "type": "Category"}, ...]},
  "discussion_state": "visible", "discussion_open": false,
  "post_date": ..., "view_count": ..., "reply_count": ...,
  "first_post_id": ..., "user_id": ..., "username": "...",
  "tags": [], "custom_fields": {},
  "posts": [
    {
      "id": 2, "position": 0, "user_id": 1, "username": "Exile",
      "user_title": "Administrator", "is_staff": true, "is_admin": true,
      "post_date": ..., "last_edit_date": ..., "message_state": "visible",
      "message_parsed": "<p>...</p>",
      "attach_count": 0,
      "attachments": [
        {"id": 508, "filename": "123.webp", "file_size": 8614,
         "width": 416, "height": 160, "is_audio": false, "is_video": false,
         "attach_date": ..., "src_url": "https://torrentpier.com/...",
         "thumbnail_url": "https://torrentpier.com/data/...",
         "local_path": null, "r2_key": null}
      ]
    }
  ]
}
```

`data/users/{id}.json`: `id`, `username`, `user_title`, `is_admin/moderator/staff`, `user_group_id`, `secondary_group_ids[]`, `avatar_urls.{o,h,l,m,s}`, `register_date`, `last_activity`, `message_count`, `view_url`.

`data/resources/{id}.json`: `id`, `title`, `tag_line`, `slug`, `url_path`, `category` (id/title/parent/slug/view_url), `user_id`, `username`, `version`, counts, `description_parsed`, `description_attachments[]`, `current_files[]`, `versions[]` (each with `files[]` carrying `src_url` from XF `download_url`, `local_path`, `r2_key`).

## Stage 2 — Mirror to Cloudflare R2 (next)

Goal: every binary referenced from `data/` lives in R2 under a stable, deduped
key, and `data/threads/*.json` / `data/resources/*.json` carry `r2_key` for
each asset.

### R2 setup (one-time, manual)

1. `wrangler login` — opens browser, OAuth into Cloudflare account that
   owns torrentpier.com.
2. `wrangler r2 bucket create torrentpier-archive` — creates the bucket.
3. In the Cloudflare dashboard → R2 → `torrentpier-archive` → Settings →
   Custom Domains → add `files-ox.torrentpier.com`. Cloudflare will also
   create the matching DNS record.
4. R2 → Manage R2 API Tokens → "Create API token" with **Object Read &
   Write** on `torrentpier-archive`. Save Access Key ID + Secret Access
   Key into `.env` as `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY`.
5. Set `R2_ACCOUNT_ID`, `R2_BUCKET=torrentpier-archive`, `R2_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com`, `R2_PUBLIC_URL=https://files-ox.torrentpier.com`.

### Bucket layout

```
attachments/{attachment_id}/{filename}              # XF native attachments
avatars/{user_id}.jpg                               # standardised on size "l"
inline/{sha256[:2]}/{sha256}{ext}                   # external <img src> in posts (deduped)
resources/{resource_id}/icon{ext}                   # resource icons
resources/{resource_id}/v/{version_id}/{filename}   # resource version files
```

### Implementation tasks

Code goes into a new `mirror/` package mirroring `exporter/` layout:

- [ ] `mirror/r2.py` — boto3 S3-compatible client. Helpers: `head(key)`,
  `put(key, body, content_type)`. Reads creds from env.
- [ ] `mirror/scan.py` — generator that walks `data/` and yields every
  asset that still has `r2_key=None`. Yields tuples
  `(category, owner_json_path, asset_dict, target_r2_key)`.
- [ ] `mirror/download.py` — fetches an asset from `src_url`. For attachments
  and inline images: anonymous GET. For **resource version files**: must
  use the `XfClient` from `exporter.api` because the URL is an authenticated
  API endpoint. For **avatars**: download `avatar_urls.l` (large size).
- [ ] `mirror/inline.py` — scans `message_parsed` for external `<img src>`
  not already covered by an attachment, downloads the image, hashes it,
  uploads to `inline/...`. Maintains an in-memory dedupe map keyed by sha256.
- [ ] `mirror/main.py` — CLI:
  ```
  xf-mirror upload --data data --concurrency 8
  xf-mirror upload --data data --only attachments
  xf-mirror verify --data data           # HEAD every r2_key, report missing
  ```
- [ ] After successful upload, atomically rewrite the owning JSON to set
  `r2_key`. Idempotent: `xf-mirror upload` after a clean run is a no-op.

### Builder integration (after mirror)

- [ ] Update `builder/rewrite.py` to take an `asset_url_map: dict[str, str]`
  (XF `direct_url`/`thumbnail_url` → R2 URL). Replace `<img src>` and
  `<a href>` pointing at any of those URLs.
- [ ] Update `builder/site.py` to build that map from `data/threads/**.json`
  attachments + `data/resources/**.json` versions + `data/users/*.json`
  avatars + the inline-image dedupe map (need to persist that map to
  `data/inline_index.json` from the mirror stage).
- [ ] Replace avatar URLs in `templates/thread.html` (`user.avatar_urls.m`)
  with the R2 URL when the user has been mirrored.
- [ ] Update `templates/resource.html` so the version download links point
  at R2, not the XF API endpoint.

## Stage 3 — Builder (mostly Done)

Code in `builder/`:
- `render.py` — Jinja2 env, filters: `timestamp`, `filesize`, `urlpath`.
- `site.py` — load `data/`, build forum/category/resource indexes,
  render every page. `_paginate()` helper handles slicing.
- `rewrite.py` — sanitises `message_parsed`: strips `<script>` and
  `on*` handlers, drops iframes outside the YouTube allowlist, adds
  `loading=lazy` and `decoding=async` to `<img>`, rewrites internal
  links to relative paths with **canonical slugs**, adds
  `rel="noopener nofollow"` to external `<a>`.
- `main.py` — CLI: `xf-build build --data data --out dist`.

To re-run:
```bash
.venv/bin/python -m builder build --data data --out dist
.venv/bin/python -m http.server 8765 --directory dist
```

### Pages currently produced

| URL                                        | Template       | Notes                                  |
|--------------------------------------------|----------------|----------------------------------------|
| `/`                                        | `index.html`   | Categories with their child forums     |
| `/categories/{slug}.{id}/`                 | `category.html`| Forums in a category                   |
| `/forums/{slug}.{id}/page-N/`              | `forum.html`   | Threads in a forum, 30/page            |
| `/threads/{slug}.{id}/page-N/`             | `thread.html`  | Posts in a thread, 10/page             |
| `/resources/`                              | `resources_index.html` | Resource categories            |
| `/resources/categories/{slug}.{id}/`       | `rcategory.html` | Resources in a category              |
| `/resources/{slug}.{id}/`                  | `resource.html`| Resource detail with versions table    |
| `/search/`                                 | `search.html`  | Placeholder until Worker exists        |
| `/sitemap.xml`                             | (script)       | All canonical URLs with lastmod        |
| `/robots.txt`                              | static         | Allow all                              |

### Outstanding builder tasks

- [ ] Wire R2 URLs into `message_parsed` rewrite + avatar rendering after mirror stage runs.
- [ ] `/posts/{id}/` → meta-refresh redirect to `/threads/{slug}.{id}/page-N/#post-{id}` so old `/post-{id}` deep links keep working.
- [ ] `/members/{slug}.{id}/` minimal pages (avatar, name, title, post count).
- [ ] Determinism pass: sort iteration, freeze `build_time` to a fixed
  source-of-truth value (e.g. exporter's `meta.exported_at`) so identical
  `data/` produces byte-identical `dist/`.
- [ ] `dist/CNAME` containing `ox.torrentpier.com` (for GitHub Pages).

## Stage 4 — Search worker + D1 (TODO)

### D1 schema

```sql
CREATE TABLE threads (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    forum_id INTEGER NOT NULL,
    forum_title TEXT NOT NULL,
    username TEXT,
    post_date INTEGER,
    reply_count INTEGER
);
CREATE TABLE posts (
    id INTEGER PRIMARY KEY,
    thread_id INTEGER NOT NULL,
    page_no INTEGER NOT NULL,
    username TEXT,
    post_date INTEGER
);
CREATE VIRTUAL TABLE posts_fts USING fts5(
    body,                   -- lemmatised plain text of the post
    title,                  -- denormalised thread title
    content='',             -- contentless table; originals only in posts/threads
    tokenize='unicode61 remove_diacritics 2'
);
```

### Indexer (Python, run once locally)

- [ ] `search/index.py`: walks `data/threads/`, for each post:
  `BeautifulSoup(...).get_text()`, normalise whitespace, lemmatise via
  `pymorphy3` (cache lemmas per token), emit `INSERT` statements.
- [ ] Output `search/seed.sql`. Feed to D1 in batches of ~5,000 statements
  (D1 import limit):
  ```bash
  wrangler d1 create ox-archive-search
  wrangler d1 execute ox-archive-search --file=search/seed.sql --remote
  ```
- [ ] `seed.sql` should be regenerable from `data/` deterministically — keep
  insertion order sorted by `(thread_id, position)`.

### Worker (TypeScript, ~80 lines)

- [ ] `search-worker/src/index.ts`: GET `/search?q=...` → escape FTS5 query
  syntax, run a single SQL with `snippet(posts_fts, 0, '<mark>', '</mark>',
  '…', 32)`, return JSON, cache 1h.
- [ ] `search-worker/wrangler.toml`: D1 binding, route
  `search-ox.torrentpier.com/*`.
- [ ] Lemmatise the user query the same way as the index. Two viable options:
  - Lemmatise on the client (small JS lemmatiser bundle) before calling.
  - Lemmatise inside the worker using a pure-JS port of pymorphy3.
  Decide during stage 4. **Default to the client option** — keeps the
  worker stateless.

### Frontend search page

- [ ] Replace `templates/search.html` placeholder with a real `<form>` +
  `<script src="/js/search.js">`. Submit to
  `https://search-ox.torrentpier.com/search?q=...`, render results as
  links with breadcrumbs and `<mark>`-highlighted snippet, debounce 200ms.

## Stage 5 — Deploy (TODO)

### `.github/workflows/build.yml`

```yaml
name: Build & deploy
on:
  push:
    branches: [main]
    paths: ['data/**', 'templates/**', 'static/**', 'builder/**', '.github/workflows/build.yml']
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.13' }
      - run: pip install -e .
      - run: python -m builder build --data data --out dist
      - run: cp dist/CNAME dist/CNAME 2>/dev/null || echo ox.torrentpier.com > dist/CNAME
      - uses: actions/upload-pages-artifact@v3
        with: { path: ./dist }

  deploy:
    needs: build
    permissions: { pages: write, id-token: write }
    environment: github-pages
    runs-on: ubuntu-latest
    steps:
      - uses: actions/deploy-pages@v4
```

### Cloudflare side

- [ ] DNS: `ox.torrentpier.com` CNAME → `<gh-user>.github.io`.
- [ ] Page Rule / Bulk Redirect List: any request to `torrentpier.com/*`
  (or whichever hostname currently runs the live forum) → 301 to
  `https://ox.torrentpier.com/$1`. **The URL paths are preserved by
  design** so this is a clean cutover with no per-thread redirect rules.
- [ ] Verify R2 custom domain (`files-ox.torrentpier.com`) responds.
- [ ] Verify Worker custom domain (`search-ox.torrentpier.com`) responds.
- [ ] Add an `Archive` notice banner in `templates/base.html` with a
  link to GitHub for source — set after the cutover, not before.

### Cutover checklist

- [ ] Final exporter run (capture anything posted in the time between the
  earlier export and the cutover). With `data/threads/{id}.json` as the
  marker, `xf-export threads` only re-fetches missing threads — fast.
- [ ] Final builder run + push to `main` so Pages picks it up.
- [ ] DNS flip.
- [ ] Smoke-test 5–10 deep-link URLs from real search engines / chats.
- [ ] **Revoke the super-user API key** in the XF admin panel.

## Open questions

- [ ] Server-side size of the forum's actual attachments (not resource files).
  User's estimate is 1–5 GB; well within the R2 free tier of 10 GB. Will be
  measured precisely the moment the mirror stage starts (sum
  `attachments[].file_size` across `data/threads/**.json`).
- [ ] **Profile posts / resource discussion comments not exported.** The
  public message counter on the forum is 45,473; we captured 42,623 forum
  posts. The 2,850 delta is almost certainly profile-wall comments and
  resource discussion threads, which live behind `/api/profile-posts/`
  and `/api/resources/{id}/discussions/` (TBC). Decide whether to add a
  fifth export stage.
- [ ] **YouTube iframes.** Current rewrite keeps them (relies on YouTube
  staying online). Consider downgrading to a text link "[video: …]"
  during stage 3 so the archive degrades gracefully if YouTube ever
  removes a video.
- [ ] Consider a `/posts/{id}/` redirect page that resolves to
  `/threads/{slug}.{id}/page-N/#post-{id}` so old XF-style deep-links
  stay alive.

## How to resume — runbook for the next operator

1. Open this file and read the "Status snapshot" + "Outstanding tasks" of
   the relevant stage. The state of every commit is in `git log feat/archive`.
2. `cp .env.example .env` (if `.env` is gone) and put back `XF_API_KEY`,
   `XF_API_USER`. To rebuild the venv: `uv venv .venv --python 3.13 && uv
   pip install --python .venv/bin/python -e .`
3. Sanity check the exporter: `.venv/bin/python -m exporter --data data
   nodes` (no-op if `data/meta.json` exists; remove it to re-fetch).
4. Sanity check the builder: `.venv/bin/python -m builder build --data
   data --out dist && .venv/bin/python -m http.server 8765 --directory
   dist` then open <http://localhost:8765>.
5. Pick the first unchecked `[ ]` in the relevant stage. Start there.
6. **Update this file in the same commit as the work that produced the
   change** — that's the contract that keeps it useful.

### Recommended task order (by dependency)

1. **Mirror stage (Stage 2).** Unblocks the rest. Without it, attachments
   and resource downloads point at torrentpier.com — the moment the
   forum is shut down, those links 404. Also ~30 min real time to run.
2. **Builder R2 wiring + `/posts/{id}/` redirect + `/members/`.** Quick;
   needs the asset URL map produced by Mirror.
3. **GitHub Actions deploy (Stage 5 first half).** Once committed and
   pushed, every change auto-deploys. Cheap insurance.
4. **DNS cutover.** Independent of the search worker. Decide whether to
   cut over before or after search.
5. **Search worker + indexer (Stage 4).** Adds polish; the archive is
   usable without it.
6. **Profile posts / resource discussions (open question).** Decide
   whether to add and run a fifth export stage.
7. **Revoke the super-user API key.**

## References

- XenForo API docs: <https://docs.xenforo.com/api>
- Cloudflare R2 docs: <https://developers.cloudflare.com/r2/>
- Cloudflare D1 + FTS5: <https://developers.cloudflare.com/d1/>
- pymorphy3: <https://github.com/no-plagiarism/pymorphy3>
- This repo's commit log: `git log feat/archive --oneline`
