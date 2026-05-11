from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .index import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xf-search")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="Build local SQLite + optional SQL dump")
    p_build.add_argument("--data", type=Path, default=Path("data"))
    p_build.add_argument("--db", type=Path, default=Path("search/local.db"))
    p_build.add_argument(
        "--sql",
        type=Path,
        default=None,
        help="Also write a SQL dump suitable for `wrangler d1 execute --file`",
    )

    args = parser.parse_args(argv)

    if args.cmd == "build":
        threads, posts = build(args.data, args.db, args.sql)
        size_mb = args.db.stat().st_size / (1024 * 1024)
        msg = f"built {args.db} — {threads} threads, {posts} posts, {size_mb:.1f} MiB"
        if args.sql:
            sql_mb = args.sql.stat().st_size / (1024 * 1024)
            msg += f"; sql {args.sql} {sql_mb:.1f} MiB"
        print(msg)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
