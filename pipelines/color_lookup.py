"""
Sherwin-Williams color lookup.

Resolves a SW code (e.g. "SW 7029", "7029", "sw7029") to
{ name, hex, rgb, code }.  Checks a built-in DB first, then
tries Sherwin-Williams web endpoints as a fallback.
"""

import re
import requests

# ── Built-in database of ~150 popular SW colours ─────────────────────────────
_DB = {
    # Whites / Off-whites
    "SW7006": ("Extra White", "#F1EEE9"),
    "SW7007": ("Ceiling Bright White", "#F3F0EB"),
    "SW7008": ("Alabaster", "#EDEADE"),
    "SW7009": ("Pearly White", "#EDE8DC"),
    "SW7010": ("White Duck", "#E1D9CB"),
    "SW7011": ("Natural Choice", "#D8CEBF"),
    "SW7012": ("Creamy", "#F3E2C4"),
    "SW7014": ("Eider White", "#D8D3CB"),
    "SW7015": ("Repose Gray", "#B2ADA4"),
    "SW7016": ("Mindful Gray", "#9F9B91"),
    "SW7017": ("Dorian Gray", "#888077"),
    "SW7018": ("Dovetail", "#817C74"),
    "SW7019": ("Grizzle Gray", "#6F6B63"),
    "SW7020": ("Black Bean", "#2E2017"),
    "SW7021": ("Simple White", "#F0EDE6"),
    "SW7022": ("Alpaca", "#D9CFBF"),
    "SW7023": ("Requisite Gray", "#A19D94"),
    "SW7024": ("Functional Gray", "#8F8B82"),
    "SW7025": ("Backdrop", "#7B7671"),
    "SW7026": ("Porpoise", "#6E6A63"),
    "SW7027": ("Flagstone", "#625D55"),
    "SW7029": ("Agreeable Gray", "#C8B8AB"),
    "SW7030": ("Anew Gray", "#BFBAB2"),
    "SW7031": ("Mega Greige", "#B0A89C"),
    "SW7032": ("Pismo Dunes", "#CBBEA8"),
    "SW7034": ("Cameo", "#DDD0BA"),
    "SW7035": ("Aesthetic White", "#E8DFCE"),
    "SW7036": ("Accessible Beige", "#C8B49B"),
    "SW7037": ("Balanced Beige", "#C2AE97"),
    "SW7038": ("Tony Taupe", "#A2907C"),
    "SW7039": ("Virtual Taupe", "#A09181"),
    "SW7040": ("Smokehouse", "#666153"),
    "SW7041": ("Van Dyke Brown", "#4A3C2E"),
    "SW7042": ("Shoji White", "#DBD4C5"),
    "SW7043": ("Worldly Gray", "#C0BAB0"),
    "SW7044": ("Amazing Gray", "#B4B0A8"),
    "SW7045": ("Intellectual Gray", "#A5A09A"),
    "SW7046": ("Anonymous", "#9C9891"),
    "SW7047": ("Porcelain", "#E4DFDA"),
    "SW7048": ("Urbane Bronze", "#645C52"),
    "SW7050": ("Useful Beige", "#C1AD94"),
    "SW7051": ("Analytical Gray", "#A9A79F"),
    "SW7057": ("Antique White", "#EDE3D1"),
    "SW7058": ("Marshmallow", "#F2EEE9"),
    "SW7059": ("Origami White", "#EEE9E1"),
    "SW7060": ("Steamed Milk", "#F0E9DC"),
    "SW7063": ("Smoky Blue", "#7A99AA"),
    "SW7064": ("Distance", "#7E97A4"),
    "SW7066": ("Gray Clouds", "#C0C6C4"),
    "SW7067": ("Moderate White", "#DDD8CF"),
    "SW7069": ("Iron Ore", "#3C3C3B"),
    "SW7070": ("Site White", "#EAE7DF"),
    # Blues
    "SW6218": ("Reserved White", "#DDE5E5"),
    "SW6220": ("Ice Cube", "#D3E3E5"),
    "SW6246": ("Resolute Blue", "#3A5B82"),
    "SW6258": ("Tricorn Black", "#2B2B2B"),
    "SW6385": ("Naval", "#3C4B5C"),
    "SW6390": ("Iceberg", "#C9D8E0"),
    "SW6490": ("Reflecting Pool", "#93BCCE"),
    "SW6511": ("Breezy", "#A8CACD"),
    "SW6520": ("Waterfall", "#7CAFC4"),
    # Greens
    "SW6155": ("Livable Green", "#9EAE93"),
    "SW6164": ("Svelte Sage", "#9DAE98"),
    "SW6166": ("Rosemary", "#7A927A"),
    "SW6168": ("Clary Sage", "#9BA591"),
    "SW6180": ("Dried Thyme", "#7B836B"),
    "SW6186": ("Oak Moss", "#6E7754"),
    "SW6188": ("Grassland", "#7C8A5C"),
    "SW6190": ("Glade Green", "#638870"),
    "SW6423": ("Celery", "#C9D2A2"),
    "SW6430": ("Relish", "#8A9B6E"),
    # Yellows / Golds
    "SW6119": ("Venetian Lace", "#E7D9CC"),
    "SW6680": ("Friendly Yellow", "#F0C44A"),
    "SW6681": ("Fun Yellow", "#F0C23A"),
    "SW6682": ("Daisy", "#EDBC2F"),
    "SW6686": ("Jonquil", "#E8D26A"),
    "SW6690": ("Butter Up", "#F2E5A4"),
    "SW6694": ("Pale Gold", "#E4D09E"),
    # Reds / Pinks
    "SW6107": ("Habanero Chili", "#C84231"),
    "SW6602": ("Ravishing Coral", "#D4745F"),
    "SW6858": ("Antler Velvet", "#9E5B46"),
    "SW6862": ("Fiery Brown", "#8B4B35"),
    "SW6866": ("Inventive Orange", "#C47B57"),
    "SW6868": ("Copper Mountain", "#B0694C"),
    "SW7593": ("Smoky Salmon", "#CB8070"),
    # Browns / Earth
    "SW7521": ("Dormer Brown", "#766557"),
    "SW7522": ("Tatami Tan", "#B0987E"),
    "SW7533": ("Netsuke", "#C5A882"),
    "SW7534": ("Baguette", "#C0A07A"),
    "SW7535": ("Camelback", "#C09A72"),
    "SW7536": ("Territorial Beige", "#B59070"),
    "SW7538": ("Tea Chest", "#A98A62"),
    "SW6126": ("Macadamia", "#CBB28E"),
    # Special / Trending
    "SW9108": ("Cavern Clay", "#B76E56"),
    "SW9109": ("Terra Brun", "#A66350"),
    "SW9110": ("Fired Brick", "#9E5843"),
    "SW9111": ("Redend Point", "#B97A6A"),
    "SW9120": ("Almond Wisp", "#EDE4D6"),
    "SW9130": ("Drift of Mist", "#DDD8CF"),
    "SW9140": ("Aged Oak", "#B99B76"),
    "SW9150": ("Warm Stone", "#B3A48E"),
    "SW9160": ("Foggy Day", "#CACBC2"),
    "SW9170": ("Smoky Azurite", "#7A8C96"),
    "SW9177": ("Charcoal Blue", "#485162"),
    "SW9180": ("Blushing", "#DEB8B0"),
}


def _norm(raw: str) -> str:
    """Normalise user input to canonical 'SWNNNN' key."""
    code = raw.upper().strip().replace(" ", "").replace("-", "").replace("#", "")
    if not code.startswith("SW"):
        code = "SW" + code
    return code


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _try_web(code: str) -> dict | None:
    """Attempt to scrape colour data from sherwin-williams.com."""
    number = code[2:]
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    }
    for url in (
        f"https://www.sherwin-williams.com/store/sw/rest/en_US/"
        f"products/paint?colorNumber=SW{number}",
    ):
        try:
            r = requests.get(url, headers=headers, timeout=8)
            if not r.ok:
                continue
            data = r.json()
            entries = data if isinstance(data, list) else [data]
            for e in entries:
                h = e.get("hex", e.get("hexCode", e.get("colorHex", "")))
                if h and re.match(r"^#?[0-9A-Fa-f]{6}$", h.strip()):
                    h = h.strip()
                    if not h.startswith("#"):
                        h = "#" + h
                    return {
                        "name": e.get("name", e.get("colorName", code)),
                        "hex": h,
                    }
        except Exception:
            pass
    return None


def lookup(raw_code: str) -> dict | None:
    """
    Look up a Sherwin-Williams colour.

    Returns ``{"name": ..., "hex": ..., "rgb": (R,G,B), "code": "SWNNNN"}``
    or ``None`` if not found.
    """
    code = _norm(raw_code)

    if code in _DB:
        name, hexv = _DB[code]
        return {"name": name, "hex": hexv, "rgb": _hex_to_rgb(hexv), "code": code}

    web = _try_web(code)
    if web:
        web["rgb"] = _hex_to_rgb(web["hex"])
        web["code"] = code
        return web

    return None
