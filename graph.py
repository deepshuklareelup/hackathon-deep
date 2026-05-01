"""
graph.py — LangGraph pipeline for Rofy Reel Agent.

Defines a StateGraph where each node is one stage of the reel production pipeline:

  script_node → image_node → video_node → tts_node → edit_node → upload_node → END

The shared state is the ReelJob dataclass (passed as a typed dict wrapper).
Each node calls the existing agent module and returns the mutated job.
Conditional edges skip stages when API keys are missing.
"""
from __future__ import annotations

import operator
import uuid
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.types import Command, RetryPolicy, interrupt

from agent import script_agent, image_agent, video_agent, tts_agent, editor, uploader, qa_agent, critic_agent
from agent.tracer import export_trace
from config import validate_keys
from models import ReelJob, ProductInput


# ── State ─────────────────────────────────────────────────────────────────────

class GraphState(TypedDict):
    """Single shared state object flowing through all nodes."""
    job: ReelJob
    # Accumulates via operator.add — counts critic-driven rewrites 
    script_rewrites: Annotated[int, operator.add]
    # Accumulates via operator.add — counts QA-driven edit retries
    qa_retries: Annotated[int, operator.add]


# ── Node functions ─────────────────────────────────────────────────────────────

def node_script(state: GraphState) -> GraphState:
    """Stage 1: Generate script with Claude (smart model routing + caching)."""
    job = state["job"]
    job.set_status("scripting")
    job = script_agent.run(job)
    return {"job": job}


def node_image(state: GraphState) -> GraphState:
    """Stage 2: Generate scene images with fal.ai FLUX (with retry + image cache)."""
    job = state["job"]
    job.set_status("imaging")
    keys = validate_keys()
    if keys["image_agent"]:
        job = image_agent.run(job)
    else:
        job.log("image_node", "skipped", "FAL_KEY not configured — skipping image generation")
    return {"job": job}


def node_video(state: GraphState) -> GraphState:
    """Stage 3: Generate video clips with fal.ai ltx-video (with retry)."""
    job = state["job"]
    job.set_status("videoing")
    keys = validate_keys()
    if keys["video_agent"]:
        job = video_agent.run(job)
    else:
        job.log("video_node", "skipped", "FAL_KEY not configured — skipping video clip generation")
    return {"job": job}


def node_tts(state: GraphState) -> GraphState:
    """Stage 4: Generate narration audio with OpenAI TTS."""
    job = state["job"]
    job.set_status("tts")
    keys = validate_keys()
    if keys["tts_agent"]:
        job = tts_agent.run(job)
    else:
        job.log("tts_node", "skipped", "OPENAI_API_KEY not configured — skipping TTS")
    return {"job": job}


def node_edit(state: GraphState) -> GraphState:
    """Stage 5: Stitch final video with ffmpeg."""
    job = state["job"]
    job.set_status("editing")
    job = editor.run(job)
    return {"job": job}


def node_upload(state: GraphState) -> GraphState:
    """Stage 6: Upload final video to GCS (optional)."""
    job = state["job"]
    job.set_status("uploading")
    job = uploader.run(job)
    job.set_status("done")
    export_trace(job)
    return {"job": job}


# ── Conditional edges ──────────────────────────────────────────────────────────

def node_critic(state: GraphState) -> dict:
    """
    OBSERVE stage — Score the generated script on hook, clarity, engagement.
    If verdict is 'rewrite', route_after_critic sends us back to script_node
    with the rewrite_instruction injected as human_feedback. (04_cycles_loops)
    """
    job = state["job"]
    critic_agent.run(job)
    return {"job": job, "script_rewrites": 1}   # accumulates each critic pass


def route_after_critic(state: GraphState) -> Literal["node_review", "script_node"]:
    """Loop back to rewrite if score < 7, max 2 rewrites, then always proceed."""
    job = state["job"]
    report = getattr(job, "critic_report", {}) or {}
    verdict = report.get("verdict", "approve")
    rewrites = state["script_rewrites"]

    if verdict == "rewrite" and rewrites <= 2:
        # Inject the critic's feedback so script_agent can use it
        job.human_feedback = report.get("rewrite_instruction", "")
        job.log("critic_agent", "rewrite",
                f"Score {report.get('overall_score', '?')}/10 — requesting rewrite (attempt {rewrites}): {job.human_feedback}")
        return "script_node"

    job.log("critic_agent", "approve",
            f"Score {report.get('overall_score', '?')}/10 — proceeding to human review")
    return "node_review"


def node_review(state: GraphState) -> dict:
    """
    HUMAN-IN-THE-LOOP — pause graph here for human script approval.

    The graph suspends. server.py catches the interrupt, emits an SSE 'review'
    event with the script + critic scores, and waits for the user to click
    Approve or send feedback via POST /api/jobs/{job_id}/resume.

    When resumed:
      - Command(resume='approved') → continues to image_node
      - Command(resume='<feedback text>') → back to script_node with that feedback
    """
    job = state["job"]
    critic = getattr(job, "critic_report", {}) or {}

    # Build the payload shown to the human
    script_preview = None
    if job.script:
        script_preview = {
            "hook": job.script.hook,
            "cta": job.script.cta,
            "total_duration": job.script.total_duration,
            "scenes": [
                {"index": s.index, "narration": s.narration,
                 "duration": s.duration_seconds, "visual_direction": s.visual_direction}
                for s in job.script.scenes
            ],
        }

    # interrupt() suspends the graph — invoke() returns to the caller.
    # When caller does invoke(Command(resume=value), config=...), we continue.
    human_decision = interrupt({
        "job_id": job.job_id,
        "script": script_preview,
        "critic": {
            "hook_score":        critic.get("hook_score"),
            "clarity_score":     critic.get("clarity_score"),
            "engagement_score":  critic.get("engagement_score"),
            "overall_score":     critic.get("overall_score"),
            "hook_feedback":     critic.get("hook_feedback", ""),
            "engagement_feedback": critic.get("engagement_feedback", ""),
        },
    })

    job.human_feedback = human_decision
    job.log("node_review", "human_decision", f"Human responded: {str(human_decision)[:80]}")
    return {"job": job}


def route_after_review(state: GraphState) -> Literal["image_node", "script_node"]:
    """Approved → image generation. Feedback text → rewrite script."""
    job = state["job"]
    decision = getattr(job, "human_feedback", "approved") or "approved"
    if decision.strip().lower() == "approved":
        job.human_feedback = None   # clear so script_agent won't re-use it
        return "image_node"
    # Human gave feedback — use it as rewrite instruction
    job.log("node_review", "rewrite", f"Human requested changes: {decision[:80]}")
    return "script_node"


def node_qa(state: GraphState) -> dict:
    """Stage 6: Run ffprobe QA checks on the final stitched video."""
    job = state["job"]
    qa_agent.run(job)
    # Returning qa_retries: 1 accumulates via operator.add each time QA runs.
    # First pass → qa_retries=1, retry pass → qa_retries=2, etc.
    return {"job": job, "qa_retries": 1}


def route_after_qa(state: GraphState) -> Literal["upload_node", "edit_node", "__end__"]:
    """Cycle back to edit_node if QA found a hard failure (max 2 retries)."""
    job = state["job"]
    retries = state["qa_retries"]
    if job.error:
        if retries < 2:
            job.log("qa_agent", "retry", f"Hard failure on QA pass {retries} — retrying edit stage")
            job.error = None  # clear so the editor can attempt a fresh stitch
            return "edit_node"
        job.status = "failed"
        return "__end__"
    return "upload_node"


def route_after_script(state: GraphState) -> Literal["node_critic", "__end__"]:
    """Stop the graph early if script generation failed, else move to critic."""
    job = state["job"]
    if job.error or not job.script:
        job.status = "failed"
        return "__end__"
    return "node_critic"


def route_after_edit(state: GraphState) -> Literal["qa_node", "__end__"]:
    """Stop early if ffmpeg editing failed, otherwise proceed to QA."""
    job = state["job"]
    if job.error:
        job.status = "failed"
        return "__end__"
    return "qa_node"


# ── Build the graph ────────────────────────────────────────────────────────────

# Shared in-memory checkpointer — survives within the process.
# Lets run_graph() resume from the last successful node if re-invoked
# with the same thread_id (i.e. the same job_id). (07_checkpointing)
_checkpointer = MemorySaver()


def build_graph() -> StateGraph:
    """Construct and compile the LangGraph StateGraph."""
    g = StateGraph(GraphState)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    # script_node: Claude call — no RetryPolicy needed, script_agent handles its own retries
    g.add_node("script_node", node_script)
    g.add_node("node_critic",  node_critic)  # OBSERVE: score script (04_cycles_loops)
    g.add_node("node_review",  node_review)  # HUMAN-IN-THE-LOOP: interrupt() (21_interrupt)

    # image_node / video_node: external HTTP APIs — RetryPolicy handles transient failures
    # (23_error_handling: RetryPolicy with exponential back-off)
    g.add_node(
        "image_node", node_image,
        retry=RetryPolicy(max_attempts=3, backoff_factor=2.0, initial_interval=1.0),
    )
    g.add_node(
        "video_node", node_video,
        retry=RetryPolicy(max_attempts=3, backoff_factor=2.0, initial_interval=1.0),
    )
    # tts_node: OpenAI TTS — slightly longer back-off for rate limits
    g.add_node(
        "tts_node", node_tts,
        retry=RetryPolicy(max_attempts=3, backoff_factor=2.0, initial_interval=2.0),
    )

    g.add_node("edit_node",   node_edit)
    g.add_node("qa_node",     node_qa)   # QA with retry loop (04_cycles_loops)
    g.add_node("upload_node", node_upload)

    # ── Edges ─────────────────────────────────────────────────────────────────
    g.set_entry_point("script_node")

    # After script: fail-fast on error, else score with critic
    g.add_conditional_edges("script_node", route_after_script)

    # Critic loop: rewrite up to 2× if score < 7, then pause for human (04_cycles_loops)
    g.add_conditional_edges("node_critic", route_after_critic)

    # Human review interrupt: approved → images, feedback → rewrite (21_interrupt)
    g.add_conditional_edges("node_review", route_after_review)

    # Linear pipeline: images → video clips → narration audio → stitch
    g.add_edge("image_node",  "video_node")
    g.add_edge("video_node",  "tts_node")
    g.add_edge("tts_node",    "edit_node")

    # After editing: fail-fast on ffmpeg error, otherwise QA
    g.add_conditional_edges("edit_node", route_after_edit)

    # QA cycle: if hard failure → back to edit_node (up to 2 retries)
    # (04_cycles_loops pattern: conditional edge that routes BACK to an earlier node)
    g.add_conditional_edges("qa_node", route_after_qa)

    g.add_edge("upload_node", END)

    # Compile with MemorySaver so each job_id is a resumable checkpoint thread
    return g.compile(checkpointer=_checkpointer)


# Compiled graph — importable singleton
reel_graph = build_graph()


# ── Public API ─────────────────────────────────────────────────────────────────

def run_graph(product: ProductInput, output_dir: str = "./output") -> ReelJob:
    """
    Run the full reel pipeline via LangGraph.

    Args:
        product: ProductInput with all product details.
        output_dir: Directory for intermediate and final files.

    Returns:
        Final ReelJob with status='done' (or 'failed').
    """
    job_id = uuid.uuid4().hex[:8]
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    job = ReelJob(job_id=job_id, product=product, output_dir=output_dir)
    initial_state: GraphState = {"job": job, "qa_retries": 0, "script_rewrites": 0}
    # thread_id ties this run to a unique checkpoint slot (07_checkpointing).
    # Re-invoking with the same job_id resumes from the last successful node.
    config = {"configurable": {"thread_id": job.job_id}}
    final_state: GraphState = reel_graph.invoke(initial_state, config=config)
    return final_state["job"]


def run_graph_script_only(product: ProductInput, output_dir: str = "./output") -> ReelJob:
    """
    Run only Stage 1 (script generation) — used by the FastAPI /api/generate/script endpoint
    so the user can review the script before committing to expensive image/video generation.
    """
    job_id = uuid.uuid4().hex[:8]
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    job = ReelJob(job_id=job_id, product=product, output_dir=output_dir)
    job.set_status("scripting")
    job = script_agent.run(job)
    return job
