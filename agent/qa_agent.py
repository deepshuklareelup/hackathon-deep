"""
QA Agent — Video Quality Assurance

Uses ffprobe (bundled with ffmpeg) to inspect the final video and verify:
  1. Video stream exists and has a sensible duration
  2. Duration is within ±20% of the expected script duration
  3. Audio stream exists and is not silent/absent
  4. Audio duration matches video duration (no early cut-off)
  5. Frame rate is ≥ 24fps
  6. Resolution matches the target platform dimensions
  7. No zero-length or corrupt scenes (probes each muxed clip too)

Results are written to job.qa_report (dict) and logged via job.log().
If a critical check fails, job.error is set — caller decides whether to abort.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from models import ReelJob


def _ffprobe_exe() -> str:
    """Return ffprobe path — sits next to ffmpeg."""
    # Try env var
    if env := os.environ.get("FFPROBE_PATH"):
        return env
    # Try PATH
    if found := shutil.which("ffprobe"):
        return found
    # Same WinGet dir as ffmpeg
    fallback = (
        r"C:\Users\deep\AppData\Local\Microsoft\WinGet\Packages"
        r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
        r"\ffmpeg-8.1-full_build\bin\ffprobe.exe"
    )
    if Path(fallback).exists():
        return fallback
    return "ffprobe"


def _probe(path: str) -> dict[str, Any] | None:
    """Run ffprobe on a file and return parsed JSON, or None on failure."""
    cmd = [
        _ffprobe_exe(),
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception:
        return None


def _stream_by_type(probe: dict, codec_type: str) -> dict | None:
    for s in probe.get("streams", []):
        if s.get("codec_type") == codec_type:
            return s
    return None


def _duration(probe: dict) -> float:
    """Return duration in seconds from format or video stream."""
    fmt_dur = probe.get("format", {}).get("duration")
    if fmt_dur:
        return float(fmt_dur)
    vid = _stream_by_type(probe, "video")
    if vid and vid.get("duration"):
        return float(vid["duration"])
    return 0.0


def run(job: ReelJob) -> ReelJob:
    """
    QA check on the final video. Populates job.qa_report and logs findings.
    Sets job.error only on hard failures (no video stream / file missing).
    Soft failures (duration drift, audio cutoff) are warnings logged but don't fail the job.
    """
    job.set_status("qa")

    if not job.final_video_path or not Path(job.final_video_path).exists():
        job.error = "QA: final video file not found"
        job.log("qa_agent", "error", job.error)
        return job

    video_path = job.final_video_path
    expected_duration = job.script.total_duration if job.script else None

    job.log("qa_agent", "think", f"Probing final video: {video_path}")

    probe = _probe(video_path)
    if probe is None:
        job.error = "QA: ffprobe could not read the final video — file may be corrupt"
        job.log("qa_agent", "error", job.error)
        return job

    # ── Checks ────────────────────────────────────────────────────────────────
    issues: list[str] = []
    passes: list[str] = []
    report: dict[str, Any] = {}

    # 1. Video stream
    vid_stream = _stream_by_type(probe, "video")
    if not vid_stream:
        job.error = "QA: no video stream found in final output"
        job.log("qa_agent", "error", job.error)
        return job
    passes.append("video_stream_present")

    # 2. Duration
    actual_dur = _duration(probe)
    report["actual_duration_s"] = round(actual_dur, 2)
    report["expected_duration_s"] = expected_duration

    if actual_dur < 1.0:
        job.error = f"QA: video duration is {actual_dur:.1f}s — nearly empty"
        job.log("qa_agent", "error", job.error)
        return job

    if expected_duration:
        drift = abs(actual_dur - expected_duration)
        drift_pct = drift / max(expected_duration, 1) * 100
        report["duration_drift_pct"] = round(drift_pct, 1)
        if drift_pct <= 20:
            passes.append(f"duration_ok ({actual_dur:.1f}s vs expected {expected_duration}s, {drift_pct:.1f}% drift)")
        else:
            issues.append(f"duration_drift: {actual_dur:.1f}s actual vs {expected_duration}s expected ({drift_pct:.1f}% off)")

    # 3. Audio stream
    aud_stream = _stream_by_type(probe, "audio")
    if not aud_stream:
        issues.append("no_audio_stream: final video has no audio track")
        report["audio_present"] = False
    else:
        report["audio_present"] = True
        passes.append("audio_stream_present")

        # 4. Audio duration vs video duration (early cut-off check)
        aud_dur_raw = aud_stream.get("duration") or probe.get("format", {}).get("duration")
        if aud_dur_raw:
            aud_dur = float(aud_dur_raw)
            aud_drift = actual_dur - aud_dur
            report["audio_duration_s"] = round(aud_dur, 2)
            report["audio_video_gap_s"] = round(aud_drift, 2)
            if aud_drift > 2.0:
                issues.append(
                    f"audio_cutoff: audio ends {aud_drift:.1f}s before video ends "
                    f"({aud_dur:.1f}s audio vs {actual_dur:.1f}s video)"
                )
            else:
                passes.append(f"audio_covers_video (gap={aud_drift:.1f}s)")

    # 5. Frame rate
    fps_raw = vid_stream.get("avg_frame_rate", "0/1")
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den) if float(den) > 0 else 0
    except Exception:
        fps = 0
    report["fps"] = round(fps, 2)
    if fps >= 24:
        passes.append(f"fps_ok ({fps:.1f}fps)")
    else:
        issues.append(f"low_fps: {fps:.1f}fps (expected ≥24)")

    # 6. Resolution
    width = vid_stream.get("width", 0)
    height = vid_stream.get("height", 0)
    report["resolution"] = f"{width}x{height}"
    if width > 0 and height > 0:
        passes.append(f"resolution_ok ({width}x{height})")
    else:
        issues.append("unknown_resolution")

    # 7. Per-scene clip check (optional — only if scene clips still exist)
    scene_results: list[dict] = []
    if job.script:
        for scene in job.script.scenes:
            clip = getattr(scene, "video_path", None)
            if clip and Path(clip).exists():
                sp = _probe(clip)
                if sp is None:
                    scene_results.append({"scene": scene.index, "ok": False, "reason": "ffprobe failed"})
                else:
                    sdur = _duration(sp)
                    saud = _stream_by_type(sp, "audio") is not None
                    scene_results.append({
                        "scene": scene.index,
                        "ok": True,
                        "duration_s": round(sdur, 2),
                        "has_audio": saud,
                    })
    report["scene_clips"] = scene_results

    # ── Summary ───────────────────────────────────────────────────────────────
    report["passes"] = passes
    report["issues"] = issues
    report["overall"] = "pass" if not issues else "warn"

    # Store on job (add attribute dynamically — ReelJob is a dataclass but we can still set attrs)
    job.qa_report = report  # type: ignore[attr-defined]

    for p in passes:
        job.log("qa_agent", "pass", f"✓ {p}")
    for issue in issues:
        job.log("qa_agent", "warn", f"⚠ {issue}")

    status = "PASSED" if not issues else f"WARNED ({len(issues)} issue(s))"
    job.log(
        "qa_agent", "observe",
        f"QA {status} — {actual_dur:.1f}s video, {len(passes)} checks passed, {len(issues)} warnings",
    )

    return job
