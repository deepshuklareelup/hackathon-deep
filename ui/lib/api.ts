export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ProductInput {
  name: string;
  description: string;
  features: string[];
  tone: string;
  platform: string;
  target_duration?: number;
  price?: string;
  target_audience?: string;
}

export interface Scene {
  index: number;
  narration: string;
  image_prompt: string;
  duration?: number;
  visual_direction?: string;
  video_url?: string;
  image_url?: string;
  audio_path?: string;
  clip_url?: string;
}

export interface Script {
  hook: string;
  cta: string;
  scenes: Scene[];
  total_duration: number;
  model_used?: string;
  cost_usd?: number;
}

export interface CriticReport {
  hook_score?: number;
  clarity_score?: number;
  engagement_score?: number;
  overall_score?: number;
  verdict?: string;
  hook_feedback?: string;
  engagement_feedback?: string;
  rewrite_instruction?: string;
}

export interface ReelJob {
  job_id: string;
  status: string;
  product?: ProductInput;
  script?: Script;
  final_video_path?: string;
  final_video_url?: string;
  total_cost: number;
  costs?: Record<string, number>;
  error?: string;
  critic_report?: CriticReport;
  logs: Array<{
    stage: string;
    action: string;
    result: string;
    cost_usd?: number;
  }>;
}

export interface SSEEvent {
  type: string;
  stage?: string;
  message?: string;
  job?: ReelJob;
  error?: string;
  scenes?: Array<{ index: number; image_url?: string; clip_url?: string }>;
  images_ok?: number;
  images_failed?: number;
  failed_scene_indices?: number[];
  qa_report?: {
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
  };
}

// Phase 1: Generate script
export async function generateScript(product: ProductInput): Promise<ReelJob> {
  const res = await fetch(`${API_BASE}/api/generate/script`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ product }),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

// Phase 2: Stream full pipeline via SSE
export function streamFullPipeline(
  jobId: string,
  onEvent: (evt: SSEEvent) => void,
  onDone: (job: ReelJob) => void,
  onError: (msg: string) => void,
  onRewriteDone?: () => void,
): () => void {
  const es = new EventSource(`${API_BASE}/api/generate/full/${jobId}`);
  let receivedError = false;

  // Named "rewrite_done" event — script was rewritten, go back to review
  es.addEventListener("rewrite_done", () => {
    es.close();
    onRewriteDone?.();
  });

  // Named "progress" events
  es.addEventListener("progress", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data as string) as SSEEvent;
      onEvent({ ...data, type: "progress" });
    } catch {
      /* ignore */
    }
  });

  // Named "done" event
  es.addEventListener("done", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data as string);
      onDone(data as ReelJob);
      es.close();
    } catch {
      /* ignore */
    }
  });

  // Named "error" event — real pipeline error with message
  es.addEventListener("error", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data as string) as { message?: string };
      receivedError = true;
      onError(data.message ?? "Pipeline error");
      es.close();
    } catch {
      /* ignore */
    }
  });

  // Fallback: unnamed messages (shouldn't happen but just in case)
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data as string) as SSEEvent & { type?: string };
      if (data.type === "done") {
        onDone(data.job!);
        es.close();
      } else if (data.type === "error") {
        receivedError = true;
        onError(data.error ?? "Unknown error");
        es.close();
      } else onEvent(data);
    } catch {
      /* ignore */
    }
  };

  // onerror fires when stream closes — only show if we didn't already get a real error
  es.onerror = () => {
    if (!receivedError) {
      onError("Connection to server lost");
    }
    es.close();
  };

  return () => es.close();
}

// Get job state
export async function getJob(jobId: string): Promise<ReelJob> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Human-in-the-loop: approve or request rewrite
export async function resumeJob(
  jobId: string,
  decision: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

// Research Sub-Agent: extract product data from a URL
export interface ResearchResult {
  name: string;
  description: string;
  price?: string;
  features: string[];
  target_audience?: string;
  tone: string;
  confidence: number;
  source_url: string;
  source_domain: string;
  from_knowledge?: boolean;
}

export interface QuickStartSuggestion {
  emoji: string;
  label: string;
  data: ProductInput;
}

export async function researchProduct(url: string): Promise<ResearchResult> {
  const res = await fetch(`${API_BASE}/api/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchQuickStartSuggestions(
  count = 6,
): Promise<QuickStartSuggestion[]> {
  const res = await fetch(
    `${API_BASE}/api/suggestions/quick-start?count=${count}`,
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  const data = (await res.json()) as { suggestions?: QuickStartSuggestion[] };
  return data.suggestions ?? [];
}

export function clipUrl(jobId: string, sceneIndex: number): string {
  return `${API_BASE}/api/jobs/${jobId}/scenes/${sceneIndex}/clip`;
}

// Reconnect to an existing job's SSE stream (for page refresh recovery)
export function reconnectJobStream(
  jobId: string,
  onLog: (stage: string, action: string, message: string) => void,
  onDone: (job: ReelJob) => void,
  onError: (msg: string) => void,
): () => void {
  const es = new EventSource(`${API_BASE}/api/jobs/${jobId}/reconnect`);

  es.addEventListener("reconnected", (e) => {
    const d = JSON.parse(e.data) as { status: string; log_count: number };
    onLog(
      "server",
      "reconnected",
      `Reconnected — job is '${d.status}' with ${d.log_count} log entries`,
    );
  });

  es.addEventListener("log", (e) => {
    const d = JSON.parse(e.data) as {
      stage: string;
      action: string;
      message: string;
    };
    onLog(d.stage, d.action, d.message);
  });

  es.addEventListener("done", (e) => {
    es.close();
    onDone(JSON.parse(e.data) as ReelJob);
  });

  es.addEventListener("error", (e) => {
    es.close();
    try {
      const d = JSON.parse((e as MessageEvent).data ?? "{}") as {
        message?: string;
      };
      onError(d.message ?? "Reconnect stream error");
    } catch {
      onError("Reconnect stream error");
    }
  });

  return () => es.close();
}

// Video download URL
export function videoUrl(jobId: string): string {
  return `${API_BASE}/api/jobs/${jobId}/video`;
}

// Keys status
export async function getKeys(): Promise<Record<string, boolean>> {
  const res = await fetch(`${API_BASE}/api/keys`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
