"""MongoDB Atlas connection and reference-data bootstrap.

The Mongo collections are intentionally document-shaped: inspections embed their
regions and resolved model/profile/material/station fields. That removes relational
joins from the serverless request path and makes one inspection an atomic write.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from app.config import Settings
from app.profiles import ACTIVE_PROFILE


class MongoConnection:
    is_mongo = True

    def __init__(self, database: Any) -> None:
        self.db = database

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        # MongoClient is process-cached for connection-pool reuse on warm functions.
        pass


@lru_cache(maxsize=2)
def _client(uri: str):
    from pymongo import MongoClient

    return MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                       retryWrites=True, appname="vision404-vercel")


def connect_mongo(settings: Settings) -> MongoConnection:
    client = _client(settings.mongodb_uri)
    return MongoConnection(client[settings.mongodb_database])


def next_id(conn: MongoConnection, name: str) -> int:
    from pymongo import ReturnDocument

    row = conn.db.counters.find_one_and_update(
        {"_id": name}, {"$inc": {"value": 1}}, upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(row["value"])


def ensure_reference_data(conn: MongoConnection, settings: Settings) -> None:
    """Create indexes and idempotently bootstrap stable production reference data."""
    db = conn.db
    db.inspections.create_index("inspection_id", unique=True)
    db.inspections.create_index([("captured_at", -1), ("inspection_id", -1)])
    db.inspections.create_index("batch_run_id")
    db.batches.create_index("batch_run_id", unique=True)
    db.reference.create_index([("kind", 1), ("id", 1)], unique=True)

    metrics: dict[str, Any] = {}
    try:
        metrics = json.loads(settings.metrics_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass

    material_rows = metrics.get("materials") or [
        {
            "material_code": "steel",
            "material_name": "Steel",
            "support_status": "supported",
            "notes": "Default production material",
        }
    ]
    materials = []
    for material_id, row in enumerate(material_rows, start=1):
        materials.append({
            "kind": "material", "id": material_id, "material_id": material_id,
            "material_code": row["material_code"], "material_name": row["material_name"],
            "support_status": row["support_status"], "notes": row.get("notes"),
        })
    steel = next((row for row in materials if row["material_code"] == "steel"), None)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    profile = ACTIVE_PROFILE
    profile_base = {
        "version_no": profile.version_no,
        "crack_threshold": profile.crack_thresh,
        "scratch_threshold": profile.scratch_thresh,
        "minimum_area_px": profile.min_area_px,
        "minimum_skeleton_px": profile.min_skeleton_px,
        "created_at": now,
        "is_active": 1,
    }
    model_metrics = metrics.get("model", {})
    model_size = round(settings.model_file.stat().st_size / 1024**2, 2) if settings.model_file.exists() else None
    docs = [
        *materials,
        {"kind": "defect_class", "id": 1, "class_id": 1, "class_code": "crack", "display_name": "Crack"},
        {"kind": "defect_class", "id": 2, "class_id": 2, "class_code": "scratch", "display_name": "Scratch"},
        {"kind": "profile", "id": 1, "profile_id": 1, "material_id": None, **profile_base},
        {
            "kind": "model", "id": 1, "model_version_id": 1,
            "file_name": settings.model_file.name, "version": "V12_22",
            "artefact_sha256": settings.model_sha256.lower(),
            "parameter_count": model_metrics.get("parameter_count"), "size_mb": model_size,
            "precision": model_metrics.get("precision", "float32"),
            "latency_ms": model_metrics.get("latency_ms"), "created_at": now, "is_active": 1,
        },
        {
            "kind": "station", "id": 1, "station_id": 1,
            "station_code": settings.station_id,
            "line_code": settings.station_id.split("-cam")[0],
            "mm_per_pixel": None, "camera_status": "ok", "created_at": now,
        },
    ]
    if steel:
        docs.append({
            "kind": "profile", "id": 2, "profile_id": 2,
            "material_id": steel["material_id"], **profile_base,
        })
    for doc in docs:
        db.reference.update_one(
            {"kind": doc["kind"], "id": doc["id"]},
            {"$setOnInsert": doc},
            upsert=True,
        )
    for name in ("inspection", "batch_run", "station", "region"):
        db.counters.update_one({"_id": name}, {"$setOnInsert": {"value": 0}}, upsert=True)


def is_mongo(conn: Any) -> bool:
    return bool(getattr(conn, "is_mongo", False))
