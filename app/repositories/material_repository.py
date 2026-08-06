"""Materials, defect classes and threshold profiles."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.database.mongo import is_mongo

SUPPORT_LABELS = {
    "supported": "supported",
    "one_product_only": "one product only",
    "thin_coverage": "thin coverage",
    "typing_unsupported": "typing unsupported",
    "not_supported": "not supported",
    "under_evaluation": "under evaluation",
}


def all_materials(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if is_mongo(conn):
        return list(conn.db.reference.find({"kind": "material"}, {"_id": 0, "kind": 0, "id": 0}).sort("material_id", 1))
    rows = conn.execute(
        "SELECT material_id, material_code, material_name, support_status, notes "
        "FROM material ORDER BY material_id"
    )
    return [dict(r) for r in rows]


def by_code(conn: sqlite3.Connection, code: str) -> dict[str, Any] | None:
    if is_mongo(conn):
        row = conn.db.reference.find_one({"kind": "material", "material_code": code}, {"_id": 0, "kind": 0, "id": 0})
        return row
    row = conn.execute(
        "SELECT material_id, material_code, material_name, support_status, notes "
        "FROM material WHERE material_code = ?",
        [code],
    ).fetchone()
    return dict(row) if row else None


def material_id(conn: sqlite3.Connection, code: str | None) -> int | None:
    if not code:
        return None
    if is_mongo(conn):
        row = conn.db.reference.find_one({"kind": "material", "material_code": code}, {"material_id": 1})
        return int(row["material_id"]) if row else None
    row = conn.execute("SELECT material_id FROM material WHERE material_code = ?", [code]).fetchone()
    return int(row["material_id"]) if row else None


def defect_classes(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if is_mongo(conn):
        return list(conn.db.reference.find({"kind": "defect_class"}, {"_id": 0, "kind": 0, "id": 0}).sort("class_id", 1))
    rows = conn.execute("SELECT class_id, class_code, display_name FROM defect_class ORDER BY class_id")
    return [dict(r) for r in rows]


def class_id(conn: sqlite3.Connection, code: str) -> int:
    if is_mongo(conn):
        row = conn.db.reference.find_one({"kind": "defect_class", "class_code": code}, {"class_id": 1})
        if row is None:
            raise KeyError(f"Unknown defect class: {code}")
        return int(row["class_id"])
    row = conn.execute("SELECT class_id FROM defect_class WHERE class_code = ?", [code]).fetchone()
    if row is None:
        raise KeyError(f"Unknown defect class: {code}")
    return int(row["class_id"])


def active_profile(conn: sqlite3.Connection, material_code: str | None = None) -> dict[str, Any] | None:
    """The profile in force.

    A material-specific profile wins over the global one; both come from
    app/postprocess.py at seed time and are stored so an old inspection still resolves
    to the thresholds that produced it.
    """
    if is_mongo(conn):
        profiles = list(conn.db.reference.find({"kind": "profile", "is_active": 1}, {"_id": 0, "kind": 0, "id": 0}))
        material = by_code(conn, material_code) if material_code else None
        chosen = [p for p in profiles if material and p.get("material_id") == material["material_id"]]
        if not chosen:
            chosen = [p for p in profiles if p.get("material_id") is None]
        if not chosen:
            chosen = profiles
        if not chosen:
            return None
        row = max(chosen, key=lambda p: p.get("version_no", 0))
        row["material_code"] = material_code if row.get("material_id") else None
        return row
    if material_code:
        row = conn.execute(
            """
            SELECT p.*, m.material_code FROM profile p
            LEFT JOIN material m ON m.material_id = p.material_id
            WHERE p.is_active = 1 AND m.material_code = ?
            ORDER BY p.version_no DESC LIMIT 1
            """,
            [material_code],
        ).fetchone()
        if row:
            return dict(row)
    row = conn.execute(
        """
        SELECT p.*, m.material_code FROM profile p
        LEFT JOIN material m ON m.material_id = p.material_id
        WHERE p.is_active = 1
        ORDER BY (p.material_id IS NULL) DESC, p.version_no DESC LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def all_profiles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if is_mongo(conn):
        rows = list(conn.db.reference.find({"kind": "profile"}, {"_id": 0, "kind": 0, "id": 0}).sort("profile_id", 1))
        by_id = {m["material_id"]: m["material_code"] for m in all_materials(conn)}
        for row in rows:
            row["material_code"] = by_id.get(row.get("material_id"))
        return rows
    rows = conn.execute(
        """
        SELECT p.*, m.material_code FROM profile p
        LEFT JOIN material m ON m.material_id = p.material_id
        ORDER BY p.profile_id
        """
    )
    return [dict(r) for r in rows]
