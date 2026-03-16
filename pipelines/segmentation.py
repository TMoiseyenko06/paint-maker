"""
Wall segmentation using SegFormer (ADE20K).

Provides `segment_walls(img_rgb)` which returns a uint8 mask
(0 = not-wall, 255 = wall) at the original image resolution.
"""

import threading
import numpy as np
import cv2
from PIL import Image
from config import SEGMENTATION_MODEL

_model = None
_processor = None
_lock = threading.Lock()

# ADE20K label names we treat as paintable wall surfaces
_WALL_LABELS = {"wall"}


def _load():
    global _model, _processor
    with _lock:
        if _model is None:
            from transformers import (
                AutoImageProcessor,
                SegformerForSemanticSegmentation,
            )

            _processor = AutoImageProcessor.from_pretrained(SEGMENTATION_MODEL)
            _model = SegformerForSemanticSegmentation.from_pretrained(
                SEGMENTATION_MODEL
            )
            _model.eval()
    return _processor, _model


def segment_walls(img_rgb: np.ndarray) -> np.ndarray:
    """Return a wall mask (uint8, 0/255) at the original resolution."""
    import torch
    import torch.nn.functional as F

    processor, model = _load()
    h, w = img_rgb.shape[:2]

    inputs = processor(images=Image.fromarray(img_rgb), return_tensors="pt")
    with torch.no_grad():
        logits = model(**inputs).logits  # (1, C, H', W')

    up = F.interpolate(logits, size=(h, w), mode="bilinear", align_corners=False)
    seg = up.argmax(dim=1)[0].cpu().numpy()

    wall_ids = {
        k for k, v in model.config.id2label.items() if v.lower() in _WALL_LABELS
    }
    mask = np.zeros((h, w), dtype=np.uint8)
    for wid in wall_ids:
        mask[seg == wid] = 255

    # Clean up
    kern_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    kern_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kern_close)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kern_open)
    return mask
