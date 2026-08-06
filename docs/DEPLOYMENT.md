# Vercel + MongoDB Atlas deployment

The UI, FastAPI backend, and real CPU ONNX inference deploy as **one Vercel project**.
MongoDB Atlas is an external managed database, not another copy of this application.
The FastAPI function connects to Atlas directly using a server-side `MONGODB_URI`.

Do not create a second Vercel project for the backend. A second project would require
cross-origin configuration, another public API boundary, two deployments, and an extra
network hop. It provides no benefit while FastAPI already owns the pages and `/api/*`.

## Production architecture

```text
Browser -> one Vercel domain -> FastAPI Python Function -> MongoDB Atlas
                                  |
                                  +-> bundled model.onnx / ONNX Runtime CPU
```

- `api/index.py` exports the FastAPI ASGI application.
- `data/export/model.onnx` is bundled and verified by SHA-256 before inference.
- `requirements.txt` includes ONNX Runtime, OpenCV, and PyMongo. Centreline
  skeletonization is implemented locally to keep scikit-image/SciPy out of the bundle.
- MongoDB stores inspection documents, embedded regions, batch sessions, reference
  records, source images, and overlays.
- An empty MongoDB database is bootstrapped idempotently from application profile,
  model configuration, and the bundled coverage-metrics JSON. Vercel does not need a
  SQLite database.
- No MongoDB credential is stored in Git or `vercel.json`.

## 1. Create MongoDB Atlas

1. Create or sign in to a MongoDB Atlas account.
2. Create a project and an M0/Flex or larger cluster.
3. Under **Database Access**, create a dedicated application user. Give it
   `readWrite` access to the `vision404` database; do not reuse your Atlas account.
4. Use a long generated password. URL-encode special characters if manually inserting
   the password into a connection URI.
5. Under **Network Access**, allow connections from Vercel. Vercel deployments use
   dynamic outbound addresses; the standard Atlas/Vercel integration uses
   `0.0.0.0/0`. Authentication and TLS still apply. For stricter production networking,
   use Vercel Secure Compute/static egress and allow only those addresses.
6. Choose **Connect > Drivers > Python** and copy the `mongodb+srv://...` URI.
7. Ensure the URI names or is paired with the database `vision404`.

Never paste the URI into source code, Git, screenshots, or chat messages.

## 2. Prepare and test the repository

From the application root:

```powershell
python -m venv .venv-app
.\.venv-app\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

Confirm the model identity:

```powershell
Get-FileHash data\export\model.onnx -Algorithm SHA256
```

Expected SHA-256:

```text
DF411260E21EC6361E97D4754B0C3F6920B7F5C2F6EC32C034CEF17C3576B42D
```

Review and commit the deployment files and model. The model was previously ignored,
so explicitly verify it is staged:

```powershell
git add .gitignore .vercelignore vercel.json api app docs tests
git add requirements.txt requirements-dev.txt README.md .env.example
git add -f data/export/model.onnx
git status
git commit -m "Deploy real model with MongoDB persistence on Vercel"
git push
```

Do not add `.env`. Review the pre-existing `data/inspection.db` modification separately
before deciding whether it belongs in the commit.

## 3. Create the one Vercel project

1. In Vercel, select **Add New > Project** and import the Git repository.
2. If this application is nested, set Root Directory to
   `INDUSTRIAL-SURFACE-DEFECT-INSPECTION-SYSTEM`; otherwise leave it unchanged.
3. Use Framework Preset **Other**.
4. Leave Build Command and Output Directory empty.
5. In **Environment Variables**, add:

```text
MONGODB_URI=mongodb+srv://APP_USER:URL_ENCODED_PASSWORD@CLUSTER.mongodb.net/?retryWrites=true&w=majority
```

Apply it to Production and Preview (and Development only if you want `vercel dev` to
use Atlas). `MONGODB_DATABASE=vision404` and the non-secret model settings are already
in `vercel.json`.

6. Deploy. If you added the variable after the first deployment, redeploy; existing
   deployments do not acquire newly added values automatically.

The application intentionally refuses to start a real Vercel deployment without
`MONGODB_URI`, preventing an accidental fallback to ephemeral SQLite.

## 4. Verify

Open:

```text
https://YOUR-PROJECT.vercel.app/healthz
https://YOUR-PROJECT.vercel.app/status
https://YOUR-PROJECT.vercel.app/capture
https://YOUR-PROJECT.vercel.app/history
https://YOUR-PROJECT.vercel.app/analytics
```

Expected health response:

```json
{"status":"ok","provider":"real"}
```

On Status, confirm:

- Inference provider: real
- Model file/hash: verified
- Database: MongoDB Atlas
- Camera/station: registered

Upload a PNG or JPEG smaller than 4 MB, wait for CPU inference, then confirm the result
appears in History after refreshing or opening a new browser session. Source and
overlay images should also load after a cold start.

## Limits and troubleshooting

- Vercel Function request and response bodies are limited to 4.5 MB, so the application
  advertises a 4 MB upload ceiling in production.
- CPU inference can cold-start slowly. The function duration is set to 60 seconds;
  large images or batches can still time out.
- Batch work is synchronous on Vercel because background threads are not durable after
  a response. Keep bundled batches small.
- If deployment reports a bundle-size error, inspect native dependencies and Vercel's
  function output. Python functions currently have a 500 MB uncompressed bundle limit.
- `Model hash mismatch` means the committed artefact differs from `MODEL_SHA256`. Do
  not bypass it; update both only when intentionally deploying a new measured model.
- MongoDB connection timeouts usually mean the Atlas IP access list, URI credentials,
  database user permissions, or URL encoding is wrong.
- View runtime errors in the Vercel project under **Logs**.

## CLI deployment alternative

```powershell
npm install --global vercel
vercel login
vercel env add MONGODB_URI production
vercel env add MONGODB_URI preview
vercel
vercel --prod
```

Enter the URI only when the CLI prompts; do not put it on the command line because
shell history can retain it.
