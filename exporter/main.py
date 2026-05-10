"""CLI entry point for the XenForo exporter."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import api, nodes, threads


def cmd_nodes(args: argparse.Namespace) -> None:
    with api.from_env() as client:
        nodes.export_nodes(client, Path(args.data))


def cmd_threads(args: argparse.Namespace) -> None:
    with api.from_env() as client:
        threads.export_threads(
            client,
            Path(args.data),
            forum_ids=args.forum or None,
            only_thread=args.only_thread,
            force=args.force,
        )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="xf-export")
    p.add_argument("--data", default="data", help="Output directory (default: data)")
    p.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_nodes = sub.add_parser("nodes", help="Export /api/nodes to data/meta.json")
    p_nodes.set_defaults(func=cmd_nodes)

    p_threads = sub.add_parser(
        "threads", help="Export threads + posts to data/threads/ (also fills data/users/)"
    )
    p_threads.add_argument(
        "--forum",
        type=int,
        action="append",
        help="Limit to a forum node id (repeatable; default: all forums in meta.json)",
    )
    p_threads.add_argument(
        "--only-thread",
        type=int,
        help="Export a single thread by id (debug)",
    )
    p_threads.add_argument(
        "--force",
        action="store_true",
        help="Re-export threads even if their JSON already exists",
    )
    p_threads.set_defaults(func=cmd_threads)
    return p


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # httpx is chatty at INFO; quiet it unless verbose
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    args.func(args)


if __name__ == "__main__":
    main()
