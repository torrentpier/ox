"""Build a local SQLite FTS5 DB + matching seed.sql for D1.

The local DB is for offline query testing (sqlite3 ./search/local.db).
The seed.sql is plain DDL + INSERTs only — D1 forbids PRAGMA
writable_schema and the iterdump-style direct CREATE TABLE on FTS5
shadow tables (`posts_fts_data` etc.), so we emit the schema + inserts
by hand using the public VIRTUAL TABLE interface.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import IO

from .text import stem_text, to_plain

POSTS_PER_PAGE = 10

# D1 rejects single statements over ~100 KB. Cap body_plain at 32K chars so
# the resulting INSERT (plus the stemmed posts_fts row) fits even after SQL
# escaping of quotes.
MAX_BODY_CHARS = 32000

SCHEMA = """
CREATE TABLE threads (
    id INTEGER PRIMARY KEY,
    slug TEXT,
    title TEXT NOT NULL,
    forum_id INTEGER NOT NULL,
    forum_title TEXT NOT NULL,
    username TEXT,
    post_date INTEGER,
    reply_count INTEGER,
    url_path TEXT NOT NULL
);

CREATE TABLE posts (
    id INTEGER PRIMARY KEY,
    thread_id INTEGER NOT NULL,
    page_no INTEGER NOT NULL,
    position INTEGER NOT NULL,
    username TEXT,
    post_date INTEGER,
    body_plain TEXT NOT NULL
);

CREATE INDEX idx_posts_thread ON posts(thread_id, position);

CREATE VIRTUAL TABLE posts_fts USING fts5(
    body,
    title,
    content='',
    tokenize='unicode61 remove_diacritics 2'
);
"""


def _q(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    raise TypeError(f"unsupported type for SQL emit: {type(v)} {v!r}")


def _emit_insert(f: IO[str], table: str, columns: tuple[str, ...], values: tuple) -> None:
    cols = ",".join(columns)
    vals = ",".join(_q(v) for v in values)
    f.write(f"INSERT INTO {table}({cols}) VALUES({vals});\n")


def build(data_dir: Path, db_path: Path, sql_path: Path | None = None) -> tuple[int, int]:
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    sql_f: IO[str] | None = None
    if sql_path:
        sql_path.parent.mkdir(parents=True, exist_ok=True)
        sql_f = sql_path.open("w", encoding="utf-8")
        sql_f.write(SCHEMA.lstrip())

    thread_count = 0
    post_count = 0
    thread_cols = (
        "id", "slug", "title", "forum_id", "forum_title",
        "username", "post_date", "reply_count", "url_path",
    )
    post_cols = (
        "id", "thread_id", "page_no", "position",
        "username", "post_date", "body_plain",
    )

    thread_paths = sorted(
        data_dir.glob("threads/*.json"), key=lambda p: int(p.stem)
    )
    for path in thread_paths:
        with path.open(encoding="utf-8") as f:
            t = json.load(f)

        thread_values = (
            t["id"],
            t.get("slug"),
            t["title"],
            t["forum"]["id"],
            t["forum"]["title"],
            t.get("username"),
            t.get("post_date"),
            t.get("reply_count", 0),
            t["url_path"],
        )
        conn.execute(
            f"INSERT INTO threads({','.join(thread_cols)}) "
            f"VALUES({','.join('?' * len(thread_cols))})",
            thread_values,
        )
        if sql_f:
            _emit_insert(sql_f, "threads", thread_cols, thread_values)
        thread_count += 1

        stemmed_title = stem_text(t["title"])

        for post in t.get("posts", []):
            position = post.get("position", 0)
            page_no = position // POSTS_PER_PAGE + 1
            body_plain = to_plain(post.get("message_parsed", ""))
            if len(body_plain) > MAX_BODY_CHARS:
                body_plain = body_plain[:MAX_BODY_CHARS].rstrip() + "…"
            body_stemmed = stem_text(body_plain)

            post_values = (
                post["id"],
                t["id"],
                page_no,
                position,
                post.get("username"),
                post.get("post_date"),
                body_plain,
            )
            conn.execute(
                f"INSERT INTO posts({','.join(post_cols)}) "
                f"VALUES({','.join('?' * len(post_cols))})",
                post_values,
            )
            conn.execute(
                "INSERT INTO posts_fts(rowid, body, title) VALUES (?, ?, ?)",
                (post["id"], body_stemmed, stemmed_title),
            )
            if sql_f:
                _emit_insert(sql_f, "posts", post_cols, post_values)
                _emit_insert(
                    sql_f,
                    "posts_fts",
                    ("rowid", "body", "title"),
                    (post["id"], body_stemmed, stemmed_title),
                )
            post_count += 1

        if thread_count % 200 == 0:
            conn.commit()
            print(f"  {thread_count} threads, {post_count} posts", flush=True)

    conn.commit()
    conn.execute("INSERT INTO posts_fts(posts_fts) VALUES('optimize')")
    conn.commit()
    conn.close()

    if sql_f:
        sql_f.write("INSERT INTO posts_fts(posts_fts) VALUES('optimize');\n")
        sql_f.close()

    return thread_count, post_count
