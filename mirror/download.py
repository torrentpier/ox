"""HTTP downloader used by the mirror pipeline.

Supports two modes:
- anonymous: attachments, avatars, resource icons, inline external images.
- authenticated: resource version files. Their `download_url` is the XF API
  endpoint and needs the `XF-Api-Key` header.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)
USER_AGENT = "torrentpier-archive-mirror/0.1"
_HTTPX_LIMITS = httpx.Limits(max_connections=64, max_keepalive_connections=16)


@dataclass
class Downloader:
    auth_headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 60.0
    rps: float = 2.0
    _client: httpx.Client = field(init=False, repr=False)
    _last_request_at: float = field(default=0.0, init=False, repr=False)
    _throttle_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            limits=_HTTPX_LIMITS,
        )

    def _throttle(self) -> None:
        """Globally cap requests at `rps` across concurrent workers."""
        if self.rps <= 0:
            return
        gap = 1.0 / self.rps
        with self._throttle_lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < gap:
                time.sleep(gap - elapsed)
            self._last_request_at = time.monotonic()

    def fetch(
        self,
        url: str,
        *,
        authenticated: bool = False,
    ) -> tuple[bytes, str | None, int] | None:
        """Fetch `url` once.

        Returns `(body, content_type, status)` on 2xx.
        Returns `(b"", None, status)` on non-2xx (so callers can record the
        status code, e.g. to mark a permanent 4xx in the inline index).
        Returns `None` on transport-level failure.
        """
        self._throttle()
        headers = dict(self.auth_headers) if authenticated else None
        try:
            r = self._client.get(url, headers=headers)
        except httpx.HTTPError as e:
            log.warning("download error %s: %s", url, e)
            return None
        if 200 <= r.status_code < 300:
            return r.content, r.headers.get("content-type"), r.status_code
        log.info("download %s -> HTTP %d", url, r.status_code)
        return b"", None, r.status_code

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Downloader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
