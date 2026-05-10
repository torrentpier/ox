"""CLI entry point for the XenForo exporter."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import api, nodes


def cmd_nodes(args: argparse.Namespace) -> None:
    with api.from_env() as client:
        nodes.export_nodes(client, Path(args.data))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="xf-export")
    p.add_argument("--data", default="data", help="Output directory (default: data)")
    p.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_nodes = sub.add_parser("nodes", help="Export /api/nodes to data/meta.json")
    p_nodes.set_defaults(func=cmd_nodes)
    return p


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args.func(args)


if __name__ == "__main__":
    main()
