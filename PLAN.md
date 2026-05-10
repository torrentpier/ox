# Development plan: torrentpier.com static archive

This document is the single source of truth for the project. It must be
detailed enough that work can be paused and resumed at any point — by the same
or a different operator — without losing context.

Update it after every meaningful decision or completed step. Treat it as part
of the deliverable, not a side note.

## Status snapshot

| Item                                | State                                  |
|-------------------------------------|----------------------------------------|
| Branch                              | `feat/archive`                         |
| Repo skeleton (dirs + meta files)   | Done (`c12ba69`)                       |
| Plan + decisions doc                | Done (`2265934`)                       |
| API smoke + endpoint verification   | Done — see "API surface" below         |
| Resource binary size estimate       | Done — 62.83 MiB across 511 files      |
| Wrangler installed (Homebrew)       | Done — 4.90.0                          |
| Cloudflare auth (`wrangler login`)  | Pending — must be run interactively by user |
| Python venv (`.venv/`, py3.13)      | Done via `uv` — `uv pip install -e .`  |
| Exporter — http client (`api.py`)   | Done                                   |
| Exporter — atomic JSON writer       | Done                                   |
| Exporter — `nodes` stage            | Done — first end-to-end run wrote `data/meta.json` (34 nodes, 27 forums) |
| Exporter — `threads` stage (code)   | Done — smoke-tested on thread 2 (50 posts, 5 pages → 32 KB JSON) |
| Exporter — `threads` full run       | In progress / pending                  |
| Exporter — `users` stage            | Captured incidentally during `threads` (27 users from thread 2 smoke run) |
| Exporter — `resources` stage (code) | Done                                   |
| Exporter — `resources` full run     | Done — 230 resources, 2.2 MB on disk   |
| Builder — minimal slice             | Done — `index`, category, forum, thread, resource and resource-category pages; dark-mode CSS |
| Builder — pagination (forum + thread) | Not started — every thread/forum is one HTML page |
| Builder — `message_parsed` rewrite (URLs, sandboxing) | Not started          |
| Builder — sitemap, robots.txt       | Done — `sitemap.xml` lists all categories, forums, threads, resources with lastmod where available |
| Builder — `/resources/` index, `/search/` placeholder | Done                 |
| Attachment mirror to R2             | Not started — R2 bucket not provisioned|
| Static builder (`builder/`)         | Not started                            |
| Search worker + D1                  | Not started                            |
| GitHub Actions deploy               | Not started                            |
| Cutover (DNS + redirects)           | Not started                            |

## Source forum

- URL: `https://torrentpier.com`
- Engine: XenForo 2 (with Resource Manager)
- Currently in read-only / maintenance mode (good — snapshot is consistent)
- Volume: 3,304 threads, 45,473 posts, 5,194 members, 230 resources, 1–5 GB attachments

## Target hosts

- Site: `ox.torrentpier.com` (CNAME → GitHub Pages)
- Files: `files-ox.torrentpier.com` (Cloudflare R2 custom domain)
  - Hyphenated, not `files.ox.torrentpier.com`, because Cloudflare's universal
    SSL doesn't cover 4th-level subdomains.

## Decisions log

| #  | Decision                                                                                          | Reasoning                                                                                                  |
|----|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------|
| 1  | Intermediate format = JSON (one file per thread / resource), checked into git                     | Source of truth, diffable, trivially editable, easy GDPR-style deletes                                     |
| 2  | Final format = pre-rendered HTML on GitHub Pages                                                  | Longevity, $0 cost, archive is read-only forever                                                           |
| 3  | Files (attachments, avatars, inline images) on Cloudflare R2 with custom domain                   | GitHub Pages 1 GB repo limit; R2 has 10 GB free tier and zero-egress pricing                               |
| 4  | Search = Cloudflare Worker + D1 (SQLite FTS5), not Pagefind                                       | FTS5 + Russian lemmatisation gives meaningful search; Pagefind gives literal-only match for Russian        |
| 5  | Exporter / builder language = Python (3.11+)                                                      | Faster iteration on JSON munging + Jinja2 + BS4                                                            |
| 6  | URL scheme = identical to XenForo (`/threads/{slug}.{id}/page-N/`)                                | Old links from search engines / chats keep working without redirect rules                                  |
| 7  | Don't carry: deleted/hidden posts, private conversations, reactions                               | Per user                                                                                                   |
| 8  | Carry: text + attachments + avatars + per-post username/title/group + resources                   | Per user                                                                                                   |
| 9  | API auth via super-user key + dotenv (`XF_API_KEY`, `XF_API_USER`)                                | Forum is being shut down; key will be revoked post-export                                                  |
| 10 | Subdomain via CNAME, redirects from old hostname handled via Cloudflare (out of scope for repo)   | Per user                                                                                                   |
| 11 | Hostnames: `ox.torrentpier.com` for site, `files-ox.torrentpier.com` for R2                       | Cloudflare universal SSL doesn't cover 4th-level (`files.ox.torrentpier.com` would need a paid cert)       |
| 12 | Carry resource binaries: **all versions of all 230 resources**                                    | Total size measured at 62.83 MiB — negligible relative to forum attachments                                |
| 13 | Pagination is server-side fixed and per-endpoint: `per_page=30` for `/api/forums/{id}/threads` and `/api/resources`, `per_page=10` for `/api/threads/{id}/?with_posts=1`. The `per_page` query param is ignored. | Confirmed by probing `per_page=20/30/50/100/200` against forum 17 (47 threads) — server always returned 30 — and observing `pagination.per_page` in thread 37048 detail page. |
| 14 | R2 provisioning via `wrangler` from this machine; `wrangler login` runs interactively by the user | Avoids handling a Cloudflare API token in the repo or in dotenv                                            |
| 15 | In `/api/threads/{id}/?with_posts=1`: `posts` and `pagination` are top-level keys; attachments are named `Attachments` (capital A). | Verified against thread 37048; embedded resource conventions in XF API |
| 16 | `User` object is embedded in every post under `post.User` — bulk `/api/users/{id}` calls are unnecessary in the common case | Saves ~5,000 requests; only fetch `/api/users/{id}` for users referenced via `[USER=N]` mentions / quotes who never authored a post |
| 17 | `/api/resources/{id}/versions` may return `400 xfrm_this_resource_is_not_versioned` for single-file or fileless resources living in a versioned category. Treat as zero versions and rely on `current_files` from the detail call. | Discovered against resource 254 ("Мод noindex,nofollow"); silently skipping kept the run going. |
| 18 | Resource description: store `description_parsed` (rendered HTML) alongside `DescriptionAttachments` so the builder can render it the same way as posts. | Mirrors the post schema (`message_parsed` + `Attachments`); avoids re-parsing BBCode. |

## API surface (verified against torrentpier.com on 2026-05-11)

Probed with a super-user key. Endpoints not listed were not checked.

| Endpoint                                                | Status | Notes                                                                                                  |
|---------------------------------------------------------|--------|--------------------------------------------------------------------------------------------------------|
| `GET /api/`                                             | 200    | Returns `version_id`, `site_title`, key info                                                           |
| `GET /api/me`                                           | 200    | Acting user                                                                                            |
| `GET /api/nodes`                                        | 200    | **Categories + forums + pages + links** — full tree via `tree_map` + flat `nodes[]` array              |
| `GET /api/nodes/flattened`                              | 200    | Alternative flat form                                                                                  |
| `GET /api/forums/{node_id}`                             | 200    | Single forum incl. breadcrumbs and `view_url` with slug                                                |
| `GET /api/forums/{node_id}/threads?page=N`              | 200    | Threads in forum, paginated. **Server-fixed `per_page=30`** (query param ignored).                     |
| `GET /api/threads/{id}/?with_posts=1&page=N`            | 200    | Returns `{thread, posts, pagination}` at top level. **Server-fixed `per_page=10` for posts.** Each post has `User` embedded |
| `GET /api/threads/{id}/posts?page=N`                    | 200    | Posts-only listing if needed                                                                           |
| `GET /api/users/{id}`                                   | 200    | Full user object incl. `avatar_urls`, `user_title`, `is_admin/moderator/staff`. Rarely needed — most users come embedded in posts |
| `GET /api/resources?page=N`                             | 200    | Resource Manager content with embedded `Category` per resource. **Server-fixed `per_page=30`.**        |
| `GET /api/resources/{id}`                               | 200    | Single resource detail; includes `current_files[]` (latest version files) and `Category`               |
| `GET /api/resources/{id}/versions`                      | 200    | All versions; each has `files[]` with `id`, `filename`, `size` (bytes), `download_url`                 |
| `GET /api/attachments/{id}`                             | 404 page | Endpoint exists ("requested_page_not_found" for missing id, vs "endpoint_not_found" for bad route)   |
| `GET /api/attachments/{id}/data`                        | TBD    | Not yet probed with a real attachment id; download URL is in the embedded `attachments[]` of a post   |
| `GET /api/categories`                                   | 404    | Categories live under `/api/nodes`, not here                                                           |
| `GET /api/forums` (collection)                          | 404    | Use `/api/nodes`                                                                                       |
| `GET /api/tags`                                         | 404    | No bulk tag listing; tags appear inline on threads                                                     |
| `GET /api/rm`, `/api/rm/*`                              | 404    | Resource Manager API root is `/api/resources`, not `/api/rm`                                           |
| `GET /api/resources/categories`                         | 404    | Categories only appear embedded inside resource objects                                                |
| `GET /api/resources/categories/{id}`                    | 404    | Same                                                                                                   |
| `GET /api/resources/{id}/icon`                          | 404    | Icon URL lives on the `resource` object, not a separate endpoint                                       |
| `GET /api/resources/{id}/files`                         | 404    | Files are inside `versions[].files[]`                                                                  |

### Endpoints still to verify before writing the exporter

- [x] **Attachment download URL** — every attachment object carries a `direct_url` (e.g. `https://torrentpier.com/attachments/123-webp.508/`). No need for `/api/attachments/{id}/data`. Verified against post 9435 in thread 37048.
- [ ] Behaviour of `include_deleted=1` on post listings — confirm it's a no-op without elevated permissions or that it indeed exposes soft-deleted posts (we drop them per decision #7 either way).

### Key schema notes

**Node tree** (`/api/nodes`): `tree_map: {parent_id: [child_ids]}` plus `nodes[]` with `node_id`, `node_type_id` (`Category` / `Forum` / `Page` / `Link`), `parent_node_id`, `title`, `description`, `node_name`.

**Thread response envelope** (`/api/threads/{id}/?with_posts=1&page=N`):
```jsonc
{
  "thread":     { /* thread metadata, see below */ },
  "posts":      [ /* this page's posts, max 10 */ ],
  "pagination": {"current_page": N, "last_page": M, "per_page": 10, "shown": 10, "total": 198}
}
```
The `thread` object has its own `Forum` (with `breadcrumbs[]`) embedded.

**Thread metadata** (`thread.*`): `thread_id`, `title`, `view_url` (e.g. `/threads/otkrytie-foruma.2/` — slug + id baked in), `discussion_state`, `discussion_open`, `view_count`, `reply_count`, `post_date`, `first_post_id`, `username`, `user_id`, `custom_fields`, `tags`, `node_id`, `prefix_id`, `sticky`, `is_first_post_pinned`, `highlighted_post_ids`, `last_post_*`.

**Post** (each item in top-level `posts[]`):
- Identity: `post_id`, `position`, `thread_id`
- Body: `message` (raw BBCode, can be discarded), `message_parsed` (rendered HTML — **always use this**), `message_state`, `last_edit_date`
- Author: `user_id`, `username`, plus a fully-embedded `User` object with the same shape as `/api/users/{id}` (covered below)
- Attachments: `Attachments` (note the **capital A**) — array of attachment objects. Sample shape:
  ```jsonc
  {
    "attachment_id": 508,
    "content_id": 9435,           // post_id
    "content_type": "post",
    "filename": "123.webp",
    "file_size": 8614,
    "width": 416, "height": 160,
    "is_audio": false, "is_video": false,
    "attach_date": 1326481417,
    "view_count": 1091,
    "direct_url": "https://torrentpier.com/attachments/123-webp.508/",     // download from here
    "thumbnail_url": "https://torrentpier.com/data/attachments/0/508-...jpg?hash=..."
  }
  ```
  Also `attach_count` int on the post itself.
- Misc we drop: `can_*` (viewer-dependent), `is_first_post`/`is_last_post` (computable), `is_reacted_to`, `is_unread`, `reaction_score` (per decision #7), `view_url` (computable), `warning_message`.

**User** (full object — same as `/api/users/{id}` — embedded in each post under `User`):
`user_id`, `username`, `user_title` (e.g. `Administrator`, custom titles like `Разработчик`), `user_group_id`, `secondary_group_ids[]`, `is_admin`, `is_moderator`, `is_staff`, `avatar_urls.{o,h,l,m,s}`, `view_url`, `register_date`, `message_count`, `last_activity`. We keep username + title + avatar URL + staff flags + register_date + message_count.

**Resource**: `resource_id`, `title`, `view_url` (`/resources/{slug}.{id}/`), `version`, `view_count`, `description` (HTML), `Category` embedded, `user_id`, `username`, `current_files[]`. Versions and per-version files available at `/versions`.

**Resource version**: `resource_version_id`, `version_string`, `release_date`, `download_count`, `version_state`, `files[]` with `id`, `filename`, `size` (bytes), `download_url`.

**Pagination envelope** (used on listing endpoints):
```
"pagination": {
    "current_page": 1,
    "last_page": 12,
    "per_page": 20,        // hard-capped server-side, can't be raised
    "shown": 20,
    "total": 231
}
```

## Pipeline overview

```
XenForo REST API
        |
        v
  [1] exporter/    --> data/threads/*.json
                       data/resources/*.json
                       data/users/*.json
                       data/meta.json (nodes)
        |
        +----> [2] mirror/        --> Cloudflare R2 (attachments, avatars, inline images, resource files)
        |
        v
  [3] builder/     --> dist/  (HTML + CSS + JS, sitemap, canonical URLs)
        |
        +----> [4] search/        --> Cloudflare D1 (FTS5 over lemmatised post bodies)
        |                            + Worker exposing /search?q=...
        v
  [5] deploy via GitHub Actions --> GitHub Pages --> ox.torrentpier.com
```

Estimated request budget for the exporter against the live API
(updated for verified per-endpoint `per_page`):

- Nodes: 1 call.
- Threads listings: 3304 / 30 ≈ 110 calls (sum across all forums).
- Thread detail pages: 45473 / 10 ≈ **4548 calls** (each page returns up to 10 posts).
- Users: ~0 in the common case — every post embeds its `User`. Only a fallback pass for usernames mentioned in `[USER=N]` / quotes who never authored a post. Budget ~200 calls.
- Resources: 8 listing calls + 230 detail calls + 230 `/versions` calls = 468 calls.

Total ≈ **5325 calls**. At a polite 3 rps, ~30 minutes for a clean run. At 1 rps,
~1.5 hours. The forum is read-only so a long run is fine.

## Stage 1 — Exporter

Goal: turn the live API into a complete on-disk JSON snapshot under `data/`,
re-runnable and resumable.

### Output layout

```
data/
├── meta.json              # nodes (categories+forums) + lookup tables + export stats
├── users/                 # one file per user encountered
│   ├── 1.json
│   └── ...
├── threads/
│   ├── 2.json             # one file per thread, all posts inline
│   └── ...
└── resources/
    ├── 1.json             # one file per resource, includes its versions+files
    └── ...
```

Why one-file-per-thread: easy diff, easy delete (GDPR), git happy, easy parallel
write from multiple workers.

### `data/meta.json` shape (proposed)

```jsonc
{
  "exported_at": "2026-05-11T...",
  "site_title": "TorrentPier support forum",
  "nodes": [ /* /api/nodes payload, normalised */ ],
  "user_groups": { "2": "Administrator", "3": "Разработчик", ... },
  "stats": { "threads": 3304, "posts": 45473, "users": 5194, "resources": 230 }
}
```

### `data/threads/{id}.json` shape (proposed)

```jsonc
{
  "id": 2,
  "title": "Открытие форума",
  "slug": "otkrytie-foruma",            // extracted from view_url
  "url_path": "/threads/otkrytie-foruma.2/",
  "forum": {
    "id": 110,
    "breadcrumbs": [{"id": 1, "title": "TorrentPier.com"}, ...]
  },
  "tags": [],
  "discussion_state": "visible",
  "discussion_open": false,
  "post_date": 1309190400,
  "view_count": 12345,
  "reply_count": 89,
  "posts": [
    {
      "id": 2,
      "position": 0,
      "user_id": 1,
      "username": "Exile",
      "user_title": "Administrator",
      "is_staff": true,
      "post_date": 1309190400,
      "message_parsed": "<p>...</p>",
      "attachments": [
        {
          "id": 508,
          "filename": "123.webp",
          "file_size": 8614,
          "width": 416,
          "height": 160,
          "is_video": false,
          "is_audio": false,
          "src_url": "https://torrentpier.com/attachments/123-webp.508/",  // from API direct_url
          "thumbnail_url": "https://torrentpier.com/data/attachments/...",
          "local_path": "attachments/508/123.webp",     // filled by mirror stage
          "r2_key": null                                 // filled by mirror stage
        }
      ]
    }
  ]
}
```

### Implementation tasks

- [x] `exporter/api.py`: `httpx.Client` wrapper with auth headers (`XF-Api-Key`, `XF-Api-User`), `tenacity` retry (exponential backoff, retry on 5xx/429/transport), per-request rate limit (token bucket, default 3 rps, configurable via `XF_API_RPS` env var).
- [x] `exporter/io.py`: atomic JSON writer (tempfile + `os.replace`).
- [x] `exporter/nodes.py`: `GET /api/nodes` → write `data/meta.json` with `tree_map`, full `nodes[]`, `by_type` index and `forum_ids` shortcut.
- [x] `exporter/threads.py`: for each forum: paginate `/api/forums/{id}/threads` (page envelope at top level), for each thread: paginate `/api/threads/{id}/?with_posts=1&page=N` until `current_page == last_page`. Posts are at top-level `posts[]`, not nested in `thread`. Captures `post.User` into a shared `UserCache`. Merges pages into one `data/threads/{id}.json`. Skips existing files unless `--force`. CLI flags: `--forum N` (repeatable), `--only-thread N`, `--force`.
- [x] `exporter/users.py`: `UserCache` flushes `data/users/{id}.json` from the side-effect cache populated by the thread pass.
- [ ] Optional second user pass: scan `message_parsed` for `[USER=N]`/`<a data-user-id=N>` references and fetch any users that weren't seen as authors.
- [x] `exporter/resources.py`: paginate `/api/resources`, for each resource fetch `/api/resources/{id}` (full detail with embedded `Category`) plus `/api/resources/{id}/versions`, merge into `data/resources/{id}.json`. Captures resource-author `User` into the shared cache.
- [ ] `exporter/main.py`: orchestration (CLI flags `--stage nodes|threads|users|resources|all`, `--force`, `--rps`, `--from-thread`, `--only-thread`).
- [ ] Logging: structured (one line per HTTP call), default INFO, `--verbose` for DEBUG.
- [ ] Resumability: presence of output file = "done" marker. Failure mid-thread leaves partial-state risk; use atomic write (`tmp` + `rename`) for each `data/*.json`.
- [ ] Tests: golden-file tests for normalisation logic with response fixtures saved under `exporter/tests/fixtures/`.

### Out of scope for stage 1

- Attachment **content** download (stage 2)
- HTML rewriting (stage 3)
- Lemmatisation (stage 4)

## Stage 2 — Mirror to Cloudflare R2

Goal: every binary referenced in `data/` lives in R2 with a stable, deduped key,
and `data/threads/*.json` (and `data/resources/*.json`) carries `r2_key` for
each attachment / avatar / inline image / resource file.

### Bucket layout

```
attachments/{attachment_id}/{original_filename}     # XF native attachments
avatars/{user_id}.jpg                               # standardised on size "l"
inline/{sha256[:2]}/{sha256}{ext}                   # external <img src> hot-linked in posts (deduped)
resources/{resource_id}/v/{version_id}/{filename}   # resource version files (62.83 MiB total)
```

Resource icons: pulled directly from the resource object's `icon_url` and stored
under `resources/{resource_id}/icon{ext}` if present.

### Provisioning via wrangler

Pre-condition: `wrangler` is installed (✓ Homebrew 4.90.0 on this host) and
the user has run `wrangler login` interactively.

- [ ] `wrangler r2 bucket create torrentpier-archive`
- [ ] In Cloudflare dashboard: bind `files-ox.torrentpier.com` to the bucket as a custom domain (Workers/Pages → R2 → Settings → Custom Domains).
- [ ] Create an R2 access key + secret for use by the Python mirror script (Cloudflare dashboard → R2 → Manage R2 API Tokens). Store in `.env` as `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY`.

### Implementation tasks

- [ ] `mirror/main.py`: walks `data/`, for each unmirrored asset downloads from origin and uploads to R2 via `boto3` (S3-compatible). Concurrency via `concurrent.futures` (4–8 workers).
- [ ] In-memory dedupe by sha256 for inline images.
- [ ] Idempotent: skip R2 keys that already exist (HEAD probe or local index `mirror/state.json`).
- [ ] After upload, write `r2_key` (and remove `src_url`?) into the corresponding JSON. Pretty-print for clean diffs.
- [ ] Sanity check at the end: every `r2_key` in `data/` resolves on R2.

### Out of scope for stage 2

- Rewriting in-post HTML (`message_parsed`) to use R2 URLs — that happens at build time so we can change the public R2 URL without rewriting `data/`.

## Stage 3 — Static builder

Goal: deterministic `dist/` ready for GitHub Pages.

### Pages to generate

| Path                                     | Template       | Content                                    |
|------------------------------------------|----------------|--------------------------------------------|
| `/index.html`                            | `index.html`   | Top-level categories                       |
| `/categories/{slug}.{id}/`               | `category.html`| Forums in category                         |
| `/forums/{slug}.{id}/page-{N}/`          | `forum.html`   | Threads (20/page)                          |
| `/threads/{slug}.{id}/page-{N}/`         | `thread.html`  | Posts (20/page) with `<article id="post-{id}">` anchors |
| `/posts/{id}/`                           | `post-redirect.html` | `<meta http-equiv="refresh">` to thread anchor — preserves XF deep-link compatibility |
| `/resources/categories/{slug}.{id}/`     | `rcategory.html`| Resources in category                     |
| `/resources/{slug}.{id}/`                | `resource.html`| Resource detail with version download list |
| `/members/{slug}.{id}/`                  | `member.html`  | Minimal: avatar, name, title, post count   |
| `/sitemap.xml`                           | (script)       | All canonical URLs                         |
| `/robots.txt`                            | static         | Allow all                                  |
| `/search/`                               | `search.html`  | Search UI talking to the worker            |

### `message_parsed` post-processing

Each post body runs through a sanitisation + rewriting pass with BeautifulSoup:

1. Replace `<img src=...>` and `<a href=...>` pointing at hosted attachments / avatars with their public R2 URLs (via lookup table).
2. Replace external `<img>` (lookup against the inline-image dedupe table) with R2.
3. Rewrite XF internal links (`/threads/...`, `/forums/...`, `/posts/...`, `/members/...`, `/resources/...`) to be **same-origin** (URL scheme already matches → typically just strip the `https://torrentpier.com` prefix).
4. Strip `<script>`, all `on*` attributes, and `<iframe>` whose `src` host is not in an allowlist (YouTube only).
5. Add `loading="lazy"` to all `<img>`.
6. Add `rel="noopener nofollow"` to external `<a>`.

### Implementation tasks

- [x] `builder/main.py` — CLI orchestration (`build --data data --out dist`).
- [x] `builder/render.py` — Jinja2 environment, `timestamp` and `filesize` filters.
- [x] `builder/site.py` — load `data/`, render `index.html` + one HTML per thread under `/threads/{slug}.{id}/index.html`. No pagination yet (one page per thread).
- [x] Minimal `templates/{base,index,thread}.html` and `static/style.css` with dark-mode via `prefers-color-scheme`.
- [ ] `builder/forum.py` — render `/forums/{slug}.{id}/page-N/` listings.
- [ ] Pagination inside threads (currently one HTML page per thread carries all posts).
- [ ] `builder/rewrite.py` — `message_parsed` rewriter (R2 URLs, internal-link normalisation, script/iframe sandboxing).
- [ ] `builder/sitemap.py`.
- [ ] Resource pages.
- [ ] Determinism: same `data/` → byte-identical `dist/` (sorted iteration, frozen timestamps).

## Stage 4 — Search worker + D1

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
    content='',
    tokenize='unicode61 remove_diacritics 2'
);
```

### Indexer (Python, run once locally)

- [ ] `search/index.py`: walks `data/threads/`, for each post: BeautifulSoup→`get_text()`, normalise whitespace, lemmatise via `pymorphy3` (cache per token), emit `INSERT` statements.
- [ ] Output `search/seed.sql` fed to D1 via `wrangler d1 execute --file=...` in batches of ~5000 statements.

### Worker (TypeScript, ~80 lines)

- [ ] `search-worker/src/index.ts`: `/search?q=...` endpoint, escapes FTS5 query syntax, returns top-30 results with `<mark>`-highlighted snippets, `Cache-Control: public, max-age=3600`.
- [ ] `search-worker/wrangler.toml`: D1 binding, custom domain route `search-ox.torrentpier.com/*`.
- [ ] Lemmatise the user query the same way as the index. Two viable options:
  - Lemmatise on the client (small JS lemmatiser bundle) before calling the worker — keeps the worker stateless.
  - Lemmatise inside the worker using a pure-JS port of pymorphy3 dictionaries.

### Frontend search page

- [ ] `static/js/search.js` — submits to `https://search-ox.torrentpier.com/search?q=...`, renders results as links with breadcrumbs and snippet, debounce 200ms.

## Stage 5 — Deploy

- [ ] `.github/workflows/build.yml`: on push to `main` touching `data/`, `templates/`, `static/`, `builder/`: install deps, run `python -m builder.main`, upload `dist/` as Pages artifact, deploy.
- [ ] CNAME file in `static/CNAME` with `ox.torrentpier.com`.
- [ ] Cloudflare side: CNAME `ox.torrentpier.com` → `<user>.github.io`, plus Bulk Redirect List from old hostname (`torrentpier.com`) → `ox.torrentpier.com` (URL paths preserved by design).

## Open questions

- [ ] Server-side size of the forum's actual attachments (not resource files). User's estimate is 1–5 GB; well within the R2 free tier of 10 GB. Will be measured precisely during stage 1 by summing `attachments[].file_size` across all posts.
- [ ] **Resource version downloads require API auth.** `download_url` in `/api/resources/{id}/versions[].files[]` is `https://torrentpier.com/api/resource-versions/{vid}/download?file={fid}` — fetching it without `XF-Api-Key` returns 403. Must download every file via the API during the mirror stage and rehost on R2; the rendered resource page must point at R2 URLs, not the API endpoint.
- [ ] **YouTube iframes.** Keep as iframes (relies on YouTube staying online) or downgrade to text links during HTML rewrite? Decide during stage 3.

## How to resume

1. Read this file end-to-end.
2. `git log feat/archive` — see what's already committed.
3. `cp .env.example .env` and fill in `XF_API_KEY`/`XF_API_USER` (and R2 creds when stage 2 starts).
4. Find the next unchecked `[ ]` task in the relevant stage; that's the next thing to do.
5. Update this file with any new decisions or surprises **in the same commit** as the work that produced them.

## References

- XenForo API docs: <https://docs.xenforo.com/api>
- Cloudflare R2 docs: <https://developers.cloudflare.com/r2/>
- Cloudflare D1 + FTS5: <https://developers.cloudflare.com/d1/>
- pymorphy3: <https://github.com/no-plagiarism/pymorphy3>
