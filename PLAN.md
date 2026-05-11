# Development plan: torrentpier.com static archive

This document is the single source of truth for the project. It must be
detailed enough that work can be paused and resumed at any point — by the
same or a different operator — without losing context. Update it after every
meaningful decision or completed step.

## Status snapshot (2026-05-11, end of session 4)

| # | Item                                                       | State |
|---|------------------------------------------------------------|-------|
|   | Branch                                                     | `feat/archive` (~35 commits, **still not pushed**) |
|   | Repo skeleton (dirs + meta files)                          | Done (`c12ba69`) |
|   | API surface verified (probed live)                         | Done — see "API surface" below |
|   | Wrangler installed (Homebrew)                              | Done — 4.90.0 |
|   | Cloudflare auth (`wrangler login`)                         | n/a — operator works via R2 token + `.env`, wrangler not actually used |
|   | Python venv + deps (`uv venv`, py3.13)                     | Done — `.venv/` in repo (gitignored) |
| 1 | Exporter — `nodes` stage                                   | Done — 34 nodes (7 categories, 27 forums) |
| 1 | Exporter — `threads` stage (incl. sticky)                  | Done — **3,304 threads, 42,868 posts** after sticky fix; matches XF UI totals across container forums |
| 1 | Exporter — `users` stage (incidental from `post.User`)     | Done — 1,096 unique authors (after sticky re-run); `UserCache.flush` now merges, preserving mirror-side fields |
| 1 | Exporter — `resources` stage                               | Done — 230 resources, 548 versions, 511 files (62.83 MiB binary) |
| 1 | Exporter — `profile-posts` stage                           | Done — **90 walls, 209 wall posts, 62 comments** across 1,109 users. Requires DB-side privacy reset (see "Session 3 — profile-posts ramp-up" below) because XF API enforces per-user `allow_view_profile`/`is_banned`/`visible` even for super-admin keys. |
| 1 | Exporter — `resource-reviews` stage                        | Done — **60 reviews** across 32 resources (was 1 — fixed in session 4 by switching from global feed to per-resource enumeration via `/api/resources/{id}/reviews/`). |
| 1 | Exporter — `resource-updates` stage                        | Done — **329 update announcements** across 120 resources (DB has 562 — investigate API filter). |
| 1 | Exporter — thread polls (free side-effect)                 | Done — `thread.Poll` captured during the standard threads stage, no extra API calls. 17 polls captured. |
| 1 | Exporter — `wall-owners` helper                            | Done — fetches lurker users who own a wall but never posted/commented. Used to add 8 wall owners not covered by post-author + comment-author harvest. |
| 2 | Mirror — R2 bucket + custom domain (`files-ox.torrentpier.com`) | Done — bucket `torrentpier-archive`, custom domain live |
| 2 | Mirror — Python uploader (boto3, ThreadPoolExecutor, atomic JSON update) | Done — concurrent (8 workers); full run ~13 min, sticky-delta + avatar re-up ~5 min |
| 2 | Mirror — `r2_key` written into every JSON asset; inline dedupe map | Done — **3319 attachments / 506 hi-res avatars / 136 icons / 511 res-files / 549 inline live + 423 dead** |
| 2 | Mirror — `--force` flag for re-uploads (e.g. avatar `l`→`h` swap) | Done — used to upgrade every avatar from size `l` to size `h` (hi-res) |
| 3 | Builder — index + category + forum (paginated 30/page, recursive counts, sub-forum block) | Done |
| 3 | Builder — thread (paginated 10/page) with avatars + badges + clickable breadcrumbs | Done |
| 3 | Builder — resource pages with version table + icon                | Done |
| 3 | Builder — `message_parsed` sanitiser + URL canonicaliser (threads/forums/members) | Done |
| 3 | Builder — `/resources/`, `/search/`, `sitemap.xml`, `robots.txt` | Done |
| 3 | Builder — wire R2 URLs after mirror stage runs             | Done — attachments by id, inline by src URL, avatars + icons + version files |
| 3 | Builder — `/posts/{id}/` redirect to thread anchor         | Done — 42,868 meta-refresh pages |
| 3 | Builder — `/members/` index + `/members/{slug}.{id}/` pages | Done — 1,096 users, paginated index |
| 3 | Builder — `dist/CNAME`, build time pinned to `meta.exported_at` (determinism) | Done — verified byte-identical on rebuild |
| 3 | Builder — visual refresh (XF-style cards, header + logo + nav, table posts) | Done |
| 3 | Builder — wall section on `/members/{slug}.{id}/` + `/profile-posts/{id}/` + `/profile-posts/comments/{id}/` redirects | Done — 271 profile-post redirects, sanitiser/canonicaliser applied to wall + comment bodies |
| 3 | Builder — resource page rating widget + reviews block       | Done — half-star widget driven by `rating_avg`, review cards under the version table |
| 3 | Builder — resource page Updates timeline                    | Done — chronological updates section above Versions |
| 3 | Builder — thread page poll widget                           | Done — bar-chart poll under the title, shown on page 1 only |
| 3 | Builder — sub-forums UI overhaul                            | Done — index/category use pill-style chips inside a tinted "Sub-forums" plate; forum page Sub-forums block uses the same card row pattern as index. No more double-chevron artifact. |
| 4 | Search — Python indexer (lemmatised plain text → SQL)      | Not started |
| 4 | Search — Cloudflare D1 schema + import                     | Not started — needs `wrangler login` (this stage truly does) |
| 4 | Search — TypeScript Worker exposing `/search?q=`           | Not started |
| 4 | Search — frontend on `/search/` page                       | Not started (placeholder lives) |
| 5 | Deploy — GitHub Actions build + Pages deploy               | Workflow committed (`.github/workflows/build.yml`); will fire on **first push to `main`** |
| 5 | Deploy — DNS: `ox.torrentpier.com` CNAME → Pages           | Not started |
| 5 | Deploy — Bulk Redirect from `torrentpier.com/*` → archive  | Not started |
| 5 | Cutover — confirm archive live, revoke super-user API key  | Not started |
| 5 | R2 cache purge for `/avatars/*` (one-time, after avatar `h` swap) | **Pending — manual user action in Cloudflare dashboard**; old `l`-size cached on edge until purge or natural TTL |

## Source forum

- URL: `https://torrentpier.com`
- Engine: XenForo 2 with the Resource Manager add-on
- Currently in read-only / maintenance mode — snapshot is consistent
- Volume: 3,280 visible threads, 42,623 forum posts, 1,085 posting users
  (5,194 registered total; the rest are lurkers and don't appear in the
  archive), 230 resources, 209 profile-post wall messages + 62 wall comments
  across 90 active walls (1,109 users after wall-comment authors merged in),
  1 textual resource review.

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
| 21 | Profile posts are inlined into `data/users/{id}.json` under `wall_posts[]` (with nested `comments[]`) + a top-level `wall_total` and `wall_access` marker. | Volumes are tiny (max wall = 21 posts) and the data semantically belongs to a user. Keeps file count flat. |
| 22 | Wall export resets XF privacy gates server-side: for any user with `wall_access == 'hidden'` (XF returns 403 `member_limits_viewing_profile`) we flip `xf_user_privacy.allow_view_profile = 'everyone'` plus `xf_user.is_banned = 0` and `xf_user.visible = 1` directly in MariaDB. | XF respects per-user privacy even for super-admin API keys and the `XF-Api-Bypass-Permissions` header — there is no API-side workaround. The forum is shutting down; the user owns it and explicitly authorised the change. Backup of original rows is at `/opt/xenforo/data/xf_user{,_privacy}.backup-2026-05-11.sql` on the server. |
| 23 | Resource reviews are exported via `/api/resource-reviews` (collection) and inlined into `data/resources/{id}.json` under `reviews[]`. | XF has no `/api/resources/{id}/reviews` endpoint. Re-running the stage rewrites every resource's `reviews` list deterministically (sorted by `rating_date, id`). |

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
| `GET /api/profile-posts/`                               | 404    | No bulk collection endpoint — list per user via `/api/users/{id}/profile-posts`                        |
| `GET /api/users/{id}/profile-posts?page=N`              | 200/403 | Wall listing, server-fixed `per_page=10`. 403 `member_limits_viewing_profile` when the user has `allow_view_profile != 'everyone'`, `is_banned == 1`, or `visible == 0` — even for super-admin tokens with `XF-Api-Bypass-Permissions: 1`. |
| `GET /api/profile-posts/{id}/comments?page=N`           | 200    | Comments on a profile post (when `comment_count > len(LatestComments)` in the listing).                |
| `GET /api/profile-posts/{id}?with_comments=1`           | 200    | Single profile post detail with `ProfileUser` (wall owner) and `User` (poster). `with_comments=1` is accepted but **does not embed comments** — only `LatestComments` is ever populated.  |
| `GET /api/resource-reviews?page=N`                      | 200    | Collection of textual reviews across all resources. `pagination.total=1` on this forum. Each review carries embedded `Resource` and `User`. |
| `GET /api/resources/{id}/reviews`                       | 404    | No per-resource endpoint. Filter the collection client-side.                                            |
| `GET /api/resource-updates`                             | 405    | POST-only — write API for creating update announcements. No read access.                                |
| `GET /api/media`, `/api/featured-content`               | 404    | XF Media Gallery + Featured Content add-ons not installed.                                              |

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

## Session 4 — deep re-audit of API vs DB (Done)

Cross-checked every content table in the source DB against the archive
counts. The headline finding is that **forum posts are complete** — the
"2,605-post delta" assumption from earlier sessions was wrong (the count
in the PLAN was stale; archive has 45,473 visible posts, matches DB).

Real gaps found and fixed in this session:

| Area              | DB | Archive (before) | Archive (after) |
|-------------------|----|------------------|-----------------|
| Resource reviews  | 62 | 1   | **60** (2 on hidden resources) |
| Resource updates  | 562 | 0  | **329** (233 likely auto-generated version entries — investigation pending) |
| Thread polls      | 17 | 0   | **17** (free side-effect of standard thread fetch, payload always had `Poll`) |
| Wall posts        | 217 | 209 | **217** (added 8 wall-owners that weren't in the user index) |
| Wall comments     | 120 | 62  | **120** (always paginate dedicated comments endpoint; `LatestComments` was capped) |

API endpoints discovered after re-reading openapi.json that we previously
missed (now used):
- `/api/resources/{id}/reviews/` and `/api/resources/{id}/updates/` (trailing
  slash matters — without it XF returns 404)
- `thread.Poll` embedded in `/api/threads/{id}/?with_posts=1` (always present
  when the thread has a poll)

Hard limits — XF data we cannot reach via the public API even with super
admin + `XF-Api-Bypass-Permissions: 1`:
- `/api/featured-content` and `/api/featured/` both 404
- `/api/tags` 404 (bulk listing; tags are still per-thread inline)
- `/api/resource-updates/{id}/` 404 (only the per-resource collection works)
- `/api/profile-posts/` (bulk) 404
- 1 hidden resource and ~20 attachments on deleted posts not exposed

Other small cleanups:
- `threads.py` now preserves the per-attachment `r2_key` from the existing
  thread JSON when re-exporting (mirror-side state is precious and must not
  be clobbered by a routine `--force`).

## Session 3 — profile-posts + resource-reviews (Done)

What changed since the end-of-session-2 snapshot:

- New stage `exporter/profile_posts.py` (`xf-export profile-posts`) walks every
  `data/users/{id}.json`, fetches `/api/users/{id}/profile-posts` paginated and
  pulls the full comment list per post via `/api/profile-posts/{id}/comments`
  when `comment_count > len(LatestComments)`. Output is merged into the user
  JSON under `wall_posts[]` / `wall_total` / `wall_access`. Cache flush in
  `users.py` preserves `wall_posts`, `wall_total`, `wall_access` alongside the
  existing `avatar_r2_key`.
- New stage `exporter/resource_reviews.py` (`xf-export resource-reviews`)
  walks `/api/resource-reviews`, buckets reviews by `Resource.resource_id`,
  and rewrites every `data/resources/{id}.json` under `reviews[]`
  (deterministically sorted).
- The XF API enforces per-user `allow_view_profile`, `is_banned`, `visible`
  even for super-admin keys, returning `403 member_limits_viewing_profile`
  on 58 users. **Resolved server-side** by direct DB UPDATE: full backup at
  `/opt/xenforo/data/xf_user{,_privacy}.backup-2026-05-11.sql`, then
  `UPDATE xf_user_privacy SET allow_view_profile='everyone' …` and
  `UPDATE xf_user SET is_banned=0, visible=1 …` scoped to the 58 ids. After
  the flip, `wall_access` is `ok` for every user (1,109 of 1,109).
- Builder now renders a wall section on `/members/{slug}.{id}/` with a 120 px
  author column matching forum posts, sanitised `message_parsed` for both
  wall posts and comments, anchors `#profile-post-{id}` and
  `#profile-post-comment-{id}`. New redirect families
  `/profile-posts/{id}/` and `/profile-posts/comments/{id}/` route XF deep
  links to the right anchor on the right member page (271 redirects total).
- Resource pages get a half-star rating widget driven by `rating_avg` /
  `rating_count` and a Reviews block under the version table.

Volumes:

| Asset                              | Count |
|------------------------------------|-------|
| Wall posts (`wall_posts[]`)        | 209   |
| Wall comments (`wall_posts[].comments[]`) | 62 |
| Active walls (`wall_total > 0`)    | 90    |
| Inactive walls (`wall_total == 0`) | 1,019 |
| `wall_access == 'hidden'`          | 0 (was 58 before DB reset) |
| Textual resource reviews           | 1     |

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
.venv/bin/python -m exporter --data data threads          # idempotent: skips existing /threads/{id}.json
.venv/bin/python -m exporter --data data resources --force
.venv/bin/python -m exporter --data data profile-posts    # idempotent: skips users where wall_total is already set
.venv/bin/python -m exporter --data data resource-reviews # rewrites every data/resources/{id}.json reviews[]
.venv/bin/python -m exporter --data data resource-updates # rewrites every data/resources/{id}.json updates[]
.venv/bin/python -m exporter --data data wall-owners --add 285,906,5604,6109,6431,7819,10655,10660  # one-off
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

## Stage 2 — Mirror to Cloudflare R2

Goal: every binary referenced from `data/` lives in R2 under a stable, deduped
key, and `data/threads/*.json` / `data/resources/*.json` carry `r2_key` for
each asset.

### Status: code complete, awaiting credentials

The `mirror/` package is implemented and importable. It cannot run yet
because the R2 bucket does not exist and `.env` has no R2 credentials.
The remaining work is **all user-side, one-time setup** — see below.

Expected asset inventory (measured from current `data/`):

| Category        | Count | Bytes (where known)              |
|-----------------|-------|----------------------------------|
| Attachments     | 3,197 | 455.4 MiB                        |
| Avatars (size l)| 502   | small (≤50 KiB each)             |
| Resource icons  | 136   | small                            |
| Resource files  | 511   | 62.8 MiB                         |
| Inline external | 972 unique URLs | unknown — many likely 404 |

Comfortably inside the R2 free tier (10 GiB).

### R2 setup (one-time, manual — user)

1. `wrangler login` — opens browser, OAuth into Cloudflare account that
   owns torrentpier.com.
2. `wrangler r2 bucket create torrentpier-archive`.
3. Cloudflare dashboard → R2 → `torrentpier-archive` → Settings → Custom
   Domains → add `files-ox.torrentpier.com`. Cloudflare creates the
   matching DNS record automatically.
4. R2 → Manage R2 API Tokens → "Create API token" with **Object Read &
   Write** on `torrentpier-archive`. Save Access Key ID + Secret Access
   Key into `.env` as `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY`.
5. Fill `.env`: `R2_ACCOUNT_ID`, `R2_BUCKET=torrentpier-archive`,
   `R2_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com`,
   `R2_PUBLIC_URL=https://files-ox.torrentpier.com`.

The Python code uses **boto3** (S3-compatible API) against the R2 endpoint;
wrangler is only used for the one-time bucket/domain setup above.

### Bucket layout

```
attachments/{attachment_id}/{filename}              # XF native attachments
avatars/{user_id}{ext}                              # standardised on size "l"
inline/{sha256[:2]}/{sha256}{ext}                   # external <img src> in posts (deduped)
resources/{resource_id}/icon{ext}                   # resource icons
resources/{resource_id}/v/{version_id}/{filename}   # resource version files
```

### Package layout (implemented)

- `mirror/r2.py` — boto3 client (`head`, `put`, `public_url`).
- `mirror/download.py` — `httpx`-based downloader. Anonymous by default;
  flips to authenticated (XF-Api-Key header) for resource version files,
  whose `download_url` is an XF API endpoint. Returns `(body, ct, status)`
  on 2xx, `(b"", None, status)` on non-2xx, `None` on transport error.
- `mirror/keys.py` — pure path/filename helpers; ASCII-safe, deterministic.
- `mirror/inline.py` — `InlineIndex` persisted at `data/inline_index.json`.
  Schema: `{by_url: {url: {sha256, r2_key, size} | {failed, status}}}`.
  Idempotent across runs; permanent 4xx URLs are skipped on the next run.
- `mirror/pipeline.py` — four idempotent stages
  (`mirror_attachments`, `mirror_avatars`, `mirror_resources`,
  `mirror_inline`) plus `verify` (HEAD every `r2_key`). HEADs before any
  upload to make re-runs cheap. Inline dedupes by sha256 across URLs.
  `current_files[]` aliases the matching version-file `r2_key` instead of
  uploading twice.
- `mirror/main.py` — CLI:
  ```
  .venv/bin/python -m mirror upload --data data
  .venv/bin/python -m mirror upload --data data --only attachments --only avatars
  .venv/bin/python -m mirror verify --data data
  .venv/bin/python -m mirror scan --data data    # offline inventory, no I/O
  ```
  Throttled to 2 rps by default; override via `MIRROR_RPS`. Sequential
  (no concurrency yet — add a `ThreadPoolExecutor` if rps×duration hurts).

### Fields added to `data/*.json` by mirror

- `data/threads/{id}.json` → each `attachments[].r2_key`.
- `data/users/{id}.json` → new top-level `avatar_r2_key`.
- `data/resources/{id}.json` → new top-level `icon_r2_key`; each
  `versions[].files[].r2_key` and `current_files[].r2_key`.
- `data/inline_index.json` — the inline dedupe map.

### Builder integration (after mirror runs)

Code already canonicalises slugs in internal links. The remaining wiring
will be one focused commit once the mirror stage has run at least once:

- [ ] Build an `asset_url_map` in `builder/site.py` from:
  - `attachments[].r2_key` for every post,
  - `users[].avatar_r2_key`,
  - `resources[].icon_r2_key` and `versions[].files[].r2_key`,
  - `data/inline_index.json` (`by_url`).
- [ ] Resolve in-post `/attachments/{id}/` URL variants via a global
  `{attachment_id → r2_key}` lookup (verified: 558 of 575 internal "inline"
  URLs are alternate forms of existing attachments — do not re-mirror).
- [ ] Extend `builder/rewrite.py` to accept `asset_url_map` and swap
  `<img src>` / `<a href>` to `r2.public_url(key)`.
- [ ] `templates/thread.html` — use R2 avatar URL when `avatar_r2_key` is set.
- [ ] `templates/resource.html` — link version files to R2 instead of the
  XF API endpoint.

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
| `/posts/{id}/`                             | `redirect.html`| Meta-refresh + JS replace to the right thread page + `#post-{id}` |
| `/members/`, `/members/page-N/`            | `members_index.html` | Paginated user index, 30/page    |
| `/members/{slug}.{id}/`                    | `member.html`  | Minimal user profile                   |
| `/resources/`                              | `resources_index.html` | Resource categories            |
| `/resources/categories/{slug}.{id}/`       | `rcategory.html` | Resources in a category              |
| `/resources/{slug}.{id}/`                  | `resource.html`| Resource detail with versions table    |
| `/search/`                                 | `search.html`  | Placeholder until Worker exists        |
| `/sitemap.xml`                             | (script)       | All canonical URLs with lastmod        |
| `/robots.txt`                              | static         | Allow all                              |
| `/CNAME`                                   | (script)       | `ox.torrentpier.com` for GitHub Pages  |

### Outstanding builder tasks

- [ ] Wire R2 URLs into `message_parsed` rewrite + avatar rendering after mirror stage runs.
  Builder already canonicalises link slugs; once mirror sets `r2_key` on attachments / avatars / inline,
  add an `asset_url_map: dict[str, str]` pass that swaps `<img src>` / `<a href>` to the R2 public URL.
  Resolve in-post `/attachments/{id}/` variants via a global `{attachment_id → r2_key}` lookup (verified:
  558 of 575 internal "inline" URLs are alternate forms of existing attachments — do not re-mirror).

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

## Stage 5 — Deploy (workflow committed; awaiting first push)

The workflow at `.github/workflows/build.yml` does the following on every push
to `main` that touches `data/`, `templates/`, `static/`, `builder/`, the
workflow itself, or `pyproject.toml`:

1. Set up Python 3.13 + cache pip.
2. `pip install -e .` (installs the builder package).
3. `python -m builder build --data data --out dist`.
4. Assert `dist/CNAME == "ox.torrentpier.com"`.
5. Upload `dist/` as a Pages artifact and deploy via `actions/deploy-pages@v4`.

Concurrency group `pages` prevents overlapping deploys. The DNS flip is still
manual (see "Cloudflare side" below).

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

- [x] ~~Server-side size of the forum's actual attachments.~~ Measured at
  mirror time: 455 MiB across 3,197 attachments. Comfortable inside R2's
  10 GiB free tier.
- [x] ~~**Profile posts / resource discussion comments not exported.**~~ Done
  in session 3: 209 wall posts + 62 wall comments + 1 review captured. The
  ~2,400 still-missing messages are likely deleted/moderated forum posts
  (XF counts those in the public total) — no public API for them.
- [ ] **YouTube iframes.** Current rewrite keeps them (relies on YouTube
  staying online). Consider downgrading to a text link "[video: …]"
  during stage 3 so the archive degrades gracefully if YouTube ever
  removes a video.
- [x] ~~`/posts/{id}/` redirect page.~~ Implemented; 42,868 meta-refresh
  pages link old XF-style deep-links to the right thread page + anchor.
- [ ] **Avatar cache-busting.** Current R2 key is `avatars/{id}.jpg` —
  any future re-upload of a user's avatar will need another manual cache
  purge. Consider including an `avatar_hash` (or `avatar_urls` query
  timestamp) in the key, or setting a short `Cache-Control` header on
  PUT so the edge expires within minutes.

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

### What's left for the next session (in dependency order)

Everything that can be done locally is done. The remaining work is split
between **manual one-shots in the Cloudflare dashboard / on GitHub** and
**a single new Stage 4 implementation**.

1. **Purge `/avatars/*` on the R2 CDN (user, 30 seconds).** All 506 avatars
   were re-uploaded from size `h` (hi-res) on top of the original size-`l`
   key. R2 now serves the hi-res bytes, but the Cloudflare edge cache on
   `files-ox.torrentpier.com` is still handing out the old size-`l`
   versions until TTL expires.
   Cloudflare dashboard → Caching → Configuration → Purge Cache → Custom
   Purge → URL = `https://files-ox.torrentpier.com/avatars/*`
   (Purge Everything works too.) After this, avatars on
   `ox.torrentpier.com` will look noticeably crisper.

2. **First push to `main` (operator + GitHub).** `git push -u origin
   feat/archive` then open a PR into `main` and merge it (or push
   directly to `main` if no review needed). The committed
   `.github/workflows/build.yml` will:
   - render `dist/` via `python -m builder build`,
   - check `dist/CNAME == ox.torrentpier.com`,
   - deploy to GitHub Pages.

   **Before pushing**, decide whether to ship one branch with everything
   or split into pre-cutover (mirror+builder ready) and post-cutover
   (search). One branch is fine — the archive is already useful without
   search, and Pages only deploys what's in `dist/`.

3. **DNS flip (user, one-shot in Cloudflare dashboard).**
   - DNS → add record: `ox` CNAME `<github-user>.github.io`, proxied.
   - Wait ~1 min for propagation, hit `https://ox.torrentpier.com/`,
     smoke-test 5–10 deep-link URLs from previous chats / search engines.
   - Add Bulk Redirect list: any request to the live forum host →
     `https://ox.torrentpier.com/$1`. URL paths are preserved by design,
     so this is a clean cutover with no per-thread redirect rules.

4. **Stage 4 — search (a session of its own).** Pipeline lives in
   "Stage 4 — Search worker + D1 (TODO)" below. Order:
   - `wrangler login` + `wrangler d1 create ox-archive-search`.
   - Write `search/index.py` that walks `data/threads/` and emits a
     deterministic `search/seed.sql` (lemmatise post bodies with
     `pymorphy3`, sort inserts by `(thread_id, position)`).
   - `wrangler d1 execute ox-archive-search --file=search/seed.sql --remote`.
   - Write the ~80-line TS worker in `search-worker/` and bind it at
     `search-ox.torrentpier.com`.
   - Replace the `/search/` template placeholder with a real form + JS
     calling the worker.

5. ~~Open question: profile posts / resource discussions.~~ Done in session
   3 — see "Session 3 — profile-posts + resource-reviews" above. Server-side
   DB UPDATE in `xf_user_privacy` + `xf_user` to unblock 58 hidden walls is
   reversible via `/opt/xenforo/data/xf_user{,_privacy}.backup-2026-05-11.sql`
   if needed.

6. **Revoke the super-user API key.** Final step after the cutover
   smoke-test passes. XF admin panel → API keys → revoke
   `XF_API_KEY` from `.env`. Without this the key keeps working against
   whatever still answers on the old hostname.

### Quick resume checklist

```bash
# Sanity check the build still produces what it should
.venv/bin/python -m builder build --data data --out dist
.venv/bin/python -m http.server 8765 --directory dist
# open http://127.0.0.1:8765/

# Sanity check mirror state without touching R2
.venv/bin/python -m mirror scan --data data
# expect: every _total == _done, inline_index_done ≈ 549

# Sanity check what's actually in R2
.venv/bin/python -m mirror verify --data data --concurrency 16
# expect: only *_ok lines, no *_missing
```

## References

- XenForo API docs: <https://docs.xenforo.com/api>
- Cloudflare R2 docs: <https://developers.cloudflare.com/r2/>
- Cloudflare D1 + FTS5: <https://developers.cloudflare.com/d1/>
- pymorphy3: <https://github.com/no-plagiarism/pymorphy3>
- This repo's commit log: `git log feat/archive --oneline`
