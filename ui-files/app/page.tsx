"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { generateScript, ProductInput } from "@/lib/api";

const TONES = ["professional", "casual", "luxury", "energetic", "friendly"];
const PLATFORMS = [
  "instagram",
  "tiktok",
  "youtube_shorts",
  "linkedin",
  "twitter",
];

export default function HomePage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [featureInput, setFeatureInput] = useState("");
  const [form, setForm] = useState<ProductInput>({
    name: "",
    description: "",
    features: [],
    tone: "professional",
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
    <main className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-950 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-2xl">
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-white mb-2">
            🎬 Rofy Reel Agent
          </h1>
          <p className="text-slate-400 text-lg">
            AI-powered product video reels in seconds
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-slate-800/60 backdrop-blur rounded-2xl p-8 border border-slate-700 shadow-2xl space-y-6"
        >
          {/* Product Name */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Product Name *
            </label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
              placeholder="e.g. AeroFoam Running Shoes"
              className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:border-purple-500"
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Description *
            </label>
            <textarea
              value={form.description}
              onChange={(e) =>
                setForm((p) => ({ ...p, description: e.target.value }))
              }
              placeholder="Describe your product in detail..."
              rows={3}
              className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 resize-none"
            />
          </div>

          {/* Features */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Key Features
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
                placeholder="Add a feature and press Enter"
                className="flex-1 bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:border-purple-500"
              />
              <button
                type="button"
                onClick={addFeature}
                className="px-4 py-2.5 bg-purple-700 hover:bg-purple-600 text-white rounded-lg font-medium transition"
              >
                Add
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {form.features.map((f) => (
                <span
                  key={f}
                  className="inline-flex items-center gap-1 bg-purple-900/50 border border-purple-700 text-purple-200 rounded-full px-3 py-1 text-sm"
                >
                  {f}
                  <button
                    type="button"
                    onClick={() => removeFeature(f)}
                    className="text-purple-400 hover:text-white ml-1"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          </div>

          {/* Tone + Platform */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                Tone
              </label>
              <select
                value={form.tone}
                onChange={(e) =>
                  setForm((p) => ({ ...p, tone: e.target.value }))
                }
                className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-purple-500"
              >
                {TONES.map((t) => (
                  <option key={t} value={t}>
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">
                Platform
              </label>
              <select
                value={form.platform}
                onChange={(e) =>
                  setForm((p) => ({ ...p, platform: e.target.value }))
                }
                className="w-full bg-slate-900 border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-purple-500"
              >
                {PLATFORMS.map((p) => (
                  <option key={p} value={p}>
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
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Target Duration:{" "}
              <span className="text-purple-400">{form.target_duration}s</span>
            </label>
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
              className="w-full accent-purple-500"
            />
            <div className="flex justify-between text-xs text-slate-500 mt-1">
              <span>15s</span>
              <span>60s</span>
            </div>
          </div>

          {error && (
            <div className="bg-red-900/40 border border-red-700 rounded-lg px-4 py-3 text-red-300 text-sm">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl text-lg transition shadow-lg shadow-purple-900/40"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <span className="animate-spin h-5 w-5 border-2 border-white border-t-transparent rounded-full" />
                Generating Script...
              </span>
            ) : (
              "✨ Generate Script"
            )}
          </button>
        </form>
      </div>
    </main>
  );
}
