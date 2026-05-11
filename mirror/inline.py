"""Persistent dedupe map for inline (external) images mirrored to R2.

Stored at `data/inline_index.json`. The builder consumes this map to rewrite
`<img src>` in post bodies to the R2 URL of the deduplicated image.

Schema:

    {
      "by_url": {
        "<source url>": {"sha256": "...", "r2_key": "inline/ab/abcdef...jpg",
                          "size": 12345},
        "<source url>": {"failed": true, "status": 404}
      }
    }
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class InlineIndex:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.by_url: dict[str, dict[str, Any]] = {}
        self.by_hash: dict[str, str] = {}
        self.dirty = False
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.by_url = data.get("by_url") or {}
            for entry in self.by_url.values():
                key = entry.get("r2_key")
                sha = entry.get("sha256")
                if sha and key:
                    self.by_hash[sha] = key

    def get(self, url: str) -> dict[str, Any] | None:
        return self.by_url.get(url)

    def is_done(self, url: str) -> bool:
        entry = self.by_url.get(url)
        return bool(entry) and bool(entry.get("r2_key"))

    def is_permanently_failed(self, url: str) -> bool:
        entry = self.by_url.get(url)
        if not entry or not entry.get("failed"):
            return False
        return 400 <= int(entry.get("status") or 0) < 500

    def lookup_by_hash(self, sha256: str) -> str | None:
        return self.by_hash.get(sha256)

    def add(self, url: str, sha256: str, r2_key: str, size: int | None = None) -> None:
        self.by_url[url] = {"sha256": sha256, "r2_key": r2_key, "size": size}
        self.by_hash[sha256] = r2_key
        self.dirty = True

    def add_failed(self, url: str, status: int) -> None:
        self.by_url[url] = {"failed": True, "status": int(status)}
        self.dirty = True

    def save(self) -> None:
        if not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {"by_url": self.by_url},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.path)
        self.dirty = False
