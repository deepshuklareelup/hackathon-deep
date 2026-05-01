"""
Video Agent — THINK → ACT → OBSERVE

Free implementation using ffmpeg Ken Burns effect (pan/zoom on images).
Runs all scenes IN PARALLEL for speed.
"""
import random
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from models import ReelJob, Scene

# Ken Burns zoom/pan presets — varied per scene for visual interest.
# Each preset ends with ,fps=30 AFTER zoompan to normalize frame timing and
# eliminate the jitter/shakiness that zoompan produces on its own.
_KB_PRESETS = [
    # zoom in from center (slow, dramatic)
    "zoompan=z='min(zoom+0.0008,1.35)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps=30,fps=30",
    # zoom out from center
    "zoompan=z='if(lte(zoom,1.0),1.35,max(1.0,zoom-0.0008))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps=30,fps=30",
    # pan right + slight zoom
    "zoompan=z='1.2':x='iw/2-(iw/zoom/2)+{pan_x}*on/{frames}':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps=30,fps=30",
    # pan left + slight zoom
    "zoompan=z='1.2':x='iw/2-(iw/zoom/2)-{pan_x}*on/{frames}':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps=30,fps=30",
    # pan up + slight zoom
    "zoompan=z='1.2':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)+{pan_y}*on/{frames}':d={frames}:s={w}x{h}:fps=30,fps=30",
    # pan down + slight zoom
    "zoompan=z='1.2':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)-{pan_y}*on/{frames}':d={frames}:s={w}x{h}:fps=30,fps=30",
    # diagonal pan top-left to bottom-right + zoom in
    "zoompan=z='min(zoom+0.0006,1.25)':x='iw/2-(iw/zoom/2)+{pan_x}*on/{frames}':y='ih/2-(ih/zoom/2)+{pan_y}*on/{frames}':d={frames}:s={w}x{h}:fps=30,fps=30",
    # diagonal pan bottom-right to top-left + zoom in
    "zoompan=z='min(zoom+0.0006,1.25)':x='iw/2-(iw/zoom/2)-{pan_x}*on/{frames}':y='ih/2-(ih/zoom/2)-{pan_y}*on/{frames}':d={frames}:s={w}x{h}:fps=30,fps=30",
    # zoom in from top-left corner
    "zoompan=z='min(zoom+0.0008,1.3)':x='0':y='0':d={frames}:s={w}x{h}:fps=30,fps=30",
    # zoom in from bottom-right corner
    "zoompan=z='min(zoom+0.0008,1.3)':x='iw-iw/zoom':y='ih-ih/zoom':d={frames}:s={w}x{h}:fps=30,fps=30",
]

_FFMPEG_FALLBACK = (
    r"C:\Users\deep\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
)


def _ffmpeg_exe() -> str:
    import os, shutil
    if env := os.environ.get("FFMPEG_PATH"):
        return env
    if found := shutil.which("ffmpeg"):
        return found
    if Path(_FFMPEG_FALLBACK).exists():
        return _FFMPEG_FALLBACK
    return "ffmpeg"


def _download_image(url: str, dest: Path) -> bool:
    try:
        with httpx.Client(timeout=90.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return True
    except Exception:
        return False


def _ken_burns_clip(image_path: str, duration: int, width: int, height: int, scene_index: int, output_path: str) -> bool:
    """Apply Ken Burns pan/zoom effect to a static image to produce a video clip."""
    frames = duration * 30
    pan_x = random.choice([-80, 80])
    pan_y = random.choice([-80, 80])

    preset = _KB_PRESETS[scene_index % len(_KB_PRESETS)]
    vf = preset.format(frames=frames, w=width, h=height, pan_x=pan_x, pan_y=pan_y)

    cmd = [
        _ffmpeg_exe(), "-y",
        "-loop", "1",
        "-i", image_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        "-r", "30",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def run(job: ReelJob) -> ReelJob:
    """
    THINK → ACT → OBSERVE: Generate a Ken Burns video clip for each scene image.
    """
    if not job.script:
        job.error = "No script found — run script_agent first"
        job.log("video_agent", "error", job.error)
        return job

    scenes_with_images = [s for s in job.script.scenes if s.image_url]
    skipped = [s for s in job.script.scenes if not s.image_url]

    job.log(
        "video_agent", "think",
        f"Creating Ken Burns clips for {len(scenes_with_images)}/{len(job.script.scenes)} scenes with images. "
        f"{len(skipped)} scene(s) skipped (no image).",
    )
    for s in skipped:
        job.log("video_agent", "warn",
                f"Scene {s.index}: skipped — no image was generated in image_agent")

    if not scenes_with_images:
        job.log("video_agent", "skip", "No images available — editor will use placeholders")
        return job

    work_dir = Path(job.output_dir) / job.job_id / "video_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    # Determine output size from platform config
    from config import PLATFORM_CONFIG
    platform_cfg = PLATFORM_CONFIG.get(job.product.platform, PLATFORM_CONFIG["instagram"])
    width = platform_cfg["width"]
    height = platform_cfg["height"]

    def process_one(scene: Scene):
        scene_dir = work_dir / f"scene_{scene.index:02d}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        img_path = scene_dir / "scene.jpg"
        out_path = scene_dir / "kb_clip.mp4"

        t0 = time.time()
        if not _download_image(scene.image_url, img_path):
            return scene, False, 0.0
        ok = _ken_burns_clip(str(img_path), scene.duration_seconds, width, height, scene.index, str(out_path))
        elapsed = round(time.time() - t0, 2)
        if ok and out_path.exists():
            scene.video_path = str(out_path)
        return scene, ok, elapsed

    # Keep to 2 workers — ffmpeg is CPU-bound and more than 2 causes contention
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(process_one, scene): scene for scene in scenes_with_images}
        for future in as_completed(futures):
            scene, ok, elapsed = future.result()
            if ok:
                job.log("video_agent", "observe", f"Scene {scene.index} Ken Burns clip ready in {elapsed}s (free)", cost=0.0)
            else:
                job.log("video_agent", "warn", f"Scene {scene.index}: Ken Burns failed — editor will use static image")

    done = sum(1 for s in job.script.scenes if getattr(s, "video_path", None))
    job.log("video_agent", "done", f"Created {done}/{len(job.script.scenes)} Ken Burns clips (free)")
    return job
