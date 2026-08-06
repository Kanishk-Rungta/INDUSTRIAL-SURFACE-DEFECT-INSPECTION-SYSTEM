# Industrial Surface-Defect Inspection System

A complete, offline-first application for pixel-level crack and scratch inspection of
industrial surfaces. It runs on one local computer using FastAPI, ONNX Runtime and
SQLite. Operators can inspect uploaded images, manually capture frames from a browser
camera, process local batches, review region geometry, search history and export results.

The system locates possible defects and measures them. It does **not** issue an
accept/reject verdict, and it does not display confidence percentages because the model
scores are not calibrated probabilities.

## Current local model

The model currently installed in this workspace is:

| Property | Value |
|---|---|
| Version | `V12_22` |
| File | `data/export/model.onnx` |
| SHA-256 | `df411260e21ec6361e97d4754b0c3f6920b7f5c2f6ec32c034cef17c3576b42d` |
| Architecture | MobileNetV3-Small encoder with slim U-Net decoder |
| Parameters | 1,432,000 |
| Input | Dynamic batch, `3 x 256 x 256` float32 |
| Output | Background, crack and scratch logits |
| Preprocessing | Whole-frame resize and bilateral filter, then ImageNet normalization |
| Measured ONNX latency | 54.4 ms, one local CPU thread |

The exported graph was compared with its PyTorch checkpoint before activation:

- Maximum absolute logit difference: `1.91e-05`
- Per-pixel argmax agreement: `1.00000`

The application still uses per-class calibrated threshold rules rather than plain
argmax. Those rules and all region post-processing remain in the canonical inference
pipeline.

## Features

- Local browser interface at `http://127.0.0.1:8000`
- Real ONNX inference on CPU
- PNG and JPEG upload with drag-and-drop
- File preview, remove and replace controls
- Manual browser-camera capture with device selection, immediate inspection and retake
- Rate-limited automatic live camera inspection with non-overlapping requests
- One API and one inference path for camera, upload and batch images
- Original, overlay and side-by-side result views
- Pixel-level masks and source-resolution overlays
- Crack/scratch region classification
- Area, centreline length, maximum width, bounding box and centroid measurements
- Persistent SQLite inspection and region records
- Searchable inspection history and region detail pages
- CSV and JSON exports
- Local batch processing
- Analytics dashboard: an outcome-mix, defect-class and throughput chart per batch
  session, plus a cross-session trend view, all server-rendered SVG (no chart library,
  no JavaScript dependency)
- Model, database, storage and disk status checks
- No required cloud service, remote inference endpoint or internet connection at runtime

## Architecture

```text
Browser upload ─┐
Browser camera ─┼── POST /api/inspections ── Inspection service
Local batch ────┘                                  │
                                                   ▼
                                      Configured inspection provider
                                                   │
                                      RealInspectionProvider
                                                   │
                                      app.inference.Inspector
                                                   │
                 decode → resize → bilateral filter → normalize → ONNX
                         → class thresholds → connected regions → geometry
                                                   │
                         ┌─────────────────────────┴────────────────────────┐
                         ▼                                                  ▼
                 SQLite inspection.db                         Local source/overlay files
```

`app.inference.Inspector` is the canonical model entry point. The web routes and
frontend do not implement resizing, color conversion, normalization, softmax,
thresholds, connected components or geometry. Changing the image source therefore does
not change the model path.

## Repository layout

| Path | Purpose |
|---|---|
| `app/main.py` | FastAPI application and local lifecycle |
| `app/inference.py` | Canonical ONNX model pipeline |
| `app/postprocess.py` | Thresholds, connected regions and measurements |
| `app/providers/` | Real and mock provider boundary |
| `app/services/` | Inspection, batch, history, export, status and analytics logic |
| `app/repositories/` | SQLite persistence queries |
| `app/routes/` | Page, API and controlled media routes |
| `app/templates/` | Server-rendered interface |
| `app/static/` | Local CSS, JavaScript and icons |
| `app/database/` | Schema, migrations and seed implementation |
| `data/export/` | Active ONNX model and benchmark metadata |
| `data/sources/` | Stored source images |
| `data/overlays/` | Stored source-resolution overlays |
| `data/batches/` | Local batch input folders |
| `data/exports/` | Generated exports |
| `tests/` | Backend, database, security, model mapping and UI tests |
| `bench/` | Training evaluation and ONNX export tooling |
| `dataset/` | Dataset acquisition, normalization, splitting and QA |
| `docs/` | Detailed architecture, integration and model documentation |

## Requirements

- Windows 10/11, Linux or macOS
- Python 3.11 or newer
- Approximately 2 GB free disk space for the application environment
- A modern browser for the UI
- A browser-supported camera for live capture
- No CUDA or GPU is required

Camera access works on `localhost`, which browsers treat as a secure context. Accessing
the application through another device normally requires HTTPS for camera permission.

## Installation

### Windows PowerShell

```powershell
cd "C:\Users\Acer\OneDrive\Desktop\Vision 404\INDUSTRIAL-SURFACE-DEFECT-INSPECTION-SYSTEM"

python -m venv .venv-app
.\.venv-app\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Copy-Item .env.example .env
```

For development and tests:

```powershell
python -m pip install -r requirements-dev.txt
```

### Linux or macOS

```bash
cd /path/to/INDUSTRIAL-SURFACE-DEFECT-INSPECTION-SYSTEM

python3 -m venv .venv-app
source .venv-app/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cp .env.example .env
```

For development and tests:

```bash
python -m pip install -r requirements-dev.txt
```

## Configuration

The application reads `.env` from the repository root. The working local configuration
uses these important values:

```dotenv
APP_HOST=127.0.0.1
APP_PORT=8000
APP_ENV=development

INSPECTION_PROVIDER=real
DEMO_MODE=false

MODEL_PATH=data/export/model.onnx
MODEL_SHA256=df411260e21ec6361e97d4754b0c3f6920b7f5c2f6ec32c034cef17c3576b42d
STATION_ID=line-1-cam-A

DATABASE_PATH=data/inspection.db
SOURCE_ROOT=data/sources
OVERLAY_ROOT=data/overlays
EXPORT_ROOT=data/exports
BATCH_ROOT=data/batches
LOG_ROOT=data/logs

MAX_UPLOAD_MB=20
MAX_IMAGE_WIDTH=12000
MAX_IMAGE_HEIGHT=12000
MIN_FREE_DISK_GB=1
```

`MIN_FREE_DISK_GB=1` is the local value chosen for this machine. The distributed
`.env.example` retains a more conservative 5 GB reserve. Inspection is deliberately
blocked when the configured reserve is not available.

## Database initialization

The application creates the SQLite schema and required local directories automatically
at startup. The default database is:

```text
data/inspection.db
```

To create deterministic demonstration data in mock mode:

```powershell
$env:INSPECTION_PROVIDER = "mock"
$env:DEMO_MODE = "true"
python -m scripts.seed_db
Remove-Item Env:INSPECTION_PROVIDER
Remove-Item Env:DEMO_MODE
```

To completely replace the database and generated demonstration assets:

```powershell
$env:INSPECTION_PROVIDER = "mock"
$env:DEMO_MODE = "true"
python -m scripts.reset_db
Remove-Item Env:INSPECTION_PROVIDER
Remove-Item Env:DEMO_MODE
```

The reset command is destructive. Back up `data/inspection.db`, `data/sources/` and
`data/overlays/` first if inspection history must be retained.

## Run locally

Activate the environment and start the server:

```powershell
.\.venv-app\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Alternatively:

```powershell
python -m app.main
```

Open:

```text
http://127.0.0.1:8000
```

Use `Ctrl+C` in the terminal to stop the server.

### Optional local-network access

Only expose the server when access from another trusted device is intentional:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

This application does not provide user authentication. Do not expose it directly to the
public internet.

## Operator workflows

### Upload an image

1. Open **Capture**.
2. Choose the material.
3. Enter a product ID and optional batch ID.
4. Select a PNG/JPEG or drag it onto the upload area.
5. Review the preview; remove or replace it if necessary.
6. Click **Inspect image**.
7. Review the status, original image, overlay, region count and measurements.
8. Open a region or the automatically stored history record.

The browser sends the original file bytes. It does not resize or recompress the upload.

### Capture from a camera

1. Open **Capture** on `http://127.0.0.1:8000`.
2. Choose the material and enter the product metadata.
3. Click **Start camera** and grant browser permission.
4. Select another camera if required.
5. Click **Capture frame**; the still image is inspected immediately.
6. Review the stored result or retake the frame.
7. Stop the camera when finished.

Camera permission is requested only after **Start camera** is clicked. Frames are not
uploaded continuously. The selected frame is sent only when the operator requests an
inspection, and all MediaStream tracks are stopped when leaving the page.

### Run automatic live inspection

1. Open **Live**.
2. Select the material, product prefix and camera device.
3. Click **Start live inspection** and grant camera permission.
4. Keep **Inspect automatically** enabled.
5. The application submits one frame at the configured interval and updates the result
   in place. A new request never starts while the previous inference is running.
6. Click **Stop live inspection** when finished.

### Process a batch

1. Create a folder directly under `data/batches/`.
2. Place supported PNG/JPEG images in that folder.
3. Open **Batch**.
4. Choose the folder and material.
5. Optionally run a dry run first.
6. Start processing and monitor progress.
7. Export the completed run as CSV or JSON.

Batch paths are constrained to `BATCH_ROOT`; path traversal and arbitrary filesystem
access are rejected.

### Review results

- **Live** shows the most recent station result.
- **Regions** provides source/overlay modes, zoom and previous/next navigation.
- **History** filters stored inspections by product, date, material, status and class.
- **Materials** describes thresholds, measured coverage and model limitations.
- **Status** checks the provider, model/hash, database and free disk space.

## Common inspection API

Uploads, browser-camera frames and API batch clients use:

```http
POST /api/inspections
Content-Type: multipart/form-data
```

Multipart fields:

| Field | Required | Description |
|---|---|---|
| `image` | Yes | Original PNG or JPEG |
| `source_type` | Yes | `upload`, `camera` or `batch` |
| `material` | Yes | Material code, for example `steel` |
| `product_id` | Recommended | Product traceability ID |
| `batch_id` | No | Batch traceability metadata |
| `station_id` | No | Must match the configured station when supplied |

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/inspections \
  -F "image=@part.png;type=image/png" \
  -F "source_type=upload" \
  -F "material=steel" \
  -F "product_id=batch-77/item-12"
```

Important endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/status` | Full local health status |
| `POST /api/status/check` | Refresh status checks |
| `POST /api/inspections` | Inspect and persist one image |
| `GET /api/inspections` | Search stored inspections |
| `GET /api/inspections/{id}` | Inspection detail |
| `GET /api/inspections/{id}/regions/{index}` | Region detail |
| `POST /api/batches` | Start a local batch |
| `GET /api/batches/{id}` | Batch report and progress |
| `GET /api/inspections/export.csv` | Export filtered history |
| `GET /api/inspections/export.json` | Export filtered history as JSON |

Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

## Local storage

```text
data/
├── inspection.db
├── export/
│   ├── model.onnx
│   └── latency.json
├── sources/
├── overlays/
├── batches/
├── exports/
└── logs/
```

Source and overlay filenames are generated by the backend. User-supplied filenames are
never used as storage paths. Media responses resolve only paths within configured local
roots.

## Replacing the model

1. Export a model that follows `docs/INTEGRATION.md`.
2. Stop the application.
3. Place the new graph in `data/export/`.
4. Register it:

```powershell
python -m scripts.register_model `
  --model data/export/model.onnx `
  --version MODEL_VERSION `
  --params PARAMETER_COUNT `
  --latency-ms MEASURED_LATENCY
```

5. Copy the printed SHA-256 into `MODEL_SHA256` in `.env`.
6. Restart the server and confirm **Model file / hash: OK** on **Status**.

The application calculates the graph hash at runtime. If it differs from the configured
hash or active database model, real inference is stopped. A missing, corrupt or swapped
model is never treated as a clean inspection.

### Re-export the included checkpoint

The source checkpoint is `data/model.pt`. Its verified export contract is:

```powershell
python bench/export_onnx.py `
  --models smpslim_timm-mobilenetv3_small_100 `
  --weights data/model.pt `
  --classes 3 `
  --tag V12_22 `
  --resize `
  --size 256 `
  --prep bilateral
```

Export requires the training/export packages (`torch`, `torchvision`, `timm`,
`segmentation-models-pytorch`, `onnx` and `onnxscript`). They are not required for
normal ONNX Runtime operation.

## Testing

Install development dependencies:

```powershell
python -m pip install -r requirements-dev.txt
```

Run the backend and non-browser suite:

```powershell
python -m pytest -q
```

Install the Playwright browser and run UI tests:

```powershell
python -m playwright install chromium
python -m pytest -q
```

Additional checks:

```powershell
python -m compileall -q app tests
node --check app/static/js/capture.js
```

The latest executed default suite collected 284 tests and all 284 passed, including 25
tests in real headless Chromium and 9 canonical inference-pipeline regression tests.
Real-model verification also produced a source-resolution 400 x 400 overlay and class
map with four regions from the installed ONNX graph.

## Troubleshooting

### Model file / hash: FAILED

Confirm that these `.env` values match the installed model:

```dotenv
INSPECTION_PROVIDER=real
MODEL_PATH=data/export/model.onnx
MODEL_SHA256=df411260e21ec6361e97d4754b0c3f6920b7f5c2f6ec32c034cef17c3576b42d
```

Then restart the application. Settings and the model provider are loaded when the
process starts; refreshing the browser does not reload them.

### Disk space: FAILED

Free disk space or reduce `MIN_FREE_DISK_GB` in the machine-local `.env` only after
confirming there is still enough room for images, overlays, SQLite transactions and
exports. Restart after changing the value.

### Camera does not start

- Open the site through `http://127.0.0.1:8000`, not an arbitrary HTTP hostname.
- Grant camera permission in the browser's site settings.
- Close other applications using the camera.
- Try another device from the camera selector.
- Use image upload when no browser camera is available.

### Uploaded image is rejected

- Use PNG, JPG or JPEG.
- Ensure MIME type and file contents match.
- Keep the file below `MAX_UPLOAD_MB`.
- Confirm the image is not empty or corrupt.
- Check configured maximum dimensions.

### Application starts but inspection is blocked

Open **Status** and fix every failed blocking check. Processing failures and acquisition
failures remain distinct from clean images and include an error code/message.

### Port 8000 is already in use

Stop the earlier server with `Ctrl+C`, or run on another local port:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

## Model performance and limitations

Three seeds on the frozen v7 splits produced these research results:

| Split | clDice | IoU | Detection |
|---|---:|---:|---:|
| Factory materials | 0.6771 +/- 0.010 | 0.4646 +/- 0.008 | 0.9615 +/- 0.010 |
| Factory scratches | 0.8744 +/- 0.004 | 0.6759 +/- 0.009 | 1.0000 |
| Unseen wood | 0.7259 +/- 0.013 | 0.3413 +/- 0.007 | 0.9556 |
| Clean negatives | N/A | N/A | False-positive area 0.0046 +/- 0.001 |

Known limitations:

- Crack/scratch typing is provisional: approximately 49% crack-pixel typing accuracy on
  the headline split, biased toward scratch.
- Steel has the strongest typing evidence but relatively difficult thin geometry.
- Plastic training coverage represents one PVC-pipe product family.
- Ceramic coverage is limited.
- Epoxy has no training masks; detection may transfer, typing does not.
- Glass and non-steel metals are unsupported.
- Scratch evidence is predominantly steel.
- `max_width_px` measures the widest inscribable point along the skeleton, not the
  widest visible span.
- The system reports evidence for human review, not a quality-control verdict.

## Offline and security properties

- No CDN, remote font, analytics or telemetry is required.
- Inference uses local ONNX Runtime CPU execution.
- Uploaded filenames do not become filesystem paths.
- Batch input is constrained to configured roots.
- Stored media paths are checked before files are served.
- Database writes use transactions.
- Model hashes prevent silent model replacement.
- The local server has no authentication and should not be publicly exposed.

## Documentation

| Document | Contents |
|---|---|
| `LOCAL_SETUP.md` | Concise local setup notes |
| `docs/INTEGRATION.md` | Authoritative tensor, preprocessing and post-processing contract |
| `docs/MODEL_INTEGRATION.md` | Provider boundary and model lifecycle |
| `docs/ARCHITECTURE.md` | Full system and model architecture |
| `docs/DATABASE.md` | SQLite schema and relationships |
| `docs/DEPLOYMENT.md` | Supported local deployment |
| `docs/TEST_PLAN.md` | Requirement and test traceability |
| `docs/DATASET.md` | Dataset construction and provenance |
| `docs/RESULTS.md` | Stored experiment evidence |
| `docs/ATTRIBUTION.md` | Dataset licences and attribution |

## Licence and data note

The trained model derives from sources with mixed terms, including CC0, CC-BY,
CC-BY-NC and research-only datasets. Re-check every source in `docs/ATTRIBUTION.md`
before commercial distribution. A model trained using non-commercial data is not
automatically free of that restriction.

## Deployment status

Two supported deployments, not interchangeable. The station is a persistent local
FastAPI process with a local ONNX model, SQLite database and local media directories;
normal inspection requires no internet connection. A `Dockerfile` also builds a
mock-mode container for a public demo of the interface — every screen including
Analytics, no real inference, no factory image ever leaves this repository's control —
deployable to Render's free tier via the included `render.yaml` blueprint. See
`docs/DEPLOYMENT.md` for both. Vercel and other serverless paths are retired.
