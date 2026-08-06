"""MongoDB production persistence without requiring a live Atlas cluster."""

from datetime import UTC, datetime

import mongomock
from fastapi.testclient import TestClient

from app.config import Settings
from app.database.mongo import MongoConnection, ensure_reference_data
from app.providers.base import InspectionResult, RegionRecord
from app.repositories import batch_repository as batches
from app.repositories import inspection_repository as inspections
from app.repositories.inspection_repository import HistoryFilters
from app.services import inspection_service, mongo_media


def mongo_conn(tmp_path):
    conn = MongoConnection(mongomock.MongoClient()["vision404_test"])
    settings = Settings(
        _env_file=None,
        mongodb_uri="mongodb://test.invalid",
        database_path="data/inspection.db",
        source_root=tmp_path / "sources",
        overlay_root=tmp_path / "overlays",
        export_root=tmp_path / "exports",
        batch_root=tmp_path / "batches",
        log_root=tmp_path / "logs",
        inspection_provider="real",
    )
    settings.ensure_dirs()
    ensure_reference_data(conn, settings)
    return conn, settings


def test_reference_data_bootstraps_from_bundled_database(tmp_path):
    conn, _ = mongo_conn(tmp_path)
    assert conn.db.reference.count_documents({"kind": "material"}) >= 1
    assert conn.db.reference.find_one({"kind": "model", "is_active": 1})["version"] == "V12_22"


def test_inspection_regions_filters_and_media_are_persistent(tmp_path):
    conn, settings = mongo_conn(tmp_path)
    source = tmp_path / "sources" / "capture.png"
    overlay = tmp_path / "overlays" / "capture.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    overlay.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"source-image")
    overlay.write_bytes(b"overlay-image")
    now = datetime.now(UTC).isoformat()
    result = InspectionResult(
        status="regions_found", empty=False, product_id="mongo-item-1", material="steel",
        station_id=settings.station_id, captured_at=now, processed_at=now, latency_ms=12.5,
        source_image_path=str(source), overlay_image_path=str(overlay),
        regions=[RegionRecord(1, "crack", 40, 12.0, 3.0, (1, 2, 8, 9), (5.0, 6.0))],
    )
    inspection_id = inspection_service.store_result(conn, result, settings=settings, write_log=False)
    row = inspections.get(conn, inspection_id)
    assert row["product_id"] == "mongo-item-1"
    assert row["source_image_path"].startswith("mongodb:")
    assert mongo_media.load(conn, row["source_image_path"])[0] == b"source-image"
    assert inspections.class_breakdown(conn, inspection_id) == {"crack": 1}
    assert inspections.search(conn, HistoryFilters(material="steel")).total == 1


def test_batch_documents_are_created_and_finished(tmp_path):
    conn, _ = mongo_conn(tmp_path)
    batch_id = batches.create(conn, {"source_folder": "demo", "started_at": "2026-08-06", "status": "running"})
    batches.finish(conn, batch_id, {"status": "completed", "image_count": 3})
    assert batches.get(conn, batch_id)["status"] == "completed"
    assert batches.latest_id(conn) == batch_id


def test_server_rendered_pages_work_with_mongodb(tmp_path):
    from app.dependencies import get_db, settings_dep
    from app.main import create_app

    conn, settings = mongo_conn(tmp_path)
    app = create_app()

    def mongo_db_override():
        yield conn

    app.dependency_overrides[get_db] = mongo_db_override
    app.dependency_overrides[settings_dep] = lambda: settings
    client = TestClient(app)
    for path in ("/live", "/analytics", "/history", "/materials", "/status"):
        assert client.get(path).status_code == 200
