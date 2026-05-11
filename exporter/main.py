"""CLI entry point for the XenForo exporter."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import (
    api,
    nodes,
    profile_posts,
    resource_reviews,
    resource_updates,
    resources,
    threads,
    wall_owners,
)


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


def cmd_resources(args: argparse.Namespace) -> None:
    with api.from_env() as client:
        resources.export_resources(
            client,
            Path(args.data),
            only_resource=args.only_resource,
            force=args.force,
        )


def cmd_profile_posts(args: argparse.Namespace) -> None:
    with api.from_env() as client:
        profile_posts.export_profile_posts(
            client,
            Path(args.data),
            only_user=args.only_user,
            force=args.force,
        )


def cmd_resource_reviews(args: argparse.Namespace) -> None:
    with api.from_env() as client:
        resource_reviews.export_resource_reviews(client, Path(args.data))


def cmd_resource_updates(args: argparse.Namespace) -> None:
    with api.from_env() as client:
        resource_updates.export_resource_updates(client, Path(args.data))


def cmd_wall_owners(args: argparse.Namespace) -> None:
    ids = [int(x) for x in args.add.split(",") if x.strip()]
    with api.from_env() as client:
        wall_owners.add_wall_owners(client, Path(args.data), ids)


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

    p_resources = sub.add_parser(
        "resources", help="Export resources + versions to data/resources/"
    )
    p_resources.add_argument(
        "--only-resource",
        type=int,
        help="Export a single resource by id (debug)",
    )
    p_resources.add_argument(
        "--force",
        action="store_true",
        help="Re-export resources even if their JSON already exists",
    )
    p_resources.set_defaults(func=cmd_resources)

    p_pp = sub.add_parser(
        "profile-posts",
        help="Export per-user wall posts + comments into data/users/{id}.json",
    )
    p_pp.add_argument(
        "--only-user",
        type=int,
        help="Export a single user's wall by id (debug)",
    )
    p_pp.add_argument(
        "--force",
        action="store_true",
        help="Re-export walls even for users where wall_total is already set",
    )
    p_pp.set_defaults(func=cmd_profile_posts)

    p_rr = sub.add_parser(
        "resource-reviews",
        help="Export resource reviews into data/resources/{id}.json (reviews[])",
    )
    p_rr.set_defaults(func=cmd_resource_reviews)

    p_ru = sub.add_parser(
        "resource-updates",
        help="Export resource update announcements into data/resources/{id}.json (updates[])",
    )
    p_ru.set_defaults(func=cmd_resource_updates)

    p_wo = sub.add_parser(
        "wall-owners",
        help="Fetch wall-owner users (lurkers with wall posts) into data/users/{id}.json",
    )
    p_wo.add_argument(
        "--add",
        required=True,
        help="Comma-separated user ids to fetch",
    )
    p_wo.set_defaults(func=cmd_wall_owners)
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
