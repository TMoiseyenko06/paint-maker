"""PaintViz — Sherwin-Williams Room Colour Visualizer with ControlNet."""

import io
import os
import json
import shutil
import base64
import uuid

import numpy as np
from PIL import Image
from flask import Flask, request, jsonify, render_template, Response
from flask_cors import CORS

from config import UPLOAD_DIR, DATASET_DIR, MODEL_DIR
from pipelines import color_lookup
from pipelines import training as train_mod

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64 MB

# ── Helpers ──────────────────────────────────────────────────────────────────

def _b64_to_pil(data_url: str) -> Image.Image:
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(data_url))).convert("RGB")


def _pil_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# ── Page routes ──────────────────────────────────────────────────────────────

@app.route("/")
def page_index():
    return render_template("index.html")


@app.route("/training")
def page_training():
    return render_template("training.html")


# ── Colour API ───────────────────────────────────────────────────────────────

@app.route("/api/color/<path:code>")
def api_color(code):
    c = color_lookup.lookup(code)
    if not c:
        return jsonify(error=f'Colour "{code}" not found.'), 404
    return jsonify(c)


# ── Paint (inference) API ────────────────────────────────────────────────────

@app.route("/api/paint", methods=["POST"])
def api_paint():
    """
    One-shot: detect walls + repaint with ControlNet.

    JSON body: { image: <b64>, color_code: "SW7029",
                 model_name?: str, steps?: int, guidance?: float,
                 controlnet_scale?: float, strength?: float }
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify(error="No JSON body."), 400

    img_b64 = data.get("image")
    code = (data.get("color_code") or "").strip()
    if not img_b64:
        return jsonify(error="Missing image."), 400
    if not code:
        return jsonify(error="Missing color_code."), 400

    color = color_lookup.lookup(code)
    if not color:
        return jsonify(error=f'Colour "{code}" not found.'), 404

    # Optional custom model
    model_name = data.get("model_name")
    cn_path = None
    if model_name:
        cn_path = os.path.join(MODEL_DIR, model_name)
        if not os.path.isdir(cn_path):
            return jsonify(error=f'Model "{model_name}" not found.'), 404

    try:
        from pipelines.inference import paint_room

        pil_img = _b64_to_pil(img_b64)
        result = paint_room(
            pil_img,
            color,
            controlnet_path=cn_path,
            num_steps=int(data.get("steps", 30)),
            guidance=float(data.get("guidance", 7.5)),
            controlnet_scale=float(data.get("controlnet_scale", 0.7)),
            strength=float(data.get("strength", 0.85)),
        )
        return jsonify(result=_pil_to_b64(result), color=color)
    except Exception as exc:
        return jsonify(error=str(exc)), 500


# ── Dataset management API ───────────────────────────────────────────────────

@app.route("/api/datasets", methods=["GET"])
def api_list_datasets():
    datasets = []
    if os.path.isdir(DATASET_DIR):
        for name in sorted(os.listdir(DATASET_DIR)):
            path = os.path.join(DATASET_DIR, name)
            if not os.path.isdir(path):
                continue
            info = train_mod.validate_dataset(path)
            info["name"] = name
            datasets.append(info)
    return jsonify(datasets)


@app.route("/api/datasets", methods=["POST"])
def api_create_dataset():
    name = (request.form.get("name") or "").strip()
    if not name:
        return jsonify(error="Missing dataset name."), 400
    name = name.replace(" ", "_").replace("/", "_")
    path = os.path.join(DATASET_DIR, name)
    os.makedirs(os.path.join(path, "before"), exist_ok=True)
    os.makedirs(os.path.join(path, "after"), exist_ok=True)
    return jsonify(name=name, path=path)


@app.route("/api/datasets/<name>/upload", methods=["POST"])
def api_upload_pair(name):
    """Upload a before/after image pair."""
    ds_path = os.path.join(DATASET_DIR, name)
    if not os.path.isdir(ds_path):
        return jsonify(error="Dataset not found."), 404

    before_file = request.files.get("before")
    after_file = request.files.get("after")
    if not before_file or not after_file:
        return jsonify(error="Need both 'before' and 'after' image files."), 400

    pair_id = request.form.get("pair_name") or str(uuid.uuid4())[:8]
    ext = ".png"

    before_file.save(os.path.join(ds_path, "before", pair_id + ext))
    after_file.save(os.path.join(ds_path, "after", pair_id + ext))

    prompt = request.form.get("prompt", "")
    if prompt:
        pf = os.path.join(ds_path, "prompts.json")
        prompts = {}
        if os.path.exists(pf):
            with open(pf) as f:
                prompts = json.load(f)
        prompts[pair_id] = prompt
        with open(pf, "w") as f:
            json.dump(prompts, f, indent=2)

    info = train_mod.validate_dataset(ds_path)
    info["name"] = name
    return jsonify(info)


@app.route("/api/datasets/<name>/pairs", methods=["GET"])
def api_list_pairs(name):
    ds_path = os.path.join(DATASET_DIR, name)
    if not os.path.isdir(ds_path):
        return jsonify(error="Dataset not found."), 404

    before_dir = os.path.join(ds_path, "before")
    after_dir = os.path.join(ds_path, "after")
    pairs = []
    if os.path.isdir(before_dir):
        for fname in sorted(os.listdir(before_dir)):
            af = os.path.join(after_dir, fname)
            if os.path.exists(af):
                # Return small base64 thumbnails
                bimg = Image.open(os.path.join(before_dir, fname)).convert("RGB")
                aimg = Image.open(af).convert("RGB")
                bimg.thumbnail((128, 128))
                aimg.thumbnail((128, 128))
                pairs.append({
                    "name": os.path.splitext(fname)[0],
                    "before": _pil_to_b64(bimg),
                    "after": _pil_to_b64(aimg),
                })
    return jsonify(pairs)


@app.route("/api/datasets/<name>", methods=["DELETE"])
def api_delete_dataset(name):
    path = os.path.join(DATASET_DIR, name)
    if os.path.isdir(path):
        shutil.rmtree(path)
        return jsonify(ok=True)
    return jsonify(error="Not found."), 404


# ── Training API ─────────────────────────────────────────────────────────────

@app.route("/api/training/start", methods=["POST"])
def api_start_training():
    if train_mod.is_running():
        return jsonify(error="Training already in progress."), 409

    data = request.get_json(silent=True) or {}
    ds_name = data.get("dataset")
    if not ds_name:
        return jsonify(error="Missing dataset name."), 400

    ds_path = os.path.join(DATASET_DIR, ds_name)
    if not os.path.isdir(ds_path):
        return jsonify(error="Dataset not found."), 404

    config = {
        "dataset_dir": ds_path,
        "model_name": data.get("model_name", ds_name),
        "epochs": int(data.get("epochs", 20)),
        "learning_rate": float(data.get("learning_rate", 1e-5)),
        "batch_size": int(data.get("batch_size", 1)),
        "resolution": int(data.get("resolution", 512)),
        "save_every": int(data.get("save_every", 5)),
    }

    train_mod.start_training(config)
    return jsonify(ok=True, config=config)


@app.route("/api/training/status")
def api_training_status():
    return jsonify(train_mod.get_status())


@app.route("/api/training/stop", methods=["POST"])
def api_stop_training():
    train_mod.request_stop()
    return jsonify(ok=True)


@app.route("/api/training/stream")
def api_training_stream():
    """SSE endpoint for live training progress."""
    import time

    def generate():
        while True:
            s = train_mod.get_status()
            yield f"data: {json.dumps(s)}\n\n"
            if s["state"] in ("completed", "failed", "idle"):
                break
            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream")


# ── Model management API ────────────────────────────────────────────────────

@app.route("/api/models")
def api_list_models():
    return jsonify(train_mod.list_models())


@app.route("/api/models/<name>", methods=["DELETE"])
def api_delete_model(name):
    if train_mod.delete_model(name):
        return jsonify(ok=True)
    return jsonify(error="Not found."), 404


@app.route("/api/models/<name>/activate", methods=["POST"])
def api_activate_model(name):
    """Reload the inference pipeline with a fine-tuned model."""
    path = os.path.join(MODEL_DIR, name)
    if not os.path.isdir(path):
        return jsonify(error="Model not found."), 404
    try:
        from pipelines.inference import reload_pipeline
        reload_pipeline(path)
        return jsonify(ok=True, model=name)
    except Exception as exc:
        return jsonify(error=str(exc)), 500


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
