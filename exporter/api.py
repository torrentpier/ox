"""HTTP client for the XenForo REST API.

Wraps `httpx.Client` with auth headers, exponential-backoff retry on
transient failures, and a simple token-bucket rate limiter.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

DEFAULT_RPS = 3.0
USER_AGENT = "torrentpier-archive/0.1"


class RetriableHTTPError(httpx.HTTPStatusError):
    """HTTP failure worth retrying (429 or 5xx)."""


@dataclass
class XfClient:
    base_url: str
    api_key: str
    api_user: str
    rps: float = DEFAULT_RPS
    timeout: float = 30.0
    _client: httpx.Client = field(init=False, repr=False)
    _last_request_at: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            base_url=self.base_url.rstrip("/"),
            headers={
                "XF-Api-Key": self.api_key,
                "XF-Api-User": str(self.api_user),
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            timeout=self.timeout,
        )

    def _throttle(self) -> None:
        if self.rps <= 0:
            return
        min_interval = 1.0 / self.rps
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_at = time.monotonic()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type((RetriableHTTPError, httpx.TransportError)),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def get(self, path: str, **params: Any) -> Any:
        self._throttle()
        r = self._client.get(path, params=params)
        log.info("GET %s -> %s (%d B)", r.request.url, r.status_code, len(r.content))
        if r.status_code == 429 or 500 <= r.status_code < 600:
            raise RetriableHTTPError(
                f"Retriable {r.status_code} from {r.request.url}",
                request=r.request,
                response=r,
            )
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "XfClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def from_env() -> XfClient:
    """Build an XfClient from `.env` (loaded if present) and environment."""
    load_dotenv()
    return XfClient(
        base_url=os.environ["XF_API_URL"],
        api_key=os.environ["XF_API_KEY"],
        api_user=os.environ["XF_API_USER"],
        rps=float(os.environ.get("XF_API_RPS", DEFAULT_RPS)),
    )
