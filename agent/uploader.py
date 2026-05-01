"""
Uploader — GCS upload for final video

Uses the same GCS pattern as rofy_2_llm/app/tools.py.
Falls back gracefully if GCS is not configured (video stays local).
"""
import os
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from config import GCS_BUCKET_NAME, GOOGLE_APPLICATION_CREDENTIALS
from models import ReelJob


def _get_gcs_client():
    """Initialize GCS client using application default credentials or service account."""
    if not GCS_BUCKET_NAME:
        return None, None
    try:
        from google.cloud import storage
        if GOOGLE_APPLICATION_CREDENTIALS and Path(GOOGLE_APPLICATION_CREDENTIALS).exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS
        client = storage.Client()
        return client, GCS_BUCKET_NAME
    except Exception as e:
        return None, None


def _upload_to_gcs(local_path: str, job_id: str) -> Optional[str]:
    """Upload a file to GCS and return public URL."""
    client, bucket_name = _get_gcs_client()
    if not client:
        return None

    file_name = Path(local_path).name
    object_name = f"reels/{job_id}/{int(time.time())}_{uuid.uuid4().hex[:8]}_{file_name}"

    try:
        blob = client.bucket(bucket_name).blob(object_name)
        blob.upload_from_filename(local_path, content_type="video/mp4")
        try:
            blob.make_public()
        except Exception:
            pass
        encoded = "/".join(quote(part, safe="") for part in object_name.split("/"))
        return f"https://storage.googleapis.com/{bucket_name}/{encoded}"
    except Exception as e:
        return None


def run(job: ReelJob) -> ReelJob:
    """
    Upload final video to GCS. Falls back to local-only if GCS not configured.
    """
    if not job.final_video_path or not Path(job.final_video_path).exists():
        job.log("uploader", "skip", "No final video to upload")
        return job

    # ── THINK ─────────────────────────────────────────────────────────────────
    if not GCS_BUCKET_NAME:
        job.log(
            "uploader", "skip",
            f"GCS_BUCKET_NAME not configured — video saved locally at {job.final_video_path}",
        )
        job.final_video_url = f"file://{job.final_video_path}"
        return job

    job.log("uploader", "think", f"Uploading final video to GCS bucket: {GCS_BUCKET_NAME}")

    # ── ACT ───────────────────────────────────────────────────────────────────
    t0 = time.time()
    url = _upload_to_gcs(job.final_video_path, job.job_id)
    elapsed = round(time.time() - t0, 2)

    # ── OBSERVE ───────────────────────────────────────────────────────────────
    if url:
        job.final_video_url = url
        job.log("uploader", "done", f"Uploaded in {elapsed}s → {url}")
    else:
        job.log(
            "uploader", "warn",
            f"GCS upload failed — video still available locally: {job.final_video_path}",
        )
        job.final_video_url = f"file://{job.final_video_path}"

    return job
