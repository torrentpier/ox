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
# the export. The slug is optional: XF also accepts bare `/threads/{id}/`,
# `/forums/{id}/`, `/members/{id}/` and historical post bodies use that form.
_THREAD_PATH_RE = re.compile(r"^/threads/(?:[^/]+\.)?(\d+)(/.*)?$")
_FORUM_PATH_RE = re.compile(r"^/forums/(?:[^/]+\.)?(\d+)(/.*)?$")
_MEMBER_PATH_RE = re.compile(r"^/members/(?:[^/]+\.)?(\d+)(/.*)?$")
# `/attachments/{filename}.{id}/` and `/attachments/{id}/` shapes; an optional
# `/forum/` prefix shows up in a handful of historical post bodies.
_ATTACHMENT_PATH_RE = re.compile(r"^/(?:forum/)?attachments/(?:[^/]+\.)?(\d+)/?$")

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


def _attachment_r2_url(
    path: str | None, attachment_url_map: dict[int, str] | None
) -> str | None:
    """If `path` is an XF attachment URL we have on R2, return the R2 URL."""
    if not path or not attachment_url_map:
        return None
    m = _ATTACHMENT_PATH_RE.match(path)
    if not m:
        return None
    return attachment_url_map.get(int(m.group(1)))


def _to_relative_if_internal(
    href: str,
    thread_url_map: dict[int, str] | None = None,
    forum_url_map: dict[int, str] | None = None,
    member_url_map: dict[int, str] | None = None,
    attachment_url_map: dict[int, str] | None = None,
) -> str | None:
    """Return a replacement URL when `href` points at the source forum.

    For attachments we have on R2, returns the absolute R2 public URL. For
    everything else, returns a path-only URL with canonical thread/forum/
    member slugs. Returns None when `href` is not on torrentpier.com.
    """
    if not href:
        return None
    parsed = _safe_urlparse(href)
    if parsed is None or parsed.hostname not in INTERNAL_HOSTS:
        return None
    path = parsed.path or "/"
    r2 = _attachment_r2_url(path, attachment_url_map)
    if r2:
        return r2
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
    attachment_url_map: dict[int, str] | None = None,
    inline_url_map: dict[str, str] | None = None,
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
        src = (img.get("src") or "").strip()
        if src:
            # External image we mirrored to R2 by sha256
            if inline_url_map and src in inline_url_map:
                img["src"] = inline_url_map[src]
            else:
                parsed = _safe_urlparse(src)
                if parsed is not None and parsed.hostname in INTERNAL_HOSTS:
                    r2 = _attachment_r2_url(parsed.path or "", attachment_url_map)
                    if r2:
                        img["src"] = r2
        if "loading" not in img.attrs:
            img["loading"] = "lazy"
        if "decoding" not in img.attrs:
            img["decoding"] = "async"

    for a in soup.find_all("a"):
        href = a.get("href")
        if not href:
            continue
        rel_path = _to_relative_if_internal(
            href,
            thread_url_map=thread_url_map,
            forum_url_map=forum_url_map,
            member_url_map=member_url_map,
            attachment_url_map=attachment_url_map,
        )
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
