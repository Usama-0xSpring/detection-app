# Detection App (local)

React frontend + FastAPI backend + YOLOv8 (ONNX, CPU only).

```
detection-app/
├─ backend/    FastAPI + onnxruntime   (main.py, detector.py, export_model.py)
└─ frontend/   React + Vite            (src/App.jsx)
```

Needs: **Python 3.10–3.12** and **Node 18+** (Node 20 LTS recommended).

## 1. Backend (terminal 1)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1

# one-time: create the model file (downloads yolov8n.pt ~6 MB, exports to ONNX)
pip install -r requirements-export.txt
python export_model.py

# run the API
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
Check http://localhost:8000/health -> `{"status":"ok","model_loaded":true}`
Interactive docs: http://localhost:8000/docs

## 2. Frontend (terminal 2)

```powershell
cd frontend
npm install
npm run dev
```
Open http://localhost:5173, upload a photo (people, cars, chairs…), click Detect.

## 3. Tests

```powershell
cd backend
pip install -r requirements-dev.txt
pytest
```

## 4. Run with Docker (backend + frontend containers)

Needs Docker Desktop running. From the repo root, in PowerShell:

```powershell
# checksum of your local model (the container verifies the file against it)
$env:MODEL_SHA256 = (Get-FileHash backend\models\model.onnx -Algorithm SHA256).Hash.ToLower()

# build and start; the override file makes the container "download" your local model
docker compose -f docker-compose.yml -f docker-compose.local-model.yml up --build
```
Open http://localhost, upload an image. API health: http://localhost/api/health

Useful commands:

```powershell
docker compose ps                  # status and health of each container
docker compose logs -f backend     # watch the model download and verify
docker compose down                # stop (keeps the downloaded model volume)
docker compose down -v             # stop AND delete the model volume (forces a re-download)
docker images                      # check image sizes
```

To see a bad checksum rejected: `$env:MODEL_SHA256 = "0" * 64`, run `docker compose down -v`, then start again.
`/api/health` shows `model_loaded: false` with the reason, and `docker compose ps` shows the backend as unhealthy.

## 5. CI/CD pipeline (GitHub Actions -> Azure VM)

`.github/workflows/ci.yml` runs on every push:

```
backend tests ─┐
               ├─> docker build + smoke test ─> push images to GHCR ─> deploy to VM
frontend build ┘                                  (main only)           (main only)
```

- **Pull requests:** tests and the Docker smoke test only.
- **Push to `main`:** also pushes `detection-backend` / `detection-frontend` images to
  GHCR (tagged with the commit SHA and `latest`) and deploys them to the VM over SSH.
- The VM runs `docker-compose.prod.yml` (images from GHCR, no build). The backend
  downloads the model from `MODEL_URL` and checks `MODEL_SHA256`. The deploy job
  passes only when `/api/health` reports `model_loaded: true`.
- Re-run the pipeline by hand: Actions tab -> CI/CD -> Run workflow.

Secrets live in the GitHub environment `production` (Settings -> Environments):

| Secret | What it is |
|---|---|
| `VM_HOST` | VM public IP |
| `VM_USER` | SSH user (e.g. `azureuser`) |
| `VM_SSH_KEY` | private key matching a public key in the VM's `~/.ssh/authorized_keys` |
| `MODEL_URL` | read-only SAS URL of the model blob (expires; renew it) |
| `MODEL_SHA256` | checksum of that model file |

The VM also needs Docker installed and inbound ports 22 and 80 open.

## How the model works

1. `export_model.py` (run once) downloads pretrained `yolov8n.pt` (COCO: 80 everyday
   objects, NOT signatures) and exports `models/model.onnx` + `models/labels.txt`.
   PyTorch is only needed for this step.
2. On startup `main.py` creates a `Detector` (`detector.py`), which opens the ONNX
   file with `onnxruntime` on CPU.
3. For each upload: resize with padding to 640x640 -> run model -> keep boxes above
   25% confidence -> remove overlapping boxes (NMS) -> map back to original pixels.
4. The API returns JSON; the frontend draws the boxes over the image.

## Swapping in your own signature model later

```powershell
python export_model.py path\to\best.pt
```
That overwrites `models/model.onnx` and `models/labels.txt`. No code changes.

## Config (environment variables, all optional)

| Variable | Default | Where |
|---|---|---|
| `MODEL_PATH` | `backend/models/model.onnx` | backend |
| `LABELS_PATH` | `backend/models/labels.txt` | backend |
| `MODEL_URL` | _(unset)_ download the model here if the file is missing (https; may be a secret SAS URL) | backend |
| `MODEL_SHA256` | _(unset)_ expected checksum; **required** when `MODEL_URL` is set | backend |
| `CORS_ORIGINS` | `http://localhost:5173` | backend |
| `VITE_API_URL` | `http://localhost:8000` | frontend (build time) |
