"""
Cache layer — avoids redundant API calls across runs.

Caches:
  - Script JSON (keyed by SHA256 of product input)
  - Image URLs (keyed by image prompt SHA256)

Cache lives in ./output/_cache/ as simple JSON files.
This saves cost on repeated runs with the same product.
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional


_CACHE_DIR = Path("./output/_cache")


def _key(data: str) -> str:
    """Stable SHA256 of any string — used as cache key."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def _script_cache_path(product_hash: str) -> Path:
    return _CACHE_DIR / "scripts" / f"{product_hash}.json"


def _image_cache_path(prompt_hash: str) -> Path:
    return _CACHE_DIR / "images" / f"{prompt_hash}.json"


def _ensure_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def product_hash(product_dict: dict) -> str:
    """Deterministic hash of product input (name + desc + platform + tone + features + duration)."""
    key_fields = {
        "name": product_dict.get("name", ""),
        "description": product_dict.get("description", ""),
        "platform": product_dict.get("platform", ""),
        "tone": product_dict.get("tone", ""),
        "features": sorted(product_dict.get("features", [])),
        "price": product_dict.get("price", ""),
        "target_duration": product_dict.get("target_duration", 30),
    }
    return _key(json.dumps(key_fields, sort_keys=True))


# ── Script cache ──────────────────────────────────────────────────────────────

def get_cached_script(phash: str) -> Optional[dict]:
    """Return cached script JSON dict, or None if not cached."""
    path = _script_cache_path(phash)
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_script_cache(phash: str, script_data: dict):
    """Persist script JSON to disk."""
    path = _script_cache_path(phash)
    _ensure_dir(path)
    with open(path, "w") as f:
        json.dump(script_data, f, indent=2)


# ── Image URL cache ───────────────────────────────────────────────────────────

def get_cached_image(prompt: str) -> Optional[str]:
    """Return a previously generated image URL for this prompt, or None."""
    path = _image_cache_path(_key(prompt))
    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
                return data.get("url")
        except Exception:
            return None
    return None


def save_image_cache(prompt: str, url: str):
    """Store the image URL for this prompt."""
    path = _image_cache_path(_key(prompt))
    _ensure_dir(path)
    with open(path, "w") as f:
        json.dump({"url": url, "prompt": prompt}, f)
