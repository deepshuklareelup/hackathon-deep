"""
Script Agent — THINK → ACT → OBSERVE

THINK:  Analyze product JSON + platform + tone to determine reel structure.
ACT:    Call Claude to generate scene-by-scene narration, visual directions, image prompts.
OBSERVE: Parse JSON response, validate scenes, return a Script object.
"""
import json
import re
import time
from typing import Optional

import anthropic

from agent.cache import get_cached_script, save_script_cache, product_hash
from config import ANTHROPIC_API_KEY, choose_script_model, PLATFORM_CONFIG
from models import Scene, Script, ReelJob

# Cost rates per million tokens (Haiku / Sonnet)
_COST_RATES = {
    "claude-haiku-4-5": {"input": 0.80, "output": 4.0},
    "claude-sonnet-4-5":         {"input": 3.0,  "output": 15.0},
}


_SYSTEM_PROMPT = """You are an expert product reel scriptwriter for social media.
You create short, punchy, high-converting video scripts for Instagram Reels and TikTok.

Your scripts follow the proven structure:
1. HOOK — 1 sentence that stops the scroll (question, bold claim, or shocking stat)
2. SCENES — 3-5 short scenes that show the product solving a pain point
3. CTA — Clear call to action ("Link in bio", "Shop now", "Try it today")

Each scene should be 2-4 seconds — fast-paced, visual, emotional.
Image prompts should be photorealistic product photography style.

You MUST respond with valid JSON only. No markdown, no explanation."""

_USER_PROMPT_TEMPLATE = """Create a product reel script for:

Product: {name}
Description: {description}
Price: {price}
Features: {features}
Target Audience: {audience}
Tone: {tone}
Platform: {platform} ({width}x{height} — vertical video)
Target Duration: {target_duration} seconds total

Return ONLY this JSON structure (no markdown, no extra text):
{{
  "hook": "One punchy opening line that grabs attention",
  "scenes": [
    {{
      "index": 0,
      "narration": "Short spoken narration for this scene (max 15 words)",
      "visual_direction": "What to visually show (for human reference)",
      "duration_seconds": 3,
      "image_prompt": "Detailed photorealistic FLUX image prompt for this scene (include product name, lighting, style)"
    }}
  ],
  "cta": "Clear call to action line",
  "total_duration": {target_duration}
}}

Rules:
- Total video must be approximately {target_duration} seconds
- Use {scene_count} scenes, each {scene_duration} seconds on average
- total_duration MUST equal the sum of all scene duration_seconds values
- image_prompt must include: product context, lighting ({tone} mood), camera angle, style
- narration should be punchy, no filler words
- hook must be under 10 words{feedback_section}"""


def run(job: ReelJob) -> ReelJob:
    """
    THINK → ACT → OBSERVE: Generate a structured video script from product data.
    Includes: smart model routing, caching, self-validation reflection loop.
    """
    product = job.product
    platform_cfg = PLATFORM_CONFIG.get(product.platform, PLATFORM_CONFIG["instagram"])

    # ── THINK — smart model routing ───────────────────────────────────────────
    model = choose_script_model(product)
    job.log("script_agent", "think",
            f"Analyzing '{product.name}' for {product.platform} — routing to {model}")

    if not ANTHROPIC_API_KEY:
        job.error = "ANTHROPIC_API_KEY not configured"
        job.log("script_agent", "error", job.error)
        return job

    # ── CACHE CHECK ───────────────────────────────────────────────────────────
    # Skip cache entirely when rewriting based on feedback — always call the LLM.
    _feedback_for_cache = getattr(job, "human_feedback", None)
    phash = product_hash({
        "name": product.name, "description": product.description,
        "platform": product.platform, "tone": product.tone,
        "features": product.features, "price": product.price or "",
        "target_duration": getattr(product, "target_duration", None) or 30,
    })
    cached = get_cached_script(phash)
    if cached and not _feedback_for_cache:
        job.log("script_agent", "cache_hit", f"Script loaded from cache (cost $0) hash={phash}")
        return _build_script_from_data(job, cached)

    # ── ACT ───────────────────────────────────────────────────────────────────
    target_duration = getattr(product, "target_duration", None) or 30
    # Spread duration evenly across 3-7 scenes; each scene 3-8s
    scene_count = max(3, min(7, round(target_duration / 5)))
    scene_duration = round(target_duration / scene_count)

    # If the critic or human sent feedback, include it as a rewrite instruction.
    # Also detect explicit scene count requests like "only 3 scenes" / "4 scenes" etc.
    feedback = getattr(job, "human_feedback", None)
    if feedback:
        import re as _re
        m = _re.search(r'\b(?:only\s+)?(\d+)\s+scenes?\b', feedback, _re.IGNORECASE)
        if m:
            requested = int(m.group(1))
            scene_count = max(1, min(10, requested))
            scene_duration = round(target_duration / scene_count)

    feedback_section = (
        f"\n\nIMPORTANT — Rewrite instruction from reviewer:\n{feedback}\nPlease fix this specifically."
        if feedback else ""
    )

    prompt = _USER_PROMPT_TEMPLATE.format(
        name=product.name,
        description=product.description,
        price=product.price or "not specified",
        features=", ".join(product.features) if product.features else "none",
        audience=product.target_audience or "general audience",
        tone=product.tone,
        platform=product.platform,
        width=platform_cfg["width"],
        height=platform_cfg["height"],
        target_duration=target_duration,
        scene_count=scene_count,
        scene_duration=scene_duration,
        feedback_section=feedback_section,
    )

    job.log("script_agent", "act", f"Calling {model} to generate script")

    t0 = time.time()
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        job.error = f"Script generation failed: {e}"
        job.log("script_agent", "error", job.error)
        return job

    elapsed = round(time.time() - t0, 2)

    # Accurate cost using per-model rates
    rates = _COST_RATES.get(model, {"input": 3.0, "output": 15.0})
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = round((input_tokens / 1_000_000 * rates["input"]) + (output_tokens / 1_000_000 * rates["output"]), 6)

    raw_text = response.content[0].text.strip()

    # ── OBSERVE ───────────────────────────────────────────────────────────────
    job.log(
        "script_agent", "observe",
        f"Received response in {elapsed}s ({input_tokens} in / {output_tokens} out) via {model}",
        cost=cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
    )

    # Parse JSON — strip markdown fences if model added them
    json_text = _extract_json(raw_text)
    if not json_text:
        job.error = f"Could not extract JSON from LLM response: {raw_text[:200]}"
        job.log("script_agent", "error", job.error)
        return job

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        job.error = f"Invalid JSON from LLM: {e} — raw: {json_text[:200]}"
        job.log("script_agent", "error", job.error)
        return job

    # ── SELF-VALIDATION reflection loop ───────────────────────────────────────
    issues = _validate_script_data(data, product)
    if issues:
        job.log("script_agent", "reflect",
                f"Script issues detected: {issues} — requesting revision from model")
        fix_prompt = (
            f"The script you generated has these issues:\n{chr(10).join(f'- {i}' for i in issues)}\n\n"
            f"Please fix them and return the corrected JSON only. Original script:\n{json_text}"
        )
        try:
            fix_response = client.messages.create(
                model=model,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": raw_text},
                    {"role": "user", "content": fix_prompt},
                ],
            )
            fix_tokens_in = fix_response.usage.input_tokens
            fix_tokens_out = fix_response.usage.output_tokens
            fix_cost = round((fix_tokens_in / 1_000_000 * rates["input"]) + (fix_tokens_out / 1_000_000 * rates["output"]), 6)
            job.log("script_agent", "reflect_result",
                    f"Revision received ({fix_tokens_out} tokens)", cost=fix_cost)
            fixed_json = _extract_json(fix_response.content[0].text.strip())
            if fixed_json:
                data = json.loads(fixed_json)
        except Exception as e:
            job.log("script_agent", "reflect_error", f"Revision call failed: {e} — using original")

    # ── Build model objects + cache ────────────────────────────────────────────
    # Don't pollute the cache with feedback-driven rewrites — only cache clean generations.
    if not feedback:
        save_script_cache(phash, data)
    return _build_script_from_data(job, data)


def _validate_script_data(data: dict, product) -> list[str]:
    """
    Self-check: return a list of issues with the script.
    Empty list = script is good. This implements the 'checks own output' criterion.
    """
    issues = []
    scenes = data.get("scenes", [])

    if not data.get("hook"):
        issues.append("Missing hook")
    if not data.get("cta"):
        issues.append("Missing CTA")
    if len(scenes) < 2:
        issues.append(f"Too few scenes: {len(scenes)} (need at least 2)")
    if len(scenes) > 6:
        issues.append(f"Too many scenes: {len(scenes)} (max 6)")

    for i, scene in enumerate(scenes):
        if not scene.get("narration"):
            issues.append(f"Scene {i} missing narration")
        if not scene.get("image_prompt"):
            issues.append(f"Scene {i} missing image_prompt")
        dur = scene.get("duration_seconds", 0)
        if dur < 2 or dur > 6:
            issues.append(f"Scene {i} duration {dur}s out of range (2-6s)")
        # Check image prompt mentions product name (brand safety)
        if product.name.lower() not in scene.get("image_prompt", "").lower():
            issues.append(f"Scene {i} image_prompt doesn't mention product name")

    return issues


def _build_script_from_data(job: ReelJob, data: dict) -> ReelJob:
    """Build Scene/Script objects from parsed JSON dict and attach to job."""
    scenes = []
    for raw_scene in data.get("scenes", []):
        scenes.append(Scene(
            index=raw_scene.get("index", len(scenes)),
            narration=raw_scene.get("narration", ""),
            visual_direction=raw_scene.get("visual_direction", ""),
            duration_seconds=int(raw_scene.get("duration_seconds", 3)),
            image_prompt=raw_scene.get("image_prompt", ""),
        ))

    if not scenes:
        job.error = "Script agent returned zero scenes"
        job.log("script_agent", "error", job.error)
        return job

    job.script = Script(
        hook=data.get("hook", ""),
        scenes=scenes,
        cta=data.get("cta", ""),
        total_duration=int(data.get("total_duration", sum(s.duration_seconds for s in scenes))),
    )
    job.log("script_agent", "done",
            f"Script ready: {len(scenes)} scenes, ~{job.script.total_duration}s total")
    return job


def _extract_json(text: str) -> Optional[str]:
    """Strip markdown fences and extract JSON object."""
    # Remove ```json ... ``` fences
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)
    text = text.strip()

    # Find first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    return text[start:end + 1]
