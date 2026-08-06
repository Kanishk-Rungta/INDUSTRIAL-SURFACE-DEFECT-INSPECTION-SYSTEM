"""Model versions."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database.mongo import is_mongo, next_id


def active_model(conn: sqlite3.Connection) -> dict[str, Any] | None:
    if is_mongo(conn):
        row = conn.db.reference.find_one({"kind": "model", "is_active": 1}, {"_id": 0, "kind": 0, "id": 0}, sort=[("model_version_id", -1)])
        if row is None:
            row = conn.db.reference.find_one({"kind": "model"}, {"_id": 0, "kind": 0, "id": 0}, sort=[("model_version_id", -1)])
        return row
    row = conn.execute(
        "SELECT * FROM model_version WHERE is_active = 1 ORDER BY model_version_id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM model_version ORDER BY model_version_id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def all_models(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if is_mongo(conn):
        return list(conn.db.reference.find({"kind": "model"}, {"_id": 0, "kind": 0, "id": 0}).sort("model_version_id", 1))
    return [dict(r) for r in conn.execute("SELECT * FROM model_version ORDER BY model_version_id")]


def by_sha(conn: sqlite3.Connection, sha256: str) -> dict[str, Any] | None:
    if is_mongo(conn):
        return conn.db.reference.find_one({"kind": "model", "artefact_sha256": sha256}, {"_id": 0, "kind": 0, "id": 0})
    row = conn.execute("SELECT * FROM model_version WHERE artefact_sha256 = ?", [sha256]).fetchone()
    return dict(row) if row else None


def stations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if is_mongo(conn):
        return list(conn.db.reference.find({"kind": "station"}, {"_id": 0, "kind": 0, "id": 0}).sort("station_id", 1))
    return [dict(r) for r in conn.execute("SELECT * FROM station ORDER BY station_id")]


def station_by_code(conn: sqlite3.Connection, code: str) -> dict[str, Any] | None:
    if is_mongo(conn):
        return conn.db.reference.find_one({"kind": "station", "station_code": code}, {"_id": 0, "kind": 0, "id": 0})
    row = conn.execute("SELECT * FROM station WHERE station_code = ?", [code]).fetchone()
    return dict(row) if row else None


def create_station(conn: sqlite3.Connection, values: dict[str, Any]) -> int:
    if is_mongo(conn):
        station_id = next_id(conn, "station")
        conn.db.reference.insert_one({"kind": "station", "id": station_id, "station_id": station_id, **values})
        return station_id
    cur = conn.execute(
        "INSERT INTO station (station_code, line_code, mm_per_pixel, camera_status, created_at) VALUES (?, ?, ?, ?, ?)",
        [values["station_code"], values["line_code"], values.get("mm_per_pixel"), values.get("camera_status", "ok"), values["created_at"]],
    )
    return int(cur.lastrowid)
