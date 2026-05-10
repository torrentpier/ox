# torrentpier.com XenForo archive

Static archive generator for the soon-to-be-closed torrentpier.com XenForo 2 forum.

## Goal

Preserve threads, posts, attachments and resources as a static, read-only site
served from GitHub Pages, with files hosted on Cloudflare R2 and full-text
search powered by a small Cloudflare Worker + D1 (SQLite/FTS5).

## Layout

| Path             | Purpose                                                |
|------------------|--------------------------------------------------------|
| `exporter/`      | Python script: pulls JSON from the XenForo REST API    |
| `builder/`       | Python script: renders static HTML from `data/`        |
| `search-worker/` | Cloudflare Worker + D1 schema (full-text search API)   |
| `data/`          | Versioned API export (one JSON per thread / resource)  |
| `templates/`     | Jinja2 templates for the static site                   |
| `static/`        | CSS, JS, fonts, icons                                  |
| `dist/`          | Build output (gitignored; produced by `builder`)       |
| `attachments/`   | Local mirror before R2 upload (gitignored)             |

## Status

WIP — repository skeleton only. See branch `feat/archive`.

Pipeline stages, in order:

1. **Export** XenForo API → `data/threads/*.json`, `data/resources/*.json`, `data/meta.json`
2. **Mirror** attachments + avatars + inline images → Cloudflare R2
3. **Build** static HTML from `data/` via Jinja2 templates → `dist/`
4. **Index** post bodies (lemmatised) into Cloudflare D1, served by a Worker
5. **Deploy** `dist/` to GitHub Pages via GitHub Actions; CNAME to the archive subdomain

## Configuration

Copy `.env.example` to `.env` and fill in the required values. `.env` is
gitignored.

## License

TBD.
