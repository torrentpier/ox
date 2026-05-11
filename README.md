# TorrentPier Ox Archive

Static, read-only archive of the TorrentPier support forum (XenForo 2),
which ran from 2011 to 2026.

## Goal

Preserve every public thread, post, attachment, resource and profile-post
as a static, read-only site served from GitHub Pages, with binary files
hosted on Cloudflare R2 and full-text Russian search powered by a
Cloudflare Worker + D1 (SQLite/FTS5 with Snowball stemming).

## Snapshot

As of 2026-05-11:

| Threads | Posts  | Authors | Resources | Wall posts | Wall comments | Reviews | Polls |
|--------:|-------:|--------:|----------:|-----------:|--------------:|--------:|------:|
| 3,304   | 45,473 | 1,120   | 230       | 217        | 120           | 60      | 17    |

R2 binaries: 3,319 attachments · 506 hi-res avatars · 136 resource icons ·
511 resource version files · 549 deduped inline images. Full-text search
runs over every post body via D1 FTS5.

## Layout

| Path             | What it holds                                              |
|------------------|------------------------------------------------------------|
| `exporter/`      | XenForo REST API → JSON (CLI: `xf-export`)                 |
| `mirror/`        | Cloudflare R2 upload for attachments / avatars / inline    |
| `builder/`       | Jinja2 templates → static HTML in `dist/`                  |
| `search/`        | Snowball-stemmed FTS5 indexer that produces `seed.sql`     |
| `search-worker/` | Cloudflare Worker at `search-ox.torrentpier.com`           |
| `data/`          | Versioned JSON export (one file per thread / resource / user) |
| `templates/`     | Jinja2 templates                                           |
| `static/`        | CSS                                                        |

## Build locally

```bash
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python -e .
cp .env.example .env  # fill XF_API_KEY, R2 creds; only needed for re-export

.venv/bin/python -m builder build --data data --out dist
.venv/bin/python -m http.server 8765 --directory dist
# open http://127.0.0.1:8765/
```

The exporter, mirror and search indexer all read from `data/`, so the
builder can produce the full static site without any network access.

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) — Mermaid diagrams of the data
pipeline, the search request flow, the deploy flow, plus a decisions log
and a verified map of the XenForo API surface.

## License

[MIT](./LICENSE).
