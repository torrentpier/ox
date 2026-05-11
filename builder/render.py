"""Jinja2 environment factory + template helpers."""

from __future__ import annotations

import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning
from jinja2 import Environment, FileSystemLoader, select_autoescape

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

_WS_RE = re.compile(r"\s+")


def _plaintext(html: str | None, limit: int = 200) -> str:
    """HTML → plain text, single-space normalised, truncated for OG descriptions."""
    if not html:
        return ""
    text = BeautifulSoup(html, "lxml").get_text(separator=" ")
    text = _WS_RE.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


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


def _format_count(n: int | None) -> str:
    """Short numeric format used in forum-row stat columns: 276, 13.6K, 2.1M."""
    if not n:
        return "0"
    n = int(n)
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        s = f"{n / 1000:.1f}K"
        return s.replace(".0K", "K")
    s = f"{n / 1_000_000:.1f}M"
    return s.replace(".0M", "M")


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
    env.filters["count"] = _format_count
    env.filters["urlpath"] = lambda u: urlparse(u or "").path or "/"
    env.filters["plaintext"] = _plaintext
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
        "site_name": "TorrentPier Ox Archive",
        "site_url": "https://ox.torrentpier.com",
        "files_url": "https://files-ox.torrentpier.com",
        "site_description": (
            "Static read-only archive of the TorrentPier support forum (2011–2026)."
        ),
        "build_time": _format_build_time(exported_at),
    }
