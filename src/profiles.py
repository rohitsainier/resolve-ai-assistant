#!/usr/bin/env python3
"""Creator profiles — per-user style configuration.

A profile is a small JSON document describing an editor's preferences:
tone, pacing, cut style, target platforms, typical voice. The agent loads
the active profile on every run and injects a summary into its system
prompt, so "find the funniest 3 moments" behaves differently for a
corporate creator vs a YouTuber.

Profiles live at ~/.resolve-ai-assistant/profiles/<id>.json
The active profile pointer lives at ~/.resolve-ai-assistant/active_profile
"""

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


PROFILES_DIR = os.path.expanduser("~/.resolve-ai-assistant/profiles")
ACTIVE_POINTER = os.path.expanduser("~/.resolve-ai-assistant/active_profile")


@dataclass
class Profile:
    id: str
    name: str
    description: str = ""
    # Editing style
    tone: str = "neutral"                      # e.g. "casual", "formal", "energetic"
    pacing: str = "balanced"                   # "fast", "balanced", "slow"
    max_shot_seconds: Optional[float] = None   # None = no limit
    # Target platforms & formats
    target_platforms: List[str] = field(default_factory=list)  # e.g. ["youtube_1080p"]
    target_lufs: float = -14.0
    # Content preferences
    filler_sensitivity: str = "medium"         # "low", "medium", "high" — how aggressively to cut um/uh
    dead_air_threshold: float = 3.0            # seconds — pauses longer than this are cut candidates
    preferred_marker_colors: Dict[str, str] = field(default_factory=dict)  # e.g. {"highlight": "Green"}
    # Free-form hints for the LLM
    style_notes: str = ""                      # e.g. "I like hard cuts, no fades. Never add zoom effects."

    def to_prompt_summary(self) -> str:
        """Compact one-paragraph summary to inject into the agent system prompt."""
        parts = [f"Creator profile: **{self.name}**."]
        if self.description:
            parts.append(self.description.strip())
        attrs = []
        if self.tone != "neutral":
            attrs.append(f"tone: {self.tone}")
        if self.pacing != "balanced":
            attrs.append(f"pacing: {self.pacing}")
        if self.max_shot_seconds:
            attrs.append(f"max shot ≈ {self.max_shot_seconds}s")
        if self.target_platforms:
            attrs.append(f"target platforms: {', '.join(self.target_platforms)}")
        if self.target_lufs != -14.0:
            attrs.append(f"target loudness: {self.target_lufs} LUFS")
        if self.filler_sensitivity != "medium":
            attrs.append(f"filler-cut sensitivity: {self.filler_sensitivity}")
        if attrs:
            parts.append("Preferences: " + "; ".join(attrs) + ".")
        if self.style_notes:
            parts.append(f"Style notes: {self.style_notes.strip()}")
        return " ".join(parts)


# ---------- Built-in starter profiles ----------

BUILTINS: Dict[str, Profile] = {
    "default": Profile(
        id="default",
        name="Default",
        description="Balanced baseline — no strong opinions.",
    ),
    "youtube_creator": Profile(
        id="youtube_creator",
        name="YouTube Creator",
        description="Long-form YouTube with a mix of talk + b-roll.",
        tone="casual",
        pacing="balanced",
        max_shot_seconds=12.0,
        target_platforms=["youtube_1080p"],
        target_lufs=-14.0,
        filler_sensitivity="high",
        dead_air_threshold=2.0,
        style_notes="Keep hooks at the start. Cut filler words aggressively. "
                    "Prefer hard cuts over fades.",
    ),
    "shorts_creator": Profile(
        id="shorts_creator",
        name="Shorts / TikTok Creator",
        description="Vertical short-form, fast-paced.",
        tone="energetic",
        pacing="fast",
        max_shot_seconds=4.0,
        target_platforms=["tiktok_vertical"],
        target_lufs=-14.0,
        filler_sensitivity="high",
        dead_air_threshold=1.0,
        style_notes="Every cut needs to feel kinetic. Max 4 seconds per shot. "
                    "Grab attention in the first second.",
    ),
    "podcast_host": Profile(
        id="podcast_host",
        name="Podcast Host",
        description="Multi-speaker conversation; preserve natural pacing.",
        tone="conversational",
        pacing="slow",
        max_shot_seconds=None,
        target_platforms=["youtube_1080p"],
        target_lufs=-16.0,
        filler_sensitivity="low",
        dead_air_threshold=5.0,
        style_notes="Do NOT cut every um/uh — that kills conversational feel. "
                    "Only cut true dead air (>5s). Respect speaker changes.",
    ),
    "corporate_explainer": Profile(
        id="corporate_explainer",
        name="Corporate / Explainer",
        description="Formal tone, accurate diction, careful pacing.",
        tone="formal",
        pacing="balanced",
        max_shot_seconds=8.0,
        target_platforms=["youtube_1080p"],
        target_lufs=-16.0,
        filler_sensitivity="high",
        dead_air_threshold=2.5,
        style_notes="Remove all filler words. No casual humor. "
                    "Add chapter markers at every topic shift.",
    ),
}


# ---------- Disk I/O ----------

def _ensure_dir():
    os.makedirs(PROFILES_DIR, exist_ok=True)


def _safe_id(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "_", s)
    return s[:60] or "profile"


def load_profile(profile_id: str) -> Optional[Profile]:
    """Load a profile. Checks disk first, then builtins."""
    _ensure_dir()
    path = os.path.join(PROFILES_DIR, f"{profile_id}.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # preferred_marker_colors was sometimes missing on older saves
            data.setdefault("preferred_marker_colors", {})
            return Profile(**data)
        except Exception:
            pass
    return BUILTINS.get(profile_id)


def save_profile(profile: Profile) -> str:
    """Write a profile to disk. Returns the saved path."""
    _ensure_dir()
    profile.id = _safe_id(profile.id)
    path = os.path.join(PROFILES_DIR, f"{profile.id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(profile), f, indent=2)
    return path


def list_all() -> List[Dict]:
    """Return shallow info for every known profile (builtins + on-disk)."""
    _ensure_dir()
    seen = set()
    out = []
    # On-disk first (they override builtins of the same id)
    for name in sorted(os.listdir(PROFILES_DIR)):
        if not name.endswith(".json"):
            continue
        pid = name[:-5]
        p = load_profile(pid)
        if p:
            out.append({"id": p.id, "name": p.name, "description": p.description, "builtin": False})
            seen.add(pid)
    for pid, p in BUILTINS.items():
        if pid in seen:
            continue
        out.append({"id": p.id, "name": p.name, "description": p.description, "builtin": True})
    return out


def get_active_id() -> str:
    """Return the id of the active profile (default: 'default')."""
    try:
        with open(ACTIVE_POINTER, "r", encoding="utf-8") as f:
            pid = f.read().strip()
            if pid:
                return pid
    except Exception:
        pass
    return "default"


def set_active_id(profile_id: str) -> None:
    _ensure_dir()
    with open(ACTIVE_POINTER, "w", encoding="utf-8") as f:
        f.write(profile_id)


def get_active_profile() -> Profile:
    """Return the currently-active profile (or 'default' if missing)."""
    pid = get_active_id()
    p = load_profile(pid)
    if p is None:
        p = BUILTINS["default"]
    return p
