"""ONE-TIME setup: download a pretrained YOLOv8 model and export it to ONNX.

    pip install -r requirements-export.txt
    python export_model.py                # yolov8n (COCO, 80 everyday objects)
    python export_model.py best.pt        # LATER: your own trained signature model

Writes models/model.onnx and models/labels.txt. The running API only needs
onnxruntime (small); PyTorch/ultralytics are used here and nowhere else.
"""
import shutil
import sys
from pathlib import Path

from ultralytics import YOLO

weights = sys.argv[1] if len(sys.argv) > 1 else "yolov8n.pt"  # auto-downloaded
out_dir = Path(__file__).parent / "models"
out_dir.mkdir(exist_ok=True)

model = YOLO(weights)
onnx_path = model.export(format="onnx", imgsz=640, opset=12, simplify=False)
shutil.copy(onnx_path, out_dir / "model.onnx")
(out_dir / "labels.txt").write_text(
    "\n".join(model.names[i] for i in sorted(model.names)), encoding="utf-8"
)
print(f"Done: {out_dir / 'model.onnx'} ({len(model.names)} classes)")
