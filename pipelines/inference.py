"""
ControlNet-guided room-recolouring pipeline.

Uses Stable Diffusion inpainting + ControlNet (canny edges) to repaint
only the wall regions detected by the segmentation model.
"""

import threading
import numpy as np
import cv2
from PIL import Image

from config import (
    SD_INPAINT_MODEL,
    CONTROLNET_MODEL,
    DEFAULT_STEPS,
    DEFAULT_GUIDANCE,
    DEFAULT_CONTROLNET_SCALE,
    DEFAULT_STRENGTH,
    MAX_IMAGE_DIM,
)
from pipelines.segmentation import segment_walls

_pipe = None
_lock = threading.Lock()


def _load_pipeline(controlnet_path: str | None = None):
    """Lazy-load the SD + ControlNet inpainting pipeline (thread-safe)."""
    global _pipe
    with _lock:
        if _pipe is not None:
            return _pipe

        import torch
        from diffusers import (
            ControlNetModel,
            StableDiffusionControlNetInpaintPipeline,
        )

        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        cn_id = controlnet_path or CONTROLNET_MODEL

        controlnet = ControlNetModel.from_pretrained(cn_id, torch_dtype=dtype)
        _pipe = StableDiffusionControlNetInpaintPipeline.from_pretrained(
            SD_INPAINT_MODEL,
            controlnet=controlnet,
            torch_dtype=dtype,
            safety_checker=None,
        )

        if torch.cuda.is_available():
            _pipe.enable_model_cpu_offload()
            try:
                _pipe.enable_xformers_memory_efficient_attention()
            except Exception:
                pass
        else:
            _pipe.to("cpu")

    return _pipe


def reload_pipeline(controlnet_path: str | None = None):
    """Force-reload the pipeline (e.g. after fine-tuning a new model)."""
    global _pipe
    _pipe = None
    return _load_pipeline(controlnet_path)


def _canny(img_rgb: np.ndarray, low: int = 80, high: int = 200) -> Image.Image:
    """Extract Canny edges and return as a PIL image."""
    gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, low, high)
    return Image.fromarray(np.stack([edges] * 3, axis=-1))


def _fit_dim(val: int, limit: int = MAX_IMAGE_DIM, multiple: int = 8) -> int:
    """Clamp *val* to *limit* and round to nearest *multiple*."""
    val = min(val, limit)
    return (val // multiple) * multiple


def paint_room(
    image: np.ndarray | Image.Image,
    color_info: dict,
    *,
    controlnet_path: str | None = None,
    num_steps: int = DEFAULT_STEPS,
    guidance: float = DEFAULT_GUIDANCE,
    controlnet_scale: float = DEFAULT_CONTROLNET_SCALE,
    strength: float = DEFAULT_STRENGTH,
) -> Image.Image:
    """
    Repaint the walls in *image* with the Sherwin-Williams colour
    described by *color_info*.

    Parameters
    ----------
    image : RGB array or PIL Image
    color_info : dict with ``name``, ``hex``, ``rgb`` keys
    controlnet_path : optional path to a fine-tuned ControlNet checkpoint

    Returns
    -------
    PIL.Image  — the repainted room
    """
    pipe = _load_pipeline(controlnet_path)

    if isinstance(image, np.ndarray):
        pil_img = Image.fromarray(image)
        img_rgb = image
    else:
        pil_img = image.convert("RGB")
        img_rgb = np.array(pil_img)

    # Resize to pipeline-friendly dims
    ow, oh = pil_img.size
    w = _fit_dim(ow)
    h = _fit_dim(oh)
    pil_resized = pil_img.resize((w, h), Image.LANCZOS)
    rgb_resized = np.array(pil_resized)

    # 1. Wall mask  (uint8 0/255)
    mask = segment_walls(rgb_resized)
    mask_pil = Image.fromarray(mask).convert("RGB")

    # 2. Canny control image
    canny_pil = _canny(rgb_resized)

    # 3. Prompt
    cname = color_info["name"].lower()
    chex = color_info["hex"]
    prompt = (
        f"a room with {cname} painted walls, hex colour {chex}, "
        "professional interior photography, realistic lighting, high quality, 8k"
    )
    negative = (
        "cartoon, illustration, painting, drawing, sketch, distorted, "
        "blurry, low quality, watermark, text"
    )

    # 4. Run pipeline
    result = pipe(
        prompt=prompt,
        negative_prompt=negative,
        image=pil_resized,
        mask_image=mask_pil,
        control_image=canny_pil,
        num_inference_steps=num_steps,
        guidance_scale=guidance,
        controlnet_conditioning_scale=controlnet_scale,
        strength=strength,
    ).images[0]

    # 5. Up-scale back to original size
    if (w, h) != (ow, oh):
        result = result.resize((ow, oh), Image.LANCZOS)

    return result
