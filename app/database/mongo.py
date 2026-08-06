"""MongoDB Atlas connection and reference-data bootstrap.

The Mongo collections are intentionally document-shaped: inspections embed their
regions and resolved model/profile/material/station fields. That removes relational
joins from the serverless request path and makes one inspection an atomic write.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import Settings


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
    """Create indexes and copy stable reference rows from the bundled SQLite seed."""
    db = conn.db
    db.inspections.create_index("inspection_id", unique=True)
    db.inspections.create_index([("captured_at", -1), ("inspection_id", -1)])
    db.inspections.create_index("batch_run_id")
    db.batches.create_index("batch_run_id", unique=True)
    db.reference.create_index([("kind", 1), ("id", 1)], unique=True)
    if db.reference.find_one({"kind": "material"}):
        return

    import sqlite3

    source = sqlite3.connect(settings.bundled_db_file)
    source.row_factory = sqlite3.Row
    try:
        mappings = {
            "material": ("material", "material_id"),
            "defect_class": ("defect_class", "class_id"),
            "profile": ("profile", "profile_id"),
            "model": ("model_version", "model_version_id"),
            "station": ("station", "station_id"),
        }
        docs = []
        for kind, (table, key) in mappings.items():
            for row in source.execute(f"SELECT * FROM {table}"):
                doc = dict(row)
                doc.update({"kind": kind, "id": int(doc[key])})
                docs.append(doc)
        if docs:
            db.reference.insert_many(docs, ordered=False)
        for name, table, key in (
            ("inspection", "inspection", "inspection_id"),
            ("batch_run", "batch_run", "batch_run_id"),
            ("station", "station", "station_id"),
        ):
            maximum = source.execute(f"SELECT COALESCE(MAX({key}), 0) FROM {table}").fetchone()[0]
            db.counters.update_one({"_id": name}, {"$setOnInsert": {"value": int(maximum)}}, upsert=True)
    finally:
        source.close()


def is_mongo(conn: Any) -> bool:
    return bool(getattr(conn, "is_mongo", False))
