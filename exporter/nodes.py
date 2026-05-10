"""Stage: export the node tree (categories + forums + pages + links).

Output: `data/meta.json` with `tree_map`, full `nodes[]`, and convenience
indexes (`by_type`, `forum_ids`).
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any

from .api import XfClient
from .io import write_json_atomic

log = logging.getLogger(__name__)


def export_nodes(client: XfClient, data_dir: Path) -> dict[str, Any]:
    payload = client.get("/nodes")
    nodes = payload.get("nodes", [])
    tree_map = payload.get("tree_map", {})

    by_type: dict[str, list[int]] = {}
    for n in nodes:
        by_type.setdefault(n.get("node_type_id", "Unknown"), []).append(n["node_id"])
    for ids in by_type.values():
        ids.sort()

    log.info(
        "Got %d nodes (%s)",
        len(nodes),
        ", ".join(f"{k}={len(v)}" for k, v in sorted(by_type.items())),
    )

    meta = {
        "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tree_map": tree_map,
        "nodes": nodes,
        "by_type": by_type,
        "forum_ids": by_type.get("Forum", []),
    }
    out = data_dir / "meta.json"
    write_json_atomic(out, meta)
    log.info("Wrote %s", out)
    return meta
