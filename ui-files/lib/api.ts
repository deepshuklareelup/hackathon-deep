const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ProductInput {
  name: string;
  description: string;
  features: string[];
  tone: string;
  platform: string;
  target_duration?: number;
}

export interface Scene {
  index: number;
  narration: string;
  image_prompt: string;
  duration: number;
  video_url?: string;
  image_url?: string;
  audio_path?: string;
}

export interface Script {
  hook: string;
  cta: string;
  scenes: Scene[];
  total_duration: number;
  model_used?: string;
  cost_usd?: number;
}

export interface ReelJob {
  job_id: string;
  status: string;
  product: ProductInput;
  script?: Script;
  final_video_path?: string;
  gcs_url?: string;
  total_cost_usd: number;
  error?: string;
  logs: Array<{ agent: string; event: string; detail: string; ts: string }>;
}

export interface SSEEvent {
  type: string;
  stage?: string;
  message?: string;
  job?: ReelJob;
  error?: string;
}

// Phase 1: Generate script
export async function generateScript(product: ProductInput): Promise<ReelJob> {
  const res = await fetch(`${API_BASE}/api/generate/script`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(product),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
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
): () => void {
  const es = new EventSource(`${API_BASE}/api/generate/full/${jobId}`);

  es.onmessage = (e) => {
    try {
      const data: SSEEvent = JSON.parse(e.data);
      if (data.type === "done") {
        onDone(data.job!);
        es.close();
      } else if (data.type === "error") {
        onError(data.error ?? "Unknown error");
        es.close();
      } else {
        onEvent(data);
      }
    } catch {
      // ignore parse errors
    }
  };

  es.onerror = () => {
    onError("Connection to server lost");
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

// Video URL
export function videoUrl(jobId: string): string {
  return `${API_BASE}/api/jobs/${jobId}/video`;
}

// Keys
export async function getKeys(): Promise<Record<string, boolean>> {
  const res = await fetch(`${API_BASE}/api/keys`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
