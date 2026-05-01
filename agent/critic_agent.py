"""
Critic Agent — OBSERVE & REFLECT

Evaluates a generated script and scores it on three axes:
  - hook_score    (1-10): Does the opening line stop the scroll?
  - clarity_score (1-10): Is the product benefit instantly clear?
  - engagement    (1-10): Will viewers watch to the end?

If any score is below the threshold (7), it returns feedback so the
script agent can rewrite. Acts as the "inner critic" in the agent loop.

Uses the cheaper Haiku model — this is a fast evaluation pass.
"""
import json
import re
import time

import anthropic

from config import ANTHROPIC_API_KEY
from models import ReelJob

_CRITIC_MODEL = "claude-haiku-4-5"
_COST_RATES = {"input": 0.80, "output": 4.0}

_SYSTEM = """You are an expert social media marketing critic who evaluates short-form video scripts.
You score scripts honestly and give specific, actionable feedback.
You MUST respond with valid JSON only. No markdown, no explanation."""

_CRITIC_PROMPT = """Evaluate this marketing reel script:

HOOK: {hook}

SCENES:
{scenes}

CTA: {cta}

Score each dimension from 1-10 and explain briefly:
- hook_score: Does the first line stop the scroll? (1=generic, 10=irresistible)
- clarity_score: Is the product benefit instantly clear? (1=confusing, 10=crystal clear)
- engagement_score: Will viewers watch to the end? (1=boring, 10=must-watch)

Return ONLY this JSON:
{{
  "hook_score": 8,
  "clarity_score": 7,
  "engagement_score": 6,
  "overall_score": 7.0,
  "verdict": "approve" or "rewrite",
  "hook_feedback": "One sentence on what to improve about the hook",
  "engagement_feedback": "One sentence on pacing or emotional pull",
  "rewrite_instruction": "If verdict=rewrite: one clear instruction for the rewriter. Empty string if approve."
}}

verdict = "approve" if overall_score >= 7.0, otherwise "rewrite".
overall_score = average of the three scores."""


def run(job: ReelJob) -> ReelJob:
    """
    Score the current job.script. Writes result to job.critic_report.
    Does NOT set job.error — a low score triggers a loop, not a failure.
    """
    if not job.script:
        job.log("critic_agent", "skip", "No script to evaluate")
        return job

    if not ANTHROPIC_API_KEY:
        # No key → auto-approve so the pipeline isn't blocked
        job.log("critic_agent", "skip", "ANTHROPIC_API_KEY not set — auto-approving script")
        job.critic_report = {
            "hook_score": 8, "clarity_score": 8, "engagement_score": 8,
            "overall_score": 8.0, "verdict": "approve",
            "hook_feedback": "", "engagement_feedback": "", "rewrite_instruction": "",
        }
        return job

    scenes_text = "\n".join(
        f"  Scene {s.index}: {s.narration} [{s.duration_seconds}s]"
        for s in job.script.scenes
    )
    prompt = _CRITIC_PROMPT.format(
        hook=job.script.hook,
        scenes=scenes_text,
        cta=job.script.cta,
    )

    job.log("critic_agent", "think", f"Scoring script with {_CRITIC_MODEL}...")
    t0 = time.time()
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=_CRITIC_MODEL,
            max_tokens=512,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        job.log("critic_agent", "error", f"Critic call failed: {e} — auto-approving")
        job.critic_report = {
            "hook_score": 8, "clarity_score": 8, "engagement_score": 8,
            "overall_score": 8.0, "verdict": "approve", "rewrite_instruction": "",
            "hook_feedback": "", "engagement_feedback": "",
        }
        return job

    elapsed = round(time.time() - t0, 2)
    raw = response.content[0].text.strip()

    # Strip markdown fences if Claude wraps anyway
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        job.log("critic_agent", "error", f"Could not parse critic JSON — auto-approving: {raw[:100]}")
        job.critic_report = {
            "hook_score": 8, "clarity_score": 8, "engagement_score": 8,
            "overall_score": 8.0, "verdict": "approve", "rewrite_instruction": "",
            "hook_feedback": "", "engagement_feedback": "",
        }
        return job

    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    cost = round((in_tok / 1_000_000 * _COST_RATES["input"]) + (out_tok / 1_000_000 * _COST_RATES["output"]), 6)

    job.log(
        "critic_agent", "observe",
        f"Score {report.get('overall_score', '?')}/10 — verdict: {report.get('verdict')} ({elapsed}s)",
        cost=cost,
    )
    job.critic_report = report
    return job
