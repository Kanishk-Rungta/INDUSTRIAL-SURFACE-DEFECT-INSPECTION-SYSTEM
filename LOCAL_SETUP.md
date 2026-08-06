# Local setup

See the README **Local quick start**. Runtime state is entirely local: FastAPI on
`127.0.0.1:8000`, SQLite at `DATABASE_PATH`, the ONNX graph at `MODEL_PATH`, and media
under `data/`. No cloud account, API key, remote asset, or internet connection is used
during normal operation.

If Status reports low disk, free at least `MIN_FREE_DISK_GB` before inspection. If it
reports a model hash mismatch, recompute the SHA-256 and update `MODEL_SHA256` only after
verifying that the intended model file was installed. Camera permission can be reset in
the browser's localhost site settings.
