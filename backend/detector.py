"""Model wrapper: the ONLY file that knows how the ONNX model is loaded and run.

To use your own signature model later, export it to ONNX (see export_model.py),
drop it at models/model.onnx with a matching models/labels.txt. No code changes.

Expected ONNX output (standard YOLOv8 export): shape (1, 4 + num_classes, N)
where the first 4 values are cx, cy, w, h in the 640x640 letterboxed input.
"""
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps


def iou_one_vs_many(box, boxes):
    x1 = np.maximum(box[0], boxes[:, 0])
    y1 = np.maximum(box[1], boxes[:, 1])
    x2 = np.minimum(box[2], boxes[:, 2])
    y2 = np.minimum(box[3], boxes[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = (box[2] - box[0]) * (box[3] - box[1])
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    return inter / (area + areas - inter + 1e-9)


def nms(boxes, scores, iou_thr):
    """Plain numpy non-max suppression. Returns indices to keep."""
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        order = rest[iou_one_vs_many(boxes[i], boxes[rest]) < iou_thr]
    return keep


def decode(output, ratio, pad_x, pad_y, width, height, conf_thr=0.25, iou_thr=0.45):
    """Turn raw model output into [(x1, y1, x2, y2, score, class_id), ...] in
    ORIGINAL image pixels."""
    preds = output[0].T  # (N, 4 + num_classes)
    class_scores = preds[:, 4:]
    class_ids = class_scores.argmax(axis=1)
    scores = class_scores.max(axis=1)

    mask = scores >= conf_thr
    preds, class_ids, scores = preds[mask], class_ids[mask], scores[mask]
    if not len(scores):
        return []

    cx, cy, w, h = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    # undo letterbox: remove padding, then undo resize
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pad_x) / ratio
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - pad_y) / ratio
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, width)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, height)

    keep = nms(boxes, scores, iou_thr)
    return [(*boxes[i], scores[i], int(class_ids[i])) for i in keep]


class Detector:
    def __init__(self, model_path, labels_path, input_size=640):
        self.input_size = input_size
        self.session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name
        self.labels = [
            line.strip()
            for line in Path(labels_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _preprocess(self, img):
        s = self.input_size
        w, h = img.size
        ratio = min(s / w, s / h)
        nw, nh = round(w * ratio), round(h * ratio)
        canvas = Image.new("RGB", (s, s), (114, 114, 114))
        pad_x, pad_y = (s - nw) // 2, (s - nh) // 2
        canvas.paste(img.resize((nw, nh), Image.BILINEAR), (pad_x, pad_y))
        arr = np.asarray(canvas, dtype=np.float32) / 255.0
        return arr.transpose(2, 0, 1)[None], ratio, pad_x, pad_y

    def detect(self, img, conf_thr=0.25):
        img = ImageOps.exif_transpose(img).convert("RGB")
        width, height = img.size
        tensor, ratio, pad_x, pad_y = self._preprocess(img)
        output = self.session.run(None, {self.input_name: tensor})[0]
        results = decode(output, ratio, pad_x, pad_y, width, height, conf_thr)
        return {
            "width": width,
            "height": height,
            "detections": [
                {
                    "label": self.labels[c] if c < len(self.labels) else f"class_{c}",
                    "confidence": round(float(score), 4),
                    "box": [round(float(v), 1) for v in (x1, y1, x2, y2)],
                }
                for x1, y1, x2, y2, score, c in results
            ],
        }
