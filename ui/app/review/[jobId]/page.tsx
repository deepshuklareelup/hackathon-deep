"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { getJob, resumeJob, streamFullPipeline, type ReelJob } from "@/lib/api";
import {
  Loader2,
  CheckCircle,
  Clock,
  Mic2,
  Film,
  Clapperboard,
  Bot,
  MessageSquare,
  ArrowLeft,
} from "lucide-react";

/* ── Shared nav bar ──────────────────────────────────────────────────────── */
function NavBar({ sub }: { sub: string }) {
  return (
    <div className="flex items-center gap-2.5 mb-8">
      <div
        className="w-7 h-7 rounded-lg flex items-center justify-center text-white font-bold text-xs"
        style={{ background: "var(--accent)" }}
      >
        R
      </div>
      <span className="text-white font-semibold text-base tracking-tight">
        Rofy <span style={{ color: "var(--text-3)" }}>/</span>{" "}
        <span style={{ color: "var(--text-2)" }}>{sub}</span>
      </span>
    </div>
  );
}

/* ── Score bar ───────────────────────────────────────────────────────────── */
function ScoreBar({ label, score }: { label: string; score?: number }) {
  const pct = score ? Math.round((score / 10) * 100) : 0;
  const barColor =
    pct >= 70 ? "var(--accent)" : pct >= 50 ? "#facc15" : "#ef4444";
  return (
    <div>
      <div
        className="flex justify-between text-[12px] mb-1"
        style={{ color: "var(--text-2)" }}
      >
        <span>{label}</span>
        <span className="text-white font-semibold">{score ?? "—"}/10</span>
      </div>
      <div
        className="h-1.5 rounded-full overflow-hidden"
        style={{ background: "rgba(255,255,255,0.07)" }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, background: barColor }}
        />
      </div>
    </div>
  );
}

/* ── Card ────────────────────────────────────────────────────────────────── */
function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl p-5 ${className}`}
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border-md)",
      }}
    >
      {children}
    </div>
  );
}

/* ── Section label ───────────────────────────────────────────────────────── */
function SLabel({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      className="flex items-center gap-2 text-[13px] font-semibold mb-3"
      style={{ color: "var(--text-2)" }}
    >
      <span style={{ color: "var(--accent)" }}>{icon}</span>
      {children}
    </div>
  );
}

export default function ReviewPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const router = useRouter();
  const [job, setJob] = useState<ReelJob | null>(null);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [showFeedback, setShowFeedback] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [rewriting, setRewriting] = useState(false);
  const [rewriteMessage, setRewriteMessage] = useState("");
  const [rewriteError, setRewriteError] = useState("");

  useEffect(() => {
    getJob(jobId)
      .then(setJob)
      .catch((e: Error) => setError(e.message));
  }, [jobId]);

  async function handleApprove() {
    setSubmitting(true);
    try {
      await resumeJob(jobId, "approved");
    } catch {
      /* non-fatal */
    }
    router.push(`/generate/${jobId}`);
  }

  async function handleRequestRewrite() {
    if (!feedback.trim()) return;
    setSubmitting(true);
    setRewriting(true);
    setRewriteError("");
    setRewriteMessage("Sending feedback…");
    try {
      await resumeJob(jobId, feedback.trim());
    } catch {
      /* non-fatal */
    }
    setRewriteMessage("Rewriting script…");
    streamFullPipeline(
      jobId,
      (evt) => {
        if (evt.message) setRewriteMessage(evt.message);
      },
      () => {
        /* full pipeline done — not expected here */
      },
      (err) => {
        setRewriteError(err);
        setRewriting(false);
        setSubmitting(false);
      },
      () => {
        // rewrite_done — refresh job data in place
        setRewriteMessage("Loading updated script…");
        getJob(jobId)
          .then((updated) => {
            setJob(updated);
            setRewriting(false);
            setSubmitting(false);
            setShowFeedback(false);
            setFeedback("");
            setRewriteMessage("");
          })
          .catch(() => {
            setRewriting(false);
            setSubmitting(false);
          });
      },
    );
  }

  /* ── Loading / error states ─────────────────────────────────────────────── */
  if (error) {
    return (
      <main
        className="min-h-screen flex items-center justify-center p-4"
        style={{ background: "var(--bg-base)" }}
      >
        <Card className="max-w-sm w-full text-center">
          <p
            className="text-base font-semibold mb-1"
            style={{ color: "#f87171" }}
          >
            Error loading script
          </p>
          <p className="text-sm mb-4" style={{ color: "var(--text-2)" }}>
            {error}
          </p>
          <button
            onClick={() => router.push("/")}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white"
            style={{ background: "var(--accent)" }}
          >
            Start Over
          </button>
        </Card>
      </main>
    );
  }

  if (!job || !job.script) {
    return (
      <main
        className="min-h-screen flex items-center justify-center"
        style={{ background: "var(--bg-base)" }}
      >
        <div className="text-center space-y-2">
          <Loader2
            size={32}
            className="animate-spin mx-auto"
            style={{ color: "var(--accent)" }}
          />
          <p className="text-sm" style={{ color: "var(--text-3)" }}>
            {!job ? "Loading job…" : "Waiting for script…"}
          </p>
        </div>
      </main>
    );
  }

  const script = job.script;

  return (
    <main
      className="min-h-screen px-4 py-10"
      style={{ background: "var(--bg-base)" }}
    >
      <div className="max-w-2xl mx-auto">
        <NavBar sub="Script Review" />

        {/* Heading */}
        <div className="mb-6">
          <h1 className="text-[1.6rem] font-semibold text-white tracking-tight mb-1">
            Review your script
          </h1>
          <p className="text-sm" style={{ color: "var(--text-2)" }}>
            Check every scene, then approve or request changes.
          </p>
          {script.model_used && (
            <span
              className="inline-block mt-2 text-[11px] font-medium rounded-md px-2.5 py-1"
              style={{
                background: "var(--bg-card)",
                border: "1px solid var(--border-md)",
                color: "var(--text-2)",
              }}
            >
              Model: {script.model_used}
            </span>
          )}
        </div>

        {/* Rewriting banner */}
        {rewriting && (
          <div
            className="flex items-center gap-3 rounded-xl px-4 py-3 mb-4 text-sm font-medium"
            style={{
              background: "rgba(255,98,0,0.10)",
              border: "1px solid rgba(255,98,0,0.25)",
              color: "var(--accent)",
            }}
          >
            <Loader2 size={16} className="animate-spin shrink-0" />
            {rewriteMessage || "Rewriting script…"}
          </div>
        )}

        {/* Rewrite error */}
        {rewriteError && (
          <div
            className="flex items-center gap-3 rounded-xl px-4 py-3 mb-4 text-sm"
            style={{
              background: "rgba(239,68,68,0.10)",
              border: "1px solid rgba(239,68,68,0.25)",
              color: "#f87171",
            }}
          >
            {rewriteError}
          </div>
        )}

        <div className="space-y-4">
          {/* Hook */}
          <Card>
            <SLabel icon={<Mic2 size={14} />}>Hook</SLabel>
            <p className="text-white text-[15px] italic leading-relaxed">
              &ldquo;{script.hook}&rdquo;
            </p>
          </Card>

          {/* Scenes */}
          <Card>
            <SLabel icon={<Clapperboard size={14} />}>
              Scenes ({script.scenes.length})
            </SLabel>
            <div className="space-y-3">
              {script.scenes.map((scene, i) => (
                <div
                  key={i}
                  className="rounded-lg p-4"
                  style={{
                    background: "var(--bg-input)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span
                      className="text-[11px] font-bold uppercase tracking-wider"
                      style={{ color: "var(--accent)" }}
                    >
                      Scene {i + 1}
                    </span>
                    <span
                      className="flex items-center gap-1 text-[11px]"
                      style={{ color: "var(--text-3)" }}
                    >
                      <Clock size={11} /> {scene.duration}s
                    </span>
                  </div>
                  <p className="text-white text-sm leading-relaxed mb-2">
                    {scene.narration}
                  </p>
                  <p
                    className="text-[12px] italic leading-relaxed"
                    style={{ color: "var(--text-3)" }}
                  >
                    ↳ {scene.image_prompt}
                  </p>
                </div>
              ))}
            </div>
          </Card>

          {/* CTA */}
          <Card>
            <SLabel icon={<Film size={14} />}>Call to Action</SLabel>
            <p className="text-white text-[15px] italic leading-relaxed">
              &ldquo;{script.cta}&rdquo;
            </p>
          </Card>

          {/* Stats */}
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: "Duration", value: `${script.total_duration}s` },
              { label: "Scenes", value: String(script.scenes.length) },
              {
                label: "Script cost",
                value:
                  script.cost_usd != null
                    ? `$${script.cost_usd.toFixed(4)}`
                    : "—",
              },
            ].map(({ label, value }) => (
              <div
                key={label}
                className="rounded-xl p-4 text-center"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border-md)",
                }}
              >
                <p
                  className="text-xl font-bold"
                  style={{ color: "var(--accent)" }}
                >
                  {value}
                </p>
                <p
                  className="text-[11px] mt-1"
                  style={{ color: "var(--text-3)" }}
                >
                  {label}
                </p>
              </div>
            ))}
          </div>

          {/* AI Critic */}
          {job.critic_report && (
            <Card>
              <div className="flex items-center justify-between mb-4">
                <SLabel icon={<Bot size={14} />}>AI Critic Analysis</SLabel>
                <span
                  className="text-[11px] font-semibold px-2.5 py-1 rounded-md"
                  style={
                    job.critic_report.verdict === "approve"
                      ? {
                          background: "rgba(255,98,0,0.12)",
                          color: "var(--accent)",
                          border: "1px solid rgba(255,98,0,0.25)",
                        }
                      : {
                          background: "rgba(250,204,21,0.10)",
                          color: "#facc15",
                          border: "1px solid rgba(250,204,21,0.25)",
                        }
                  }
                >
                  {job.critic_report.verdict === "approve"
                    ? "Looks good"
                    : "Needs work"}{" "}
                  · {job.critic_report.overall_score?.toFixed(1)}/10
                </span>
              </div>
              <div className="space-y-3 mb-4">
                <ScoreBar
                  label="Hook strength"
                  score={job.critic_report.hook_score}
                />
                <ScoreBar
                  label="Clarity"
                  score={job.critic_report.clarity_score}
                />
                <ScoreBar
                  label="Engagement"
                  score={job.critic_report.engagement_score}
                />
              </div>
              {job.critic_report.hook_feedback && (
                <p
                  className="text-[13px] mb-1 leading-relaxed"
                  style={{ color: "var(--text-2)" }}
                >
                  <span style={{ color: "var(--text-3)" }}>Hook — </span>
                  {job.critic_report.hook_feedback}
                </p>
              )}
              {job.critic_report.engagement_feedback && (
                <p
                  className="text-[13px] leading-relaxed"
                  style={{ color: "var(--text-2)" }}
                >
                  <span style={{ color: "var(--text-3)" }}>Engagement — </span>
                  {job.critic_report.engagement_feedback}
                </p>
              )}
            </Card>
          )}

          {/* Feedback textarea */}
          {showFeedback && (
            <Card>
              <label
                className="text-[13px] font-medium flex items-center gap-2 mb-3"
                style={{ color: "var(--text-2)" }}
              >
                <MessageSquare size={14} style={{ color: "var(--accent)" }} />{" "}
                What should be changed?
              </label>
              <textarea
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                rows={3}
                placeholder="e.g. Make the hook more urgent, add price in scene 2..."
                className="w-full rounded-lg px-3.5 py-2.5 text-sm text-white placeholder-[#444] resize-none mb-3 transition-all"
                style={{
                  background: "var(--bg-input)",
                  border: "1px solid var(--border-md)",
                }}
                onFocus={(e) =>
                  ((e.target as HTMLTextAreaElement).style.borderColor =
                    "var(--accent)")
                }
                onBlur={(e) =>
                  ((e.target as HTMLTextAreaElement).style.borderColor =
                    "var(--border-md)")
                }
              />
              <div className="flex gap-2">
                <button
                  onClick={() => setShowFeedback(false)}
                  className="px-4 py-2 rounded-lg text-sm text-white"
                  style={{
                    background: "var(--bg-hover)",
                    border: "1px solid var(--border-md)",
                  }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleRequestRewrite}
                  disabled={!feedback.trim() || submitting}
                  className="flex-1 py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-50 flex items-center justify-center gap-2"
                  style={{ background: "#854d0e" }}
                >
                  {submitting ? (
                    <>
                      <Loader2 size={15} className="animate-spin" />{" "}
                      {rewriteMessage || "Rewriting…"}
                    </>
                  ) : (
                    "Submit & Rewrite"
                  )}
                </button>
              </div>
            </Card>
          )}

          {/* Actions */}
          <div className="flex gap-3 pb-8">
            <button
              onClick={() => router.push("/")}
              className="px-4 py-3 rounded-lg text-sm font-medium text-white flex items-center gap-1.5"
              style={{
                background: "var(--bg-card)",
                border: "1px solid var(--border-md)",
              }}
            >
              <ArrowLeft size={15} /> Start Over
            </button>
            <button
              onClick={() => setShowFeedback(true)}
              disabled={showFeedback || submitting}
              className="flex-1 py-3 rounded-lg text-sm font-semibold text-white disabled:opacity-40 flex items-center justify-center gap-2"
              style={{
                background: "var(--bg-card)",
                border: "1px solid var(--border-md)",
              }}
            >
              <MessageSquare size={15} /> Request Changes
            </button>
            <button
              onClick={handleApprove}
              disabled={submitting}
              className="flex-1 py-3 rounded-lg text-sm font-semibold text-white disabled:opacity-50 flex items-center justify-center gap-2"
              style={{ background: "var(--accent)" }}
              onMouseEnter={(e) =>
                ((e.currentTarget as HTMLButtonElement).style.filter =
                  "brightness(1.1)")
              }
              onMouseLeave={(e) =>
                ((e.currentTarget as HTMLButtonElement).style.filter = "")
              }
            >
              {submitting ? (
                <Loader2 size={17} className="animate-spin" />
              ) : (
                <>
                  <CheckCircle size={17} /> Approve &amp; Produce
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
