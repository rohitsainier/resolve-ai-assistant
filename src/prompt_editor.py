#!/usr/bin/env python3
"""Natural-language timeline editing.

User types a plain-English instruction; the LLM reads the cached transcript
and returns a list of actions (add_marker, clear_markers, create_rough_cut,
create_shorts_timeline). We execute them against Resolve.
"""

import json
import os
import time
from typing import List

from analyze import EditMarker, MarkerType, llm_complete


# Directory for prompt logs
LOG_DIR = os.path.expanduser("~/.resolve-ai-assistant")
LOG_PATH = os.path.join(LOG_DIR, "prompt.log")


def _log(msg: str):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


# Valid marker colors Resolve accepts
VALID_COLORS = {
    "Green", "Red", "Blue", "Yellow", "Cyan", "Purple",
    "Fuchsia", "Rose", "Lavender", "Sky", "Mint", "Lemon",
    "Sand", "Cocoa", "Cream",
}


ACTIONS_SCHEMA_DOC = """Available actions (return a JSON array in "actions"):

1. add_marker       — Add one colored marker at a specific time range.
   Fields: start_seconds (number), end_seconds (number), color (one of:
   Green, Red, Blue, Yellow, Cyan, Purple, Fuchsia, Rose, Lavender, Sky,
   Mint, Lemon, Sand, Cocoa, Cream), label (short str), note (str).

2. clear_markers    — Remove existing markers.
   Fields: color (optional; omit to clear ALL markers on timeline).

3. create_rough_cut — Build a new timeline with specified regions removed.
   Fields: cut_regions (array of {start, end} in seconds, these will be REMOVED),
   name (timeline name).

4. create_shorts_timeline — Build a new timeline containing only these regions.
   Fields: keep_regions (array of {start, end} in seconds, these will be KEPT),
   name (timeline name).

Use the timestamps from the transcript to place markers/regions accurately.
Be conservative — only act on what the user explicitly asks for.
"""


def build_prompt(user_request: str, transcript, timeline_name: str) -> str:
    return f"""You are a video editing assistant operating on a DaVinci Resolve timeline named "{timeline_name}".

{ACTIONS_SCHEMA_DOC}

TRANSCRIPT (timestamps are seconds from the timeline's start):
{transcript.to_timestamped_text()}

USER REQUEST:
{user_request}

Return ONLY valid JSON, no prose before or after:
```json
{{
  "explanation": "Brief explanation of what you're doing (1-3 sentences).",
  "actions": [
    {{"type": "add_marker", "start_seconds": 10.5, "end_seconds": 13.2, "color": "Green", "label": "Funny moment", "note": ""}},
    {{"type": "clear_markers", "color": "Red"}}
  ]
}}
```

If the request is unclear or you cannot satisfy it, return an empty actions array and explain in "explanation"."""


def parse_response(text: str) -> dict:
    """Pull JSON out of the LLM response and return a dict."""
    t = text.strip()
    if "```json" in t:
        t = t.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in t:
        t = t.split("```", 1)[1].split("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        _log(f"JSON parse failed: {e}")
        _log(f"Raw response: {text[:500]}")
        return {"explanation": f"LLM returned unparseable JSON: {e}",
                "actions": []}


def _parse_timestamp(v) -> float:
    """Accept a number or a "HH:MM:SS.mmm" / "MM:SS" string."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        parts = v.replace(",", ".").split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        try:
            return float(parts[0])
        except ValueError:
            return 0.0
    return 0.0


def _color_to_marker_type(color: str) -> MarkerType:
    """Map Resolve color to our internal MarkerType, defaulting to REVIEW."""
    mapping = {
        "Green": MarkerType.HIGHLIGHT,
        "Red": MarkerType.DEAD_AIR,
        "Blue": MarkerType.SHORT_CLIP,
        "Yellow": MarkerType.REVIEW,
    }
    return mapping.get(color, MarkerType.REVIEW)


def execute_actions(actions: List[dict], resolve, timeline) -> List[str]:
    """Execute the action list. Returns a list of human-readable result strings."""
    from markers import (apply_markers, clear_markers,
                         create_rough_cut_timeline, create_subclip_timeline)

    results = []
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()

    for i, action in enumerate(actions, start=1):
        atype = action.get("type", "").strip()
        _log(f"action {i}/{len(actions)}: {atype} -> {action}")

        try:
            if atype == "add_marker":
                start = _parse_timestamp(action.get("start_seconds", 0))
                end = _parse_timestamp(action.get("end_seconds", start + 1))
                color = action.get("color", "Yellow")
                if color not in VALID_COLORS:
                    results.append(f"⚠ #{i} add_marker: invalid color '{color}'")
                    continue
                label = action.get("label", "")[:80]
                note = action.get("note", "")[:200]
                marker = EditMarker(
                    start_seconds=start,
                    end_seconds=max(end, start + 0.1),
                    marker_type=_color_to_marker_type(color),
                    label=label,
                    note=note,
                )
                # Override the color to whatever user requested
                # (apply_markers uses get_marker_color which reads marker_type;
                # we need to force the specific color, so monkey-apply here)
                added = _apply_single_marker(timeline, marker, color)
                results.append(
                    f"✓ #{i} marker '{label}' [{start:.1f}-{end:.1f}s, {color}]"
                    if added else
                    f"⚠ #{i} marker '{label}' not added (frame conflict?)"
                )

            elif atype == "clear_markers":
                color = action.get("color") or None
                if color and color not in VALID_COLORS:
                    results.append(f"⚠ #{i} clear_markers: invalid color '{color}'")
                    continue
                removed = clear_markers(timeline, color)
                results.append(f"✓ #{i} cleared {removed} {color or 'all'} markers")

            elif atype == "create_rough_cut":
                regions = action.get("cut_regions") or []
                dead_markers = [
                    EditMarker(
                        start_seconds=_parse_timestamp(r.get("start", 0)),
                        end_seconds=_parse_timestamp(r.get("end", 0)),
                        marker_type=MarkerType.DEAD_AIR,
                        label="cut", note="",
                    )
                    for r in regions
                ]
                if not dead_markers:
                    results.append(f"⚠ #{i} create_rough_cut: no regions provided")
                    continue
                name = action.get("name") or f"{timeline.GetName()} - Rough Cut"
                new_tl = create_rough_cut_timeline(project, timeline, dead_markers, name=name)
                results.append(f"✓ #{i} built rough cut '{new_tl.GetName()}'")

            elif atype == "create_shorts_timeline":
                regions = action.get("keep_regions") or []
                shorts = [
                    EditMarker(
                        start_seconds=_parse_timestamp(r.get("start", 0)),
                        end_seconds=_parse_timestamp(r.get("end", 0)),
                        marker_type=MarkerType.SHORT_CLIP,
                        label=r.get("label", "short"), note="",
                    )
                    for r in regions
                ]
                if not shorts:
                    results.append(f"⚠ #{i} create_shorts_timeline: no regions")
                    continue
                name = action.get("name") or f"{timeline.GetName()} - Shorts"
                new_tl = create_subclip_timeline(project, timeline, shorts, name=name)
                if new_tl:
                    results.append(f"✓ #{i} built shorts timeline '{new_tl.GetName()}'")
                else:
                    results.append(f"⚠ #{i} shorts timeline build failed")

            else:
                results.append(f"⚠ #{i} unknown action type '{atype}'")

        except Exception as e:
            _log(f"action {i} crashed: {type(e).__name__}: {e}")
            results.append(f"✗ #{i} {atype}: {type(e).__name__}: {e}")

    return results


def _apply_single_marker(timeline, marker: EditMarker, color: str) -> bool:
    """Add a single marker with an explicit color (bypasses marker_type mapping)."""
    from markers import seconds_to_frames
    fps = float(timeline.GetSetting("timelineFrameRate"))
    frame_offset = seconds_to_frames(marker.start_seconds, fps)
    duration_frames = max(1, seconds_to_frames(
        marker.end_seconds - marker.start_seconds, fps))
    return bool(timeline.AddMarker(
        frame_offset, color, marker.label, marker.note, duration_frames, ""
    ))


def run_prompt(user_request: str, transcript, resolve, timeline) -> dict:
    """Main entry point. Returns {'explanation': str, 'results': [str]}."""
    _log(f"=== prompt: {user_request!r}")
    if not transcript or not transcript.segments:
        return {
            "explanation": "No transcript available. Run Analyze first to transcribe the timeline.",
            "results": [],
        }

    prompt = build_prompt(user_request, transcript, timeline.GetName())
    _log(f"sending prompt to LLM ({len(prompt)} chars)")
    response_text = llm_complete(prompt, max_tokens=4096)
    _log(f"got response ({len(response_text)} chars)")

    parsed = parse_response(response_text)
    actions = parsed.get("actions", [])
    explanation = parsed.get("explanation", "")

    _log(f"executing {len(actions)} actions")
    results = execute_actions(actions, resolve, timeline)

    return {
        "explanation": explanation,
        "actions": actions,
        "results": results,
    }
