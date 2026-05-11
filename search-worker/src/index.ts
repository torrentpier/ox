// GET /search?q=...&limit=N → JSON results from D1 FTS5.
//
// The query is tokenised + Snowball-stemmed (matching the indexer in
// ../search/text.py), wrapped in double quotes per token to neutralise
// FTS5 special chars, and joined as an implicit AND. Hits come back
// ordered by FTS5 rank. The Worker re-tokenises `body_plain` to build a
// short snippet with <mark>-highlighted matches.

import { makeSnippet } from "./snippet";
import { stemQuery } from "./text";

export interface Env {
  DB: D1Database;
}

interface PostRow {
  thread_id: number;
  title: string;
  slug: string | null;
  url_path: string;
  forum_title: string;
  post_id: number;
  page_no: number;
  post_author: string | null;
  post_date: number | null;
  body_plain: string;
}

const CORS_HEADERS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
      ...CORS_HEADERS,
      ...(init.headers as Record<string, string> | undefined),
    },
  });
}

function buildFtsMatch(stems: string[]): string {
  // Wrap each stem in double quotes to neutralise FTS5 operators
  // (`*`, `-`, `:`, parens, etc.). Space-separated = implicit AND.
  return stems.map((s) => `"${s.replaceAll('"', '""')}"`).join(" ");
}

function postUrl(row: PostRow): string {
  const base = row.url_path.endsWith("/") ? row.url_path : row.url_path + "/";
  const page = row.page_no > 1 ? `page-${row.page_no}/` : "";
  return `${base}${page}#post-${row.post_id}`;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }
    if (request.method !== "GET") {
      return new Response("Method Not Allowed", { status: 405, headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    if (url.pathname !== "/search") {
      return new Response("Not Found", { status: 404, headers: CORS_HEADERS });
    }

    const q = (url.searchParams.get("q") ?? "").trim();
    if (q.length < 2 || q.length > 200) {
      return jsonResponse({ q, results: [], count: 0 });
    }

    const stems = stemQuery(q);
    if (stems.length === 0) {
      return jsonResponse({ q, results: [], count: 0 });
    }

    const limitParam = parseInt(url.searchParams.get("limit") ?? "20", 10);
    const limit = Number.isFinite(limitParam) && limitParam > 0 ? Math.min(limitParam, 50) : 20;
    const offsetParam = parseInt(url.searchParams.get("offset") ?? "0", 10);
    const offset = Number.isFinite(offsetParam) && offsetParam >= 0
      ? Math.min(offsetParam, 5000)
      : 0;

    const ftsMatch = buildFtsMatch(stems);

    // Fetch limit+1 to cheaply detect whether more results exist without a
    // separate COUNT query against FTS5 (which would double D1 latency).
    const fetchN = limit + 1;
    const sql = `
      SELECT t.id AS thread_id, t.title, t.slug, t.url_path, t.forum_title,
             p.id AS post_id, p.page_no,
             p.username AS post_author, p.post_date,
             p.body_plain
      FROM posts_fts
      JOIN posts p ON p.id = posts_fts.rowid
      JOIN threads t ON t.id = p.thread_id
      WHERE posts_fts MATCH ?
      ORDER BY rank
      LIMIT ? OFFSET ?
    `;

    let rawRows: PostRow[];
    try {
      const result = await env.DB.prepare(sql).bind(ftsMatch, fetchN, offset).all<PostRow>();
      rawRows = result.results ?? [];
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return jsonResponse({ q, error: "query_failed", message }, { status: 500 });
    }

    const hasMore = rawRows.length > limit;
    const rows = hasMore ? rawRows.slice(0, limit) : rawRows;

    const stemSet = new Set(stems);
    const results = rows.map((row) => ({
      thread_id: row.thread_id,
      title: row.title,
      url: postUrl(row),
      forum_title: row.forum_title,
      post_author: row.post_author,
      post_date: row.post_date,
      snippet: makeSnippet(row.body_plain, stemSet),
    }));

    return jsonResponse({
      q,
      offset,
      limit,
      count: results.length,
      has_more: hasMore,
      results,
    });
  },
} satisfies ExportedHandler<Env>;
