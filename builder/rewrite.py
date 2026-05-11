"""Sanitisation + rewriting pass for `message_parsed` HTML.

This pass runs against every post body and resource description:
- strips `<script>` and inline `on*` event handlers
- removes `<iframe>` whose host isn't on a tiny allowlist
- adds `loading="lazy"` and `decoding="async"` to every `<img>`
- rewrites links to torrentpier.com to be same-origin relative paths
- adds `rel="noopener nofollow"` to remaining external links

Asset URL rewriting (R2) lands in a later commit alongside the mirror stage.
"""

from __future__ import annotations

import re
import warnings
from urllib.parse import urlparse

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

# Many post bodies are short plain-text snippets without HTML; bs4 mistakes
# those for filenames/URLs and emits a noisy warning per parse. Silence it.
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

# Match /threads/<anything>.{id}/<optional rest>. The slug part of the URL on
# the source forum can be different from the slug XenForo currently produces
# (Cyrillic vs transliterated) — we replace it with the canonical slug from
# the export.
_THREAD_PATH_RE = re.compile(r"^/threads/[^/]+\.(\d+)(/.*)?$")
_FORUM_PATH_RE = re.compile(r"^/forums/[^/]+\.(\d+)(/.*)?$")
_MEMBER_PATH_RE = re.compile(r"^/members/[^/]+\.(\d+)(/.*)?$")

INTERNAL_HOSTS = {"torrentpier.com", "www.torrentpier.com"}
IFRAME_ALLOWED_HOSTS = {
    "www.youtube.com",
    "youtube.com",
    "www.youtube-nocookie.com",
    "youtube-nocookie.com",
}


def _safe_urlparse(href: str):
    try:
        return urlparse(href)
    except ValueError:
        return None


def _canonicalise_thread_path(
    path: str, thread_url_map: dict[int, str] | None
) -> str:
    if not thread_url_map:
        return path
    m = _THREAD_PATH_RE.match(path)
    if not m:
        return path
    canonical = thread_url_map.get(int(m.group(1)))
    if not canonical:
        return path
    return canonical.rstrip("/") + (m.group(2) or "/")


def _canonicalise_forum_path(
    path: str, forum_url_map: dict[int, str] | None
) -> str:
    if not forum_url_map:
        return path
    m = _FORUM_PATH_RE.match(path)
    if not m:
        return path
    canonical = forum_url_map.get(int(m.group(1)))
    if not canonical:
        return path
    return canonical.rstrip("/") + (m.group(2) or "/")


def _canonicalise_member_path(
    path: str, member_url_map: dict[int, str] | None
) -> str:
    if not member_url_map:
        return path
    m = _MEMBER_PATH_RE.match(path)
    if not m:
        return path
    canonical = member_url_map.get(int(m.group(1)))
    if not canonical:
        return path
    return canonical.rstrip("/") + (m.group(2) or "/")


def _to_relative_if_internal(
    href: str,
    thread_url_map: dict[int, str] | None = None,
    forum_url_map: dict[int, str] | None = None,
    member_url_map: dict[int, str] | None = None,
) -> str | None:
    """Return path-only URL if `href` points at the source forum, else None."""
    if not href:
        return None
    parsed = _safe_urlparse(href)
    if parsed is None or parsed.hostname not in INTERNAL_HOSTS:
        return None
    path = parsed.path or "/"
    path = _canonicalise_thread_path(path, thread_url_map)
    path = _canonicalise_forum_path(path, forum_url_map)
    path = _canonicalise_member_path(path, member_url_map)
    if parsed.query:
        path += "?" + parsed.query
    if parsed.fragment:
        path += "#" + parsed.fragment
    return path


def rewrite_html(
    html: str | None,
    *,
    thread_url_map: dict[int, str] | None = None,
    forum_url_map: dict[int, str] | None = None,
    member_url_map: dict[int, str] | None = None,
) -> str:
    """Apply the sanitisation/rewrite pass. Empty input returns "".
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")

    for s in soup.find_all("script"):
        s.decompose()

    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.startswith("on"):
                del tag[attr]

    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "") or ""
        parsed = _safe_urlparse(src)
        host = parsed.hostname if parsed else ""
        if host not in IFRAME_ALLOWED_HOSTS:
            iframe.decompose()

    for img in soup.find_all("img"):
        if "loading" not in img.attrs:
            img["loading"] = "lazy"
        if "decoding" not in img.attrs:
            img["decoding"] = "async"

    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        rel_path = _to_relative_if_internal(href, thread_url_map, forum_url_map, member_url_map)
        if rel_path is not None:
            a["href"] = rel_path
            continue
        parsed = _safe_urlparse(href)
        if parsed is not None and parsed.scheme in ("http", "https"):
            rel = a.get("rel") or []
            if isinstance(rel, str):
                rel = rel.split()
            rel = list(rel)
            for token in ("noopener", "nofollow"):
                if token not in rel:
                    rel.append(token)
            a["rel"] = rel

    # lxml/bs4 wraps in <html><body> — strip those wrappers if present so the
    # output stays a fragment, like message_parsed itself.
    body = soup.body
    if body is not None:
        return body.decode_contents()
    return str(soup)
