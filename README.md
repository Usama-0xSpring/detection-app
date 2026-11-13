# Detection App: React + FastAPI + YOLOv8n with CI/CD on Azure

A small object-detection web app (React frontend, FastAPI backend, YOLOv8n model running on CPU) used to teach a complete deployment workflow: a push to `main` is tested, built into Docker images, and deployed automatically to an Azure VM, with the model fetched from Azure Blob Storage and verified by checksum.

> The default model is pretrained on everyday objects (COCO), **not signatures**. It is a stand-in; your own model plugs in without code changes (see [Swap in your own model](#swap-in-your-own-model)).

## Documentation

| Document | What it is |
| --- | --- |
| [RUNBOOK.md](RUNBOOK.md) | Step-by-step guide from the local build to Azure, with every command and a troubleshooting table |
| [docs/Detection-App-Runbook.docx](docs/Detection-App-Runbook.docx) | The same runbook as a Word document, for sharing and printing |
| [architecture.drawio](architecture.drawio) | Editable architecture diagram with animated arrows (open it at app.diagrams.net) |

## How it works

```
push to main
   |
   v
GitHub Actions (.github/workflows/ci.yml)
   backend tests --+
                   +--> docker build + smoke test --> push images to GHCR --> deploy to VM
   frontend build -+                                    (main only)           (main only)

Azure VM (docker compose)
   nginx + React (port 80)  --/api-->  FastAPI + onnxruntime (port 8000)
                                              |
                              model downloaded on first start from
                              Azure Blob Storage (read-only SAS URL)
                              and verified against MODEL_SHA256
```

| Part | Choice |
| --- | --- |
| Frontend | React (Vite), served by nginx |
| Backend | FastAPI + onnxruntime (CPU only, no PyTorch at runtime) |
| Model | YOLOv8n exported to ONNX (about 12.8 MB) |
| Model storage | Azure Blob Storage with a read-only SAS URL |
| Containers | Docker and Docker Compose |
| Registry | GitHub Container Registry (GHCR) |
| CI/CD | GitHub Actions, deploying over SSH |
| Host | One Azure VM (Ubuntu, 2 vCPU, 4 GiB) |

## Repository layout

```
detection-app/
├─ backend/        FastAPI + onnxruntime: main.py, detector.py, model_store.py, export_model.py, tests/
├─ frontend/       React + Vite: src/App.jsx, nginx.conf, Dockerfile
├─ docs/           Word version of the runbook
├─ docker-compose.yml              build and run locally
├─ docker-compose.local-model.yml  test override: "download" the model from a local file
├─ docker-compose.prod.yml         used on the VM: runs images from GHCR
├─ architecture.drawio             architecture diagram
├─ RUNBOOK.md                      full step-by-step guide
└─ .github/workflows/ci.yml        the CI/CD pipeline
```

## Quick start (Windows, PowerShell)

Needs **Python 3.10-3.12**, **Node 18+** (Node 20 LTS recommended) and, for the container route, Docker Desktop.

### 1. Backend (terminal 1)

Calling the venv's Python directly (`.venv\Scripts\python.exe -m ...`) avoids broken launchers if the folder is ever renamed.

```powershell
cd backend
python -m venv .venv

# one-time: create models\model.onnx (downloads yolov8n.pt, ~6 MB, exports to ONNX; PyTorch is large)
.venv\Scripts\python.exe -m pip install -r requirements-export.txt
.venv\Scripts\python.exe export_model.py

# run the API
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Check http://localhost:8000/health (expect `"model_loaded":true`). Interactive API docs: http://localhost:8000/docs.

### 2. Frontend (terminal 2)

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, upload a photo and click **Detect**. Boxes and labels are drawn over the image.

### 3. Tests

```powershell
cd backend
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

No model file is needed for the tests.

### 4. Run with Docker (backend + frontend containers)

```powershell
# checksum of your local model (the container verifies the file against it)
$env:MODEL_SHA256 = (Get-FileHash backend\models\model.onnx -Algorithm SHA256).Hash.ToLower()

# build and start; the override file makes the container "download" your local model
docker compose -f docker-compose.yml -f docker-compose.local-model.yml up --build
```

Open http://localhost and upload an image. Health: http://localhost/api/health. If port 80 is busy, change `"80:80"` to `"8080:80"` in `docker-compose.yml`.

```powershell
docker compose ps                  # status and health of each container
docker compose logs -f backend     # watch the model download and verify
docker compose exec backend bash   # shell inside the backend container
docker compose down                # stop (keeps the downloaded model volume)
docker compose down -v             # stop and delete the model volume (forces a re-download)
```

To see a bad checksum rejected: `$env:MODEL_SHA256 = "0" * 64`, run `docker compose down -v`, then start again. `/api/health` shows `model_loaded: false` with the reason, and `docker compose ps` shows the backend as unhealthy.

## The model: download at startup

The model file is **not** in Git or in the Docker image. `backend/model_store.py` makes sure it exists when the app starts:

| Situation at startup | What the app does |
| --- | --- |
| File exists, no checksum set | Uses it as is (your laptop) |
| File exists and matches `MODEL_SHA256` | Uses it, no download |
| File exists but differs, `MODEL_URL` set | Replaces it (a new model version) |
| File missing, `MODEL_URL` set | Downloads, verifies, saves, loads |
| Checksum wrong | Rejects the file; `/health` shows `model_loaded: false` and the reason; `/predict` returns 503 |
| `MODEL_URL` set without `MODEL_SHA256` | Refused: the checksum is required |
| Plain `http://` to a remote host | Refused: only https (or http to localhost) |

- `MODEL_URL` is where to download from. A SAS URL is a **secret**.
- `MODEL_SHA256` is the expected fingerprint. It is not secret; it proves the file is the exact one you meant.
- SAS tokens are stripped from every error message. Get a checksum with:

```powershell
(Get-FileHash backend\models\model.onnx -Algorithm SHA256).Hash.ToLower()
```

This code only **downloads**. Uploading the model to Blob is a separate step (see the runbook).

### How inference works
1. On startup `main.py` creates a `Detector` (`detector.py`), which opens the ONNX file with onnxruntime on CPU.
2. For each upload: resize with padding to 640x640, run the model, keep boxes above 25% confidence, remove overlapping boxes (NMS), and map back to original pixels.
3. The API returns JSON; the frontend draws the boxes.

### Swap in your own model

```powershell
python export_model.py path\to\best.pt
```

That writes a new `models/model.onnx` and `models/labels.txt`. No code changes. For a deployed app, upload the new file to Blob under a new path (for example `v2/model.onnx`), update the `MODEL_URL` and `MODEL_SHA256` secrets, and re-run the workflow. No image rebuild is needed, and rolling back means re-running with the previous values.

## CI/CD pipeline (GitHub Actions to Azure VM)

`.github/workflows/ci.yml` is the whole pipeline; GitHub finds it automatically.

| Job | What it does | Runs on |
| --- | --- | --- |
| Backend tests | Python 3.11, `pytest` | every push and pull request |
| Frontend build | Node 20, `npm ci`, `npm run build` | every push and pull request |
| Docker build and smoke test | Builds both images, starts the stack, checks `/api/health` through nginx | every push and pull request |
| Push images to GHCR | Pushes `detection-backend` and `detection-frontend`, tagged with the commit SHA and `latest` | `main` only |
| Deploy to Azure VM | Copies `docker-compose.prod.yml`, writes `.env` from secrets, pulls images, restarts, waits for `model_loaded: true` | `main` only |

- **Pull requests** never deploy. There is no manual approval gate; a push to `main` deploys automatically.
- **The VM does not poll the registry.** The deploy job writes the new image version into a `.env` file on the VM and tells it to run `docker compose pull` and `up -d`.
- The smoke test has no model (it is not in Git), so it proves the images build and nginx reaches FastAPI; real inference is confirmed by the deploy job's health check.
- Re-run the pipeline by hand: Actions tab, CI/CD, **Run workflow**.

### Secrets

Stored in the GitHub environment `production` (Settings, Environments):

| Secret | What it is |
| --- | --- |
| `VM_HOST` | VM public IP |
| `VM_USER` | SSH user (for example `azureuser`) |
| `VM_SSH_KEY` | Private key matching a public key in the VM's `~/.ssh/authorized_keys` |
| `MODEL_URL` | Read-only SAS URL of the model blob (it expires; renew it) |
| `MODEL_SHA256` | Checksum of that model file |

The VM also needs Docker installed and inbound ports 22 and 80 open. Never commit secrets, keys or SAS URLs.

## Configuration (environment variables, all optional)

| Variable | Default | Where |
| --- | --- | --- |
| `MODEL_PATH` | `backend/models/model.onnx` | backend |
| `LABELS_PATH` | `backend/models/labels.txt` | backend |
| `MODEL_URL` | _(unset)_ download the model here if the file is missing (https; may be a secret SAS URL) | backend |
| `MODEL_SHA256` | _(unset)_ expected checksum; **required** when `MODEL_URL` is set | backend |
| `CORS_ORIGINS` | `http://localhost:5173` | backend |
| `VITE_API_URL` | `http://localhost:8000` | frontend (build time) |

## Cost and cleanup

- A demo on a 2 vCPU / 4 GiB B-series VM costs about $0.04 per hour. Use the Azure free trial or Azure for Students, and **never click Upgrade** on a trial.
- A stopped VM still bills for compute; a deallocated VM bills only disk and IP; deleting the resource group bills nothing.
- When you are done, delete everything:

```powershell
az group delete -n rg-demo --yes --no-wait
```

## Troubleshooting

The runbook has a table of the problems hit while building this (failed fetch, busy ports, unavailable VM sizes, SSH key issues, expired SAS links, and more) with a fix for each: see [RUNBOOK.md](RUNBOOK.md).

## Limits and next steps

- The site is served over plain HTTP; HTTPS needs a domain name.
- Monitoring is basic: Actions logs, `docker compose logs`, the Azure portal's VM metrics and a budget alert.
- SSH password login should be turned off once key login works.
- For very large or GPU models, consider a separate model service or a managed endpoint.
