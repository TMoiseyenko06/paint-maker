import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "data", "uploads")
DATASET_DIR = os.path.join(BASE_DIR, "data", "datasets")
MODEL_DIR = os.path.join(BASE_DIR, "data", "models")

# Create dirs on import
for d in (UPLOAD_DIR, DATASET_DIR, MODEL_DIR):
    os.makedirs(d, exist_ok=True)

# ── HuggingFace model IDs ────────────────────────────────────────────────────
SD_BASE_MODEL = "runwayml/stable-diffusion-v1-5"
SD_INPAINT_MODEL = "runwayml/stable-diffusion-inpainting"
CONTROLNET_MODEL = "lllyasviel/sd-controlnet-canny"
SEGMENTATION_MODEL = "nvidia/segformer-b2-finetuned-ade-512-512"

# ── Inference defaults ────────────────────────────────────────────────────────
DEFAULT_STEPS = 30
DEFAULT_GUIDANCE = 7.5
DEFAULT_CONTROLNET_SCALE = 0.7
DEFAULT_STRENGTH = 0.85
MAX_IMAGE_DIM = 768

# ── Training defaults ────────────────────────────────────────────────────────
DEFAULT_TRAIN_LR = 1e-5
DEFAULT_TRAIN_EPOCHS = 20
DEFAULT_TRAIN_BATCH = 1
DEFAULT_TRAIN_RESOLUTION = 512
DEFAULT_SAVE_EVERY = 5
