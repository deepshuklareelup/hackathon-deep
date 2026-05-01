"""
Tracer — structured observability for the Rofy Reel Agent.

Exports a JSON trace file per job to ./output/traces/{job_id}.json.
Includes: all log entries, cost breakdown, timing, model usage.
This is the "Langfuse-lite" for the hackathon demo.
"""
import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import ReelJob


def export_trace(job: "ReelJob"):
    """
    Write a full trace JSON for a completed job.
    Creates: ./output/traces/{job_id}.json
    """
    trace_dir = Path(job.output_dir) / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)

    trace = {
        "job_id": job.job_id,
        "status": job.status,
        "product": {
            "name": job.product.name,
            "platform": job.product.platform,
            "tone": job.product.tone,
        },
        "costs": job.costs,
        "total_cost_usd": job.total_cost,
        "final_video_path": job.final_video_path,
        "final_video_url": job.final_video_url,
        "error": job.error,
        "script": _serialize_script(job),
        "logs": [
            {
                "stage": entry.stage,
                "action": entry.action,
                "result": entry.result,
                "cost_usd": entry.cost_usd,
                "metadata": entry.metadata,
            }
            for entry in job.logs
        ],
    }

    trace_path = trace_dir / f"{job.job_id}.json"
    with open(trace_path, "w") as f:
        json.dump(trace, f, indent=2)

    return str(trace_path)


def _serialize_script(job: "ReelJob") -> dict | None:
    if not job.script:
        return None
    return {
        "hook": job.script.hook,
        "cta": job.script.cta,
        "total_duration": job.script.total_duration,
        "scene_count": job.script.scene_count,
        "scenes": [
            {
                "index": s.index,
                "narration": s.narration,
                "visual_direction": s.visual_direction,
                "duration_seconds": s.duration_seconds,
                "image_url": s.image_url,
                "video_url": s.video_url,
                "audio_path": s.audio_path,
                "video_path": s.video_path,
            }
            for s in job.script.scenes
        ],
    }
