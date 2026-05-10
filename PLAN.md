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
| Repo skeleton (dirs + meta files)   | Done (commit `c12ba69`)                |
| API smoke-test                      | Done — see "API surface" below         |
| Exporter (`exporter/`)              | Not started                            |
| Attachment mirror to R2             | Not started — R2 bucket not provisioned|
| Static builder (`builder/`)         | Not started                            |
| Search worker + D1                  | Not started                            |
| GitHub Actions deploy               | Not started                            |
| Cutover (DNS + redirects)           | Not started                            |

## Source forum

- URL: `https://torrentpier.com`
- Engine: XenForo 2 (with Resource Manager)
- Currently in read-only / maintenance mode (good — snapshot is consistent)
- Volume: 3,304 threads, 45,473 posts, 5,194 members, 231 resources, 1–5 GB attachments

## Decisions log

Decisions made up to this point. Reasoning lives here so future-you can tell
which decisions are load-bearing and which are merely "current best guess".

| # | Decision                                                                                          | Reasoning                                                                                                  |
|---|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------|
| 1 | Intermediate format = JSON (one file per thread / resource), checked into git                     | Source of truth, diffable, trivially editable, easy GDPR-style deletes                                     |
| 2 | Final format = pre-rendered HTML on GitHub Pages                                                  | Longevity, $0 cost, archive is read-only forever                                                           |
| 3 | Files (attachments, avatars, inline images) on Cloudflare R2 with custom domain                   | GitHub Pages 1 GB repo limit; R2 has 10 GB free tier and zero-egress pricing                               |
| 4 | Search = Cloudflare Worker + D1 (SQLite FTS5), not Pagefind                                       | FTS5 + Russian lemmatisation gives meaningful search; Pagefind gives literal-only match for Russian        |
| 5 | Exporter / builder language = Python (3.11+)                                                      | Faster iteration on JSON munging + Jinja2 + BS4; Go was considered, no decisive win for one-off scripts    |
| 6 | URL scheme = identical to XenForo (`/threads/{slug}.{id}/page-N/`)                                | Old links from search engines / chats keep working without redirect rules                                  |
| 7 | Don't carry: deleted/hidden posts, private conversations, reactions                               | Per user                                                                                                   |
| 8 | Carry: text + attachments + avatars + per-post username/title/group + resources                   | Per user                                                                                                   |
| 9 | API auth via super-user key + dotenv (`XF_API_KEY`, `XF_API_USER`)                                | Forum is being shut down; key will be revoked post-export                                                  |
| 10| Subdomain via CNAME, redirects from old hostname handled via Cloudflare (out of scope for repo)   | Per user                                                                                                   |

## API surface (verified against torrentpier.com)

Probed with a super-user key on 2026-05-11. Endpoints not listed were not
checked.

| Endpoint                                            | Status | Notes                                                                                          |
|-----------------------------------------------------|--------|------------------------------------------------------------------------------------------------|
| `GET /api/`                                         | 200    | Returns `version_id`, `site_title`, key info                                                   |
| `GET /api/me`                                       | 200    | Acting user                                                                                    |
| `GET /api/nodes`                                    | 200    | **Categories + forums + pages + links** — full tree via `tree_map` + flat `nodes[]` array      |
| `GET /api/nodes/flattened`                          | 200    | Alternative flat form                                                                          |
| `GET /api/forums/{node_id}`                         | 200    | Single forum incl. breadcrumbs and `view_url` with slug                                        |
| `GET /api/forums/{node_id}/threads?per_page=20&page=N` | 200 | Threads in forum, paginated. **`per_page` clamps; default = 20, max appears to be 20.**        |
| `GET /api/threads/{id}/?with_posts=1&page=N`        | 200    | Thread + embedded `Forum` + posts on that page (20/page). Single call gets you everything      |
| `GET /api/threads/{id}/posts?per_page=N`            | 200    | Posts-only listing if needed                                                                   |
| `GET /api/users/{id}`                               | 200    | Full user object incl. `avatar_urls`, `user_title`, `is_admin/moderator/staff`                 |
| `GET /api/resources?per_page=20&page=N`             | 200    | Resource Manager content with embedded `Category` per resource, paginated                      |
| `GET /api/categories`                               | 404    | Categories live under `/api/nodes`, not here                                                   |
| `GET /api/forums` (collection)                      | 404    | Same — use `/api/nodes`                                                                        |
| `GET /api/tags`                                     | 404    | No bulk tag listing; tags appear inline on threads                                             |
| `GET /api/rm`, `/api/rm/*`                          | 404    | Resource Manager API root is `/api/resources`, not `/api/rm`                                   |
| `GET /api/resources/categories`                     | 404    | Categories embedded inside resource objects; bulk listing not available                        |

### Key schema notes (from real responses)

**Node tree** (`/api/nodes`):
- `tree_map: {parent_id: [child_ids]}` plus `nodes[]` with `node_id`, `node_type_id` (`Category`/`Forum`/`Page`/`Link`), `parent_node_id`, `title`, `description`, `node_name` (URL slug fragment, can be null).

**Thread** (`/api/threads/{id}/?with_posts=1`):
- Top-level fields: `thread_id`, `title`, `view_url` (e.g. `/threads/otkrytie-foruma.2/` — slug + id baked in), `discussion_state`, `discussion_open`, `view_count`, `reply_count`, `post_date`, `first_post_id`, `username`, `user_id`, `custom_fields`, `tags` (array, can be empty).
- Embedded `Forum` object with `breadcrumbs[]` chain (Category → Forum → ...).
- Embedded `posts[]` for the requested page.

**Post**:
- `post_id`, `position`, `post_date`, `user_id`, `username`, `message_parsed` (rendered HTML — **use this, never re-parse BBCode**), `attachments[]`, plus moderation flags. Reaction details available via separate endpoint (skipped per decision #7).

**User**:
- `user_id`, `username`, `user_title` (e.g. `Administrator`, custom titles like `Разработчик`), `user_group_id`, `secondary_group_ids[]`, `is_admin`, `is_moderator`, `is_staff`, `avatar_urls.{o,h,l,m,s}` (sized variants), `view_url`. We need username + title + avatar URL + staff flag. Everything else is dropped.

**Resource**:
- `resource_id`, `title`, `view_url` (`/resources/{slug}.{id}/`), `version`, `view_count`, `description` (HTML), `Category` embedded, `user_id`, `username`. Versions / files separate endpoints (TBD).

**Pagination envelope** (used on listing endpoints):
```
"pagination": {
    "current_page": 1,
    "last_page": 12,
    "per_page": 20,
    "shown": 20,
    "total": 231
}
```

### Endpoints still to verify before writing the exporter

- [ ] `GET /api/threads/{id}/posts?include_deleted=1` — does it return soft-deleted? (We drop them per decision #7, but need to confirm they're filtered by default.)
- [ ] `GET /api/posts/{id}/attachments` vs attachments embedded in post — which has the download URL?
- [ ] `GET /api/attachments/{id}/data` — actual file bytes, content-type
- [ ] `GET /api/resources/{id}/versions` and `GET /api/resources/{id}/icon` — for full resource archival
- [ ] Behaviour of `per_page` on `/api/forums/{id}/threads` — first probe was ignored, confirm if `per_page=100` works or 20 is hard cap

## Pipeline overview

```
XenForo REST API
        |
        v
  [1] exporter/    --> data/threads/*.json
                       data/resources/*.json
                       data/meta.json (nodes, users)
        |
        +----> [2] mirror/        --> Cloudflare R2 (attachments, avatars, inline images)
        |
        v
  [3] builder/     --> dist/  (HTML + CSS + JS, sitemap, canonical URLs)
        |
        +----> [4] search/        --> Cloudflare D1 (FTS5 over lemmatised post bodies)
        |                            + Worker exposing /search?q=...
        v
  [5] deploy via GitHub Actions --> GitHub Pages --> archive.<domain>
```

## Stage 1 — Exporter

Goal: turn the live API into a complete on-disk JSON snapshot under `data/`,
re-runnable and resumable.

### Output layout

```
data/
├── meta.json              # nodes (categories+forums) + lookup tables
├── users/                 # one file per user encountered
│   ├── 1.json
│   └── ...
├── threads/
│   ├── 2.json             # one file per thread, all posts inline
│   └── ...
└── resources/
    ├── 1.json
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
  "user_groups": { "2": "Administrator", "3": "Разработчик", ... }, // derived
  "stats": { "threads": 3304, "posts": 45473, "users": 5194, "resources": 231 }
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
          "id": 123,
          "filename": "screen.png",
          "width": 1920,
          "height": 1080,
          "src_url": "https://torrentpier.com/attachments/screen-png.123/",
          "local_path": "attachments/123/screen.png",  // filled by mirror stage
          "r2_key": null                                // filled by mirror stage
        }
      ]
    }
  ]
}
```

### Implementation tasks

- [ ] `exporter/http.py`: `httpx.Client` wrapper with auth headers, `tenacity` retry (exponential backoff, retry on 5xx/429/transport), per-request rate limit (token bucket, default 1 rps, configurable).
- [ ] `exporter/nodes.py`: `GET /api/nodes` → write `data/meta.json` skeleton, return list of forum node ids to crawl.
- [ ] `exporter/threads.py`: for each forum: paginate `/api/forums/{id}/threads`, for each thread: paginate `/api/threads/{id}/?with_posts=1&page=N`, merge pages into one `data/threads/{id}.json`. Skip if file already exists unless `--force`.
- [ ] `exporter/users.py`: collect every `user_id` referenced from threads/posts/resources; fetch unique users; write `data/users/{id}.json`. Two-pass approach: first pass records ids, second pass fetches the missing ones.
- [ ] `exporter/resources.py`: paginate `/api/resources`, write `data/resources/{id}.json`. Need to confirm versions/files endpoints.
- [ ] `exporter/main.py`: orchestration (CLI flags `--stage nodes|threads|users|resources|all`, `--force`, `--rps`, `--from-thread`, `--only-thread`).
- [ ] Logging: structured (one line per HTTP call), default level INFO, `--verbose` for DEBUG.
- [ ] Resumability: presence of output file = "done" marker. No separate state file unless we discover XF returns paginated content with cursors that benefit from snapshotting.
- [ ] Tests: golden-file tests for normalisation logic with response fixtures saved under `exporter/tests/fixtures/`.

### Out of scope for stage 1

- Attachment **content** download (stage 2)
- HTML rewriting (stage 3)
- Lemmatisation (stage 4)

## Stage 2 — Mirror to Cloudflare R2

Goal: every binary referenced in `data/` lives in R2 with a stable, deduped key,
and `data/threads/*.json` carries `r2_key` for each attachment / avatar /
inline image.

### Bucket layout

```
attachments/{attachment_id}/{original_filename}     # XF native attachments
avatars/{user_id}.jpg                               # whichever size we standardise on (probably "l")
inline/{sha256[:2]}/{sha256}{ext}                   # external <img src> hot-linked in posts (deduped)
resources/{resource_id}/icon{ext}                   # resource icons
resources/{resource_id}/v/{version_id}/{filename}   # resource version files
```

### Implementation tasks

- [ ] Provision R2 bucket (`torrentpier-archive`) and a custom domain (e.g. `files.archive.<domain>`). **Open question — see below.**
- [ ] `mirror/main.py`: walks `data/`, for each unmirrored asset downloads from origin and uploads to R2 via `boto3` (S3-compatible). Concurrency via `asyncio` or `concurrent.futures` (4–8 workers).
- [ ] In-memory dedupe by sha256 for inline images (same image referenced from multiple posts → one R2 object).
- [ ] Idempotent: skip R2 keys that already exist (HEAD probe or local index `mirror/state.json`).
- [ ] After upload, write `r2_key` (and remove `src_url`?) into the corresponding JSON. Pretty-print for clean diffs.
- [ ] Sanity check at the end: every `r2_key` in `data/` resolves on R2.

### Out of scope for stage 2

- Rewriting the in-post HTML (`message_parsed`) to use R2 URLs — that happens at build time so we can change the public R2 URL without touching `data/`.

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
| `/resources/{slug}.{id}/`                | `resource.html`| Resource detail                            |
| `/members/{slug}.{id}/`                  | `member.html`  | Minimal: avatar, name, title, post count   |
| `/sitemap.xml`                           | (script)       | All canonical URLs                         |
| `/robots.txt`                            | static         | Allow all                                  |
| `/search/`                               | `search.html`  | Search UI talking to the worker            |

### `message_parsed` post-processing

Each post body runs through a sanitisation + rewriting pass with BeautifulSoup:

1. Replace `<img src=...>` and `<a href=...>` pointing at hosted attachments / avatars with their public R2 URLs (via lookup table).
2. Replace external `<img>` (lookup against the inline-image dedupe table) with R2.
3. Rewrite XF internal links (`/threads/...`, `/forums/...`, `/posts/...`, `/members/...`, `/resources/...`) to be **same-origin** (URL scheme already matches → typically just strip the `https://torrentpier.com` prefix).
4. Strip `<script>`, all `on*` attributes, and `<iframe>` whose `src` host is not in an allowlist (YouTube only, probably).
5. Add `loading="lazy"` to all `<img>`.
6. Add `rel="noopener nofollow"` to external `<a>`.

### Implementation tasks

- [ ] `builder/main.py` — orchestration (`--data data/ --out dist/`).
- [ ] `builder/render.py` — Jinja2 environment, helpers for date formatting, URL building.
- [ ] `builder/rewrite.py` — `message_parsed` rewriter.
- [ ] `builder/sitemap.py`.
- [ ] `templates/` + `static/`: minimal, readable, dark-mode via `prefers-color-scheme`. No XF CSS.
- [ ] Determinism: same `data/` → byte-identical `dist/` (sorted file iteration, frozen timestamps).

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
    title,                  -- denormalised thread title (boosted in queries)
    content='',             -- contentless table; we store originals only in posts/threads
    tokenize='unicode61 remove_diacritics 2'
);
```

### Indexer (Python, run once locally)

- [ ] `search/index.py`: walks `data/threads/`, for each post: BeautifulSoup→`get_text()`, normalise whitespace, lemmatise via `pymorphy3` (cache per token), emit `INSERT` statements.
- [ ] Output a `search/seed.sql` that's fed to D1 via `wrangler d1 execute --file=...` in batches of ~5000 statements (D1 import limit).

### Worker (TypeScript, ~80 lines)

- [ ] `search-worker/src/index.ts`: `/search?q=...` endpoint, escapes FTS5 query syntax, returns top-30 results with `<mark>`-highlighted snippets, `Cache-Control: public, max-age=3600`.
- [ ] `search-worker/wrangler.toml`: D1 binding, custom domain route `search.archive.<domain>/*`.
- [ ] Lemmatise the user query the same way as the index. Two viable options:
  - Lemmatise on the client (small JS lemmatiser bundle) before calling the worker — keeps the worker stateless.
  - Lemmatise inside the worker using a pure-JS port of pymorphy3 dictionaries — bigger bundle, simpler frontend.
  Decide during stage 4.

### Frontend search page

- [ ] `static/js/search.js` — submits to `https://search.archive.<domain>/search?q=...`, renders results as links with breadcrumbs and snippet, debounce 200ms.

## Stage 5 — Deploy

- [ ] `.github/workflows/build.yml`: on push to `main` touching `data/`, `templates/`, `static/`, `builder/`: install deps, run `python -m builder.main`, upload `dist/` as Pages artifact, deploy.
- [ ] CNAME file in `static/CNAME` with the archive subdomain.
- [ ] Cloudflare side: CNAME → `<user>.github.io`, plus Bulk Redirect List from old hostname → `archive.<domain>` (URL paths are preserved by design).

## Open questions / decisions still owed

- [ ] **R2 provisioning route.** Either user issues a Cloudflare API token (`Account → R2 Storage → Edit`, plus `Workers Scripts → Edit` and `D1 → Edit` for stage 4) and we provision via `wrangler` from the repo, or user creates the bucket manually and hands over an R2 access key + secret + endpoint + bucket name. Decide before stage 2.
- [ ] **R2 public URL.** Is `files.archive.<domain>` the wanted hostname? What is `<domain>`?
- [ ] **Archive subdomain.** Is `archive.<domain>` the wanted hostname?
- [ ] **Resources file content.** Are the actual resource downloads (binary mods/scripts) part of the archive, or just the description pages?
- [ ] **YouTube iframes.** Keep as iframes (relies on YouTube staying online) or downgrade to text links during HTML rewrite? Decide during stage 3.
- [ ] **Per-page count.** Confirm `per_page=100` is allowed on listing endpoints, otherwise 3304 threads = 165 paginated calls per stage instead of ~33.

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
