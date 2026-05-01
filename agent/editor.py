"""
Editor — ffmpeg stitching pipeline

For each scene:
  1. Download video clip (or convert static image → video)
  2. Overlay narration audio (trim/pad to match video duration)
Concatenate all scene clips → final.mp4
"""
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import httpx

from models import ReelJob, Scene

# Allow overriding ffmpeg path via env var, then fall back to PATH search,
# then try the known WinGet install location on Windows.
_FFMPEG_FALLBACK = (
    r"C:\Users\deep\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
)

def _ffmpeg_exe() -> str:
    """Return the ffmpeg executable path, checking env var and fallback paths."""
    if env := os.environ.get("FFMPEG_PATH"):
        return env
    if found := shutil.which("ffmpeg"):
        return found
    if Path(_FFMPEG_FALLBACK).exists():
        return _FFMPEG_FALLBACK
    return "ffmpeg"  # will fail with clear error


def _check_ffmpeg() -> bool:
    try:
        subprocess.run([_ffmpeg_exe(), "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _download_file(url: str, dest: Path) -> bool:
    """Download a URL to a local file."""
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return True
    except Exception:
        return False


def _image_to_video(image_path: str, duration: int, output_path: str) -> bool:
    """Convert a static image to a video clip using ffmpeg (fallback when no video URL)."""
    cmd = [
        _ffmpeg_exe(), "-y",
        "-loop", "1",
        "-i", image_path,
        "-c:v", "libx264",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def _mux_video_audio(video_path: str, audio_path: Optional[str], duration: int, output_path: str) -> bool:
    """Mux video + audio, trimming/padding audio to match video duration."""
    if audio_path and Path(audio_path).exists():
        cmd = [
            _ffmpeg_exe(), "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex", f"[1:a]apad=pad_dur={duration}[a]",
            "-map", "0:v:0",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-t", str(duration),
            output_path,
        ]
    else:
        # No audio — just copy video
        cmd = [
            _ffmpeg_exe(), "-y",
            "-i", video_path,
            "-c:v", "copy",
            "-an",
            "-t", str(duration),
            output_path,
        ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def _has_audio_stream(clip_path: str) -> bool:
    """Return True if the clip has at least one audio stream."""
    try:
        r = subprocess.run(
            [_ffmpeg_exe(), "-i", clip_path],
            capture_output=True,
        )
        return b"Audio:" in r.stderr
    except Exception:
        return False


def _add_silent_audio(clip_path: str, output_path: str, duration: int) -> bool:
    """Add a silent audio track to a video-only clip."""
    cmd = [
        _ffmpeg_exe(), "-y",
        "-i", clip_path,
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={duration}",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


_XFADE_TRANSITIONS = [
    "fade", "fadeblack", "fadewhite", "slideleft", "slideright", "slideup", "slidedown",
    "circlecrop", "smoothleft", "smoothright", "smoothup", "smoothdown",
]
_XFADE_DURATION = 0.5  # seconds


def _get_clip_duration(clip_path: str) -> float:
    """Return clip duration in seconds via ffprobe. Falls back to 5.0 if unavailable."""
    try:
        result = subprocess.run(
            [
                _ffmpeg_exe().replace("ffmpeg", "ffprobe"),
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                clip_path,
            ],
            capture_output=True, text=True,
        )
        return float(result.stdout.strip())
    except Exception:
        return 5.0


def _concatenate_clips_with_xfade(clip_paths: list[str], output_path: str) -> bool:
    """Join clips with smooth xfade transitions between scenes (video + audio crossfade)."""
    import logging
    import random as _random
    logger = logging.getLogger("editor")

    # Get real durations for offset calculation
    durations = [_get_clip_duration(p) for p in clip_paths]

    n = len(clip_paths)
    inputs = []
    for p in clip_paths:
        inputs += ["-i", p]

    # Build filter_complex: chain xfade for video, acrossfade for audio
    video_nodes = [f"[{i}:v]" for i in range(n)]
    audio_nodes = [f"[{i}:a]" for i in range(n)]
    filters = []

    # Video xfade chain
    cur_v = video_nodes[0]
    offset = 0.0
    for i in range(1, n):
        offset += durations[i - 1] - _XFADE_DURATION
        out_v = f"[xv{i}]" if i < n - 1 else "[vout]"
        transition = _XFADE_TRANSITIONS[i % len(_XFADE_TRANSITIONS)]
        filters.append(
            f"{cur_v}{video_nodes[i]}xfade=transition={transition}"
            f":duration={_XFADE_DURATION}:offset={offset:.3f}{out_v}"
        )
        cur_v = out_v.rstrip("]").lstrip("[")
        cur_v = f"[xv{i}]" if i < n - 1 else "[vout]"

    # Audio acrossfade chain
    cur_a = audio_nodes[0]
    for i in range(1, n):
        out_a = f"[xa{i}]" if i < n - 1 else "[aout]"
        filters.append(f"{cur_a}{audio_nodes[i]}acrossfade=d={_XFADE_DURATION}{out_a}")
        cur_a = out_a

    filter_complex = ";".join(filters)

    cmd = [
        _ffmpeg_exe(), "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        logger.error("xfade concat stderr: %s", result.stderr.decode(errors="replace")[-3000:])
    return result.returncode == 0


def _concatenate_clips(clip_paths: list[str], output_path: str) -> bool:
    """Use ffmpeg concat demuxer to join clips, re-encoding for compatibility."""
    import logging
    logger = logging.getLogger("editor")

    # Normalize all clips to have an audio stream so concat doesn't fail on
    # mixed audio/video-only streams (common when some scenes have TTS and some don't)
    normalized: list[str] = []
    work_dir = Path(output_path).parent
    for i, p in enumerate(clip_paths):
        if not _has_audio_stream(p):
            norm_path = str(work_dir / f"norm_{i:02d}.mp4")
            scene_dur = max(1, int(round(_get_clip_duration(p))))
            if _add_silent_audio(p, norm_path, scene_dur):
                logger.info("Clip %d: added silent audio track", i)
                normalized.append(norm_path)
            else:
                logger.warning("Clip %d: could not add silent audio — using original", i)
                normalized.append(p)
        else:
            normalized.append(p)

    concat_file = Path(output_path).parent / "concat_list.txt"
    # Use forward slashes — backslashes break ffmpeg's concat parser on Windows
    lines = [f"file '{str(Path(p).resolve()).replace(chr(92), '/')}'\n" for p in normalized]
    concat_file.write_text("".join(lines))

    cmd = [
        _ffmpeg_exe(), "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-movflags", "+faststart",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    concat_file.unlink(missing_ok=True)
    if result.returncode != 0:
        logger.error("ffmpeg concat stderr: %s", result.stderr.decode(errors="replace")[-3000:])
    return result.returncode == 0


# Gradient palette per scene index — keeps placeholder visually distinct
_PLACEHOLDER_COLORS = [
    ("#1a0533", "#6d28d9"),  # purple
    ("#0f172a", "#7c3aed"),  # indigo
    ("#0c1a2e", "#2563eb"),  # blue
    ("#0f1f0f", "#16a34a"),  # green
    ("#1a0a00", "#ea580c"),  # orange
]


def _make_placeholder_clip(index: int, duration: int, output_path: str) -> bool:
    """Generate a solid gradient placeholder video when no image/video is available."""
    c1, c2 = _PLACEHOLDER_COLORS[index % len(_PLACEHOLDER_COLORS)]
    cmd = [
        _ffmpeg_exe(), "-y",
        "-f", "lavfi",
        "-i", f"color=c={c1}:size=1080x1920:rate=30:duration={duration}",
        "-vf", f"geq=r='between(Y,0,H/2)*(hexint('{c1[1:]}')>>16)+between(Y,H/2,H)*(hexint('{c2[1:]}')>>16)':g='between(Y,0,H/2)*((hexint(\'{c1[1:]}\')>>8)&0xff)+between(Y,H/2,H)*((hexint(\'{c2[1:]}\')>>8)&0xff)':b='between(Y,0,H/2)*(hexint(\'{c1[1:]}\')&0xff)+between(Y,H/2,H)*(hexint(\'{c2[1:]}\')&0xff)'",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-t", str(duration),
        output_path,
    ]
    # Simpler fallback: solid color
    cmd = [
        _ffmpeg_exe(), "-y",
        "-f", "lavfi",
        "-i", f"color=c={c2[1:]}:size=1080x1920:rate=30:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-t", str(duration),
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def _process_scene(scene: Scene, work_dir: Path, job: ReelJob) -> Optional[str]:
    """Download, convert, and mux a single scene. Returns path to scene clip or None."""
    scene_dir = work_dir / f"scene_{scene.index:02d}"
    scene_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Get video source — priority: local Ken Burns clip > remote video URL > image > placeholder
    video_src = None

    # Ken Burns clip generated by video_agent (local path)
    local_clip = getattr(scene, "video_path", None)
    if local_clip and Path(local_clip).exists():
        job.log("editor", "act", f"Scene {scene.index}: using Ken Burns clip")
        video_src = local_clip

    if not video_src and scene.video_url:
        video_dl = scene_dir / "clip.mp4"
        job.log("editor", "act", f"Scene {scene.index}: downloading video clip")
        if _download_file(scene.video_url, video_dl):
            video_src = str(video_dl)
        else:
            job.log("editor", "warn", f"Scene {scene.index}: video download failed, falling back to image")

    if not video_src and scene.image_url:
        img_dl = scene_dir / "scene.jpg"
        job.log("editor", "act", f"Scene {scene.index}: downloading image for static video")
        if _download_file(scene.image_url, img_dl):
            static_video = str(scene_dir / "static.mp4")
            if _image_to_video(str(img_dl), scene.duration_seconds, static_video):
                video_src = static_video

    if not video_src:
        # No image or video — generate a solid-color placeholder so the pipeline still produces a video
        placeholder = str(scene_dir / "placeholder.mp4")
        job.log("editor", "act", f"Scene {scene.index}: no media — generating placeholder clip")
        if _make_placeholder_clip(scene.index, scene.duration_seconds, placeholder):
            video_src = placeholder
        else:
            job.log("editor", "error", f"Scene {scene.index}: placeholder generation failed — skipping")
            return None

    # Step 2: Mux with audio
    muxed = str(scene_dir / "muxed.mp4")
    audio = scene.audio_path if scene.audio_path and Path(scene.audio_path).exists() else None
    if not _mux_video_audio(video_src, audio, scene.duration_seconds, muxed):
        job.log("editor", "warn", f"Scene {scene.index}: mux failed, using raw video")
        muxed = video_src

    scene.video_path = muxed
    return muxed


def run(job: ReelJob) -> ReelJob:
    """
    Stitch all scene clips into a single final video using ffmpeg.
    """
    if not job.script:
        job.error = "No script — run script_agent first"
        job.log("editor", "error", job.error)
        return job

    # ── THINK ─────────────────────────────────────────────────────────────────
    if not _check_ffmpeg():
        job.error = "ffmpeg not found. Install it: https://ffmpeg.org/download.html"
        job.log("editor", "error", job.error)
        return job

    work_dir = Path(job.output_dir) / job.job_id / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    final_dir = Path(job.output_dir) / job.job_id
    final_path = str(final_dir / "final.mp4")

    scenes_to_process = job.script.scenes  # process ALL scenes; placeholders used when no media
    job.log("editor", "think", f"Processing {len(scenes_to_process)} scenes with ffmpeg")

    t0 = time.time()

    # ── ACT ───────────────────────────────────────────────────────────────────
    clip_paths = []
    for scene in scenes_to_process:
        clip = _process_scene(scene, work_dir, job)
        if clip:
            clip_paths.append(clip)

    if not clip_paths:
        job.error = "No clips processed — cannot produce final video"
        job.log("editor", "error", job.error)
        return job

    if len(clip_paths) == 1:
        # Single scene — just copy it
        import shutil as _shutil
        _shutil.copy(clip_paths[0], final_path)
    else:
        job.log("editor", "act", f"Concatenating {len(clip_paths)} clips with xfade transitions")
        if not _concatenate_clips_with_xfade(clip_paths, final_path):
            # Fallback to simple concat if xfade fails (e.g. audio issues)
            job.log("editor", "warn", "xfade failed — falling back to simple concat")
            if not _concatenate_clips(clip_paths, final_path):
                job.error = "ffmpeg concatenation failed — check server logs for details"
                job.log("editor", "error", job.error)
                return job

    elapsed = round(time.time() - t0, 2)

    # ── OBSERVE ───────────────────────────────────────────────────────────────
    expected_total = sum(max(0, int(s.duration_seconds)) for s in scenes_to_process)
    actual_total = round(_get_clip_duration(final_path), 2) if Path(final_path).exists() else 0.0
    drift = round(actual_total - expected_total, 2)
    size_mb = round(os.path.getsize(final_path) / 1024 / 1024, 2) if Path(final_path).exists() else 0
    job.final_video_path = final_path
    job.log(
        "editor",
        "done",
        f"Final video ready in {elapsed}s — {size_mb}MB — duration {actual_total}s "
        f"(expected {expected_total}s, drift {drift}s) → {final_path}",
    )
    return job
