#!/usr/bin/env python3
"""Visual frame analysis.

Extracts a frame at a given timeline timestamp via ffmpeg, then sends it to
the configured LLM's vision endpoint (Claude or GPT-4o) for description or
scoring. Both providers supported; uses the same auto-detection as analyze.py.
"""

import base64
import os
import subprocess
import tempfile
from typing import List, Optional, Tuple

from transcribe import _ffmpeg, get_all_media_paths


LOG_PATH = os.path.expanduser("~/.resolve-ai-assistant/vision.log")


def _log(msg: str):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        import time
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _resolve_source_for_timestamp(timeline, timeline_seconds: float
                                 ) -> Tuple[Optional[str], float]:
    """Map a timeline timestamp to (source_file_path, source_seconds).

    For single-clip timelines this is trivial. For multi-clip timelines we walk
    the video track in track 1 and find the clip that contains this moment.
    Returns (None, 0) if we can't resolve.
    """
    try:
        fps = float(timeline.GetSetting("timelineFrameRate") or 24)
        tl_start = timeline.GetStartFrame()
    except Exception:
        return None, 0.0

    target_frame = tl_start + int(timeline_seconds * fps)

    try:
        items = timeline.GetItemListInTrack("video", 1) or []
    except Exception:
        items = []

    for clip in items:
        try:
            cs, ce = clip.GetStart(), clip.GetEnd()
            if cs <= target_frame < ce:
                media_item = clip.GetMediaPoolItem()
                if not media_item:
                    continue
                props = media_item.GetClipProperty()
                path = props.get("File Path")
                if not path or not os.path.exists(path):
                    continue
                # source frame = (target_frame - clip_start) + left_offset
                left_off = clip.GetLeftOffset()
                src_frame = (target_frame - cs) + left_off
                return path, src_frame / fps
        except Exception:
            continue

    # Fallback — first media file, treat timestamp as-is (works for simple
    # single-clip timelines that start at the source's beginning).
    paths = get_all_media_paths(timeline)
    if paths:
        return paths[0], timeline_seconds
    return None, 0.0


def extract_frame(timeline, timeline_seconds: float,
                  output_path: Optional[str] = None,
                  max_width: int = 1024) -> Optional[str]:
    """Extract a single JPEG frame at the given timeline timestamp.

    Returns the path to the JPEG (or None on failure). Uses the smallest
    source-file operation possible via ffmpeg's -ss seek.
    """
    src_path, src_seconds = _resolve_source_for_timestamp(timeline, timeline_seconds)
    if not src_path:
        _log(f"could not resolve source for ts={timeline_seconds}")
        return None

    if output_path is None:
        tf = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tf.close()
        output_path = tf.name

    cmd = [
        _ffmpeg(), "-y",
        "-ss", f"{max(0, src_seconds):.3f}",
        "-i", src_path,
        "-frames:v", "1",
        "-vf", f"scale={max_width}:-2",
        "-q:v", "4",
        output_path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            _log(f"ffmpeg frame extract failed: {r.stderr[:300]}")
            return None
        if not os.path.exists(output_path) or os.path.getsize(output_path) < 100:
            return None
        return output_path
    except Exception as e:
        _log(f"frame extract crashed: {e}")
        return None


# ---------- Vision API ----------

def _image_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("ascii")


def describe_frame(image_path: str, prompt: str = None) -> str:
    """Run vision model on a frame. Returns a text description."""
    from analyze import _detect_provider, _default_model
    provider = _detect_provider()
    model = _default_model(provider)

    if prompt is None:
        prompt = (
            "Briefly describe this video frame: subject, shot type "
            "(close-up / medium / wide), composition, lighting, notable elements. "
            "Keep under 40 words."
        )

    b64 = _image_to_base64(image_path)
    _log(f"[describe] provider={provider} size={os.path.getsize(image_path)}")

    if provider == "openai":
        from openai import OpenAI
        client = OpenAI()
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            max_tokens=300,
        )
        return resp.choices[0].message.content or ""
    else:
        from anthropic import Anthropic
        client = Anthropic()
        resp = client.messages.create(
            model=model,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return resp.content[0].text


def score_thumbnail(image_path: str, context: str = "") -> dict:
    """Score a frame for thumbnail potential. Returns {score, description, reasons}.

    Score is 0-100. Higher = more clickable.
    """
    prompt = (
        "You are judging this frame as a potential YouTube thumbnail. "
        "Score 0-100 on visual impact (clear subject, expressive face/pose, "
        "good lighting, readable composition). "
        f"Context about the moment: {context or '(none)'}. "
        "Return ONLY JSON (no prose), shaped: "
        '{"score": 82, "description": "Close-up, clear expression, well-lit", '
        '"strengths": ["expressive face"], "weaknesses": ["busy background"]}'
    )
    import json
    try:
        text = describe_frame(image_path, prompt=prompt).strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        _log(f"score_thumbnail parse failed: {e}")
        return {"score": 0, "description": "(parse failed)", "strengths": [], "weaknesses": []}
