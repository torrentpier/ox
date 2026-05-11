"""Jinja2 environment factory + template helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape


def _format_timestamp(ts: int | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _format_size(size: int | None) -> str:
    if not size:
        return "0 B"
    n = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


def make_env(template_dir: Path) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["timestamp"] = _format_timestamp
    env.filters["filesize"] = _format_size
    env.filters["urlpath"] = lambda u: urlparse(u or "").path or "/"
    return env


def _format_build_time(exported_at: str | None) -> str:
    """Format the snapshot timestamp into a stable UTC string.

    Pinned to the export run so identical `data/` produces identical HTML.
    """
    if not exported_at:
        return "unknown"
    try:
        dt = datetime.fromisoformat(exported_at.replace("Z", "+00:00"))
    except ValueError:
        return exported_at
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def context_globals(exported_at: str | None = None) -> dict[str, Any]:
    return {
        "site_name": "TorrentPier archive",
        "build_time": _format_build_time(exported_at),
    }
