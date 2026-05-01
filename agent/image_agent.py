"""
Image Agent — THINK → ACT → OBSERVE

Uses Pollinations.ai — completely FREE, no API key needed.

Reliability strategy:
  1. Parallel pass with max 2 workers (gentle on free API, avoids rate-limits)
  2. Sequential retry pass for every scene that failed — with exponential backoff
     and a varied seed so Pollinations doesn't return a cached error.
  3. All failures are explicitly logged with the failure reason.
"""
import random
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from agent.cache import get_cached_image, save_image_cache
from config import PLATFORM_CONFIG
from models import ReelJob, Scene

# Conservative — Pollinations is free and rate-limits hard at >2 concurrent
_PARALLEL_WORKERS = 2
_BASE_BACKOFF = 1.5  # seconds — doubled each attempt

# Model fallback ladder: most reliable first
_MODEL_LADDER = ["flux", "flux-pro", "turbo"]

_QUALITY_SUFFIX = (
    "highly detailed, vibrant colors, cinematic lighting, sharp focus, "
    "professional commercial photography, 8K resolution, studio quality"
)
_NEGATIVE_PROMPT = urllib.parse.quote(
    "blurry, dull, washed out, low quality, dark, flat lighting, "
    "oversaturated, noisy, grainy, pixelated, ugly, deformed"
)


def _build_url(
    prompt: str, width: int, height: int, seed: int | None = None, model: str = "flux"
) -> str:
    short_prompt = prompt[:380]
    full_prompt = f"{short_prompt}, {_QUALITY_SUFFIX}"
    encoded = urllib.parse.quote(full_prompt)
    _seed = seed if seed is not None else abs(hash(prompt)) % 99999
    return (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}&nologo=true&model={model}&seed={_seed}"
        f"&negative={_NEGATIVE_PROMPT}"
    )


def _fetch_image(url: str, timeout: float = 90.0) -> tuple[bool, str]:
    """
    Returns (ok, error_reason). Verifies the response is actually an image.
    """
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url)
            ct = resp.headers.get("content-type", "")
            if resp.status_code == 200 and ct.startswith("image/"):
                return True, ""
            return False, f"HTTP {resp.status_code} content-type={ct!r}"
    except httpx.TimeoutException:
        return False, "Timeout (>90s)"
    except Exception as exc:
        return False, str(exc)


def _generate_image_with_retry(
    prompt: str, width: int, height: int, max_attempts: int = 6
) -> dict:
    """
    Try up to max_attempts times cycling through model fallback ladder,
    with exponential back-off and varied seeds each attempt.
    Returns {"ok": True, "url": ...} or {"ok": False, "error": ...}.
    """
    base_seed = abs(hash(prompt)) % 99999
    last_error = "unknown"
    for attempt in range(1, max_attempts + 1):
        seed = (base_seed + attempt * 7919) % 99999
        # Cycle through model ladder so repeated failures auto-fall back
        model = _MODEL_LADDER[(attempt - 1) % len(_MODEL_LADDER)]
        url = _build_url(prompt, width, height, seed=seed, model=model)
        ok, reason = _fetch_image(url)
        if ok:
            return {"ok": True, "url": url}
        last_error = f"[{model}] {reason}"
        if attempt < max_attempts:
            backoff = _BASE_BACKOFF * (2 ** min(attempt - 1, 4)) + random.uniform(0, 1.5)
            time.sleep(backoff)
    return {"ok": False, "error": f"All {max_attempts} attempts failed. Last: {last_error}"}


def _process_scene(
    scene: Scene, product, width: int, height: int, max_attempts: int = 6
) -> tuple[Scene, dict, float]:
    enhanced_prompt = (
        f"{scene.image_prompt}, "
        f"featuring {product.name}, "
        f"professional product photography, "
        f"high quality, sharp focus, {product.tone} mood, "
        f"vertical composition, bold composition, dramatic depth of field"
    )
    cached = get_cached_image(enhanced_prompt)
    if cached:
        return scene, {"ok": True, "url": cached, "cached": True}, 0.0

    t0 = time.time()
    result = _generate_image_with_retry(enhanced_prompt, width, height, max_attempts)
    elapsed = round(time.time() - t0, 2)
    if result["ok"]:
        save_image_cache(enhanced_prompt, result["url"])
    return scene, result, elapsed


def run(job: ReelJob) -> ReelJob:
    """
    THINK → ACT → OBSERVE

    Pass 1 — parallel (max 2 workers, 2 quick attempts each).
    Pass 2 — sequential retry for every scene that failed in pass 1
             (up to 3 more attempts with full back-off).
    """
    if not job.script:
        job.error = "No script found — run script_agent first"
        job.log("image_agent", "error", job.error)
        return job

    product = job.product
    platform_cfg = PLATFORM_CONFIG.get(product.platform, PLATFORM_CONFIG["instagram"])
    width = platform_cfg["width"]
    height = platform_cfg["height"]
    scenes = job.script.scenes

    job.log(
        "image_agent", "think",
        f"Generating {len(scenes)} images at {width}x{height}. "
        f"Pass 1: {_PARALLEL_WORKERS} parallel workers, up to 3 attempts each. "
        f"Pass 2: sequential retry (up to 6 attempts, model fallback ladder: {_MODEL_LADDER}).",
    )

    # ── Pass 1: parallel, 3 attempts per scene ────────────────────────────────
    failed_scenes: list[Scene] = []
    with ThreadPoolExecutor(max_workers=_PARALLEL_WORKERS) as pool:
        futures = {
            pool.submit(_process_scene, scene, product, width, height, 3): scene
            for scene in scenes
        }
        for future in as_completed(futures):
            scene, result, elapsed = future.result()
            if result["ok"]:
                scene.image_url = result["url"]
                label = "cached" if result.get("cached") else f"{elapsed}s"
                job.log("image_agent", "observe",
                        f"Scene {scene.index}: image ready ({label})", cost=0.0)
            else:
                failed_scenes.append(scene)
                job.log("image_agent", "warn",
                        f"Scene {scene.index}: pass-1 failed — {result['error']} — will retry")

    # ── Pass 2: sequential retry for failures, full model ladder ─────────────
    if failed_scenes:
        job.log("image_agent", "retry",
                f"Pass 2 — retrying {len(failed_scenes)} failed scene(s) sequentially with back-off and model fallback...")
        for scene in failed_scenes:
            _, result, elapsed = _process_scene(scene, product, width, height, max_attempts=6)
            if result["ok"]:
                scene.image_url = result["url"]
                job.log("image_agent", "observe",
                        f"Scene {scene.index}: retry succeeded in {elapsed}s", cost=0.0)
            else:
                job.log("image_agent", "error",
                        f"Scene {scene.index}: PERMANENTLY FAILED — {result['error']}")

    done = sum(1 for s in scenes if s.image_url)
    total = len(scenes)
    status = "ok" if done == total else ("partial" if done > 0 else "failed")
    job.log("image_agent", "done",
            f"Images: {done}/{total} ready (status={status}). All free via Pollinations.ai.", cost=0.0)

    if done == 0:
        job.error = "Image generation completely failed — Pollinations.ai may be down"

    return job
