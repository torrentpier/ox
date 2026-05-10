"""CLI entry point for the static-site builder."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import site


def cmd_build(args: argparse.Namespace) -> None:
    site.build(Path(args.data), Path(args.out))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="xf-build")
    p.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_build = sub.add_parser("build", help="Render the static site")
    p_build.add_argument("--data", default="data", help="Input data directory (default: data)")
    p_build.add_argument("--out", default="dist", help="Output directory (default: dist)")
    p_build.set_defaults(func=cmd_build)
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
