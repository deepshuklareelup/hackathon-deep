# Rofy Reel Agent

An AI agent that turns a product JSON + optional image into a short-form video reel (Instagram/TikTok/YouTube Shorts).

## Architecture

```
main.py
  └── orchestrator.py (coordinator)
        ├── script_agent.py   → Claude Haiku writes scene-by-scene script
        ├── image_agent.py    → fal.ai FLUX generates scene images
        ├── video_agent.py    → fal.ai ltx-video generates motion clips
        ├── tts_agent.py      → OpenAI TTS generates narration audio
        ├── editor.py         → ffmpeg stitches clips + audio → final.mp4
        └── uploader.py       → GCS upload (optional)
```

Each agent follows **Think → Act → Observe** and logs every step to `ReelJob.logs`.

## Setup

```bash
cd Hackathon/rofy_reel_agent

# Install dependencies
pip install -r requirements.txt

# Install ffmpeg (required for video editing)
# Windows: winget install ffmpeg
# Mac:     brew install ffmpeg
# Linux:   sudo apt install ffmpeg
```

API keys are **auto-loaded** from `../../rofy_2_llm/.env` — no extra setup needed.  
To override or add a `FAL_KEY`, create a local `.env` file (see `.env.example`).

## Usage

```bash
# Basic — uses sample product with human approval step
python main.py --product sample_product.json

# With product image
python main.py --product sample_product.json --image product.jpg

# Fully automatic (no approval prompt)
python main.py --product sample_product.json --no-approve

# Custom output directory
python main.py --product sample_product.json --output ./my_reels
```

## Product JSON Format

```json
{
  "name": "Your Product Name",
  "description": "What it does",
  "price": "$29.99",
  "features": ["Feature 1", "Feature 2"],
  "target_audience": "Who it's for",
  "tone": "exciting",
  "platform": "instagram"
}
```

**Tone options:** `exciting` | `professional` | `playful` | `luxury`  
**Platform options:** `instagram` | `tiktok` | `youtube_shorts`

## Output

```
output/
  {job_id}/
    final.mp4          ← the finished reel
    audio/
      scene_00.mp3     ← per-scene narration
      scene_01.mp3
    work/
      scene_00/        ← intermediate clips
      scene_01/
```

## Cost Estimate (4-scene reel)

| Stage           | Service          | Approx Cost |
| --------------- | ---------------- | ----------- |
| Script          | Claude Haiku     | ~$0.001     |
| Images (4)      | fal.ai FLUX      | ~$0.012     |
| Video clips (4) | fal.ai ltx-video | ~$0.20      |
| TTS narration   | OpenAI tts-1     | ~$0.005     |
| **Total**       |                  | **~$0.22**  |
