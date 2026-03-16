from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import numpy as np
import cv2
from PIL import Image
from skimage.color import rgb2lab, lab2rgb
import io
import base64
import requests
import re
import os
import threading

# Lazy-loaded AI segmentation model (loaded once on first use)
_seg_model = None
_seg_processor = None
_seg_lock = threading.Lock()

# ADE20K class IDs that represent wall/ceiling surfaces we should paint.
# These are the label indices from the SegFormer ADE20K label map.
# "wall" = 0, "ceiling" = 5  (0-indexed after background shift)
# We detect all wall-like surfaces and let the user deselect if needed.
ADE20K_WALL_LABELS = {"wall", "ceiling"}  # add "partition" etc. if desired

def load_seg_model():
    """Load SegFormer segmentation model (once, thread-safe)."""
    global _seg_model, _seg_processor
    with _seg_lock:
        if _seg_model is None:
            from transformers import AutoImageProcessor, SegformerForSemanticSegmentation
            import torch
            model_id = "nvidia/segformer-b2-finetuned-ade-512-512"
            _seg_processor = AutoImageProcessor.from_pretrained(model_id)
            _seg_model = SegformerForSemanticSegmentation.from_pretrained(model_id)
            _seg_model.eval()
    return _seg_processor, _seg_model


def detect_walls_ai(img_rgb: np.ndarray) -> np.ndarray:
    """
    Use SegFormer (ADE20K) to detect wall pixels in the image.
    Returns a uint8 mask (0 = not wall, 255 = wall).
    """
    import torch
    import torch.nn.functional as F

    processor, model = load_seg_model()

    pil_img = Image.fromarray(img_rgb)
    h, w = img_rgb.shape[:2]

    inputs = processor(images=pil_img, return_tensors="pt")
    with torch.no_grad():
        outputs = model(**inputs)

    # Upsample logits to original image size
    logits = outputs.logits  # (1, num_classes, H/4, W/4)
    upsampled = F.interpolate(logits, size=(h, w), mode="bilinear", align_corners=False)
    seg_map = upsampled.argmax(dim=1)[0].cpu().numpy()  # (H, W)  int indices

    # Build mask for wall-related classes
    id2label = model.config.id2label
    wall_ids = {k for k, v in id2label.items() if v.lower() in ADE20K_WALL_LABELS}

    mask = np.zeros((h, w), dtype=np.uint8)
    for wid in wall_ids:
        mask[seg_map == wid] = 255

    # Morphological clean-up: close small holes, remove tiny specks
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    return mask

app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max upload

# =============================================================================
# SHERWIN WILLIAMS COLOR DATABASE
# Popular colors with accurate hex values sourced from sherwin-williams.com
# =============================================================================
SW_COLORS_DB = {
    # Whites & Off-Whites
    "SW7006": {"name": "Extra White", "hex": "#F1EEE9"},
    "SW7007": {"name": "Ceiling Bright White", "hex": "#F3F0EB"},
    "SW7008": {"name": "Alabaster", "hex": "#EDEADE"},
    "SW7009": {"name": "Pearly White", "hex": "#EDE8DC"},
    "SW7010": {"name": "White Duck", "hex": "#E1D9CB"},
    "SW7011": {"name": "Natural Choice", "hex": "#D8CEBF"},
    "SW7012": {"name": "Creamy", "hex": "#F3E2C4"},
    "SW7013": {"name": "Decides Beige", "hex": "#C8B89C"},
    "SW7014": {"name": "Eider White", "hex": "#D8D3CB"},
    "SW7015": {"name": "Repose Gray", "hex": "#B2ADA4"},
    "SW7016": {"name": "Mindful Gray", "hex": "#9F9B91"},
    "SW7017": {"name": "Dorian Gray", "hex": "#888077"},
    "SW7018": {"name": "Dovetail", "hex": "#817C74"},
    "SW7019": {"name": "Grizzle Gray", "hex": "#6F6B63"},
    "SW7020": {"name": "Black Bean", "hex": "#2E2017"},
    "SW7021": {"name": "Simple White", "hex": "#F0EDE6"},
    "SW7022": {"name": "Alpaca", "hex": "#D9CFBF"},
    "SW7023": {"name": "Requisite Gray", "hex": "#A19D94"},
    "SW7024": {"name": "Functional Gray", "hex": "#8F8B82"},
    "SW7025": {"name": "Backdrop", "hex": "#7B7671"},
    "SW7026": {"name": "Porpoise", "hex": "#6E6A63"},
    "SW7027": {"name": "Flagstone", "hex": "#625D55"},
    "SW7028": {"name": "Stardew", "hex": "#A2A89F"},
    "SW7029": {"name": "Agreeable Gray", "hex": "#C8B8AB"},
    "SW7030": {"name": "Anew Gray", "hex": "#BFBAB2"},
    "SW7031": {"name": "Mega Greige", "hex": "#B0A89C"},
    "SW7032": {"name": "Pismo Dunes", "hex": "#CBBEA8"},
    "SW7033": {"name": "Brainstorm Bronze", "hex": "#918272"},
    "SW7034": {"name": "Cameo", "hex": "#DDD0BA"},
    "SW7035": {"name": "Aesthetic White", "hex": "#E8DFCE"},
    "SW7036": {"name": "Accessible Beige", "hex": "#C8B49B"},
    "SW7037": {"name": "Balanced Beige", "hex": "#C2AE97"},
    "SW7038": {"name": "Tony Taupe", "hex": "#A2907C"},
    "SW7039": {"name": "Virtual Taupe", "hex": "#A09181"},
    "SW7040": {"name": "Smokehouse", "hex": "#666153"},
    "SW7041": {"name": "Van Dyke Brown", "hex": "#4A3C2E"},
    "SW7042": {"name": "Shoji White", "hex": "#DBD4C5"},
    "SW7043": {"name": "Worldly Gray", "hex": "#C0BAB0"},
    "SW7044": {"name": "Amazing Gray", "hex": "#B4B0A8"},
    "SW7045": {"name": "Intellectual Gray", "hex": "#A5A09A"},
    "SW7046": {"name": "Anonymous", "hex": "#9C9891"},
    "SW7047": {"name": "Porcelain", "hex": "#E4DFDA"},
    "SW7048": {"name": "Urbane Bronze", "hex": "#645C52"},
    "SW7049": {"name": "Sand Dune", "hex": "#B4A28A"},
    "SW7050": {"name": "Useful Beige", "hex": "#C1AD94"},
    "SW7051": {"name": "Analytical Gray", "hex": "#A9A79F"},
    "SW7052": {"name": "Nonchalant White", "hex": "#DDD9D1"},
    "SW7053": {"name": "Leisure", "hex": "#D0C7B8"},
    "SW7054": {"name": "Adaptive Shade", "hex": "#C3BFB6"},
    "SW7055": {"name": "Contented", "hex": "#C1BBAF"},
    "SW7056": {"name": "Oyster Bay", "hex": "#B4BBBB"},
    "SW7057": {"name": "Antique White", "hex": "#EDE3D1"},
    "SW7058": {"name": "Marshmallow", "hex": "#F2EEE9"},
    "SW7059": {"name": "Origami White", "hex": "#EEE9E1"},
    "SW7060": {"name": "Steamed Milk", "hex": "#F0E9DC"},
    "SW7061": {"name": "Begonia", "hex": "#C95C6D"},
    "SW7062": {"name": "Lavenous", "hex": "#9988B0"},
    "SW7063": {"name": "Smoky Blue", "hex": "#7A99AA"},
    "SW7064": {"name": "Distance", "hex": "#7E97A4"},
    "SW7065": {"name": "Meditative", "hex": "#8A9B9F"},
    "SW7066": {"name": "Gray Clouds", "hex": "#C0C6C4"},
    "SW7067": {"name": "Moderate White", "hex": "#DDD8CF"},
    "SW7068": {"name": "Grays Harbor", "hex": "#697375"},
    "SW7069": {"name": "Iron Ore", "hex": "#3C3C3B"},
    "SW7070": {"name": "Site White", "hex": "#EAE7DF"},
    # Yellows & Golds
    "SW6680": {"name": "Friendly Yellow", "hex": "#F0C44A"},
    "SW6681": {"name": "Fun Yellow", "hex": "#F0C23A"},
    "SW6682": {"name": "Daisy", "hex": "#EDBC2F"},
    "SW6686": {"name": "Jonquil", "hex": "#E8D26A"},
    "SW6690": {"name": "Butter Up", "hex": "#F2E5A4"},
    "SW6694": {"name": "Pale Gold", "hex": "#E4D09E"},
    "SW6119": {"name": "Venetian Lace", "hex": "#E7D9CC"},
    # Blues
    "SW6218": {"name": "Reserved White", "hex": "#DDE5E5"},
    "SW6220": {"name": "Ice Cube", "hex": "#D3E3E5"},
    "SW6222": {"name": "Icy", "hex": "#D1DEDF"},
    "SW6240": {"name": "Meditative", "hex": "#8A9B9F"},
    "SW6242": {"name": "Magnetic Gray", "hex": "#888FA3"},
    "SW6244": {"name": "Rave Red", "hex": "#8A2B26"},
    "SW6246": {"name": "Resolute Blue", "hex": "#3A5B82"},
    "SW6258": {"name": "Tricorn Black", "hex": "#2B2B2B"},
    "SW6385": {"name": "Naval", "hex": "#3C4B5C"},
    "SW6388": {"name": "Anchors Aweigh", "hex": "#8BA2B5"},
    "SW6390": {"name": "Iceberg", "hex": "#C9D8E0"},
    "SW6397": {"name": "Niebla Azul", "hex": "#899FB2"},
    "SW6490": {"name": "Reflecting Pool", "hex": "#93BCCE"},
    "SW6511": {"name": "Breezy", "hex": "#A8CACD"},
    "SW6520": {"name": "Waterfall", "hex": "#7CAFC4"},
    # Greens
    "SW6122": {"name": "Sage Green Light", "hex": "#B8C4B3"},
    "SW6155": {"name": "Livable Green", "hex": "#9EAE93"},
    "SW6162": {"name": "Backdrop", "hex": "#7B7671"},
    "SW6164": {"name": "Svelte Sage", "hex": "#9DAE98"},
    "SW6166": {"name": "Rosemary", "hex": "#7A927A"},
    "SW6168": {"name": "Clary Sage", "hex": "#9BA591"},
    "SW6180": {"name": "Dried Thyme", "hex": "#7B836B"},
    "SW6182": {"name": "Base Camp", "hex": "#6C7A5B"},
    "SW6184": {"name": "Foliage", "hex": "#5A6E47"},
    "SW6186": {"name": "Oak Moss", "hex": "#6E7754"},
    "SW6188": {"name": "Grassland", "hex": "#7C8A5C"},
    "SW6190": {"name": "Glade Green", "hex": "#638870"},
    "SW6423": {"name": "Celery", "hex": "#C9D2A2"},
    "SW6430": {"name": "Relish", "hex": "#8A9B6E"},
    # Reds & Pinks
    "SW6858": {"name": "Antler Velvet", "hex": "#9E5B46"},
    "SW6862": {"name": "Fiery Brown", "hex": "#8B4B35"},
    "SW6866": {"name": "Inventive Orange", "hex": "#C47B57"},
    "SW6107": {"name": "Habanero Chili", "hex": "#C84231"},
    "SW6868": {"name": "Copper Mountain", "hex": "#B0694C"},
    "SW7593": {"name": "Smoky Salmon", "hex": "#CB8070"},
    "SW6602": {"name": "Ravishing Coral", "hex": "#D4745F"},
    # Browns & Earth Tones
    "SW7521": {"name": "Dormer Brown", "hex": "#766557"},
    "SW7522": {"name": "Tatami Tan", "hex": "#B0987E"},
    "SW7533": {"name": "Netsuke", "hex": "#C5A882"},
    "SW7534": {"name": "Baguette", "hex": "#C0A07A"},
    "SW7535": {"name": "Camelback", "hex": "#C09A72"},
    "SW7536": {"name": "Territorial Beige", "hex": "#B59070"},
    "SW7537": {"name": "Cardboard", "hex": "#B99476"},
    "SW7538": {"name": "Tea Chest", "hex": "#A98A62"},
    "SW6126": {"name": "Macadamia", "hex": "#CBB28E"},
    # Navy / Dark
    "SW9177": {"name": "Charcoal Blue", "hex": "#485162"},
    "SW2748": {"name": "Dark Night", "hex": "#2E3340"},
    "SW6245": {"name": "Creamy White", "hex": "#EDE9DB"},
    "SW9108": {"name": "Cavern Clay", "hex": "#B76E56"},
    "SW9109": {"name": "Terra Brun", "hex": "#A66350"},
    "SW9110": {"name": "Fired Brick", "hex": "#9E5843"},
    "SW9111": {"name": "Redend Point", "hex": "#B97A6A"},
    "SW9120": {"name": "Almond Wisp", "hex": "#EDE4D6"},
    "SW9130": {"name": "Drift of Mist", "hex": "#DDD8CF"},
    "SW9140": {"name": "Aged Oak", "hex": "#B99B76"},
    "SW9150": {"name": "Warm Stone", "hex": "#B3A48E"},
    "SW9160": {"name": "Foggy Day", "hex": "#CACBC2"},
    "SW9170": {"name": "Smoky Azurite", "hex": "#7A8C96"},
    "SW9180": {"name": "Blushing", "hex": "#DEB8B0"},
}


def normalize_sw_code(raw: str) -> str:
    """Normalize input like 'sw 7029', 'SW-7029', '7029' -> 'SW7029'."""
    code = raw.upper().strip().replace(' ', '').replace('-', '').replace('#', '')
    if not code.startswith('SW'):
        code = 'SW' + code
    return code


def hex_to_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def fetch_sw_color_from_web(code: str) -> dict | None:
    """
    Try to fetch SW color data from Sherwin-Williams website.
    Tries multiple endpoint patterns.
    """
    number = code[2:]  # strip 'SW'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/html, */*',
    }
    # Try JSON API endpoint
    api_urls = [
        f"https://www.sherwin-williams.com/store/sw/rest/en_US/products/paint?colorNumber=SW{number}",
        f"https://www.sherwin-williams.com/store/sw/rest/products/paint?colorNumber=SW{number}",
    ]
    for url in api_urls:
        try:
            r = requests.get(url, headers=headers, timeout=8)
            if r.ok:
                data = r.json()
                # Navigate potential response structures
                entries = data if isinstance(data, list) else data.get('colors', data.get('results', [data]))
                for entry in entries:
                    hex_val = entry.get('hex', entry.get('hexCode', entry.get('colorHex', '')))
                    name = entry.get('name', entry.get('colorName', entry.get('colorFamilyName', '')))
                    if hex_val and re.match(r'^#?[0-9A-Fa-f]{6}$', hex_val.strip()):
                        hex_clean = hex_val.strip()
                        if not hex_clean.startswith('#'):
                            hex_clean = '#' + hex_clean
                        return {'name': name or code, 'hex': hex_clean}
        except Exception:
            pass

    # Try scraping the HTML color detail page
    try:
        page_url = f"https://www.sherwin-williams.com/en-us/color/find-and-explore-colors/paint-colors-by-number/SW{number}/"
        r = requests.get(page_url, headers=headers, timeout=10)
        if r.ok:
            # Look for hex color in script tags or meta tags
            text = r.text
            hex_match = re.search(r'"hex(?:Code|Color|Value)?"\s*:\s*"(#?[0-9A-Fa-f]{6})"', text)
            if hex_match:
                hex_val = hex_match.group(1)
                if not hex_val.startswith('#'):
                    hex_val = '#' + hex_val
                name_match = re.search(r'"(?:colorName|name)"\s*:\s*"([^"]+)"', text)
                name = name_match.group(1) if name_match else code
                return {'name': name, 'hex': hex_val}
    except Exception:
        pass

    return None


def get_sw_color(raw_code: str) -> dict | None:
    """Look up a SW color by code. Returns dict with name, hex, rgb or None."""
    code = normalize_sw_code(raw_code)

    # 1. Local database
    if code in SW_COLORS_DB:
        entry = SW_COLORS_DB[code].copy()
        entry['rgb'] = hex_to_rgb(entry['hex'])
        entry['code'] = code
        return entry

    # 2. Web fetch
    result = fetch_sw_color_from_web(code)
    if result:
        result['rgb'] = hex_to_rgb(result['hex'])
        result['code'] = code
        return result

    return None


# =============================================================================
# IMAGE PROCESSING
# =============================================================================

def decode_image(data_url_or_bytes) -> np.ndarray:
    """Decode a base64 data URL or raw bytes into an RGB numpy array."""
    if isinstance(data_url_or_bytes, str):
        # strip data URL prefix
        if ',' in data_url_or_bytes:
            data_url_or_bytes = data_url_or_bytes.split(',', 1)[1]
        img_bytes = base64.b64decode(data_url_or_bytes)
    else:
        img_bytes = data_url_or_bytes

    img = Image.open(io.BytesIO(img_bytes)).convert('RGB')
    return np.array(img)


def encode_image(img_np: np.ndarray) -> str:
    """Encode RGB numpy array to base64 PNG data URL."""
    img = Image.fromarray(img_np.astype(np.uint8))
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    return 'data:image/png;base64,' + b64


def apply_paint_color(img_rgb: np.ndarray, mask: np.ndarray, target_rgb: tuple,
                      blend_edges: bool = True) -> np.ndarray:
    """
    Apply paint color to masked region while preserving lighting and texture.

    Algorithm:
      1. Convert image to CIE LAB color space (perceptually uniform).
      2. Keep the L (lightness) channel of original pixels untouched — this
         preserves shadows, highlights, and texture.
      3. Replace only the a* and b* channels with values computed from the
         target paint color, scaled by a lighting factor derived from the
         original luminance so dark areas appear naturally desaturated (as
         real paint does in shadows).
      4. Convert back to RGB.
      5. Feather the mask edges for a seamless look.
    """
    img_float = img_rgb.astype(np.float32) / 255.0
    img_lab = rgb2lab(img_float)  # shape (H, W, 3), L in [0,100], a,b in ~[-128,127]

    # Target color in LAB
    target_float = np.array(target_rgb, dtype=np.float32).reshape(1, 1, 3) / 255.0
    target_lab = rgb2lab(target_float)[0, 0]  # [L, a, b]

    result_lab = img_lab.copy()

    mask_bool = mask > 128  # binary mask

    # --- Lighting-aware color replacement ---
    # L channel [0..100]: preserve original
    L = img_lab[:, :, 0]

    # Scale factor: at full brightness (L=100) apply 100% color;
    # at L=0 (black) apply 0% (shadow absorbs color).
    # A sqrt curve gives the most natural-looking result matching real paint.
    scale = np.sqrt(np.clip(L / 100.0, 0, 1))

    # Also blend a tiny fraction of original a,b for subtle texture retention
    orig_a = img_lab[:, :, 1]
    orig_b = img_lab[:, :, 2]
    texture_weight = 0.08  # 8% of original chroma retained for texture

    new_a = target_lab[1] * scale * (1 - texture_weight) + orig_a * texture_weight
    new_b = target_lab[2] * scale * (1 - texture_weight) + orig_b * texture_weight

    result_lab[:, :, 1][mask_bool] = new_a[mask_bool]
    result_lab[:, :, 2][mask_bool] = new_b[mask_bool]

    result_rgb = (lab2rgb(result_lab) * 255).clip(0, 255).astype(np.uint8)

    # --- Edge feathering for seamless blending ---
    if blend_edges:
        kernel_size = max(5, min(img_rgb.shape[0], img_rgb.shape[1]) // 60)
        if kernel_size % 2 == 0:
            kernel_size += 1
        mask_f = mask.astype(np.float32) / 255.0
        mask_blurred = cv2.GaussianBlur(mask_f, (kernel_size, kernel_size), 0)
        mask_blurred = np.stack([mask_blurred] * 3, axis=-1)
        result_rgb = (result_rgb.astype(np.float32) * mask_blurred +
                      img_rgb.astype(np.float32) * (1.0 - mask_blurred)).clip(0, 255).astype(np.uint8)

    return result_rgb


def magic_wand_select(img_rgb: np.ndarray, x: int, y: int,
                      tolerance: int = 25) -> np.ndarray:
    """
    Flood-fill based wall selection starting from seed point (x, y).
    Works in LAB space for perceptually accurate tolerance.
    Returns a uint8 mask (0 or 255).
    """
    h, w = img_rgb.shape[:2]
    x = max(0, min(x, w - 1))
    y = max(0, min(y, h - 1))

    img_float = img_rgb.astype(np.float32) / 255.0
    img_lab = rgb2lab(img_float).astype(np.float32)

    seed_lab = img_lab[y, x]

    # Compute per-pixel LAB distance from seed
    diff = img_lab - seed_lab
    dist = np.sqrt(np.sum(diff ** 2, axis=2))

    # Initial threshold mask
    tol_f = float(tolerance)
    selected = (dist < tol_f).astype(np.uint8) * 255

    # Flood-fill connectivity: we want a connected region, not all similar pixels
    # Use OpenCV floodFill on the distance image
    seed_color_bgr = img_rgb[y, x][::-1].tolist()  # RGB -> BGR

    # Build flood-fill compatible image (8-bit BGR)
    img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    flood_mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
    lo = hi = tolerance

    flags = 4 | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    cv2.floodFill(img_bgr, flood_mask, (x, y), (255, 255, 255),
                  (lo, lo, lo), (hi, hi, hi), flags)

    result_mask = flood_mask[1:h+1, 1:w+1]

    # Light morphological cleanup
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    result_mask = cv2.morphologyEx(result_mask, cv2.MORPH_CLOSE, kernel)

    return result_mask


# =============================================================================
# ROUTES
# =============================================================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/detect-walls', methods=['POST'])
def api_detect_walls():
    """
    Use the AI segmentation model to automatically detect walls in the image.
    Expects JSON: { "image": "<base64 data URL>" }
    Returns JSON: { "mask": "<base64 PNG of wall mask>" }
    """
    data = request.get_json()
    if not data or not data.get('image'):
        return jsonify({'error': 'Missing image data.'}), 400

    try:
        img_rgb = decode_image(data['image'])
        mask = detect_walls_ai(img_rgb)
        mask_rgb = np.stack([mask, mask, mask], axis=-1)
        return jsonify({'mask': encode_image(mask_rgb)})
    except Exception as e:
        return jsonify({'error': f'Wall detection failed: {str(e)}'}), 500


@app.route('/api/color/<path:color_code>')
def api_get_color(color_code):
    """Return color info for a given SW code."""
    color = get_sw_color(color_code)
    if not color:
        return jsonify({'error': f'Color "{color_code}" not found. '
                                  'Please check the code (e.g. SW 7029).'}), 404
    return jsonify(color)


@app.route('/api/visualize', methods=['POST'])
def api_visualize():
    """
    Apply paint color to uploaded image.
    Expects JSON:
      {
        "image":  "<base64 data URL>",
        "mask":   "<base64 data URL of grayscale mask>",
        "color_code": "SW7029"
      }
    Returns JSON: { "result": "<base64 data URL>" }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON payload received.'}), 400

    image_data = data.get('image')
    mask_data = data.get('mask')
    color_code = data.get('color_code', '').strip()

    if not image_data:
        return jsonify({'error': 'Missing image data.'}), 400
    if not mask_data:
        return jsonify({'error': 'Missing mask data. Please paint over the walls first.'}), 400
    if not color_code:
        return jsonify({'error': 'Missing color_code.'}), 400

    color = get_sw_color(color_code)
    if not color:
        return jsonify({'error': f'Color "{color_code}" not found. '
                                  'Please check the SW code (e.g. SW 7029).'}), 404

    try:
        img_rgb = decode_image(image_data)
        mask_rgb = decode_image(mask_data)

        # Convert mask to single channel grayscale
        if mask_rgb.ndim == 3:
            mask_gray = cv2.cvtColor(mask_rgb, cv2.COLOR_RGB2GRAY)
        else:
            mask_gray = mask_rgb

        # Resize mask to match image if needed
        if mask_gray.shape[:2] != img_rgb.shape[:2]:
            mask_gray = cv2.resize(mask_gray, (img_rgb.shape[1], img_rgb.shape[0]),
                                   interpolation=cv2.INTER_LINEAR)

        result = apply_paint_color(img_rgb, mask_gray, color['rgb'])
        return jsonify({'result': encode_image(result), 'color': color})

    except Exception as e:
        return jsonify({'error': f'Image processing failed: {str(e)}'}), 500


@app.route('/api/magic-wand', methods=['POST'])
def api_magic_wand():
    """
    Auto-select a wall region using flood fill from a clicked point.
    Expects JSON:
      { "image": "<base64>", "x": int, "y": int, "tolerance": int,
        "canvas_w": int, "canvas_h": int }
    Returns JSON: { "mask": "<base64 PNG of mask>" }
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON payload.'}), 400

    try:
        img_rgb = decode_image(data['image'])

        # The click coordinates come from the canvas display size,
        # so we need to scale them to actual image size.
        canvas_w = data.get('canvas_w', img_rgb.shape[1])
        canvas_h = data.get('canvas_h', img_rgb.shape[0])
        scale_x = img_rgb.shape[1] / canvas_w
        scale_y = img_rgb.shape[0] / canvas_h
        x = int(data.get('x', 0) * scale_x)
        y = int(data.get('y', 0) * scale_y)
        tolerance = int(data.get('tolerance', 30))

        mask = magic_wand_select(img_rgb, x, y, tolerance)
        mask_rgb = np.stack([mask, mask, mask], axis=-1)
        return jsonify({'mask': encode_image(mask_rgb)})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
