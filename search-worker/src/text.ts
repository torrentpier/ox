// Tokenisation + Snowball stemming. Must stay byte-identical with the
// Python equivalent in `../../search/text.py` — otherwise the Worker
// stems queries differently than the indexer stemmed documents and
// recall is broken on every word that diverges.

import { newStemmer } from "snowball-stemmers";

const stemmer = newStemmer("russian");
const WORD_RE = /\p{L}[\p{L}\p{N}_]*/gu;
const CYRILLIC_RE = /[Ѐ-ӿ]/;

export function stemToken(tok: string): string {
  const norm = tok.toLowerCase().replaceAll("ё", "е");
  return CYRILLIC_RE.test(norm) ? stemmer.stem(norm) : norm;
}

export function tokenise(text: string): string[] {
  if (!text) return [];
  const out: string[] = [];
  const matches = text.matchAll(WORD_RE);
  for (const m of matches) out.push(m[0]);
  return out;
}

export function stemQuery(text: string): string[] {
  return tokenise(text).map(stemToken).filter((s) => s.length > 0);
}

export interface TokenSpan {
  start: number;
  end: number;
  stem: string;
}

export function tokenSpans(text: string): TokenSpan[] {
  const out: TokenSpan[] = [];
  const matches = text.matchAll(WORD_RE);
  for (const m of matches) {
    const start = m.index ?? 0;
    out.push({ start, end: start + m[0].length, stem: stemToken(m[0]) });
  }
  return out;
}
