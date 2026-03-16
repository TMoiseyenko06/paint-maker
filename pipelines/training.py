"""
ControlNet fine-tuning pipeline for paint-job datasets.

Dataset layout
--------------
dataset_dir/
    before/          # room photos BEFORE painting
        room_001.jpg
    after/           # same rooms AFTER painting
        room_001.jpg
    prompts.json     # optional {"room_001": "room with sage green walls"}

Training trains *only* the ControlNet weights (UNet, VAE, and text encoder
are frozen) using canny edges of the "before" images as the conditioning
signal and the "after" images as reconstruction targets.
"""

import json
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from torch.utils.data import Dataset, DataLoader

from config import (
    SD_BASE_MODEL,
    CONTROLNET_MODEL,
    MODEL_DIR,
    DEFAULT_TRAIN_LR,
    DEFAULT_TRAIN_EPOCHS,
    DEFAULT_TRAIN_BATCH,
    DEFAULT_TRAIN_RESOLUTION,
    DEFAULT_SAVE_EVERY,
)

# ── Shared training state ────────────────────────────────────────────────────
_status: dict = {
    "state": "idle",       # idle | preparing | training | saving | completed | failed
    "epoch": 0,
    "total_epochs": 0,
    "step": 0,
    "loss": 0.0,
    "progress": 0.0,
    "message": "",
    "model_name": "",
}
_thread: threading.Thread | None = None
_stop_event = threading.Event()


def get_status() -> dict:
    return dict(_status)


def is_running() -> bool:
    return _status["state"] in ("preparing", "training", "saving")


def request_stop():
    _stop_event.set()


# ── Dataset ──────────────────────────────────────────────────────────────────

class PaintJobDataset(Dataset):
    """Paired before/after paint-job images."""

    def __init__(self, data_dir: str, resolution: int = 512):
        self.resolution = resolution
        self.pairs = self._find_pairs(Path(data_dir))

    @staticmethod
    def _find_pairs(root: Path) -> list[dict]:
        before = root / "before"
        after = root / "after"
        if not before.is_dir() or not after.is_dir():
            return []

        exts = {".jpg", ".jpeg", ".png", ".webp"}
        pairs = []
        for bf in sorted(before.iterdir()):
            if bf.suffix.lower() not in exts:
                continue
            af = after / bf.name
            if af.exists():
                pairs.append({"before": str(bf), "after": str(af), "stem": bf.stem})

        # Optional per-image prompts
        pf = root / "prompts.json"
        prompts = json.loads(pf.read_text()) if pf.exists() else {}
        default_prompt = "a room with freshly painted walls, interior photography"
        for p in pairs:
            p["prompt"] = prompts.get(p["stem"], default_prompt)
        return pairs

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, idx):
        p = self.pairs[idx]
        before = Image.open(p["before"]).convert("RGB").resize(
            (self.resolution, self.resolution)
        )
        after = Image.open(p["after"]).convert("RGB").resize(
            (self.resolution, self.resolution)
        )

        # Canny conditioning from 'before' image
        arr = np.array(before)
        canny = cv2.Canny(arr, 80, 200)
        canny3 = np.stack([canny] * 3, axis=-1)

        cond = torch.from_numpy(canny3).float().permute(2, 0, 1) / 255.0
        target = torch.from_numpy(np.array(after)).float().permute(2, 0, 1) / 127.5 - 1.0

        return {"conditioning": cond, "target": target, "prompt": p["prompt"]}


# ── Validation ───────────────────────────────────────────────────────────────

def validate_dataset(dataset_dir: str) -> dict:
    """Check dataset structure and return summary."""
    root = Path(dataset_dir)
    before = root / "before"
    after = root / "after"

    result = {"valid": False, "pairs": 0, "errors": []}

    if not root.is_dir():
        result["errors"].append(f"Directory not found: {dataset_dir}")
        return result
    if not before.is_dir():
        result["errors"].append("Missing 'before/' subdirectory")
    if not after.is_dir():
        result["errors"].append("Missing 'after/' subdirectory")
    if result["errors"]:
        return result

    ds = PaintJobDataset(dataset_dir)
    result["pairs"] = len(ds)
    if len(ds) == 0:
        result["errors"].append(
            "No matching image pairs found. "
            "Ensure before/ and after/ contain files with the same names."
        )
    else:
        result["valid"] = True

    return result


# ── Training loop ────────────────────────────────────────────────────────────

def start_training(config: dict):
    """Launch training in a background thread. `config` keys:

    - dataset_dir (str): path to dataset
    - model_name (str): name for the output model
    - epochs (int)
    - learning_rate (float)
    - batch_size (int)
    - resolution (int)
    - save_every (int)
    - mixed_precision (str): "fp16" | "bf16" | "no"
    """
    global _thread
    if is_running():
        raise RuntimeError("Training is already in progress.")

    _stop_event.clear()
    _thread = threading.Thread(target=_train_loop, args=(config,), daemon=True)
    _thread.start()


def _train_loop(config: dict):
    global _status
    try:
        _status.update(state="preparing", message="Loading models…", progress=0)

        from diffusers import ControlNetModel, DDPMScheduler, AutoencoderKL, UNet2DConditionModel
        from transformers import CLIPTextModel, CLIPTokenizer

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float32  # training always in fp32 for stability

        model_name = config.get("model_name", f"paint-model-{int(time.time())}")
        output_dir = os.path.join(MODEL_DIR, model_name)
        os.makedirs(output_dir, exist_ok=True)
        _status["model_name"] = model_name

        epochs = config.get("epochs", DEFAULT_TRAIN_EPOCHS)
        lr = config.get("learning_rate", DEFAULT_TRAIN_LR)
        batch_size = config.get("batch_size", DEFAULT_TRAIN_BATCH)
        resolution = config.get("resolution", DEFAULT_TRAIN_RESOLUTION)
        save_every = config.get("save_every", DEFAULT_SAVE_EVERY)

        _status["total_epochs"] = epochs

        # ── Load pre-trained components ──────────────────────────────────
        tokenizer = CLIPTokenizer.from_pretrained(SD_BASE_MODEL, subfolder="tokenizer")
        text_encoder = CLIPTextModel.from_pretrained(
            SD_BASE_MODEL, subfolder="text_encoder", torch_dtype=dtype
        ).to(device)
        vae = AutoencoderKL.from_pretrained(
            SD_BASE_MODEL, subfolder="vae", torch_dtype=dtype
        ).to(device)
        unet = UNet2DConditionModel.from_pretrained(
            SD_BASE_MODEL, subfolder="unet", torch_dtype=dtype
        ).to(device)
        controlnet = ControlNetModel.from_pretrained(
            CONTROLNET_MODEL, torch_dtype=dtype
        ).to(device)
        scheduler = DDPMScheduler.from_pretrained(
            SD_BASE_MODEL, subfolder="scheduler"
        )

        # Freeze everything except ControlNet
        text_encoder.requires_grad_(False)
        vae.requires_grad_(False)
        unet.requires_grad_(False)
        controlnet.train()

        optimizer = torch.optim.AdamW(controlnet.parameters(), lr=lr)

        # ── Dataset ──────────────────────────────────────────────────────
        dataset = PaintJobDataset(config["dataset_dir"], resolution=resolution)
        if len(dataset) == 0:
            _status.update(state="failed", message="Dataset is empty.")
            return

        loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, num_workers=0)
        total_steps = epochs * len(loader)
        _status.update(state="training", message="Training started.")

        # ── Loop ─────────────────────────────────────────────────────────
        global_step = 0
        for epoch in range(epochs):
            if _stop_event.is_set():
                _status.update(state="completed", message="Training stopped by user.")
                break

            epoch_loss = 0.0
            for batch in loader:
                if _stop_event.is_set():
                    break

                conditioning = batch["conditioning"].to(device)
                target = batch["target"].to(device)
                prompts = batch["prompt"]

                # Encode target → latents
                with torch.no_grad():
                    latents = vae.encode(target).latent_dist.sample()
                    latents = latents * vae.config.scaling_factor

                # Sample noise + timesteps
                noise = torch.randn_like(latents)
                ts = torch.randint(
                    0,
                    scheduler.config.num_train_timesteps,
                    (latents.shape[0],),
                    device=device,
                ).long()
                noisy = scheduler.add_noise(latents, noise, ts)

                # Text embeddings
                tok = tokenizer(
                    prompts,
                    padding="max_length",
                    max_length=tokenizer.model_max_length,
                    truncation=True,
                    return_tensors="pt",
                ).input_ids.to(device)
                with torch.no_grad():
                    enc_hidden = text_encoder(tok)[0]

                # ControlNet → residuals
                down_res, mid_res = controlnet(
                    noisy, ts, encoder_hidden_states=enc_hidden,
                    controlnet_cond=conditioning, return_dict=False,
                )

                # UNet noise prediction
                pred = unet(
                    noisy, ts, encoder_hidden_states=enc_hidden,
                    down_block_additional_residuals=down_res,
                    mid_block_additional_residual=mid_res,
                ).sample

                loss = torch.nn.functional.mse_loss(pred, noise)
                loss.backward()
                optimizer.step()
                optimizer.zero_grad()

                global_step += 1
                epoch_loss += loss.item()
                _status.update(
                    epoch=epoch + 1,
                    step=global_step,
                    loss=round(loss.item(), 6),
                    progress=round(global_step / total_steps * 100, 1),
                )

            avg_loss = epoch_loss / max(len(loader), 1)
            _status["message"] = f"Epoch {epoch+1}/{epochs}  avg loss {avg_loss:.5f}"

            # Checkpoint
            if (epoch + 1) % save_every == 0:
                _status["state"] = "saving"
                cp = os.path.join(output_dir, f"checkpoint-{epoch+1}")
                controlnet.save_pretrained(cp)
                _status["state"] = "training"

        # Save final model
        _status.update(state="saving", message="Saving final model…")
        controlnet.save_pretrained(output_dir)

        # Save training config alongside the model
        meta = {**config, "final_loss": _status["loss"], "total_steps": global_step}
        with open(os.path.join(output_dir, "training_config.json"), "w") as f:
            json.dump(meta, f, indent=2)

        _status.update(
            state="completed",
            progress=100,
            message=f"Training complete. Model saved to {model_name}/",
        )
    except Exception as exc:
        _status.update(state="failed", message=str(exc))


# ── Model management ────────────────────────────────────────────────────────

def list_models() -> list[dict]:
    """Return metadata for every fine-tuned model."""
    models = []
    if not os.path.isdir(MODEL_DIR):
        return models
    for name in sorted(os.listdir(MODEL_DIR)):
        path = os.path.join(MODEL_DIR, name)
        if not os.path.isdir(path):
            continue
        info = {"name": name, "path": path}
        cfg = os.path.join(path, "training_config.json")
        if os.path.exists(cfg):
            with open(cfg) as f:
                info["config"] = json.load(f)
        models.append(info)
    return models


def delete_model(name: str) -> bool:
    import shutil

    path = os.path.join(MODEL_DIR, name)
    if os.path.isdir(path):
        shutil.rmtree(path)
        return True
    return False
