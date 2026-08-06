"""Local and Vercel deployment guarantees."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_local_defaults_bind_loopback_and_use_real_provider():
    from app.config import Settings

    settings = Settings(_env_file=None, inspection_provider="real", demo_mode=False)
    assert settings.app_host == "127.0.0.1"
    assert settings.inspection_provider == "real"
    assert settings.demo_mode is False


def test_runtime_paths_stay_under_the_local_data_root():
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        data_root=Path("data"), database_path=Path("data/inspection.db"),
        source_root=Path("data/sources"), overlay_root=Path("data/overlays"),
        export_root=Path("data/exports"), batch_root=Path("data/batches"),
        log_root=Path("data/logs"),
    )
    for path in (settings.db_file, settings.source_dir, settings.overlay_dir,
                 settings.export_dir, settings.batch_dir, settings.log_dir):
        assert path.resolve().is_relative_to((ROOT / "data").resolve())


def test_vercel_entry_and_configuration_exist():
    assert (ROOT / "vercel.json").is_file()
    assert (ROOT / ".vercelignore").is_file()
    assert (ROOT / "api" / "index.py").is_file()


def test_vercel_requirements_include_real_inference_and_mongodb():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "fastapi" in requirements
    for dependency in ("pymongo", "onnxruntime", "opencv-python-headless", "scikit-image"):
        assert dependency in requirements


def test_pyproject_declares_vercel_runtime_dependencies():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    for dependency in ("fastapi", "pymongo", "onnxruntime", "opencv-python-headless", "scikit-image"):
        assert dependency in pyproject


def test_vercel_config_uses_real_bundled_model():
    config = (ROOT / "vercel.json").read_text(encoding="utf-8")
    assert '"INSPECTION_PROVIDER": "real"' in config
    assert '"data/export/model.onnx"' in config
    assert (ROOT / "data" / "export" / "model.onnx").is_file()


def test_mongodb_is_selected_only_when_uri_is_configured():
    from app.config import Settings

    assert not Settings(_env_file=None, mongodb_uri="").uses_mongodb
    assert Settings(_env_file=None, mongodb_uri="mongodb+srv://example.invalid/db").uses_mongodb


def test_missing_mongodb_uri_returns_diagnostic_instead_of_crashing(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.config import reset_settings_cache
    from app.main import create_app

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("INSPECTION_PROVIDER", "real")
    monkeypatch.setenv("MONGODB_URI", "")
    monkeypatch.setenv("VISION404_TMP_DIR", str(tmp_path / "vercel-runtime"))
    reset_settings_cache()
    try:
        with TestClient(create_app()) as client:
            response = client.get("/healthz")
            assert response.status_code == 503
            assert response.json()["status"] == "configuration_error"
            assert "MONGODB_URI" in response.json()["detail"]
    finally:
        reset_settings_cache()


def test_serverless_paths_use_tmp(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("VERCEL", "1")
    settings = Settings(
        _env_file=None,
        data_root=Path("data"),
        database_path=Path("data/inspection.db"),
    )
    assert settings.is_serverless
    assert settings.runtime_data_dir == Path("/tmp/vision404")
    assert settings.db_file == Path("/tmp/vision404/inspection.db")
    assert settings.run_batches_synchronously


def test_stored_image_paths_are_relative_to_data_root(settings):
    from app.services.inspection_service import portable_media_path

    absolute = settings.overlay_dir / "real" / "example.png"
    assert portable_media_path(str(absolute), settings) == "overlays/real/example.png"


def test_relative_traversal_in_a_stored_path_is_refused(settings):
    from app.services.inspection_service import image_path_for

    assert image_path_for({"source_image_path": "../../../etc/passwd"}, "source", settings) is None


def test_relative_paths_resolve_against_local_data_root(seeded, settings):
    from app.services.inspection_service import image_path_for, portable_media_path

    sample = next(settings.overlay_dir.rglob("*.png"), None)
    if sample is None:
        pytest.skip("no generated overlay available")
    relative = portable_media_path(str(sample), settings)
    assert not Path(relative).is_absolute()
    assert image_path_for({"overlay_image_path": relative}, "overlay", settings) == sample.resolve()
