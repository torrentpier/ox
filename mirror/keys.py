"""R2 key builders for archive assets.

Keys are stable, deterministic paths. Filenames are kept readable when they
are ASCII / unicode-safe and sanitised only when they include path separators
or control characters. R2 itself supports unicode in keys; Cloudflare
percent-encodes them when serving over HTTP.
"""

from __future__ import annotations

import os
import re
from urllib.parse import unquote, urlparse


_UNSAFE_FN_RE = re.compile(r"[\x00-\x1f/\\]+")


def _safe_filename(filename: str) -> str:
    """Strip path separators and control characters; keep unicode otherwise."""
    name = _UNSAFE_FN_RE.sub("_", filename or "").strip()
    return name or "file"


def _ext_from_url(url: str) -> str:
    """Return the lowercase dot-extension from a URL path, or "" if missing."""
    try:
        path = urlparse(url).path
    except ValueError:
        return ""
    base = os.path.basename(unquote(path or ""))
    _, ext = os.path.splitext(base)
    return ext.lower() if 1 < len(ext) <= 6 else ""


def attachment_key(attachment_id: int, filename: str) -> str:
    return f"attachments/{int(attachment_id)}/{_safe_filename(filename)}"


def avatar_key(user_id: int, src_url: str) -> str:
    return f"avatars/{int(user_id)}{_ext_from_url(src_url) or '.jpg'}"


def inline_key(sha256: str, src_url: str) -> str:
    return f"inline/{sha256[:2]}/{sha256}{_ext_from_url(src_url)}"


def resource_icon_key(resource_id: int, src_url: str) -> str:
    return f"resources/{int(resource_id)}/icon{_ext_from_url(src_url) or '.jpg'}"


def resource_file_key(resource_id: int, version_id: int, filename: str) -> str:
    return (
        f"resources/{int(resource_id)}/v/{int(version_id)}/{_safe_filename(filename)}"
    )
