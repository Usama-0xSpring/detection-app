"""Small tests that need no model file, so they can run in CI later."""
import sys
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from detector import decode  # noqa: E402
from main import app  # noqa: E402


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_predict_rejects_non_image():
    with TestClient(app) as client:
        r = client.post("/predict", files={"file": ("x.txt", b"hello", "text/plain")})
        assert r.status_code in (400, 503)  # 503 if no model file present


def test_decode_finds_box_and_maps_to_original_pixels():
    # one fake detection: centre (320,320), 100x50, class 1 score 0.9, no padding, ratio 1
    out = np.zeros((1, 6, 3), dtype=np.float32)
    out[0, :, 0] = [320, 320, 100, 50, 0.1, 0.9]
    boxes = decode(out, ratio=1.0, pad_x=0, pad_y=0, width=640, height=640)
    assert len(boxes) == 1
    x1, y1, x2, y2, score, cls = boxes[0]
    assert (round(x1), round(y1), round(x2), round(y2)) == (270, 295, 370, 345)
    assert cls == 1
