"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  fetchQuickStartSuggestions,
  generateScript,
  researchProduct,
  type ProductInput,
  type QuickStartSuggestion,
} from "@/lib/api";
import { Loader2, Plus, X, Sparkles, Link, CheckCircle2 } from "lucide-react";

const TONES = ["professional", "casual", "luxury", "energetic", "friendly"];
const PLATFORMS = [
  "instagram",
  "tiktok",
  "youtube_shorts",
  "linkedin",
  "twitter",
];

const FALLBACK_SUGGESTIONS: Array<{
  emoji: string;
  label: string;
  data: ProductInput;
}> = [
  {
    emoji: "🏋️",
    label: "Protein Shake",
    data: {
      name: "ProPeak Whey Protein",
      description:
        "A premium grass-fed whey protein shake with 25g protein per serving, zero artificial sweeteners, and a creamy chocolate fudge flavour that actually tastes good.",
      price: "$49.99",
      features: [
        "25g protein per serving",
        "Grass-fed whey",
        "No artificial sweeteners",
        "5 flavours",
        "Easy to mix",
      ],
      target_audience: "Gym-goers and fitness enthusiasts aged 18–35",
      tone: "energetic",
      platform: "instagram",
      target_duration: 30,
    },
  },
  {
    emoji: "👟",
    label: "Running Shoes",
    data: {
      name: "AeroFoam Pro Runner",
      description:
        "Ultralight carbon-fibre plated running shoes built for speed and daily training. Responsive foam midsole returns 85% energy with every stride.",
      price: "$139",
      features: [
        "Carbon-fibre plate",
        "85% energy return",
        "165g ultralight",
        "Breathable mesh upper",
        "5-year outsole warranty",
      ],
      target_audience: "Runners and endurance athletes",
      tone: "energetic",
      platform: "tiktok",
      target_duration: 30,
    },
  },
  {
    emoji: "💆",
    label: "Face Serum",
    data: {
      name: "LumiGlow Vitamin C Serum",
      description:
        "A clinically-tested 20% Vitamin C serum with hyaluronic acid and niacinamide that visibly brightens skin and reduces fine lines in 4 weeks.",
      price: "$38",
      features: [
        "20% Vitamin C",
        "Hyaluronic acid",
        "Niacinamide",
        "Dermatologist tested",
        "Vegan & cruelty-free",
      ],
      target_audience: "Skincare enthusiasts aged 25–45",
      tone: "luxury",
      platform: "instagram",
      target_duration: 30,
    },
  },
  {
    emoji: "🎧",
    label: "Wireless Earbuds",
    data: {
      name: "SoundDrop ANC Earbuds",
      description:
        "True wireless earbuds with 40dB active noise cancellation, 36-hour total battery life, and studio-grade audio tuned by professional sound engineers.",
      price: "$89",
      features: [
        "40dB ANC",
        "36h battery",
        "IPX5 waterproof",
        "Instant pairing",
        "Studio-tuned audio",
      ],
      target_audience: "Commuters, remote workers and music lovers",
      tone: "professional",
      platform: "youtube_shorts",
      target_duration: 30,
    },
  },
  {
    emoji: "🧴",
    label: "Hair Oil",
    data: {
      name: "Rootly Argan Hair Oil",
      description:
        "A lightweight, non-greasy Moroccan argan oil treatment that tames frizz, adds mirror shine, and strengthens hair from root to tip with every drop.",
      price: "$24",
      features: [
        "100% pure argan oil",
        "Frizz control",
        "Heat protectant to 230°C",
        "Suitable for all hair types",
        "No parabens",
      ],
      target_audience: "Women aged 20–40 who care about hair health",
      tone: "casual",
      platform: "tiktok",
      target_duration: 30,
    },
  },
  {
    emoji: "💊",
    label: "Vitamin Gummies",
    data: {
      name: "SunBurst Daily Vitamin Gummies",
      description:
        "Delicious mixed-berry gummies packed with Vitamins C, D3, B12 and Zinc. One serving covers your full daily immune and energy needs — no pills, no water needed.",
      price: "$19.99",
      features: [
        "Vitamins C, D3, B12 & Zinc",
        "Sugar-free",
        "No artificial colours",
        "60 gummies / 30-day supply",
        "Kid & adult friendly",
      ],
      target_audience: "Health-conscious families and busy professionals",
      tone: "friendly",
      platform: "instagram",
      target_duration: 30,
    },
  },
];

export default function HomePage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [suggestionsLoading, setSuggestionsLoading] = useState(true);
  const [error, setError] = useState("");
  const [suggestionsError, setSuggestionsError] = useState("");
  const [featureInput, setFeatureInput] = useState("");
  const [urlInput, setUrlInput] = useState("");
  const [researching, setResearching] = useState(false);
  const [researchError, setResearchError] = useState("");
  const [researchDone, setResearchDone] = useState(false);
  const [fromKnowledge, setFromKnowledge] = useState(false);
  const [quickSuggestions, setQuickSuggestions] =
    useState<QuickStartSuggestion[]>(FALLBACK_SUGGESTIONS);

  useEffect(() => {
    let active = true;

    const loadSuggestions = async () => {
      setSuggestionsLoading(true);
      setSuggestionsError("");
      try {
        const suggestions = await fetchQuickStartSuggestions(6);
        if (!active) return;
        if (suggestions.length > 0) {
          setQuickSuggestions(suggestions);
        } else {
          setSuggestionsError(
            "No suggestions received. Showing fallback ideas.",
          );
          setQuickSuggestions(FALLBACK_SUGGESTIONS);
        }
      } catch (e: unknown) {
        if (!active) return;
        setSuggestionsError(
          e instanceof Error
            ? `${e.message} Showing fallback ideas.`
            : "Could not load suggestions. Showing fallback ideas.",
        );
        setQuickSuggestions(FALLBACK_SUGGESTIONS);
      } finally {
        if (active) setSuggestionsLoading(false);
      }
    };

    loadSuggestions();
    return () => {
      active = false;
    };
  }, []);

  async function handleResearch() {
    if (!urlInput.trim()) return;
    setResearching(true);
    setResearchError("");
    setResearchDone(false);
    setFromKnowledge(false);
    try {
      const data = await researchProduct(urlInput.trim());
      setForm((p) => ({
        ...p,
        name: data.name || p.name,
        description: data.description || p.description,
        price: data.price ?? p.price,
        features: data.features.length > 0 ? data.features : p.features,
        target_audience: data.target_audience ?? p.target_audience,
        tone: data.tone || p.tone,
      }));
      setFromKnowledge(data.from_knowledge ?? false);
      setResearchDone(true);
    } catch (e: unknown) {
      setResearchError(e instanceof Error ? e.message : String(e));
    } finally {
      setResearching(false);
    }
  }
  const [form, setForm] = useState<ProductInput>({
    name: "",
    description: "",
    features: [],
    tone: "energetic",
    platform: "instagram",
    target_duration: 30,
  });

  function addFeature() {
    const f = featureInput.trim();
    if (f && !form.features.includes(f)) {
      setForm((p) => ({ ...p, features: [...p.features, f] }));
      setFeatureInput("");
    }
  }

  function removeFeature(f: string) {
    setForm((p) => ({ ...p, features: p.features.filter((x) => x !== f) }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!form.name.trim() || !form.description.trim()) {
      setError("Product name and description are required.");
      return;
    }
    setLoading(true);
    try {
      const job = await generateScript(form);
      router.push(`/review/${job.job_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  }

  return (
    <main
      className="min-h-screen flex flex-col items-center justify-center px-4 py-12"
      style={{ background: "var(--bg-base)" }}
    >
      {/* ── Logo bar ── */}
      <div className="flex items-center gap-2.5 mb-10">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-white font-bold text-sm"
          style={{ background: "var(--accent)" }}
        >
          R
        </div>
        <span className="text-white font-semibold text-lg tracking-tight">
          Rofy <span style={{ color: "var(--text-3)" }}>/</span>{" "}
          <span style={{ color: "var(--text-2)" }}>Reel Agent</span>
        </span>
      </div>

      <div className="w-full max-w-[640px]">
        {/* ── Heading ── */}
        <div className="mb-8">
          <h1 className="text-[2rem] font-semibold text-white leading-tight tracking-tight mb-2">
            Create your product reel
          </h1>
          <p className="text-sm" style={{ color: "var(--text-2)" }}>
            Describe your product and Rofy&apos;s AI agents write, direct, and
            produce a short-form video — end to end.
          </p>
        </div>

        {/* ── Suggestion chips ── */}
        <div className="mb-6">
          <p
            className="text-[11px] font-medium uppercase tracking-widest mb-2.5"
            style={{ color: "var(--text-3)" }}
          >
            Quick start
          </p>
          {suggestionsLoading && (
            <p className="text-[12px] mb-2" style={{ color: "var(--text-3)" }}>
              Generating fresh ideas...
            </p>
          )}
          {suggestionsError && (
            <p className="text-[12px] mb-2" style={{ color: "#f87171" }}>
              {suggestionsError}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {quickSuggestions.map((s) => (
              <button
                key={s.label}
                type="button"
                disabled={loading || suggestionsLoading}
                onClick={() => {
                  setForm(s.data);
                  setFeatureInput("");
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[13px] font-medium transition-all disabled:opacity-40 cursor-pointer"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border-md)",
                  color: "var(--text-2)",
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.color =
                    "var(--text-1)";
                  (e.currentTarget as HTMLButtonElement).style.borderColor =
                    "var(--accent)";
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.color =
                    "var(--text-2)";
                  (e.currentTarget as HTMLButtonElement).style.borderColor =
                    "var(--border-md)";
                }}
              >
                {s.emoji} {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* ── Research from URL ── */}
        <div
          className="rounded-xl p-4 mb-4"
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--border-md)",
          }}
        >
          <p
            className="text-[12px] font-semibold uppercase tracking-widest mb-3"
            style={{ color: "var(--text-3)" }}
          >
            Auto-fill from product URL
          </p>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Link
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2"
                style={{ color: "var(--text-3)" }}
              />
              <input
                type="url"
                value={urlInput}
                onChange={(e) => {
                  setUrlInput(e.target.value);
                  setResearchDone(false);
                  setResearchError("");
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleResearch();
                  }
                }}
                placeholder="https://yourstore.com/product/..."
                className="w-full rounded-lg pl-8 pr-3.5 py-2.5 text-sm text-white placeholder-[#444] transition-all"
                style={{
                  background: "var(--bg-input)",
                  border: "1px solid var(--border-md)",
                }}
                onFocus={(e) =>
                  ((e.target as HTMLInputElement).style.borderColor =
                    "var(--accent)")
                }
                onBlur={(e) =>
                  ((e.target as HTMLInputElement).style.borderColor =
                    "var(--border-md)")
                }
              />
            </div>
            <button
              type="button"
              onClick={handleResearch}
              disabled={!urlInput.trim() || researching}
              className="px-4 py-2.5 rounded-lg text-sm font-semibold text-white disabled:opacity-50 flex items-center gap-2 shrink-0 transition-all"
              style={{ background: "var(--accent)" }}
            >
              {researching ? (
                <>
                  <Loader2 size={14} className="animate-spin" /> Researching…
                </>
              ) : researchDone ? (
                <>
                  <CheckCircle2 size={14} /> Auto-filled!
                </>
              ) : (
                <>
                  <Sparkles size={14} /> Auto-fill
                </>
              )}
            </button>
          </div>
          {researchError && (
            <p className="mt-2 text-[12px]" style={{ color: "#f87171" }}>
              {researchError}
            </p>
          )}
          {researchDone && (
            <p
              className="mt-2 text-[12px]"
              style={{ color: fromKnowledge ? "#facc15" : "#4ade80" }}
            >
              {fromKnowledge
                ? "⚡ Site blocks bots — filled from AI knowledge. Review carefully."
                : "✓ Fields filled from page. Review below and adjust if needed."}
            </p>
          )}
        </div>

        {/* ── Form card ── */}
        <form
          onSubmit={handleSubmit}
          className="rounded-xl p-6 space-y-5"
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--border-md)",
          }}
        >
          {/* Product name */}
          <div>
            <label
              className="block text-[13px] font-medium mb-1.5"
              style={{ color: "var(--text-2)" }}
            >
              Product name <span style={{ color: "var(--accent)" }}>*</span>
            </label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
              placeholder="e.g. AeroFoam Pro Runner"
              className="w-full rounded-lg px-3.5 py-2.5 text-sm text-white placeholder-[#444] transition-all"
              style={{
                background: "var(--bg-input)",
                border: "1px solid var(--border-md)",
              }}
              onFocus={(e) =>
                ((e.target as HTMLInputElement).style.borderColor =
                  "var(--accent)")
              }
              onBlur={(e) =>
                ((e.target as HTMLInputElement).style.borderColor =
                  "var(--border-md)")
              }
            />
          </div>

          {/* Description */}
          <div>
            <label
              className="block text-[13px] font-medium mb-1.5"
              style={{ color: "var(--text-2)" }}
            >
              Description <span style={{ color: "var(--accent)" }}>*</span>
            </label>
            <textarea
              value={form.description}
              onChange={(e) =>
                setForm((p) => ({ ...p, description: e.target.value }))
              }
              placeholder="Materials, use-case, who it's for, what makes it unique..."
              rows={3}
              className="w-full rounded-lg px-3.5 py-2.5 text-sm text-white placeholder-[#444] resize-none transition-all"
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
          </div>

          {/* Key features */}
          <div>
            <label
              className="block text-[13px] font-medium mb-1.5"
              style={{ color: "var(--text-2)" }}
            >
              Key features
            </label>
            <div className="flex gap-2 mb-2">
              <input
                type="text"
                value={featureInput}
                onChange={(e) => setFeatureInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addFeature();
                  }
                }}
                placeholder="Type a feature, press Enter"
                className="flex-1 rounded-lg px-3.5 py-2.5 text-sm text-white placeholder-[#444] transition-all"
                style={{
                  background: "var(--bg-input)",
                  border: "1px solid var(--border-md)",
                }}
                onFocus={(e) =>
                  ((e.target as HTMLInputElement).style.borderColor =
                    "var(--accent)")
                }
                onBlur={(e) =>
                  ((e.target as HTMLInputElement).style.borderColor =
                    "var(--border-md)")
                }
              />
              <button
                type="button"
                onClick={addFeature}
                className="px-3.5 py-2.5 rounded-lg text-sm font-medium text-white transition-all flex items-center gap-1.5"
                style={{
                  background: "#1e1e1e",
                  border: "1px solid var(--border-md)",
                }}
                onMouseEnter={(e) =>
                  ((e.currentTarget as HTMLButtonElement).style.borderColor =
                    "var(--accent)")
                }
                onMouseLeave={(e) =>
                  ((e.currentTarget as HTMLButtonElement).style.borderColor =
                    "var(--border-md)")
                }
              >
                <Plus size={14} /> Add
              </button>
            </div>
            {form.features.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {form.features.map((f) => (
                  <span
                    key={f}
                    className="inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-[12px] font-medium"
                    style={{
                      background: "var(--accent-dim)",
                      color: "#ff9a60",
                      border: "1px solid rgba(255,98,0,0.2)",
                    }}
                  >
                    {f}
                    <button
                      type="button"
                      onClick={() => removeFeature(f)}
                      className="ml-0.5 opacity-60 hover:opacity-100 transition-opacity"
                    >
                      <X size={11} />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Tone + Platform */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label
                className="block text-[13px] font-medium mb-1.5"
                style={{ color: "var(--text-2)" }}
              >
                Tone
              </label>
              <select
                value={form.tone}
                onChange={(e) =>
                  setForm((p) => ({ ...p, tone: e.target.value }))
                }
                className="w-full rounded-lg px-3.5 py-2.5 text-sm text-white transition-all appearance-none"
                style={{
                  background: "var(--bg-input)",
                  border: "1px solid var(--border-md)",
                }}
              >
                {TONES.map((t) => (
                  <option key={t} value={t} style={{ background: "#161616" }}>
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                className="block text-[13px] font-medium mb-1.5"
                style={{ color: "var(--text-2)" }}
              >
                Platform
              </label>
              <select
                value={form.platform}
                onChange={(e) =>
                  setForm((p) => ({ ...p, platform: e.target.value }))
                }
                className="w-full rounded-lg px-3.5 py-2.5 text-sm text-white transition-all appearance-none"
                style={{
                  background: "var(--bg-input)",
                  border: "1px solid var(--border-md)",
                }}
              >
                {PLATFORMS.map((p) => (
                  <option key={p} value={p} style={{ background: "#161616" }}>
                    {p
                      .replace(/_/g, " ")
                      .replace(/\b\w/g, (c) => c.toUpperCase())}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Duration */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <label
                className="text-[13px] font-medium"
                style={{ color: "var(--text-2)" }}
              >
                Target duration
              </label>
              <span
                className="text-[13px] font-semibold tabular-nums"
                style={{ color: "var(--accent)" }}
              >
                {form.target_duration}s
              </span>
            </div>
            {/* Custom styled range slider */}
            <div className="relative">
              {/* Track background */}
              <div
                className="absolute top-1/2 left-0 right-0 h-1.5 rounded-full -translate-y-1/2"
                style={{ background: "rgba(255,255,255,0.08)" }}
              />
              {/* Filled portion */}
              <div
                className="absolute top-1/2 left-0 h-1.5 rounded-full -translate-y-1/2 pointer-events-none"
                style={{
                  background: "var(--accent)",
                  width: `${(((form.target_duration ?? 30) - 15) / (60 - 15)) * 100}%`,
                }}
              />
              <input
                type="range"
                min={15}
                max={60}
                step={5}
                value={form.target_duration}
                onChange={(e) =>
                  setForm((p) => ({
                    ...p,
                    target_duration: Number(e.target.value),
                  }))
                }
                className="relative w-full cursor-pointer appearance-none bg-transparent"
                style={{
                  height: "20px",
                  // webkit thumb
                  WebkitAppearance: "none",
                }}
              />
            </div>
            <style>{`
              input[type=range]::-webkit-slider-thumb {
                -webkit-appearance: none;
                width: 18px;
                height: 18px;
                border-radius: 50%;
                background: var(--accent);
                box-shadow: 0 0 0 3px rgba(255,98,0,0.2);
                cursor: pointer;
                margin-top: -7px;
              }
              input[type=range]::-moz-range-thumb {
                width: 18px;
                height: 18px;
                border-radius: 50%;
                background: var(--accent);
                box-shadow: 0 0 0 3px rgba(255,98,0,0.2);
                cursor: pointer;
                border: none;
              }
              input[type=range]::-webkit-slider-runnable-track {
                height: 6px;
                background: transparent;
                border-radius: 9999px;
              }
              input[type=range]::-moz-range-track {
                height: 6px;
                background: transparent;
                border-radius: 9999px;
              }
            `}</style>
            <div
              className="flex justify-between text-[11px] mt-1.5"
              style={{ color: "var(--text-3)" }}
            >
              <span>15s</span>
              <span>30s</span>
              <span>45s</span>
              <span>60s</span>
            </div>
          </div>

          {/* Divider */}
          <div style={{ borderTop: "1px solid var(--border)" }} />

          {/* Error */}
          {error && (
            <div
              className="rounded-lg px-4 py-3 text-[13px]"
              style={{
                background: "rgba(220,38,38,0.08)",
                border: "1px solid rgba(220,38,38,0.25)",
                color: "#f87171",
              }}
            >
              {error}
            </div>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 rounded-lg text-[15px] font-semibold text-white transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: "var(--accent)" }}
            onMouseEnter={(e) => {
              if (!loading)
                (e.currentTarget as HTMLButtonElement).style.filter =
                  "brightness(1.1)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.filter = "";
            }}
          >
            {loading ? (
              <>
                <Loader2 size={18} className="animate-spin" />
                Generating script...
              </>
            ) : (
              <>
                <Sparkles size={18} />
                Generate script
              </>
            )}
          </button>
        </form>

        {/* Footer note */}
        <p
          className="text-center text-[12px] mt-5"
          style={{ color: "var(--text-3)" }}
        >
          Script generation uses Claude · Images via Pollinations.ai (free) ·
          Video stitched locally with ffmpeg
        </p>
      </div>
    </main>
  );
}
