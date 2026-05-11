// Build a short snippet with <mark>-highlighted matches from body_plain.
// We can't use FTS5 `snippet()` because the FTS5 column holds stemmed
// text — the resulting snippet would be garbled ("кошк был в дом"). So
// the Worker re-tokenises the original `body_plain`, matches stems
// against the query, and renders a small window around the first hit.

import { tokenSpans } from "./text";

const HTML_ESCAPE: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
};

function escapeHtml(s: string): string {
  return s.replace(/[&<>"]/g, (ch) => HTML_ESCAPE[ch]!);
}

export function makeSnippet(
  body: string,
  queryStems: Set<string>,
  windowChars = 90,
): string {
  if (!body) return "";
  const tokens = tokenSpans(body);
  const firstIdx = tokens.findIndex((t) => queryStems.has(t.stem));
  if (firstIdx < 0) {
    return body.length > 200 ? escapeHtml(body.slice(0, 200)) + "…" : escapeHtml(body);
  }

  const match = tokens[firstIdx]!;
  const startChar = Math.max(0, match.start - windowChars);
  const endChar = Math.min(body.length, match.end + windowChars);

  let out = startChar > 0 ? "…" : "";
  let cursor = startChar;
  for (const t of tokens) {
    if (t.end <= startChar || t.start >= endChar) continue;
    if (!queryStems.has(t.stem)) continue;
    out += escapeHtml(body.slice(cursor, t.start));
    out += "<mark>" + escapeHtml(body.slice(t.start, t.end)) + "</mark>";
    cursor = t.end;
  }
  out += escapeHtml(body.slice(cursor, endChar));
  if (endChar < body.length) out += "…";
  return out;
}
