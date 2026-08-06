"""Persistent image storage in MongoDB for serverless deployments."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

PREFIX = "mongodb:"


def persist(conn: Any, raw_path: str | None, kind: str) -> str | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_file():
        return None
    body = path.read_bytes()
    key = f"{kind}/{hashlib.sha256(body).hexdigest()}"
    conn.db.media.update_one(
        {"key": key},
        {"$setOnInsert": {"key": key, "body": body, "content_type": "image/png", "size": len(body)}},
        upsert=True,
    )
    return PREFIX + key


def load(conn: Any, value: str | None) -> tuple[bytes, str] | None:
    if not value or not value.startswith(PREFIX):
        return None
    row = conn.db.media.find_one({"key": value[len(PREFIX):]}, {"body": 1, "content_type": 1})
    return (bytes(row["body"]), row.get("content_type", "image/png")) if row else None
