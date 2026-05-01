"""
FastAPI server — REST + SSE API for the Rofy Reel Agent.

Endpoints:
  POST /api/generate/script      — Phase 1: generate script only
  POST /api/generate/full        — Phase 2: run all stages (streams SSE events)
  GET  /api/jobs/{job_id}        — Get job state
  GET  /api/jobs/{job_id}/video  — Stream the final video file
  GET  /api/keys                 — Check which API keys are configured

Run:  uvicorn server:app --reload --port 8000
"""
import asyncio
import json
import random
import re
import sys
import uuid
from pathlib import Path
from typing import Optional

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import script_agent, image_agent, video_agent, tts_agent, editor, uploader, qa_agent
from agent import research_agent
from agent.tracer import export_trace
from config import ANTHROPIC_API_KEY, validate_keys
from graph import run_graph_script_only
from models import ProductInput, ReelJob

app = FastAPI(title="Rofy Reel Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory job store ───────────────────────────────────────────────────────
_jobs: dict[str, ReelJob] = {}
# Maps job_id → LangGraph thread config (for checkpointing + interrupt resume)
_graph_configs: dict[str, dict] = {}


# ── Request models ────────────────────────────────────────────────────────────
class ProductRequest(BaseModel):
    name: str
    description: str
    price: Optional[str] = None
    features: list[str] = []
    target_audience: Optional[str] = None
    tone: str = "exciting"
    platform: str = "instagram"
    target_duration: Optional[int] = None


class ScriptGenerateRequest(BaseModel):
    product: ProductRequest
    output_dir: str = "./output"


class FullGenerateRequest(BaseModel):
    job_id: str   # job_id returned from /api/generate/script (script already approved)


class ResumeRequest(BaseModel):
    decision: str  # 'approved' or free-text feedback for rewrite


class ResearchRequest(BaseModel):
    url: str


class QuickStartSuggestion(BaseModel):
    emoji: str
    label: str
    data: ProductRequest


# ── Helpers ───────────────────────────────────────────────────────────────────
def _job_to_dict(job: ReelJob) -> dict:
    script_data = None
    if job.script:
        script_data = {
            "hook": job.script.hook,
            "cta": job.script.cta,
            "total_duration": job.script.total_duration,
            "scene_count": job.script.scene_count,
            "model_used": getattr(job.script, "model_used", None),
            "cost_usd": job.total_cost,
            "scenes": [
                {
                    "index": s.index,
                    "narration": s.narration,
                    "duration": getattr(s, "duration_seconds", None) or getattr(s, "duration", None),
                    "visual_direction": getattr(s, "visual_direction", ""),
                    "image_prompt": s.image_prompt,
                    "image_url": s.image_url,
                    "video_url": s.video_url,
                    "audio_path": s.audio_path,
                    "video_path": getattr(s, "video_path", None),
                }
                for s in job.script.scenes
            ],
        }
    return {
        "job_id": job.job_id,
        "status": job.status,
        "error": job.error,
        "script": script_data,
        "final_video_path": job.final_video_path,
        "final_video_url": job.final_video_url,
        "total_cost": job.total_cost,
        "costs": job.costs,
        "logs": [
            {"stage": e.stage, "action": e.action, "result": e.result, "cost_usd": e.cost_usd}
            for e in job.logs[-20:]  # last 20 log entries
        ],
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _extract_json_object(text: str) -> str | None:
    """Extract the first JSON object from model output (with or without markdown fences)."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return cleaned[start : end + 1]


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/keys")
def get_keys():
    return validate_keys()


@app.get("/api/suggestions/quick-start")
def get_quick_start_suggestions(count: int = 6):
    """
    Generate fresh quick-start product ideas via LLM.
    Called by the UI on page load so each refresh can show new suggestions.
    """
    if count < 1 or count > 10:
        raise HTTPException(400, "count must be between 1 and 10")

    if not ANTHROPIC_API_KEY:
        raise HTTPException(400, "ANTHROPIC_API_KEY not configured")

    # Rotate category mix for variety across refreshes.
    categories = [
        "nutrition", "beauty", "skincare", "fashion", "wearables",
        "audio", "productivity", "home", "pet care", "travel", "wellness",
        "gaming", "kitchen", "parenting", "outdoor", "automotive",
    ]
    chosen_categories = random.sample(categories, k=min(count, len(categories)))
    nonce = uuid.uuid4().hex[:8]

    system_prompt = (
        "You generate product quick-start seed examples for a social video script UI. "
        "Return strict JSON only, no markdown, no prose."
    )
    user_prompt = f"""
Generate exactly {count} unique quick-start suggestions.

Use categories: {", ".join(chosen_categories)}
Randomness nonce: {nonce}

Return JSON with this exact shape:
{{
  "suggestions": [
    {{
      "emoji": "single emoji",
      "label": "2-4 words",
      "data": {{
        "name": "specific product name",
        "description": "1-2 sentence marketing description",
        "price": "$number or number string",
        "features": ["feature 1", "feature 2", "feature 3", "feature 4", "feature 5"],
        "target_audience": "clear audience",
        "tone": "professional|casual|luxury|energetic|friendly",
        "platform": "instagram|tiktok|youtube_shorts|linkedin|twitter",
        "target_duration": 30
      }}
    }}
  ]
}}

Rules:
- Suggestions must be realistic consumer products.
- Make all labels distinct.
- Keep tone/platform sensible for each product.
- target_duration must be an integer between 15 and 60.
""".strip()

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1800,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as e:
        raise HTTPException(502, f"Suggestion generation failed: {e}")

    raw_text = response.content[0].text.strip() if response.content else ""
    json_text = _extract_json_object(raw_text)
    if not json_text:
        raise HTTPException(502, "Suggestion generation returned invalid output")

    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise HTTPException(502, f"Suggestion generation returned invalid JSON: {e}")

    suggestions = payload.get("suggestions", [])
    if not isinstance(suggestions, list):
        raise HTTPException(502, "Suggestion generation returned malformed payload")

    validated: list[dict] = []
    for item in suggestions[:count]:
        if not isinstance(item, dict):
            continue
        data = item.get("data") or {}
        if not isinstance(data, dict):
            continue

        features = data.get("features") or []
        if not isinstance(features, list):
            features = []

        normalized = {
            "emoji": str(item.get("emoji") or "✨")[:4],
            "label": str(item.get("label") or "Quick Idea").strip()[:40],
            "data": {
                "name": str(data.get("name") or "Product").strip(),
                "description": str(data.get("description") or "").strip(),
                "price": str(data.get("price")) if data.get("price") is not None else None,
                "features": [str(f).strip() for f in features if str(f).strip()][:6],
                "target_audience": str(data.get("target_audience")) if data.get("target_audience") else None,
                "tone": str(data.get("tone") or "energetic"),
                "platform": str(data.get("platform") or "instagram"),
                "target_duration": int(data.get("target_duration") or 30),
            },
        }
        validated.append(normalized)

    if not validated:
        raise HTTPException(502, "Suggestion generation returned no usable suggestions")

    return {
        "suggestions": validated,
        "generated_count": len(validated),
    }


@app.post("/api/research")
async def research_url(req: ResearchRequest):
    """
    Research Sub-Agent — fetches a product URL and returns structured product data.
    Used by the UI to auto-fill the form before script generation.
    """
    if not req.url or not req.url.strip():
        raise HTTPException(400, "URL is required")
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: research_agent.run(req.url)
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(422, str(e))


@app.post("/api/generate/script")
def generate_script(req: ScriptGenerateRequest):
    """Phase 1 — Generate + critic-score script. Returns job with script + critic for human review."""
    keys = validate_keys()
    if not keys["script_agent"]:
        raise HTTPException(400, "ANTHROPIC_API_KEY not configured")

    product = ProductInput.from_dict({
        "name": req.product.name,
        "description": req.product.description,
        "price": req.product.price,
        "features": req.product.features,
        "target_audience": req.product.target_audience,
        "tone": req.product.tone,
        "platform": req.product.platform,
        "target_duration": req.product.target_duration,
    })

    # Stage 1: generate script
    job = run_graph_script_only(product, output_dir=req.output_dir)

    # Stage 1b: critic scores the script (cheap Haiku call)
    if job.script and not job.error:
        from agent import critic_agent
        critic_agent.run(job)

    if job.error or not job.script:
        job.status = "failed"

    _jobs[job.job_id] = job
    result = _job_to_dict(job)
    # Include critic report in response
    result["critic_report"] = getattr(job, "critic_report", None)
    return result


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    result = _job_to_dict(job)
    result["critic_report"] = getattr(job, "critic_report", None)
    return result


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str, req: ResumeRequest):
    """
    Resume a graph paused at node_review (human-in-the-loop interrupt).
    decision='approved' proceeds to image generation.
    Any other text is treated as rewrite feedback for the script agent.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    job.human_feedback = req.decision
    # Store so the SSE stream picks it up when it calls /api/generate/full again
    return {"status": "resumed", "decision": req.decision}


@app.get("/api/jobs/{job_id}/scenes/{scene_index}/clip")
def get_scene_clip(job_id: str, scene_index: int):
    """Serve a local Ken Burns video clip for a specific scene."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.script:
        raise HTTPException(404, "No script")
    scene = next((s for s in job.script.scenes if s.index == scene_index), None)
    if not scene:
        raise HTTPException(404, f"Scene {scene_index} not found")
    clip_path = getattr(scene, "video_path", None)
    if not clip_path or not Path(clip_path).exists():
        raise HTTPException(404, "Clip not ready")
    return FileResponse(clip_path, media_type="video/mp4")


@app.get("/api/jobs/{job_id}/video")
def get_video(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.final_video_path or not Path(job.final_video_path).exists():
        raise HTTPException(404, "Video not yet ready")
    return FileResponse(
        job.final_video_path,
        media_type="video/mp4",
        filename=f"reel_{job_id}.mp4",
    )


@app.get("/api/generate/full/{job_id}")
async def generate_full(job_id: str):
    """
    Phase 2 — Run stages 2-6 for an already-scripted job.
    Streams Server-Sent Events so the UI can show live progress.
    Pauses at node_review (human-in-the-loop) with a 'review' SSE event.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    if not job.script:
        raise HTTPException(400, "Job has no script — run /api/generate/script first")

    async def event_stream():
        def emit(stage: str, message: str, data: dict | None = None):
            payload = {"stage": stage, "message": message, **(data or {})}
            return _sse("progress", payload)

        # ── Stage 1b: Rewrite if human requested changes ──────────────────────
        feedback = getattr(job, "human_feedback", None)
        if feedback and feedback != "approved":
            yield emit("scripting", f"Rewriting script based on your feedback: \"{feedback}\"")
            await asyncio.get_event_loop().run_in_executor(None, lambda: script_agent.run(job))
            if job.error:
                yield _sse("error", {"message": job.error, "stage": "scripting"})
                return
            # Re-score with critic
            from agent import critic_agent
            await asyncio.get_event_loop().run_in_executor(None, lambda: critic_agent.run(job))
            job.human_feedback = None  # clear so it doesn't re-trigger on next run
            yield _sse("rewrite_done", {
                "job_id": job.job_id,
                "critic_report": getattr(job, "critic_report", None),
            })
            return  # Stop here — UI will redirect to review page to approve the new script

        # ── Stage 2: Images ───────────────────────────────────────────────────
        job.set_status("imaging")
        total_scenes = len(job.script.scenes)
        yield emit("imaging", f"Generating {total_scenes} scene images via Pollinations.ai (free)..."
                   " Pass 1: parallel. Pass 2: sequential retry for failures.")
        await asyncio.get_event_loop().run_in_executor(None, lambda: image_agent.run(job))
        images_ok = sum(1 for s in job.script.scenes if s.image_url)
        images_failed = total_scenes - images_ok
        failed_indices = [s.index for s in job.script.scenes if not s.image_url]

        image_data = {
            "scenes": [{"index": s.index, "image_url": s.image_url} for s in job.script.scenes],
            "images_ok": images_ok,
            "images_failed": images_failed,
            "failed_scene_indices": failed_indices,
        }
        if images_failed == 0:
            yield emit("imaging", f"All {images_ok}/{total_scenes} images ready ✓", data=image_data)
        elif images_ok == 0:
            job.status = "failed"
            job.error = "Image generation completely failed — Pollinations.ai may be down or all scenes timed out."
            yield _sse("error", {"message": job.error, "stage": "imaging"})
            return
        else:
            yield emit(
                "imaging",
                f"⚠ {images_ok}/{total_scenes} images ready — {images_failed} scene(s) failed "
                f"(scenes {failed_indices}). Continuing with available images.",
                data=image_data,
            )

        # ── Stage 3: Video clips ──────────────────────────────────────────────
        job.set_status("videoing")
        yield emit("videoing", "Creating Ken Burns video clips (free, local ffmpeg)...")
        await asyncio.get_event_loop().run_in_executor(None, lambda: video_agent.run(job))
        clips_ok = sum(1 for s in job.script.scenes if getattr(s, 'video_path', None))
        clips_failed = total_scenes - clips_ok
        yield emit("videoing", f"{clips_ok}/{total_scenes} clips ready" + (f" — {clips_failed} skipped (no image)" if clips_failed else " ✓"), data={
            "scenes": [{"index": s.index, "image_url": s.image_url, "clip_url": f"/api/jobs/{job.job_id}/scenes/{s.index}/clip" if getattr(s, 'video_path', None) else None} for s in job.script.scenes]
        })

        # ── Stage 4: TTS ──────────────────────────────────────────────────────
        keys = validate_keys()
        job.set_status("tts")
        yield emit("tts", "Generating narration audio (OpenAI TTS)...")
        if keys["tts_agent"]:
            await asyncio.get_event_loop().run_in_executor(None, lambda: tts_agent.run(job))
            audio_ok = sum(1 for s in job.script.scenes if s.audio_path)
            yield emit("tts", f"{audio_ok}/{len(job.script.scenes)} audio files ready")
        else:
            yield emit("tts", "Skipped — OPENAI_API_KEY not set")

        # ── Stage 5: Edit ─────────────────────────────────────────────────────
        job.set_status("editing")
        yield emit("editing", "Stitching final video with ffmpeg...")
        await asyncio.get_event_loop().run_in_executor(None, lambda: editor.run(job))
        if job.error:
            job.status = "failed"
            yield _sse("error", {"message": job.error})
            return
        yield emit("editing", f"Video ready: {job.final_video_path}")

        # ── Stage 6: QA ───────────────────────────────────────────────────────
        job.set_status("qa")
        yield emit("qa", "Running quality checks (duration, audio, fps, resolution)...")
        await asyncio.get_event_loop().run_in_executor(None, lambda: qa_agent.run(job))
        qa = getattr(job, "qa_report", {})
        issues = qa.get("issues", [])
        passes = qa.get("passes", [])
        yield emit("qa", f"{len(passes)} checks passed, {len(issues)} warnings", data={"qa_report": qa})

        # ── Stage 7: Upload ───────────────────────────────────────────────────
        job.set_status("uploading")
        yield emit("uploading", "Uploading to GCS (if configured)...")
        await asyncio.get_event_loop().run_in_executor(None, lambda: uploader.run(job))
        job.status = "done"

        trace_path = export_trace(job)
        job.log("server", "trace_exported", f"Trace saved to {trace_path}")

        yield _sse("done", _job_to_dict(job))

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/jobs/{job_id}/reconnect")
async def reconnect_job(job_id: str):
    """
    Reconnect SSE endpoint for page refreshes.
    - If job is 'done' or 'failed': immediately replays all logs + final state, then closes.
    - If job is still running: replays logs so far, then polls for new logs and final state.
    - If job not found: returns 404 immediately via SSE error event.
    """
    async def reconnect_stream():
        job = _jobs.get(job_id)
        if not job:
            yield _sse("error", {"message": f"Job {job_id} not found — server may have restarted"})
            return

        # Replay all existing logs as SSE messages so the UI can rebuild its state
        yield _sse("reconnected", {"job_id": job_id, "status": job.status, "log_count": len(job.logs)})
        for entry in job.logs:
            yield _sse("log", {
                "stage": entry.stage,
                "action": entry.action,
                "message": entry.result,
                "cost_usd": entry.cost_usd,
            })
            await asyncio.sleep(0)  # yield control so response flushes

        # If already finished, send final state and close
        if job.status in ("done", "failed"):
            result = _job_to_dict(job)
            result["critic_report"] = getattr(job, "critic_report", None)
            if job.status == "done":
                yield _sse("done", result)
            else:
                yield _sse("error", {"message": job.error or "Job failed", **result})
            return

        # Job still running — poll for new logs and status changes
        last_log_count = len(job.logs)
        while True:
            await asyncio.sleep(1)
            job = _jobs.get(job_id)
            if not job:
                yield _sse("error", {"message": "Job disappeared"})
                return

            # Emit any new log entries
            current_logs = job.logs
            if len(current_logs) > last_log_count:
                for entry in current_logs[last_log_count:]:
                    yield _sse("log", {
                        "stage": entry.stage,
                        "action": entry.action,
                        "message": entry.result,
                        "cost_usd": entry.cost_usd,
                    })
                last_log_count = len(current_logs)

            if job.status == "done":
                yield _sse("done", _job_to_dict(job))
                return
            if job.status == "failed":
                yield _sse("error", {"message": job.error or "Job failed"})
                return

    return StreamingResponse(reconnect_stream(), media_type="text/event-stream")
