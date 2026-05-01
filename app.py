"""
Rofy Reel Agent — Streamlit Web UI

Run with: streamlit run app.py
"""
import json
import sys
import tempfile
import threading
from pathlib import Path

import streamlit as st

# ── Path setup so imports resolve ─────────────────────────────────────────────
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import validate_keys
from models import ProductInput

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Rofy Reel Agent",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stage-card {
        background: #1e1e2e;
        border-left: 4px solid #7c3aed;
        padding: 12px 16px;
        border-radius: 6px;
        margin: 6px 0;
    }
    .stage-done  { border-left-color: #22c55e; }
    .stage-active{ border-left-color: #f59e0b; }
    .stage-error { border-left-color: #ef4444; }
    .metric-box {
        background: #0f172a;
        padding: 16px;
        border-radius: 8px;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)


# ── Session state defaults ─────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "job": None,
        "running": False,
        "error": None,
        "script_approved": False,
        "stage_logs": [],
        "show_script_review": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ── Sidebar — Product Input ────────────────────────────────────────────────────
with st.sidebar:
    st.title("🎬 Rofy Reel Agent")
    st.caption("Turn a product into a short-form video reel")
    st.divider()

    # ── API key status ─────────────────────────────────────────────────────────
    keys = validate_keys()
    st.subheader("API Keys")
    key_labels = {
        "script_agent":  ("🤖 Claude (Script)", "ANTHROPIC_API_KEY"),
        "image_agent":   ("🖼 fal.ai (Images)", "FAL_KEY"),
        "video_agent":   ("🎥 fal.ai (Video)",  "FAL_KEY"),
        "tts_agent":     ("🔊 OpenAI (TTS)",     "OPENAI_API_KEY"),
        "upload_agent":  ("☁ GCS (Upload)",     "GOOGLE_APPLICATION_CREDENTIALS"),
    }
    for service, (label, env_var) in key_labels.items():
        status = "✅" if keys.get(service) else "❌"
        st.markdown(f"{status} **{label}**")

    st.divider()

    # ── Product JSON input ─────────────────────────────────────────────────────
    st.subheader("Product Details")
    input_mode = st.radio("Input mode", ["JSON", "Form"], horizontal=True)

    product_input: ProductInput | None = None

    if input_mode == "JSON":
        sample = {
            "name": "AquaFlow Water Bottle",
            "description": "A self-cleaning water bottle with UV purification and temperature control.",
            "price": "$49.99",
            "features": ["UV self-cleaning", "24hr temperature control", "1L BPA-free"],
            "target_audience": "fitness enthusiasts",
            "tone": "exciting",
            "platform": "instagram",
        }
        json_text = st.text_area(
            "Product JSON",
            value=json.dumps(sample, indent=2),
            height=280,
            help="Paste your product JSON here",
        )
        try:
            product_dict = json.loads(json_text)
            _parse_error = None
        except json.JSONDecodeError as e:
            product_dict = None
            _parse_error = str(e)

        if _parse_error:
            st.error(f"Invalid JSON: {_parse_error}")
    else:
        # Form mode
        name = st.text_input("Product name", "AquaFlow Water Bottle")
        description = st.text_area("Description", "A self-cleaning water bottle with UV purification.", height=80)
        price = st.text_input("Price (optional)", "$49.99")
        features_raw = st.text_area("Features (one per line)", "UV self-cleaning\n24hr temperature control\n1L BPA-free", height=80)
        target_audience = st.text_input("Target audience", "fitness enthusiasts")
        product_dict = {
            "name": name,
            "description": description,
            "price": price,
            "features": [f.strip() for f in features_raw.splitlines() if f.strip()],
            "target_audience": target_audience,
        }
        _parse_error = None

    tone = st.selectbox("Tone", ["exciting", "professional", "playful", "luxury"], index=0)
    platform = st.selectbox("Platform", ["instagram", "tiktok", "youtube_shorts"], index=0)

    # ── Image upload ──────────────────────────────────────────────────────────
    st.subheader("Product Image (optional)")
    uploaded_image = st.file_uploader(
        "Upload a product photo",
        type=["jpg", "jpeg", "png", "webp"],
        help="Used as a style reference for image generation",
    )

    st.divider()

    # ── Generate button ───────────────────────────────────────────────────────
    can_run = (
        not st.session_state.running
        and product_dict is not None
        and not _parse_error
        and keys.get("script_agent")
    )

    if not keys.get("script_agent"):
        st.warning("Add ANTHROPIC_API_KEY to your .env to enable generation.")

    generate_btn = st.button(
        "🚀 Generate Reel",
        disabled=not can_run,
        use_container_width=True,
        type="primary",
    )


# ── Main area ─────────────────────────────────────────────────────────────────
st.title("🎬 Rofy Reel Agent")
st.caption("AI-powered short-form video reel generator")

if generate_btn and product_dict and not _parse_error:
    # Save uploaded image to temp file if provided
    image_path = None
    if uploaded_image:
        suffix = Path(uploaded_image.name).suffix
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(uploaded_image.read())
        tmp.close()
        image_path = tmp.name

    # Build product
    product_dict["tone"] = tone
    product_dict["platform"] = platform
    product = ProductInput.from_dict(product_dict, image_path=image_path)

    # Reset state for new run
    st.session_state.job = None
    st.session_state.error = None
    st.session_state.script_approved = False
    st.session_state.show_script_review = False
    st.session_state.stage_logs = []
    st.session_state.running = True
    st.session_state["_product"] = product
    st.rerun()


# ── Pipeline progress UI ───────────────────────────────────────────────────────
STAGES = [
    ("1/6", "Script Generation", "scripting"),
    ("2/6", "Image Generation",  "imaging"),
    ("3/6", "Video Clips",       "videoing"),
    ("4/6", "TTS Narration",     "tts"),
    ("5/6", "Video Editing",     "editing"),
    ("6/6", "Upload",            "uploading"),
]


def _stage_icon(stage_key: str, current_status: str) -> str:
    order = [s[2] for s in STAGES]
    if current_status == "done":
        return "✅"
    if stage_key == current_status:
        return "⏳"
    try:
        if order.index(stage_key) < order.index(current_status):
            return "✅"
    except ValueError:
        pass
    return "⬜"


# ── Running state — run pipeline stage by stage ───────────────────────────────
if st.session_state.running and st.session_state.job is None:
    product: ProductInput = st.session_state["_product"]

    st.info("🔄 Running pipeline... this may take a few minutes.")
    progress_placeholder = st.empty()

    # Stage 1: Script
    with progress_placeholder.container():
        st.markdown("### Pipeline Progress")
        for num, label, key in STAGES:
            icon = "⏳" if key == "scripting" else "⬜"
            st.markdown(f"{icon} **Stage {num}:** {label}")

    with st.spinner("Generating script with Claude..."):
        from agent import script_agent
        from models import ReelJob
        import uuid

        job_id = uuid.uuid4().hex[:8]
        job = ReelJob(job_id=job_id, product=product, output_dir="./output")
        Path("./output").mkdir(parents=True, exist_ok=True)
        job.set_status("scripting")
        job = script_agent.run(job)

    if job.error or not job.script:
        st.session_state.running = False
        st.session_state.error = job.error or "Script generation failed"
        st.session_state.job = job
        st.rerun()
    else:
        st.session_state.job = job
        st.session_state.show_script_review = True
        st.session_state.running = False
        st.rerun()


# ── Script Review ─────────────────────────────────────────────────────────────
if st.session_state.show_script_review and not st.session_state.script_approved:
    job = st.session_state.job
    script = job.script

    st.success("✅ Script generated! Review and approve to continue.")

    col1, col2, col3 = st.columns([1, 1, 1])
    col1.metric("Scenes", script.scene_count)
    col2.metric("Total Duration", f"~{script.total_duration}s")
    col3.metric("Script Cost", f"${job.total_cost:.4f}")

    st.divider()

    st.markdown(f"### 🎣 Hook\n> {script.hook}")

    st.markdown("### 🎬 Scenes")
    for scene in script.scenes:
        with st.expander(f"Scene {scene.index + 1} — {scene.duration_seconds}s", expanded=True):
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("**Narration**")
                st.write(scene.narration)
            with col_b:
                st.markdown("**Visual Direction**")
                st.write(scene.visual_direction)
            st.markdown(f"**Image prompt:** `{scene.image_prompt}`")

    st.markdown(f"### 📢 CTA\n> {script.cta}")

    st.divider()

    keys = validate_keys()
    missing = []
    if not keys.get("image_agent"):
        missing.append("FAL_KEY (images will be skipped)")
    if not keys.get("tts_agent"):
        missing.append("OPENAI_API_KEY (audio will be skipped)")

    if missing:
        st.warning("⚠ Missing keys — some stages will be skipped:\n" + "\n".join(f"• {m}" for m in missing))

    col_approve, col_cancel = st.columns(2)
    with col_approve:
        if st.button("✅ Approve & Continue", type="primary", use_container_width=True):
            st.session_state.script_approved = True
            st.session_state.running = True
            st.session_state.show_script_review = False
            st.rerun()
    with col_cancel:
        if st.button("❌ Cancel", use_container_width=True):
            st.session_state.show_script_review = False
            st.session_state.running = False
            st.session_state.job = None
            st.rerun()


# ── Stages 2–6: Run after approval ────────────────────────────────────────────
if st.session_state.running and st.session_state.script_approved and st.session_state.job:
    job = st.session_state.job
    keys = validate_keys()

    progress_placeholder = st.empty()

    def _update_progress(current_stage: str):
        with progress_placeholder.container():
            st.markdown("### Pipeline Progress")
            for num, label, key in STAGES:
                icon = _stage_icon(key, current_stage)
                if key == "scripting":
                    icon = "✅"  # always done at this point
                st.markdown(f"{icon} **Stage {num}:** {label}")

    # Stage 2: Images
    _update_progress("imaging")
    with st.spinner("Stage 2/6 — Generating images with FLUX..."):
        if keys.get("image_agent"):
            from agent import image_agent
            job.set_status("imaging")
            job = image_agent.run(job)
        else:
            st.toast("⚠ FAL_KEY not set — skipping image generation", icon="⚠️")

    # Stage 3: Video clips
    _update_progress("videoing")
    with st.spinner("Stage 3/6 — Generating video clips..."):
        if keys.get("video_agent"):
            from agent import video_agent
            job.set_status("videoing")
            job = video_agent.run(job)
        else:
            st.toast("⚠ FAL_KEY not set — skipping video clip generation", icon="⚠️")

    # Stage 4: TTS
    _update_progress("tts")
    with st.spinner("Stage 4/6 — Generating narration audio..."):
        if keys.get("tts_agent"):
            from agent import tts_agent
            job.set_status("tts")
            job = tts_agent.run(job)
        else:
            st.toast("⚠ OPENAI_API_KEY not set — skipping TTS", icon="⚠️")

    # Stage 5: Edit
    _update_progress("editing")
    with st.spinner("Stage 5/6 — Editing final video with ffmpeg..."):
        from agent import editor
        job.set_status("editing")
        job = editor.run(job)

    # Stage 6: Upload
    _update_progress("uploading")
    with st.spinner("Stage 6/6 — Uploading video..."):
        from agent import uploader
        job.set_status("uploading")
        job = uploader.run(job)
        job.set_status("done")

    st.session_state.job = job
    st.session_state.running = False
    st.session_state.script_approved = False
    st.rerun()


# ── Final result display ───────────────────────────────────────────────────────
if st.session_state.job and not st.session_state.running and not st.session_state.show_script_review:
    job = st.session_state.job

    if job.status == "done":
        st.success("🎉 Reel generated successfully!")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Job ID", job.job_id)
        col2.metric("Status", job.status.upper())
        col3.metric("Total Cost", f"${job.total_cost:.4f}")
        col4.metric("Scenes", job.script.scene_count if job.script else "-")

        st.divider()

        # Video player
        if job.final_video_url and job.final_video_url.startswith("http"):
            st.markdown("### 🎥 Your Reel")
            st.video(job.final_video_url)
        elif job.final_video_path and Path(job.final_video_path).exists():
            st.markdown("### 🎥 Your Reel")
            with open(job.final_video_path, "rb") as f:
                st.video(f.read())
            st.download_button(
                "⬇ Download Video",
                data=open(job.final_video_path, "rb"),
                file_name=f"reel_{job.job_id}.mp4",
                mime="video/mp4",
                use_container_width=True,
            )
        else:
            st.warning("No video file found — check logs below.")

        # Cost breakdown
        if job.costs:
            st.divider()
            st.markdown("### 💰 Cost Breakdown")
            cost_col1, cost_col2 = st.columns([2, 1])
            with cost_col1:
                for stage, cost in job.costs.items():
                    if cost > 0:
                        st.markdown(f"- **{stage.title()}:** ${cost:.6f}")
            with cost_col2:
                st.metric("Total", f"${job.total_cost:.4f}")

        # Logs
        if job.logs:
            with st.expander("📋 Pipeline Logs", expanded=False):
                for entry in job.logs:
                    color = "green" if entry.cost_usd == 0 else "orange"
                    cost_str = f" | ${entry.cost_usd:.6f}" if entry.cost_usd > 0 else ""
                    st.markdown(
                        f"<span style='color:{color}'>[{entry.stage}]</span> "
                        f"**{entry.action}** — {entry.result}{cost_str}",
                        unsafe_allow_html=True,
                    )

        # Reset button
        st.divider()
        if st.button("🔄 Generate Another Reel", use_container_width=True):
            for k in ["job", "running", "error", "script_approved", "show_script_review", "stage_logs", "_product"]:
                st.session_state.pop(k, None)
            _init_state()
            st.rerun()

    elif job.status in ("failed", "stopped"):
        st.error(f"Pipeline {job.status}: {job.error or 'No error details'}")
        if st.button("🔄 Try Again", use_container_width=True):
            for k in ["job", "running", "error", "script_approved", "show_script_review", "stage_logs", "_product"]:
                st.session_state.pop(k, None)
            _init_state()
            st.rerun()

# ── Error display ──────────────────────────────────────────────────────────────
if st.session_state.error and not st.session_state.job:
    st.error(f"❌ Error: {st.session_state.error}")


# ── Empty state ────────────────────────────────────────────────────────────────
if (
    not st.session_state.running
    and not st.session_state.job
    and not st.session_state.show_script_review
    and not st.session_state.error
):
    st.markdown("""
    ### How it works

    1. **Fill in your product details** in the sidebar (JSON or form)
    2. **Select tone and platform** (Instagram / TikTok / YouTube Shorts)
    3. **Optionally upload a product image** for style reference
    4. Click **Generate Reel** to start the 6-stage pipeline:

    | Stage | What happens |
    |-------|-------------|
    | 1 — Script | Claude Haiku writes a scene-by-scene script |
    | 2 — Images | FLUX generates one image per scene |
    | 3 — Video  | ltx-video animates each image into a clip |
    | 4 — TTS    | OpenAI TTS narrates each scene |
    | 5 — Edit   | ffmpeg stitches clips + audio → final.mp4 |
    | 6 — Upload | Optionally uploads to Google Cloud Storage |

    5. **Review the script** before committing to the expensive image/video stages
    6. **Download or share** your finished reel

    ---
    *Add `FAL_KEY` to your `.env` file to enable image & video generation.*
    """)
