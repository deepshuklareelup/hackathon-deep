"""
Configuration loader. Loads API keys from local .env file.
"""
import os
from pathlib import Path
from dotenv import load_dotenv


def _load_env():
    root = Path(__file__).parent
    local_env = root / ".env"
    if local_env.exists():
        load_dotenv(local_env, override=True)


_load_env()

# ── API Keys ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
FAL_KEY: str = os.environ.get("FAL_KEY", "")
GCS_BUCKET_NAME: str = os.environ.get("GCS_BUCKET_NAME") or os.environ.get("GCS_BUCKET", "")
GOOGLE_APPLICATION_CREDENTIALS: str = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

# ── TTS settings ──────────────────────────────────────────────────────────────
TTS_MODEL: str = os.environ.get("TTS_MODEL", "tts-1")
TTS_VOICE: str = os.environ.get("TTS_VOICE", "nova")


# ── Models — Smart routing ────────────────────────────────────────────────────
# Simple products (< 3 features) → Haiku (cheap, fast)
# Complex products (3+ features, custom tone/audience) → Sonnet (higher quality)
SCRIPT_MODEL_FAST: str = "claude-haiku-4-5"             # $0.80/$4 per M tokens
SCRIPT_MODEL_SMART: str = "claude-sonnet-4-5"           # higher quality for complex
SCRIPT_MODEL: str = SCRIPT_MODEL_FAST                   # default; overridden at runtime


def choose_script_model(product) -> str:
    """
    Smart model routing: use Haiku for simple products, Sonnet for complex ones.
    Complexity signal: many features OR long description OR non-default tone.
    """
    feature_count = len(product.features) if product.features else 0
    desc_length = len(product.description)
    is_complex = (
        feature_count >= 4
        or desc_length > 300
        or product.tone in ("luxury", "professional")
        or bool(product.target_audience)
    )
    return SCRIPT_MODEL_SMART if is_complex else SCRIPT_MODEL_FAST

# ── fal.ai endpoints ──────────────────────────────────────────────────────────
FAL_IMAGE_MODEL: str = "fal-ai/flux/schnell"
FAL_VIDEO_MODEL: str = "fal-ai/ltx-video/image-to-video"

# ── Platform dimensions ───────────────────────────────────────────────────────
PLATFORM_CONFIG = {
    "instagram":       {"width": 576, "height": 1024, "fal_size": "portrait_16_9"},
    "tiktok":          {"width": 576, "height": 1024, "fal_size": "portrait_16_9"},
    "youtube_shorts":  {"width": 576, "height": 1024, "fal_size": "portrait_16_9"},
    "instagram_square": {"width": 1024, "height": 1024, "fal_size": "square_hd"},
}


def validate_keys() -> dict[str, bool]:
    """Check which services are available based on configured keys."""
    return {
        "script_agent":  bool(ANTHROPIC_API_KEY),
        "image_agent":   bool(FAL_KEY),
        "video_agent":   bool(FAL_KEY),
        "tts_agent":     bool(OPENAI_API_KEY),
        "uploader":      bool(GCS_BUCKET_NAME),
    }
