"""
Orchestrator — The master coordinator.

Implements the full Think → Act → Observe pipeline across all agents.
Supports human-in-the-loop approval before expensive video/audio generation.
Tracks costs and logs every step.
"""
import uuid
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from agent import script_agent, image_agent, video_agent, tts_agent, editor, uploader
from agent.tracer import export_trace
from config import validate_keys
from models import ReelJob, ProductInput

console = Console()


def _print_script_summary(job: ReelJob):
    """Pretty-print the generated script for human review."""
    script = job.script
    console.print()
    console.print(Panel(f"[bold cyan]HOOK:[/bold cyan] {script.hook}", title="Generated Script", border_style="cyan"))

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
    table.add_column("Scene", style="dim", width=6)
    table.add_column("Narration", width=40)
    table.add_column("Visual", width=40)
    table.add_column("Dur.", width=5)

    for scene in script.scenes:
        table.add_row(
            str(scene.index + 1),
            scene.narration,
            scene.visual_direction[:60] + ("..." if len(scene.visual_direction) > 60 else ""),
            f"{scene.duration_seconds}s",
        )
    console.print(table)
    console.print(Panel(f"[bold green]CTA:[/bold green] {script.cta}", border_style="green"))
    console.print(f"[dim]Total duration: ~{script.total_duration}s | Scenes: {script.scene_count}[/dim]")
    console.print()


def _print_cost_summary(job: ReelJob):
    """Print cost breakdown at end of pipeline."""
    table = Table(title="Cost Summary", box=box.SIMPLE, show_header=True, header_style="bold yellow")
    table.add_column("Stage", style="cyan")
    table.add_column("Cost (USD)", justify="right", style="yellow")

    for stage, cost in job.costs.items():
        if cost > 0:
            table.add_row(stage, f"${cost:.6f}")

    table.add_row("[bold]TOTAL[/bold]", f"[bold]${job.total_cost:.4f}[/bold]")
    console.print(table)


def run(
    product: ProductInput,
    output_dir: str = "./output",
    human_approval: bool = True,
) -> ReelJob:
    """
    Full pipeline: script → images → video → TTS → edit → upload.

    Args:
        product: ProductInput data class with all product details
        output_dir: Where to save intermediate files and final video
        human_approval: If True, pause after script generation for user approval
    """
    job_id = uuid.uuid4().hex[:8]
    job = ReelJob(job_id=job_id, product=product, output_dir=output_dir)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # ── Preflight check ───────────────────────────────────────────────────────
    keys = validate_keys()
    console.print(Panel(
        "\n".join(f"{'✅' if v else '❌'} [bold]{k}[/bold]" for k, v in keys.items()),
        title=f"[bold]Rofy Reel Agent — Job {job_id}[/bold]",
        subtitle=f"Product: {product.name} | Platform: {product.platform}",
        border_style="blue",
    ))

    if not keys["script_agent"]:
        console.print("[red]❌ ANTHROPIC_API_KEY missing — cannot continue[/red]")
        job.error = "ANTHROPIC_API_KEY not configured"
        job.status = "failed"
        return job

    # ── Stage 1: Script Generation ────────────────────────────────────────────
    job.set_status("scripting")
    console.print("\n[bold blue]Stage 1/6:[/bold blue] Generating script...")

    job = script_agent.run(job)
    if job.error or not job.script:
        console.print(f"[red]Script generation failed: {job.error}[/red]")
        job.status = "failed"
        return job

    _print_script_summary(job)

    # ── Human-in-the-loop: Script Approval ────────────────────────────────────
    if human_approval:
        answer = console.input(
            "[bold yellow]▶ Approve script and continue to image/video generation? (y/n/edit): [/bold yellow]"
        ).strip().lower()

        if answer == "n":
            console.print("[yellow]Pipeline stopped by user.[/yellow]")
            job.status = "stopped"
            return job
        elif answer == "edit":
            console.print("[dim]Manual edit not yet supported — continuing with current script.[/dim]")

    # ── Stage 2: Image Generation ─────────────────────────────────────────────
    job.set_status("imaging")
    console.print("\n[bold blue]Stage 2/6:[/bold blue] Generating scene images (FLUX)...")

    if keys["image_agent"]:
        job = image_agent.run(job)
        images_ok = sum(1 for s in job.script.scenes if s.image_url)
        console.print(f"[green]✅ {images_ok}/{len(job.script.scenes)} images generated[/green]")
    else:
        console.print("[yellow]⚠ FAL_KEY not set — skipping image generation[/yellow]")

    # ── Stage 3: Video Clip Generation ───────────────────────────────────────
    job.set_status("videoing")
    console.print("\n[bold blue]Stage 3/6:[/bold blue] Generating video clips (ltx-video)...")

    if keys["video_agent"]:
        job = video_agent.run(job)
        clips_ok = sum(1 for s in job.script.scenes if s.video_url)
        console.print(f"[green]✅ {clips_ok}/{len(job.script.scenes)} video clips generated[/green]")
    else:
        console.print("[yellow]⚠ FAL_KEY not set — will use static images as video[/yellow]")

    # ── Stage 4: TTS Narration ────────────────────────────────────────────────
    job.set_status("tts")
    console.print("\n[bold blue]Stage 4/6:[/bold blue] Generating narration audio (OpenAI TTS)...")

    if keys["tts_agent"]:
        job = tts_agent.run(job)
        audio_ok = sum(1 for s in job.script.scenes if s.audio_path)
        console.print(f"[green]✅ {audio_ok}/{len(job.script.scenes)} audio files generated[/green]")
    else:
        console.print("[yellow]⚠ OPENAI_API_KEY not set — skipping TTS[/yellow]")

    # ── Stage 5: Video Editing ────────────────────────────────────────────────
    job.set_status("editing")
    console.print("\n[bold blue]Stage 5/6:[/bold blue] Stitching final video (ffmpeg)...")

    job = editor.run(job)
    if job.error:
        console.print(f"[red]Editing failed: {job.error}[/red]")
        job.status = "failed"
        _print_cost_summary(job)
        return job

    console.print(f"[green]✅ Video stitched: {job.final_video_path}[/green]")

    # ── Stage 6: Upload ───────────────────────────────────────────────────────
    job.set_status("uploading")
    console.print("\n[bold blue]Stage 6/6:[/bold blue] Uploading to GCS...")

    job = uploader.run(job)
    job.status = "done"

    # ── Export structured trace ───────────────────────────────────────────────
    trace_path = export_trace(job)
    job.log("orchestrator", "trace_exported", f"Trace saved to {trace_path}")

    # ── Final Summary ─────────────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        f"[bold green]✅ Reel Complete![/bold green]\n\n"
        f"[bold]Local:[/bold] {job.final_video_path}\n"
        f"[bold]URL:[/bold]   {job.final_video_url or 'N/A'}\n"
        f"[bold]Job ID:[/bold] {job.job_id}",
        title="Done",
        border_style="green",
    ))
    _print_cost_summary(job)
    return job
