import io
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError

from detector import Detector
from model_store import ModelStoreError, ensure_model

BASE_DIR = Path(__file__).parent
MODEL_PATH = Path(os.getenv("MODEL_PATH", BASE_DIR / "models" / "model.onnx"))
LABELS_PATH = Path(os.getenv("LABELS_PATH", BASE_DIR / "models" / "labels.txt"))
MODEL_URL = os.getenv("MODEL_URL") or None  # may contain a secret SAS token
MODEL_SHA256 = os.getenv("MODEL_SHA256") or None
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
MAX_UPLOAD_MB = 10

state = {"detector": None, "model_sha256": None, "model_error": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        state["model_sha256"] = ensure_model(MODEL_PATH, MODEL_URL, MODEL_SHA256)
        if state["model_sha256"]:
            state["detector"] = Detector(MODEL_PATH, LABELS_PATH)
        else:
            state["model_error"] = "model not found; run export_model.py or set MODEL_URL"
    except Exception as e:  # keep the API up so /health can explain what is wrong
        state["model_error"] = str(e)
    if state["model_error"]:
        print(f"WARNING: model not loaded: {state['model_error']}")
    yield


app = FastAPI(title="Detection API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": state["detector"] is not None,
        "model_sha256": state["model_sha256"],
        "model_error": state["model_error"],
    }


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    if state["detector"] is None:
        raise HTTPException(503, "Model not loaded. Run: python export_model.py")

    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Image too large (max {MAX_UPLOAD_MB} MB)")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "File is not a valid image")

    start = time.perf_counter()
    result = state["detector"].detect(img)
    result["inference_ms"] = round((time.perf_counter() - start) * 1000, 1)
    return result
