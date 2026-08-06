"""All SQL for inspections and regions.

One rule holds this file together: the history screen, the CSV export and the summary
cards must all be answered by the *same* filter clause, or the totals stop reconciling
(FR-19 / T-16).  ``_where()`` is that single clause.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from app.database.mongo import is_mongo, next_id

SELECT_COLUMNS = """
    i.inspection_id,
    i.product_id,
    i.captured_at,
    i.processed_at,
    i.status,
    i.region_count,
    i.latency_ms,
    i.image_sha256,
    i.source_image_path,
    i.overlay_image_path,
    i.error_code,
    i.error_message,
    i.batch_run_id,
    m.material_code,
    m.material_name,
    m.support_status,
    s.station_code,
    mv.version   AS model_version,
    mv.file_name AS model_file_name,
    mv.artefact_sha256,
    p.version_no AS profile_version,
    p.crack_threshold,
    p.scratch_threshold,
    p.minimum_area_px,
    p.minimum_skeleton_px,
    (SELECT MAX(r.length_px) FROM defect_region r WHERE r.inspection_id = i.inspection_id) AS max_length_px
"""

BASE_FROM = """
    FROM inspection i
    LEFT JOIN material      m  ON m.material_id = i.material_id
    LEFT JOIN station       s  ON s.station_id = i.station_id
    LEFT JOIN model_version mv ON mv.model_version_id = i.model_version_id
    LEFT JOIN profile       p  ON p.profile_id = i.profile_id
"""


@dataclass
class HistoryFilters:
    """The six FR-18 filters, plus batch scoping used by the batch report."""

    date_from: str | None = None
    date_to: str | None = None
    material: str | None = None
    status: str | None = None
    defect_class: str | None = None
    station: str | None = None
    product_id: str | None = None
    batch_run_id: int | None = None
    page: int = 1
    page_size: int = 25

    def active(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in {
                "date_from": self.date_from,
                "date_to": self.date_to,
                "material": self.material,
                "status": self.status,
                "class": self.defect_class,
                "station": self.station,
                "product_id": self.product_id,
            }.items()
            if v
        }

    def query_string(self, **overrides: Any) -> str:
        params = {
            "date_from": self.date_from,
            "date_to": self.date_to,
            "material": self.material,
            "status": self.status,
            "class": self.defect_class,
            "station": self.station,
            "product_id": self.product_id,
            "page": self.page,
            "page_size": self.page_size,
        }
        params.update(overrides)
        from urllib.parse import urlencode

        return urlencode({k: v for k, v in params.items() if v not in (None, "")})


@dataclass
class Page:
    rows: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 25

    @property
    def page_count(self) -> int:
        return max(1, -(-self.total // self.page_size))

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.page_count

    @property
    def first_index(self) -> int:
        return 0 if self.total == 0 else (self.page - 1) * self.page_size + 1

    @property
    def last_index(self) -> int:
        return min(self.total, self.page * self.page_size)


def _where(filters: HistoryFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if filters.date_from:
        clauses.append("i.captured_at >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        # Inclusive of the whole end day when only a date was supplied.
        end = filters.date_to
        clauses.append("i.captured_at <= ?")
        params.append(end if len(end) > 10 else f"{end}T23:59:59.999999")
    if filters.material:
        clauses.append("m.material_code = ?")
        params.append(filters.material)
    if filters.status:
        clauses.append("i.status = ?")
        params.append(filters.status)
    if filters.station:
        clauses.append("s.station_code = ?")
        params.append(filters.station)
    if filters.product_id:
        pattern = filters.product_id.replace("*", "%")
        if "%" not in pattern:
            pattern = f"%{pattern}%"
        clauses.append("i.product_id LIKE ?")
        params.append(pattern)
    if filters.batch_run_id is not None:
        clauses.append("i.batch_run_id = ?")
        params.append(filters.batch_run_id)
    if filters.defect_class:
        clauses.append(
            "EXISTS (SELECT 1 FROM defect_region r JOIN defect_class c ON c.class_id = r.class_id "
            "WHERE r.inspection_id = i.inspection_id AND c.class_code = ?)"
        )
        params.append(filters.defect_class)

    return (("WHERE " + " AND ".join(clauses)) if clauses else "", params)


def count(conn: sqlite3.Connection, filters: HistoryFilters) -> int:
    if is_mongo(conn):
        return int(conn.db.inspections.count_documents(_mongo_filter(filters)))
    where, params = _where(filters)
    sql = f"SELECT COUNT(*) AS n {BASE_FROM} {where}"
    return int(conn.execute(sql, params).fetchone()["n"])


def search(conn: sqlite3.Connection, filters: HistoryFilters) -> Page:
    if is_mongo(conn):
        total = count(conn, filters)
        page_size = max(1, min(200, filters.page_size))
        page_no = max(1, filters.page)
        cursor = conn.db.inspections.find(_mongo_filter(filters), {"_id": 0, "regions": 0}).sort([("captured_at", -1), ("inspection_id", -1)]).skip((page_no - 1) * page_size).limit(page_size)
        return Page(rows=list(cursor), total=total, page=page_no, page_size=page_size)
    where, params = _where(filters)
    total = count(conn, filters)
    page_size = max(1, min(200, filters.page_size))
    page_no = max(1, filters.page)
    offset = (page_no - 1) * page_size

    sql = (
        f"SELECT {SELECT_COLUMNS} {BASE_FROM} {where} "
        "ORDER BY i.captured_at DESC, i.inspection_id DESC LIMIT ? OFFSET ?"
    )
    rows = [dict(r) for r in conn.execute(sql, [*params, page_size, offset])]
    return Page(rows=rows, total=total, page=page_no, page_size=page_size)


def all_matching(conn: sqlite3.Connection, filters: HistoryFilters) -> list[dict[str, Any]]:
    """Every matching row, unpaginated - used by exports so totals always reconcile."""
    if is_mongo(conn):
        return list(conn.db.inspections.find(_mongo_filter(filters), {"_id": 0, "regions": 0}).sort([("captured_at", -1), ("inspection_id", -1)]))
    where, params = _where(filters)
    sql = f"SELECT {SELECT_COLUMNS} {BASE_FROM} {where} ORDER BY i.captured_at DESC, i.inspection_id DESC"
    return [dict(r) for r in conn.execute(sql, params)]


def status_totals(conn: sqlite3.Connection, filters: HistoryFilters) -> dict[str, int]:
    """Counts per status for the same filter set the table and the export use."""
    if is_mongo(conn):
        pipeline = [{"$match": _mongo_filter(filters)}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
        totals = {r["_id"]: int(r["n"]) for r in conn.db.inspections.aggregate(pipeline)}
        for key in ("regions_found", "clean", "acquisition_failure", "processing_failure"):
            totals.setdefault(key, 0)
        totals["processed"] = sum(totals[k] for k in ("regions_found", "clean", "acquisition_failure", "processing_failure"))
        return totals
    where, params = _where(filters)
    sql = f"SELECT i.status AS status, COUNT(*) AS n {BASE_FROM} {where} GROUP BY i.status"
    totals = {r["status"]: int(r["n"]) for r in conn.execute(sql, params)}
    for key in ("regions_found", "clean", "acquisition_failure", "processing_failure"):
        totals.setdefault(key, 0)
    totals["processed"] = sum(
        totals[k] for k in ("regions_found", "clean", "acquisition_failure", "processing_failure")
    )
    return totals


def region_totals(conn: sqlite3.Connection, filters: HistoryFilters) -> dict[str, int]:
    if is_mongo(conn):
        pipeline = [{"$match": _mongo_filter(filters)}, {"$unwind": "$regions"}, {"$group": {"_id": "$regions.class_code", "n": {"$sum": 1}}}]
        counts = {r["_id"]: int(r["n"]) for r in conn.db.inspections.aggregate(pipeline)}
        counts.setdefault("crack", 0)
        counts.setdefault("scratch", 0)
        counts["total"] = counts["crack"] + counts["scratch"]
        return counts
    where, params = _where(filters)
    sql = (
        "SELECT c.class_code AS class_code, COUNT(*) AS n "
        "FROM defect_region r JOIN defect_class c ON c.class_id = r.class_id "
        f"WHERE r.inspection_id IN (SELECT i.inspection_id {BASE_FROM} {where}) "
        "GROUP BY c.class_code"
    )
    counts = {r["class_code"]: int(r["n"]) for r in conn.execute(sql, params)}
    counts.setdefault("crack", 0)
    counts.setdefault("scratch", 0)
    counts["total"] = counts["crack"] + counts["scratch"]
    return counts


def get(conn: sqlite3.Connection, inspection_id: int) -> dict[str, Any] | None:
    if is_mongo(conn):
        return conn.db.inspections.find_one({"inspection_id": inspection_id}, {"_id": 0, "regions": 0})
    sql = f"SELECT {SELECT_COLUMNS} {BASE_FROM} WHERE i.inspection_id = ?"
    row = conn.execute(sql, [inspection_id]).fetchone()
    return dict(row) if row else None


def latest(conn: sqlite3.Connection, station_code: str | None = None) -> dict[str, Any] | None:
    """The item currently at the station - the last inspection the station wrote.

    Ordered by inspection_id, not captured_at: "currently at the station" means the most
    recently processed part.  Ordering by capture time would let a re-processed older
    image, or a demo run seeded against a fixed anchor date, appear to be the live part.
    History is ordered by captured_at, which is the right axis there.
    """
    if is_mongo(conn):
        query = {"station_code": station_code} if station_code else {}
        return conn.db.inspections.find_one(query, {"_id": 0, "regions": 0}, sort=[("inspection_id", -1)])
    where = "WHERE s.station_code = ?" if station_code else ""
    params = [station_code] if station_code else []
    sql = f"SELECT {SELECT_COLUMNS} {BASE_FROM} {where} ORDER BY i.inspection_id DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def regions(conn: sqlite3.Connection, inspection_id: int) -> list[dict[str, Any]]:
    if is_mongo(conn):
        row = conn.db.inspections.find_one({"inspection_id": inspection_id}, {"regions": 1})
        return sorted((row or {}).get("regions", []), key=lambda r: r["region_index"])
    sql = """
        SELECT r.region_id, r.region_index, c.class_code, c.display_name,
               r.area_px, r.length_px, r.max_width_px,
               r.bbox_x, r.bbox_y, r.bbox_width, r.bbox_height,
               r.centroid_x, r.centroid_y
        FROM defect_region r
        JOIN defect_class c ON c.class_id = r.class_id
        WHERE r.inspection_id = ?
        ORDER BY r.region_index
    """
    return [dict(r) for r in conn.execute(sql, [inspection_id])]


def region(conn: sqlite3.Connection, inspection_id: int, region_index: int) -> dict[str, Any] | None:
    for row in regions(conn, inspection_id):
        if row["region_index"] == region_index:
            return row
    return None


def class_breakdown(conn: sqlite3.Connection, inspection_id: int) -> dict[str, int]:
    if is_mongo(conn):
        out: dict[str, int] = {}
        for row in regions(conn, inspection_id):
            code = row["class_code"]
            out[code] = out.get(code, 0) + 1
        return out
    sql = """
        SELECT c.class_code AS class_code, COUNT(*) AS n
        FROM defect_region r JOIN defect_class c ON c.class_id = r.class_id
        WHERE r.inspection_id = ? GROUP BY c.class_code
    """
    return {r["class_code"]: int(r["n"]) for r in conn.execute(sql, [inspection_id])}


def total_count(conn: sqlite3.Connection) -> int:
    if is_mongo(conn):
        return int(conn.db.inspections.count_documents({}))
    return int(conn.execute("SELECT COUNT(*) AS n FROM inspection").fetchone()["n"])


def insert(conn: sqlite3.Connection, values: dict[str, Any]) -> int:
    if is_mongo(conn):
        inspection_id = next_id(conn, "inspection")
        refs = conn.db.reference
        material = refs.find_one({"kind": "material", "material_id": values.get("material_id")}) or {}
        station = refs.find_one({"kind": "station", "station_id": values["station_id"]}) or {}
        model = refs.find_one({"kind": "model", "model_version_id": values["model_version_id"]}) or {}
        profile = refs.find_one({"kind": "profile", "profile_id": values["profile_id"]}) or {}
        doc = {"inspection_id": inspection_id, **values, "regions": [],
               "material_code": material.get("material_code"), "material_name": material.get("material_name"),
               "support_status": material.get("support_status"), "station_code": station.get("station_code"),
               "model_version": model.get("version"), "model_file_name": model.get("file_name"),
               "artefact_sha256": model.get("artefact_sha256"), "profile_version": profile.get("version_no"),
               "crack_threshold": profile.get("crack_threshold"), "scratch_threshold": profile.get("scratch_threshold"),
               "minimum_area_px": profile.get("minimum_area_px"), "minimum_skeleton_px": profile.get("minimum_skeleton_px"),
               "max_length_px": 0.0}
        conn.db.inspections.insert_one(doc)
        return inspection_id
    columns = [
        "station_id",
        "profile_id",
        "model_version_id",
        "material_id",
        "batch_run_id",
        "image_sha256",
        "product_id",
        "captured_at",
        "processed_at",
        "status",
        "region_count",
        "latency_ms",
        "source_image_path",
        "overlay_image_path",
        "error_code",
        "error_message",
    ]
    placeholders = ", ".join("?" for _ in columns)
    cur = conn.execute(
        f"INSERT INTO inspection ({', '.join(columns)}) VALUES ({placeholders})",
        [values.get(c) for c in columns],
    )
    return int(cur.lastrowid)


def insert_region(conn: sqlite3.Connection, inspection_id: int, values: dict[str, Any]) -> int:
    if is_mongo(conn):
        cls = conn.db.reference.find_one({"kind": "defect_class", "class_id": values["class_id"]}) or {}
        region_id = next_id(conn, "region")
        doc = {"region_id": region_id, **values, "class_code": cls.get("class_code"), "display_name": cls.get("display_name")}
        conn.db.inspections.update_one({"inspection_id": inspection_id}, {"$push": {"regions": doc}, "$max": {"max_length_px": values["length_px"]}})
        return region_id
    cur = conn.execute(
        """
        INSERT INTO defect_region
            (inspection_id, region_index, class_id, area_px, length_px, max_width_px,
             bbox_x, bbox_y, bbox_width, bbox_height, centroid_x, centroid_y)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            inspection_id,
            values["region_index"],
            values["class_id"],
            values["area_px"],
            values["length_px"],
            values["max_width_px"],
            values["bbox_x"],
            values["bbox_y"],
            values["bbox_width"],
            values["bbox_height"],
            values.get("centroid_x"),
            values.get("centroid_y"),
        ],
    )
    return int(cur.lastrowid)


def distinct_values(conn: sqlite3.Connection) -> dict[str, list[str]]:
    """Filter dropdown options, taken from the data rather than hardcoded."""
    if is_mongo(conn):
        return {
            "materials": [r["material_code"] for r in conn.db.reference.find({"kind": "material"}).sort("material_id", 1)],
            "stations": [r["station_code"] for r in conn.db.reference.find({"kind": "station"}).sort("station_id", 1)],
            "classes": [r["class_code"] for r in conn.db.reference.find({"kind": "defect_class"}).sort("class_id", 1)],
        }
    materials = [
        r["material_code"] for r in conn.execute("SELECT material_code FROM material ORDER BY material_id")
    ]
    stations = [r["station_code"] for r in conn.execute("SELECT station_code FROM station ORDER BY station_id")]
    classes = [r["class_code"] for r in conn.execute("SELECT class_code FROM defect_class ORDER BY class_id")]
    return {"materials": materials, "stations": stations, "classes": classes}


def latest_with_regions(conn: sqlite3.Connection) -> dict[str, Any] | None:
    if is_mongo(conn):
        return conn.db.inspections.find_one({"region_count": {"$gt": 0}}, {"_id": 0, "regions": 0}, sort=[("captured_at", -1), ("inspection_id", -1)])
    row = conn.execute("SELECT inspection_id FROM inspection WHERE region_count > 0 ORDER BY captured_at DESC, inspection_id DESC LIMIT 1").fetchone()
    return {"inspection_id": row["inspection_id"]} if row else None


def _mongo_filter(filters: HistoryFilters) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if filters.date_from or filters.date_to:
        query["captured_at"] = {}
        if filters.date_from:
            query["captured_at"]["$gte"] = filters.date_from
        if filters.date_to:
            end = filters.date_to
            query["captured_at"]["$lte"] = end if len(end) > 10 else f"{end}T23:59:59.999999"
    for name, value in (("material_code", filters.material), ("status", filters.status), ("station_code", filters.station), ("batch_run_id", filters.batch_run_id)):
        if value is not None:
            query[name] = value
    if filters.product_id:
        import re
        pattern = re.escape(filters.product_id).replace(r"\*", ".*")
        query["product_id"] = {"$regex": pattern, "$options": "i"}
    if filters.defect_class:
        query["regions.class_code"] = filters.defect_class
    return query
