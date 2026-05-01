"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  streamFullPipeline,
  reconnectJobStream,
  getJob,
  videoUrl,
  API_BASE,
  type ReelJob,
  type SSEEvent,
} from "@/lib/api";
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Image as ImageIcon,
  Film,
  Mic2,
  Scissors,
  Upload,
  Download,
  Terminal,
  Play,
  ShieldCheck,
  AlertCircle,
  MessageSquare,
} from "lucide-react";

const STAGE_META: Record<string, { label: string; icon: React.ReactNode }> = {
  scripting: { label: "Rewriting Script", icon: <MessageSquare size={16} /> },
  imaging: { label: "Generating Images", icon: <ImageIcon size={16} /> },
  videoing: { label: "Generating Video Clips", icon: <Film size={16} /> },
  tts: { label: "Narration (TTS)", icon: <Mic2 size={16} /> },
  editing: { label: "Editing Video", icon: <Scissors size={16} /> },
  qa: { label: "Quality Check", icon: <ShieldCheck size={16} /> },
  uploading: { label: "Uploading", icon: <Upload size={16} /> },
};

type StageStatus = "pending" | "active" | "done" | "warn" | "error";
interface StageState {
  status: StageStatus;
  message: string;
  detail?: string; // e.g. "2/6"
}

interface LogLine {
  ts: string;
  type: "info" | "error" | "done" | "stage" | "warn";
  text: string;
}

function now() {
  return new Date().toLocaleTimeString("en-US", { hour12: false });
}

export default function GeneratePage() {
  const { jobId } = useParams<{ jobId: string }>();
  const router = useRouter();

  const [stages, setStages] = useState<Record<string, StageState>>(() =>
    Object.fromEntries(
      Object.keys(STAGE_META).map((k) => [
        k,
        { status: "pending" as StageStatus, message: "" },
      ]),
    ),
  );
  const [log, setLog] = useState<LogLine[]>([
    {
      ts: now(),
      type: "info",
      text: `Connecting to pipeline for job ${jobId}…`,
    },
  ]);
  const [doneJob, setDoneJob] = useState<ReelJob | null>(null);
  const [fatalError, setFatalError] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [sceneMedia, setSceneMedia] = useState<
    Array<{ index: number; image_url?: string; clip_url?: string }>
  >([]);
  const [qaReport, setQaReport] = useState<{
    actual_duration_s?: number;
    expected_duration_s?: number;
    duration_drift_pct?: number;
    audio_present?: boolean;
    audio_video_gap_s?: number;
    fps?: number;
    resolution?: string;
    passes?: string[];
    issues?: string[];
    overall?: string;
  } | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  function addLog(line: Omit<LogLine, "ts">) {
    setLog((prev) => [...prev, { ts: now(), ...line }]);
  }

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [log]);

  useEffect(() => {
    let esCleanup: (() => void) | undefined;

    function startFreshPipeline() {
      addLog({
        type: "info",
        text: `Starting production pipeline for job ${jobId}…`,
      });
      esCleanup = streamFullPipeline(
        jobId,
        (evt: SSEEvent) => {
          const stage = evt.stage ?? "";
          const msg = evt.message ?? "";

          // Update stage tracker
          if (stage && STAGE_META[stage]) {
            setStages((prev) => {
              const next = { ...prev };
              let passed = false;
              for (const key of Object.keys(STAGE_META)) {
                if (key === stage) {
                  passed = true;
                  next[key] = { status: "active", message: msg };
                } else if (!passed && next[key].status !== "done") {
                  next[key] = { status: "done", message: next[key].message };
                }
              }
              return next;
            });
            addLog({
              type: "stage",
              text: `[${STAGE_META[stage].label}] ${msg}`,
            });
          } else if (msg) {
            addLog({ type: "info", text: msg });
          }

          // Surface any error field from SSE payload
          if (evt.error) {
            addLog({ type: "error", text: `Error: ${evt.error}` });
            setStages((prev) => {
              const next = { ...prev };
              if (stage && next[stage])
                next[stage] = { status: "error", message: evt.error! };
              return next;
            });
          }

          // Handle partial image success
          if (
            stage === "imaging" &&
            typeof evt.images_failed === "number" &&
            evt.images_failed > 0
          ) {
            const failed = evt.failed_scene_indices ?? [];
            const warnMsg = `${evt.images_failed} scene image(s) failed to generate (scenes: ${failed.map((i) => i + 1).join(", ")}). The video will be produced with ${evt.images_ok ?? 0} scenes.`;
            setWarnings((prev) => [...prev, warnMsg]);
            addLog({ type: "warn", text: `⚠ ${warnMsg}` });
            setStages((prev) => ({
              ...prev,
              imaging: {
                status: "warn",
                message: prev.imaging.message,
                detail: `${evt.images_ok}/${(evt.images_ok ?? 0) + (evt.images_failed ?? 0)}`,
              },
            }));
          }

          // Capture scene media (images / clips) sent in SSE payload
          if (evt.scenes && evt.scenes.length > 0) {
            setSceneMedia((prev) => {
              const map = new Map(prev.map((s) => [s.index, s]));
              for (const s of evt.scenes!) {
                const existing = map.get(s.index) ?? {};
                const clip = s.clip_url
                  ? s.clip_url.startsWith("http")
                    ? s.clip_url
                    : `${API_BASE}${s.clip_url}`
                  : undefined;
                map.set(s.index, {
                  ...existing,
                  ...s,
                  ...(clip ? { clip_url: clip } : {}),
                });
              }
              return Array.from(map.values()).sort((a, b) => a.index - b.index);
            });
          }

          // Capture QA report
          if (evt.qa_report) {
            setQaReport(evt.qa_report);
          }
        },
        (job: ReelJob) => {
          setStages((prev) => {
            const next = { ...prev };
            for (const key of Object.keys(next))
              next[key] = { status: "done", message: next[key].message };
            return next;
          });
          setDoneJob(job);
          addLog({
            type: "done",
            text: `Pipeline complete! Total cost: $${job.total_cost?.toFixed(4) ?? "0.0000"}`,
          });
        },
        (msg: string) => {
          setFatalError(msg);
          addLog({ type: "error", text: `Fatal: ${msg}` });
        },
        () => {
          // Script was rewritten — go back to review page to approve the new version
          router.push(`/review/${jobId}`);
        },
      );
    }

    // Check if this job already exists on the server (page refresh scenario)
    getJob(jobId)
      .then((existingJob) => {
        addLog({
          type: "info",
          text: `Reconnecting to existing job (status: ${existingJob.status})…`,
        });
        esCleanup = reconnectJobStream(
          jobId,
          (stage, _action, message) => {
            if (stage && STAGE_META[stage]) {
              setStages((prev) => {
                const next = { ...prev };
                next[stage] = { status: "active", message };
                return next;
              });
              addLog({
                type: "stage",
                text: `[${STAGE_META[stage]?.label ?? stage}] ${message}`,
              });
            } else {
              addLog({ type: "info", text: message });
            }
          },
          (job: ReelJob) => {
            setStages((prev) => {
              const next = { ...prev };
              for (const key of Object.keys(next))
                next[key] = { status: "done", message: next[key].message };
              return next;
            });
            setDoneJob(job);
            addLog({
              type: "done",
              text: `Pipeline complete! Total cost: $${job.total_cost?.toFixed(4) ?? "0.0000"}`,
            });
          },
          (msg: string) => {
            setFatalError(msg);
            addLog({ type: "error", text: `Fatal: ${msg}` });
          },
        );
      })
      .catch(() => {
        // Job not found on server — start fresh pipeline
        startFreshPipeline();
      });

    return () => esCleanup?.();
  }, [jobId]);

  const stageKeys = Object.keys(STAGE_META);

  return (
    <main
      className="min-h-screen px-4 py-10"
      style={{ background: "var(--bg-base)" }}
    >
      <div className="max-w-2xl mx-auto">
        {/* Nav bar */}
        <div className="flex items-center gap-2.5 mb-8">
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center text-white font-bold text-xs"
            style={{ background: "var(--accent)" }}
          >
            R
          </div>
          <span className="text-white font-semibold text-base tracking-tight">
            Rofy <span style={{ color: "var(--text-3)" }}>/</span>{" "}
            <span style={{ color: "var(--text-2)" }}>
              {doneJob
                ? "Reel Ready"
                : fatalError
                  ? "Production Failed"
                  : "Producing Reel"}
            </span>
          </span>
        </div>

        {/* Heading */}
        <div className="mb-6">
          {doneJob ? (
            <>
              <h1 className="text-[1.6rem] font-semibold text-white tracking-tight mb-1">
                Your reel is ready
              </h1>
              <p className="text-sm" style={{ color: "var(--text-2)" }}>
                Download or preview your product video below.
              </p>
            </>
          ) : fatalError ? (
            <>
              <h1
                className="text-[1.6rem] font-semibold tracking-tight mb-1"
                style={{ color: "#f87171" }}
              >
                Production failed
              </h1>
              <p className="text-sm" style={{ color: "var(--text-2)" }}>
                {fatalError}
              </p>
            </>
          ) : (
            <>
              <h1 className="text-[1.6rem] font-semibold text-white tracking-tight mb-1">
                Producing your reel
              </h1>
              <p className="text-sm" style={{ color: "var(--text-2)" }}>
                AI agents are working on your video — this takes a minute.
              </p>
            </>
          )}
        </div>

        <div className="space-y-4">
          {/* Warnings */}
          {warnings.length > 0 && (
            <div
              className="rounded-xl px-4 py-3 space-y-1"
              style={{
                background: "rgba(250,204,21,0.07)",
                border: "1px solid rgba(250,204,21,0.2)",
              }}
            >
              {warnings.map((w, i) => (
                <p
                  key={i}
                  className="text-xs flex items-start gap-2"
                  style={{ color: "#facc15" }}
                >
                  <span className="flex-shrink-0 mt-0.5">&#9888;</span>
                  {w}
                </p>
              ))}
            </div>
          )}

          {/* Stage tracker */}
          <div
            className="rounded-xl p-5 space-y-3"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border-md)",
            }}
          >
            {stageKeys.map((key) => {
              const meta = STAGE_META[key];
              const state = stages[key];
              const isWarn = state.status === "warn";
              const iconColor =
                state.status === "active"
                  ? "var(--accent)"
                  : state.status === "done"
                    ? "#4ade80"
                    : isWarn
                      ? "#facc15"
                      : state.status === "error"
                        ? "#f87171"
                        : "var(--text-3)";
              const labelColor =
                state.status === "active"
                  ? "#fff"
                  : state.status === "done"
                    ? "#86efac"
                    : isWarn
                      ? "#fde047"
                      : state.status === "error"
                        ? "#fca5a5"
                        : "var(--text-3)";
              const badgeStyle: React.CSSProperties =
                state.status === "active"
                  ? {
                      background: "rgba(255,98,0,0.12)",
                      color: "var(--accent)",
                      border: "1px solid rgba(255,98,0,0.25)",
                    }
                  : state.status === "done"
                    ? {
                        background: "rgba(74,222,128,0.08)",
                        color: "#4ade80",
                        border: "1px solid rgba(74,222,128,0.2)",
                      }
                    : isWarn
                      ? {
                          background: "rgba(250,204,21,0.08)",
                          color: "#facc15",
                          border: "1px solid rgba(250,204,21,0.2)",
                        }
                      : state.status === "error"
                        ? {
                            background: "rgba(248,113,113,0.08)",
                            color: "#f87171",
                            border: "1px solid rgba(248,113,113,0.2)",
                          }
                        : {
                            background: "var(--bg-input)",
                            color: "var(--text-3)",
                            border: "1px solid var(--border)",
                          };
              return (
                <div key={key} className="flex items-center gap-3">
                  <div className="flex-shrink-0" style={{ color: iconColor }}>
                    {state.status === "active" ? (
                      <Loader2 size={17} className="animate-spin" />
                    ) : state.status === "done" || isWarn ? (
                      <CheckCircle2 size={17} />
                    ) : state.status === "error" ? (
                      <XCircle size={17} />
                    ) : (
                      meta.icon
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p
                      className="text-sm font-medium"
                      style={{ color: labelColor }}
                    >
                      {meta.label}
                      {isWarn && state.detail && (
                        <span
                          className="ml-2 text-[11px] font-normal"
                          style={{ color: "#a16207" }}
                        >
                          ({state.detail} succeeded)
                        </span>
                      )}
                    </p>
                    {state.message && (
                      <p
                        className="text-[11px] truncate"
                        style={{
                          color:
                            state.status === "error"
                              ? "#f87171"
                              : isWarn
                                ? "#facc15"
                                : "var(--text-3)",
                        }}
                      >
                        {state.message}
                      </p>
                    )}
                  </div>
                  <span
                    className="text-[11px] font-medium px-2 py-0.5 rounded-md flex-shrink-0"
                    style={badgeStyle}
                  >
                    {state.status === "active"
                      ? "Running"
                      : state.status === "done"
                        ? "Done"
                        : isWarn
                          ? "Partial"
                          : state.status === "error"
                            ? "Error"
                            : "Waiting"}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Scene preview grid */}
          {sceneMedia.length > 0 && (
            <div
              className="rounded-xl p-4 space-y-3"
              style={{
                background: "var(--bg-card)",
                border: "1px solid var(--border-md)",
              }}
            >
              <p
                className="text-[11px] font-semibold uppercase tracking-wider"
                style={{ color: "var(--text-3)" }}
              >
                Scene Preview ({sceneMedia.length} scenes)
              </p>
              <div className="grid grid-cols-5 gap-2">
                {sceneMedia.map((s) => (
                  <div
                    key={s.index}
                    className="relative aspect-[9/16] rounded-lg overflow-hidden"
                    style={{
                      background: "var(--bg-input)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    {s.clip_url ? (
                      <video
                        src={s.clip_url}
                        className="w-full h-full object-cover"
                        muted
                        loop
                        playsInline
                        poster={s.image_url}
                        onMouseEnter={(e) => {
                          const v = e.currentTarget as HTMLVideoElement;
                          const p = v.play();
                          if (p !== undefined) p.catch(() => {});
                        }}
                        onMouseLeave={(e) => {
                          const v = e.currentTarget as HTMLVideoElement;
                          v.pause();
                          v.currentTime = 0;
                        }}
                      />
                    ) : status === "failed" ||
                      (status === "done" && !s.clip_url) ? (
                      <div className="w-full h-full flex flex-col items-center justify-center gap-1 px-2">
                        <AlertCircle size={16} style={{ color: "#f87171" }} />
                        <span
                          className="text-[9px] text-center leading-tight"
                          style={{ color: "#f87171" }}
                        >
                          Scene {s.index + 1} failed
                        </span>
                      </div>
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <Loader2
                          size={14}
                          className="animate-spin"
                          style={{ color: "var(--text-3)" }}
                        />
                      </div>
                    )}
                    <div className="absolute top-1 left-1 bg-black/60 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                      {s.index + 1}
                    </div>
                    {s.clip_url && (
                      <div
                        className="absolute bottom-1 right-1 rounded-full p-0.5"
                        style={{ background: "var(--accent)" }}
                      >
                        <Play size={8} className="text-white fill-white" />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Live event log */}
          <div
            className="rounded-xl overflow-hidden"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border-md)",
            }}
          >
            <div
              className="flex items-center gap-2 px-4 py-2.5"
              style={{ borderBottom: "1px solid var(--border)" }}
            >
              <Terminal size={13} style={{ color: "var(--text-3)" }} />
              <span
                className="text-[11px] font-mono"
                style={{ color: "var(--text-3)" }}
              >
                Live Event Log
              </span>
              {!doneJob && !fatalError && (
                <Loader2
                  size={11}
                  className="animate-spin ml-auto"
                  style={{ color: "var(--accent)" }}
                />
              )}
            </div>
            <div className="h-52 overflow-y-auto p-4 space-y-1 font-mono text-[11px]">
              {log.map((line, i) => (
                <div key={i} className="flex gap-2 leading-relaxed">
                  <span
                    className="flex-shrink-0"
                    style={{ color: "var(--text-3)" }}
                  >
                    {line.ts}
                  </span>
                  <span
                    style={{
                      color:
                        line.type === "error"
                          ? "#f87171"
                          : line.type === "warn"
                            ? "#facc15"
                            : line.type === "done"
                              ? "#4ade80"
                              : line.type === "stage"
                                ? "var(--accent)"
                                : "var(--text-2)",
                    }}
                  >
                    {line.text}
                  </span>
                </div>
              ))}
              <div ref={logEndRef} />
            </div>
          </div>

          {/* QA Report */}
          {qaReport && (
            <div
              className="rounded-xl p-4 space-y-3"
              style={
                qaReport.overall === "pass"
                  ? {
                      background: "rgba(74,222,128,0.05)",
                      border: "1px solid rgba(74,222,128,0.2)",
                    }
                  : {
                      background: "rgba(250,204,21,0.05)",
                      border: "1px solid rgba(250,204,21,0.2)",
                    }
              }
            >
              <div className="flex items-center gap-2">
                <ShieldCheck
                  size={15}
                  style={{
                    color: qaReport.overall === "pass" ? "#4ade80" : "#facc15",
                  }}
                />
                <p
                  className="text-sm font-semibold"
                  style={{
                    color: qaReport.overall === "pass" ? "#4ade80" : "#facc15",
                  }}
                >
                  Quality Check —{" "}
                  {qaReport.overall === "pass"
                    ? "All checks passed"
                    : `${qaReport.issues?.length} warning(s)`}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-2 text-[11px]">
                {[
                  {
                    label: "Duration",
                    value:
                      qaReport.actual_duration_s != null
                        ? `${qaReport.actual_duration_s}s (expected ${qaReport.expected_duration_s}s, ${qaReport.duration_drift_pct}% drift)`
                        : "—",
                  },
                  {
                    label: "Audio",
                    value: qaReport.audio_present
                      ? `Present (gap ${qaReport.audio_video_gap_s ?? 0}s)`
                      : "Missing ⚠",
                  },
                  {
                    label: "FPS",
                    value: qaReport.fps != null ? `${qaReport.fps} fps` : "—",
                  },
                  { label: "Resolution", value: qaReport.resolution ?? "—" },
                ].map(({ label, value }) => (
                  <div
                    key={label}
                    className="rounded-lg p-2"
                    style={{ background: "rgba(0,0,0,0.2)" }}
                  >
                    <p
                      className="uppercase tracking-wider mb-0.5"
                      style={{ color: "var(--text-3)", fontSize: "10px" }}
                    >
                      {label}
                    </p>
                    <p className="text-white font-mono">{value}</p>
                  </div>
                ))}
              </div>
              {qaReport.issues && qaReport.issues.length > 0 && (
                <div className="space-y-1">
                  {qaReport.issues.map((issue, i) => (
                    <p
                      key={i}
                      className="text-[11px] font-mono"
                      style={{ color: "#facc15" }}
                    >
                      ⚠ {issue}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Result card */}
          {doneJob && (
            <div
              className="rounded-xl p-5 space-y-4"
              style={{
                background: "var(--bg-card)",
                border: "1px solid var(--border-md)",
              }}
            >
              {doneJob.final_video_path && (
                <div className="rounded-xl overflow-hidden bg-black aspect-[9/16] max-h-96 mx-auto">
                  <video
                    src={videoUrl(jobId)}
                    controls
                    autoPlay
                    className="w-full h-full object-contain"
                  />
                </div>
              )}
              <div className="grid grid-cols-3 gap-3">
                {[
                  {
                    label: "Total cost",
                    value: `$${doneJob.total_cost?.toFixed(4) ?? "—"}`,
                  },
                  {
                    label: "Scenes",
                    value: String(doneJob.script?.scenes.length ?? "—"),
                  },
                  {
                    label: "Duration",
                    value: doneJob.script?.total_duration
                      ? `${doneJob.script.total_duration}s`
                      : "—",
                  },
                ].map(({ label, value }) => (
                  <div
                    key={label}
                    className="rounded-xl p-3 text-center"
                    style={{
                      background: "var(--bg-input)",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <p
                      className="text-lg font-bold"
                      style={{ color: "var(--accent)" }}
                    >
                      {value}
                    </p>
                    <p
                      className="text-[11px] mt-0.5"
                      style={{ color: "var(--text-3)" }}
                    >
                      {label}
                    </p>
                  </div>
                ))}
              </div>
              {doneJob.final_video_url && (
                <a
                  href={doneJob.final_video_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block text-center text-[13px] underline"
                  style={{ color: "var(--accent)" }}
                >
                  View on Cloud Storage ↗
                </a>
              )}
              <div className="flex gap-3">
                <a
                  href={videoUrl(jobId)}
                  download={`reel-${jobId}.mp4`}
                  className="flex-1 py-3 text-sm font-semibold text-white rounded-lg flex items-center justify-center gap-2"
                  style={{ background: "var(--accent)" }}
                >
                  <Download size={16} /> Download Video
                </a>
                <button
                  onClick={() => router.push("/")}
                  className="flex-1 py-3 text-sm font-semibold text-white rounded-lg"
                  style={{
                    background: "var(--bg-input)",
                    border: "1px solid var(--border-md)",
                  }}
                >
                  New Reel
                </button>
              </div>
            </div>
          )}

          {/* Error actions */}
          {fatalError && (
            <div className="flex gap-3 pb-8">
              <button
                onClick={() => router.push(`/review/${jobId}`)}
                className="flex-1 py-3 text-sm font-semibold text-white rounded-lg"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border-md)",
                }}
              >
                ← Back to Review
              </button>
              <button
                onClick={() => router.push("/")}
                className="flex-1 py-3 text-sm font-semibold text-white rounded-lg"
                style={{ background: "var(--accent)" }}
              >
                Start Over
              </button>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
