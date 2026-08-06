"""Batch runs.

The summary cards on the batch screen are computed from the inspection rows the run
produced, not from counters kept alongside them, so the cards and the export can never
disagree (FR-19 / T-16).  The counters on batch_run are written once at completion and
are only a convenience for the run list.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database.mongo import is_mongo, next_id


def create(conn: sqlite3.Connection, values: dict[str, Any]) -> int:
    if is_mongo(conn):
        batch_run_id = next_id(conn, "batch_run")
        material = conn.db.reference.find_one({"kind": "material", "material_id": values.get("material_id")}) or {}
        conn.db.batches.insert_one({"batch_run_id": batch_run_id, **values,
            "material_code": material.get("material_code"), "material_name": material.get("material_name")})
        return batch_run_id
    cur = conn.execute(
        """
        INSERT INTO batch_run (source_folder, material_id, started_at, status, image_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            values["source_folder"],
            values.get("material_id"),
            values["started_at"],
            values.get("status", "running"),
            values.get("image_count", 0),
        ],
    )
    if cur.lastrowid is None:  # pragma: no cover - SQLite always returns it here
        raise sqlite3.DatabaseError("SQLite did not return a batch_run id")
    return int(cur.lastrowid)


def finish(conn: sqlite3.Connection, batch_run_id: int, values: dict[str, Any]) -> None:
    if is_mongo(conn):
        conn.db.batches.update_one({"batch_run_id": batch_run_id}, {"$set": values})
        return
    conn.execute(
        """
        UPDATE batch_run
           SET finished_at = ?, image_count = ?, clean_count = ?,
               regions_found_count = ?, failure_count = ?, status = ?
         WHERE batch_run_id = ?
        """,
        [
            values.get("finished_at"),
            values.get("image_count", 0),
            values.get("clean_count", 0),
            values.get("regions_found_count", 0),
            values.get("failure_count", 0),
            values.get("status", "completed"),
            batch_run_id,
        ],
    )


def get(conn: sqlite3.Connection, batch_run_id: int) -> dict[str, Any] | None:
    if is_mongo(conn):
        return conn.db.batches.find_one({"batch_run_id": batch_run_id}, {"_id": 0})
    row = conn.execute(
        """
        SELECT b.*, m.material_code, m.material_name
        FROM batch_run b LEFT JOIN material m ON m.material_id = b.material_id
        WHERE b.batch_run_id = ?
        """,
        [batch_run_id],
    ).fetchone()
    return dict(row) if row else None


def recent(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    if is_mongo(conn):
        return list(conn.db.batches.find({}, {"_id": 0}).sort("batch_run_id", -1).limit(limit))
    rows = conn.execute(
        """
        SELECT b.*, m.material_code, m.material_name
        FROM batch_run b LEFT JOIN material m ON m.material_id = b.material_id
        ORDER BY b.batch_run_id DESC LIMIT ?
        """,
        [limit],
    )
    return [dict(r) for r in rows]


def latest_id(conn: sqlite3.Connection) -> int | None:
    if is_mongo(conn):
        row = conn.db.batches.find_one({}, {"batch_run_id": 1}, sort=[("batch_run_id", -1)])
        return int(row["batch_run_id"]) if row else None
    row = conn.execute("SELECT MAX(batch_run_id) AS id FROM batch_run").fetchone()
    return int(row["id"]) if row and row["id"] is not None else None


def count(conn: sqlite3.Connection) -> int:
    if is_mongo(conn):
        return int(conn.db.batches.count_documents({}))
    return int(conn.execute("SELECT COUNT(*) AS n FROM batch_run").fetchone()["n"])
