"""Search indexer for the static archive.

Reads `data/threads/{id}.json`, builds a SQLite database with FTS5 over
Snowball-stemmed post bodies + thread titles. The Cloudflare Worker
serves /search?q=... against the same DB imported into D1.

The stemmer is Snowball Russian, applied identically at index and query
time (the Worker uses the JS Snowball port). Original plain text is kept
verbatim in `posts.body_plain` so the Worker can build snippets without
exposing stemmed text to the user.
"""
