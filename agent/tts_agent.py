"""
TTS Agent — THINK → ACT → OBSERVE

THINK:  Collect narration text per scene, estimate audio length.
ACT:    Call OpenAI TTS (tts-1) to generate an .mp3 per scene.
OBSERVE: Save audio files locally, attach paths to Scene objects.
"""
import os
import time
from pathlib import Path

import httpx

from config import OPENAI_API_KEY, TTS_MODEL, TTS_VOICE
from models import ReelJob


# tts-1 pricing: $15 per 1M characters
_COST_PER_CHAR = 15 / 1_000_000


def _generate_tts(text: str, output_path: str, api_key: str) -> dict:
    """Generate speech for text and save to output_path as mp3."""
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": TTS_MODEL,
                    "voice": TTS_VOICE,
                    "input": text,
                    "response_format": "mp3",
                    "speed": 1.1,   # slightly faster for reels
                },
            )
            if resp.status_code != 200:
                return {"ok": False, "error": f"OpenAI TTS HTTP {resp.status_code}: {resp.text[:200]}"}

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(resp.content)
            return {"ok": True, "path": output_path, "bytes": len(resp.content)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run(job: ReelJob) -> ReelJob:
    """
    THINK → ACT → OBSERVE: Generate TTS narration audio for each scene.
    """
    if not job.script:
        job.error = "No script found — run script_agent first"
        job.log("tts_agent", "error", job.error)
        return job

    if not OPENAI_API_KEY:
        job.error = "OPENAI_API_KEY not configured"
        job.log("tts_agent", "error", job.error)
        return job

    audio_dir = Path(job.output_dir) / job.job_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Build narration texts: hook goes with scene 0, CTA with last scene
    texts = []
    for i, scene in enumerate(job.script.scenes):
        if i == 0:
            text = f"{job.script.hook} {scene.narration}"
        elif i == len(job.script.scenes) - 1:
            text = f"{scene.narration} {job.script.cta}"
        else:
            text = scene.narration
        texts.append(text)

    total_chars = sum(len(t) for t in texts)

    # ── THINK ─────────────────────────────────────────────────────────────────
    job.log(
        "tts_agent", "think",
        f"Generating TTS for {len(texts)} scenes, {total_chars} total characters",
    )

    for i, (scene, text) in enumerate(zip(job.script.scenes, texts)):
        audio_path = str(audio_dir / f"scene_{scene.index:02d}.mp3")

        # ── ACT ───────────────────────────────────────────────────────────────
        job.log("tts_agent", "act", f"Scene {scene.index}: TTS for '{text[:50]}...'")

        t0 = time.time()
        result = _generate_tts(text, audio_path, OPENAI_API_KEY)
        elapsed = round(time.time() - t0, 2)
        cost = round(len(text) * _COST_PER_CHAR, 6)

        # ── OBSERVE ───────────────────────────────────────────────────────────
        if result["ok"]:
            scene.audio_path = result["path"]
            job.log(
                "tts_agent", "observe",
                f"Scene {scene.index} audio ready in {elapsed}s ({result['bytes']} bytes)",
                cost=cost,
            )
        else:
            job.log("tts_agent", "observe", f"Scene {scene.index} TTS FAILED: {result['error']}")

    succeeded = sum(1 for s in job.script.scenes if s.audio_path)
    job.log("tts_agent", "done", f"Generated {succeeded}/{len(job.script.scenes)} audio files")
    return job
