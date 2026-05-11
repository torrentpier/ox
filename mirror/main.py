"""CLI entry point for the R2 mirror pipeline."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from . import r2 as r2_mod
from .download import Downloader
from .pipeline import (
    DEFAULT_WORKERS,
    mirror_attachments,
    mirror_avatars,
    mirror_inline,
    mirror_resources,
    scan_inventory,
    verify,
)

log = logging.getLogger("mirror")

STAGES = {
    "attachments": mirror_attachments,
    "avatars": mirror_avatars,
    "resources": mirror_resources,
    "inline": mirror_inline,
}


def _make_downloader() -> Downloader:
    load_dotenv()
    return Downloader(
        auth_headers={
            "XF-Api-Key": os.environ.get("XF_API_KEY", ""),
            "XF-Api-User": os.environ.get("XF_API_USER", "1"),
        },
        rps=float(os.environ.get("MIRROR_RPS", "20")),
    )


def cmd_upload(args: argparse.Namespace) -> None:
    r2 = r2_mod.from_env()
    data_dir = Path(args.data)
    only = set(args.only or []) or set(STAGES)
    totals: dict[str, int] = {}
    workers = args.concurrency
    force = bool(args.force)
    for name in ("attachments", "avatars", "resources", "inline"):
        if name not in only:
            continue
        log.info(
            "=== stage: %s (workers=%d, force=%s) ===", name, workers, force
        )
        with _make_downloader() as dl:
            stats = STAGES[name](data_dir, r2, dl, workers=workers, force=force)
        log.info("[%s] %s", name, dict(stats))
        for k, v in stats.items():
            totals[k] = totals.get(k, 0) + v
    log.info("totals: %s", totals)


def cmd_verify(args: argparse.Namespace) -> None:
    r2 = r2_mod.from_env()
    stats = verify(Path(args.data), r2, workers=args.concurrency)
    log.info("verify: %s", dict(stats))


def cmd_scan(args: argparse.Namespace) -> None:
    stats = scan_inventory(Path(args.data))
    log.info("scan: %s", dict(stats))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="xf-mirror")
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", default="data", help="Data directory (default: data)")

    parallel = argparse.ArgumentParser(add_help=False)
    parallel.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"ThreadPoolExecutor worker count (default: {DEFAULT_WORKERS})",
    )

    p_up = sub.add_parser(
        "upload",
        parents=[common, parallel],
        help="Mirror assets to R2 (idempotent)",
    )
    p_up.add_argument(
        "--only",
        action="append",
        choices=sorted(STAGES),
        help="Limit to specific asset categories (repeatable)",
    )
    p_up.add_argument(
        "--force",
        action="store_true",
        help="Re-upload even when r2_key is set / R2 already has the object",
    )
    p_up.set_defaults(func=cmd_upload)

    p_v = sub.add_parser(
        "verify",
        parents=[common, parallel],
        help="HEAD every r2_key; report missing",
    )
    p_v.set_defaults(func=cmd_verify)

    p_s = sub.add_parser(
        "scan",
        parents=[common],
        help="Offline inventory of what upload would do (no R2 / network I/O)",
    )
    p_s.set_defaults(func=cmd_scan)
    return p


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not args.verbose:
        for name in ("httpx", "botocore", "urllib3", "boto3"):
            logging.getLogger(name).setLevel(logging.WARNING)
    args.func(args)


if __name__ == "__main__":
    main()
