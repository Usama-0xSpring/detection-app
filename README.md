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
