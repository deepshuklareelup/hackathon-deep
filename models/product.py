from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProductInput:
    name: str
    description: str
    price: Optional[str] = None
    features: List[str] = field(default_factory=list)
    target_audience: Optional[str] = None
    tone: str = "exciting"        # exciting | professional | playful | luxury
    platform: str = "instagram"   # instagram | tiktok | youtube_shorts
    target_duration: Optional[int] = None  # seconds requested by user
    image_path: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict, image_path: Optional[str] = None) -> "ProductInput":
        known = {"name", "description", "price", "features", "target_audience", "tone", "platform", "target_duration"}
        return cls(
            name=data.get("name", "Product"),
            description=data.get("description", ""),
            price=data.get("price"),
            features=data.get("features", []),
            target_audience=data.get("target_audience"),
            tone=data.get("tone", "exciting"),
            platform=data.get("platform", "instagram"),
            target_duration=data.get("target_duration"),
            image_path=image_path,
            extra={k: v for k, v in data.items() if k not in known},
        )


@dataclass
class Scene:
    index: int
    narration: str           # Text spoken by narrator
    visual_direction: str    # What to show visually (human-readable)
    duration_seconds: int    # How long this scene lasts (2-5 recommended)
    image_prompt: str        # FLUX prompt for scene image generation
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    audio_path: Optional[str] = None
    video_path: Optional[str] = None


@dataclass
class Script:
    hook: str               # Opening hook line (attention grabber)
    scenes: List[Scene]
    cta: str                # Call to action (last scene narration)
    total_duration: int     # Sum of all scene durations

    @property
    def full_narration(self) -> str:
        parts = [self.hook] + [s.narration for s in self.scenes] + [self.cta]
        return " ".join(parts)

    @property
    def scene_count(self) -> int:
        return len(self.scenes)


@dataclass
class LogEntry:
    stage: str
    action: str
    result: str
    cost_usd: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReelJob:
    """
    The central state object flowing through the entire pipeline.
    Every agent reads from and writes to this object.
    """
    job_id: str
    product: ProductInput
    output_dir: str = "./output"
    script: Optional[Script] = None
    final_video_path: Optional[str] = None
    final_video_url: Optional[str] = None
    status: str = "pending"
    # pending | scripting | imaging | videoing | tts | editing | uploading | done | failed
    costs: Dict[str, float] = field(default_factory=dict)
    logs: List[LogEntry] = field(default_factory=list)
    error: Optional[str] = None
    critic_report: Optional[Dict[str, Any]] = None   # set by critic_agent
    human_feedback: Optional[str] = None             # set by human review (None = pending, 'approved' = go, else = rewrite note)

    @property
    def total_cost(self) -> float:
        return round(sum(self.costs.values()), 6)

    def log(self, stage: str, action: str, result: str, cost: float = 0.0, **meta):
        entry = LogEntry(stage=stage, action=action, result=result, cost_usd=cost, metadata=meta)
        self.logs.append(entry)
        if cost > 0:
            self.costs[stage] = round(self.costs.get(stage, 0.0) + cost, 6)

    def set_status(self, status: str):
        self.status = status
        self.log(stage=status, action="status_change", result=f"Pipeline moved to: {status}")
