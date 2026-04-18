#!/usr/bin/env python3
"""Tool definitions and dispatcher for the prompt-editing agent.

Each tool has a JSON-schema description (used by both Anthropic and OpenAI
tool-use APIs) plus a Python implementation that operates on a shared
AgentContext (which holds resolve, timeline, transcript, and an undo log).
"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ---------- Context & undo log ----------

@dataclass
class UndoEntry:
    """One reversible change. op_type is 'add'|'remove'|'timeline_created'|'clear'."""
    op_type: str
    data: dict  # depends on op_type
    timestamp: float = field(default_factory=time.time)
    description: str = ""


@dataclass
class AgentContext:
    resolve: Any
    timeline: Any
    project: Any
    transcript: Any
    undo_log: List[UndoEntry] = field(default_factory=list)
    # ui_cb(event: str, payload: dict) — called for each tool use/result so the UI can show progress
    ui_cb: Optional[Callable[[str, dict], None]] = None
    # plan_approval_cb(description, actions) -> bool
    # Set by the agent runner when a UI is attached; tools that need approval
    # call this and block until the user responds.
    plan_approval_cb: Optional[Callable[[str, list], bool]] = None

    def emit(self, event: str, payload: dict):
        if self.ui_cb:
            try:
                self.ui_cb(event, payload)
            except Exception:
                pass


# ---------- Tool schemas ----------
# Format is Anthropic-style (name/description/input_schema). OpenAI adapter
# wraps each into its own shape.

TOOL_SCHEMAS: List[dict] = [
    {
        "name": "search_transcript",
        "description": (
            "Semantically search the transcript for moments matching a query. "
            "Returns a list of {start, end, text, score} dicts ordered by relevance. "
            "Use this whenever the user asks about content topics like 'find where "
            "I mentioned X' or 'the funniest moment about Y'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."},
                "max_results": {"type": "integer", "default": 10, "description": "Max number of matches to return."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_timeline_info",
        "description": "Return timeline name, duration, fps, and clip count.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_markers",
        "description": "Return all current markers on the timeline, optionally filtered by color.",
        "input_schema": {
            "type": "object",
            "properties": {
                "color": {"type": "string", "description": "Optional: filter to this color only."},
            },
        },
    },
    {
        "name": "add_marker",
        "description": (
            "Add a colored marker at a timeline position. Timestamps are seconds "
            "from timeline start."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_seconds": {"type": "number"},
                "end_seconds": {"type": "number"},
                "color": {"type": "string", "description": "One of: Green, Red, Blue, Yellow, Cyan, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream"},
                "label": {"type": "string", "description": "Short label (max 80 chars)"},
                "note": {"type": "string", "description": "Optional longer note"},
            },
            "required": ["start_seconds", "end_seconds", "color", "label"],
        },
    },
    {
        "name": "clear_markers",
        "description": "Remove markers from the timeline. If color is omitted, clears ALL markers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "color": {"type": "string", "description": "Optional: only clear this color."},
            },
        },
    },
    {
        "name": "remove_marker",
        "description": (
            "Remove a specific marker matching given criteria. Pass at least one of: "
            "start_seconds (exact time), color, or label_contains (substring match)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_seconds": {"type": "number"},
                "color": {"type": "string"},
                "label_contains": {"type": "string"},
            },
        },
    },
    {
        "name": "create_rough_cut",
        "description": (
            "Create a new timeline with specified regions REMOVED. Use for 'cut out all "
            "the um's', 'remove first 30 seconds', 'tighten this up', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cut_regions": {
                    "type": "array",
                    "description": "Regions to remove. Each {start, end} in seconds.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "number"},
                            "end": {"type": "number"},
                        },
                        "required": ["start", "end"],
                    },
                },
                "name": {"type": "string", "description": "Name for the new timeline."},
            },
            "required": ["cut_regions"],
        },
    },
    {
        "name": "create_shorts_timeline",
        "description": (
            "Create a new timeline containing ONLY specified regions concatenated. "
            "Use for 'make a shorts timeline of the best parts', 'extract clips about X'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keep_regions": {
                    "type": "array",
                    "description": "Regions to keep. Each {start, end} in seconds.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "number"},
                            "end": {"type": "number"},
                        },
                        "required": ["start", "end"],
                    },
                },
                "name": {"type": "string"},
            },
            "required": ["keep_regions"],
        },
    },
    {
        "name": "analyze_frame",
        "description": (
            "Look at a single video frame at the given timeline timestamp and "
            "describe what's visible. Useful for checking whether a moment looks "
            "good on screen before marking it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "timestamp_seconds": {"type": "number"},
                "question": {
                    "type": "string",
                    "description": "Optional specific question. Default: general description.",
                },
            },
            "required": ["timestamp_seconds"],
        },
    },
    {
        "name": "suggest_thumbnails",
        "description": (
            "Extract frames at given timestamps (or at existing highlight markers "
            "if no timestamps provided), score each for YouTube thumbnail potential "
            "using a vision model. Returns ranked results with scores, descriptions, "
            "and saved JPEG paths."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "timestamps": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Optional specific timestamps (seconds). If omitted, uses existing highlight markers.",
                },
                "count": {"type": "integer", "default": 3, "description": "How many candidates to score."},
            },
        },
    },
    {
        "name": "identify_speakers",
        "description": (
            "Analyze the transcript to identify distinct speakers based on "
            "conversational context (who asks vs answers, topic shifts, pronouns). "
            "Returns a list of detected speakers with labels and segment ranges. "
            "Best-effort heuristic, not acoustic diarization."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "suggest_broll",
        "description": (
            "Read the transcript and propose b-roll insertion points. For each, "
            "returns a timestamp range and a short description of a good visual."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "max_count": {"type": "integer", "default": 8},
                "style_hint": {"type": "string"},
            },
        },
    },
    {
        "name": "list_media_pool",
        "description": (
            "List video clips in the Resolve media pool. Useful for matching "
            "b-roll suggestions to actual clips. Returns {name, duration, file_path}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bin_name": {"type": "string"},
            },
        },
    },
    {
        "name": "list_render_presets",
        "description": (
            "List both Resolve's built-in render presets AND our platform-tuned presets "
            "(YouTube, TikTok, Instagram, proxy). Use this before render_timeline so you "
            "know the valid preset IDs."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "render_timeline",
        "description": (
            "Queue a render job for the current timeline using one of our platform "
            "presets (youtube_1080p, youtube_4k, tiktok_vertical, instagram_square, "
            "proxy_540p). Optionally starts the render immediately. Output goes to "
            "~/.resolve-ai-assistant/renders/ by default."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "preset_id": {
                    "type": "string",
                    "description": "One of: youtube_1080p, youtube_4k, tiktok_vertical, instagram_square, proxy_540p",
                },
                "filename": {"type": "string", "description": "Output filename without extension"},
                "output_dir": {"type": "string", "description": "Override output directory"},
                "start_now": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, begins rendering immediately. Otherwise job is just queued.",
                },
            },
            "required": ["preset_id"],
        },
    },
    {
        "name": "render_status",
        "description": "Report whether a render is running and list queued/completed jobs.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "analyze_audio_levels",
        "description": (
            "Analyze the timeline's audio for loudness (EBU R128 LUFS), clipping, and "
            "silence regions. Returns measurements plus plain-English recommendations. "
            "Slow for long timelines — takes ~5s per minute of content."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_active_profile",
        "description": (
            "Return the current creator profile — tone, pacing, target platform, "
            "loudness target, style notes. The agent should check this before making "
            "stylistic choices like cut aggressiveness or marker placement."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_profiles",
        "description": "List every saved or built-in creator profile.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_active_profile",
        "description": (
            "Switch to a different creator profile. Changes take effect on the next prompt "
            "(not mid-turn)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "profile_id": {"type": "string", "description": "id of the profile (from list_profiles)"},
            },
            "required": ["profile_id"],
        },
    },
    {
        "name": "batch_render_shorts",
        "description": (
            "Render every SHORT_CLIP marker as its own separate video file. Each file "
            "uses the specified render preset. Auto-numbers filenames. Requires blue "
            "(SHORT_CLIP) markers on the timeline."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "preset_id": {
                    "type": "string",
                    "description": "Platform preset (youtube_1080p / tiktok_vertical / instagram_square / proxy_540p)",
                    "default": "tiktok_vertical",
                },
                "output_dir": {"type": "string"},
                "start_now": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "normalize_audio_render",
        "description": (
            "Render the current timeline's audio normalized to a target loudness (LUFS) "
            "using ffmpeg's loudnorm filter. Produces a new .wav/.m4a audio file with "
            "consistent loudness — useful for preparing audio before final export. "
            "This does NOT modify the Resolve timeline; it creates a separate file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_lufs": {"type": "number", "default": -14.0, "description": "Default -14 LUFS for YouTube"},
                "true_peak_dbfs": {"type": "number", "default": -1.0},
                "output_path": {"type": "string", "description": "Optional explicit output path"},
            },
        },
    },
    {
        "name": "remember",
        "description": (
            "Pin a fact about this timeline so it persists across sessions. "
            "Use sparingly — only for durable preferences like 'user prefers hard cuts' "
            "or 'host is named Alex'. Auto-loaded into future prompts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Short identifier (max 60 chars)"},
                "value": {"type": "string", "description": "The fact to remember (max 400 chars)"},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "forget",
        "description": "Remove a pinned fact by its key.",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "recall",
        "description": (
            "Search past sessions on this timeline for matching requests or summaries. "
            "Useful when the user says 'like I did last time' or 'what did we do before'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional — omit to get most recent sessions."},
                "max_results": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "submit_plan",
        "description": (
            "Propose a multi-step plan for user approval BEFORE executing. Use this "
            "whenever you're about to make multiple destructive changes (3+ edits, "
            "new timelines, renders). Returns {approved: true/false}. If approved, "
            "the actions are executed in sequence. If rejected, you must adjust and "
            "either submit again or call `finish`.\n\n"
            "NOTE: action's 'tool' field must match an existing tool name, and 'args' "
            "is that tool's argument dict. Do not put 'submit_plan' or 'finish' in the plan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "One-sentence summary of what the plan does.",
                },
                "actions": {
                    "type": "array",
                    "description": "Ordered list of {tool, args} to execute on approval.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "args": {"type": "object"},
                            "reason": {"type": "string", "description": "Brief why-this-step."},
                        },
                        "required": ["tool", "args"],
                    },
                },
            },
            "required": ["description", "actions"],
        },
    },
    {
        "name": "undo_last",
        "description": (
            "Revert the most recent timeline modification made by this agent in this session. "
            "Call this if the user says 'undo' or 'never mind'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "finish",
        "description": (
            "Call this when the user's request is fully handled and you want to end the turn. "
            "Pass a brief summary explaining what you did."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
            },
            "required": ["summary"],
        },
    },
]


# ---------- Valid Resolve marker colors ----------
VALID_COLORS = {
    "Green", "Red", "Blue", "Yellow", "Cyan", "Purple",
    "Fuchsia", "Rose", "Lavender", "Sky", "Mint", "Lemon",
    "Sand", "Cocoa", "Cream",
}


# ---------- Tool implementations ----------

def tool_search_transcript(ctx: AgentContext, args: dict) -> dict:
    query = (args.get("query") or "").lower().strip()
    max_results = int(args.get("max_results") or 10)
    if not query or ctx.transcript is None:
        return {"results": []}

    # Simple keyword scoring: count distinct query terms that appear.
    terms = [t for t in query.split() if len(t) > 2]
    results = []
    for seg in ctx.transcript.segments:
        text_l = seg.text.lower()
        score = sum(1 for t in terms if t in text_l)
        if score == 0 and query not in text_l:
            continue
        if query in text_l:
            score += 2
        results.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "score": score,
        })
    results.sort(key=lambda r: (-r["score"], r["start"]))
    return {"results": results[:max_results], "total_matches": len(results)}


def tool_get_timeline_info(ctx: AgentContext, args: dict) -> dict:
    tl = ctx.timeline
    try:
        fps = float(tl.GetSetting("timelineFrameRate") or 0)
    except Exception:
        fps = 0
    try:
        start = tl.GetStartFrame()
        end = tl.GetEndFrame()
        duration_frames = end - start
        duration_seconds = duration_frames / fps if fps else 0
    except Exception:
        duration_frames = 0
        duration_seconds = 0
    try:
        clip_count = len(tl.GetItemListInTrack("video", 1) or [])
    except Exception:
        clip_count = 0
    return {
        "name": tl.GetName(),
        "fps": fps,
        "duration_seconds": round(duration_seconds, 1),
        "duration_frames": duration_frames,
        "clip_count": clip_count,
    }


def tool_list_markers(ctx: AgentContext, args: dict) -> dict:
    tl = ctx.timeline
    try:
        all_markers = tl.GetMarkers() or {}
    except Exception:
        return {"markers": []}
    color_filter = args.get("color")
    fps = float(tl.GetSetting("timelineFrameRate") or 24)
    markers = []
    for frame_offset, data in sorted(all_markers.items()):
        if color_filter and data.get("color") != color_filter:
            continue
        markers.append({
            "start_seconds": round(frame_offset / fps, 2),
            "duration_seconds": round((data.get("duration") or 1) / fps, 2),
            "color": data.get("color"),
            "label": data.get("name", ""),
            "note": data.get("note", ""),
        })
    return {"markers": markers, "count": len(markers)}


def tool_add_marker(ctx: AgentContext, args: dict) -> dict:
    from markers import seconds_to_frames
    color = args.get("color", "Yellow")
    if color not in VALID_COLORS:
        return {"ok": False, "error": f"Invalid color '{color}'. Pick one of {sorted(VALID_COLORS)}."}

    start = float(args.get("start_seconds", 0))
    end = float(args.get("end_seconds", start + 1))
    if end <= start:
        end = start + 0.5
    label = (args.get("label") or "")[:80]
    note = (args.get("note") or "")[:200]

    fps = float(ctx.timeline.GetSetting("timelineFrameRate"))
    frame_offset = seconds_to_frames(start, fps)
    duration_frames = max(1, seconds_to_frames(end - start, fps))

    success = bool(ctx.timeline.AddMarker(
        frame_offset, color, label, note, duration_frames, ""
    ))
    if success:
        ctx.undo_log.append(UndoEntry(
            op_type="add",
            data={"frame_offset": frame_offset},
            description=f"Added {color} marker '{label}' at {start:.1f}s",
        ))
    return {
        "ok": success,
        "start_seconds": start,
        "color": color,
        "label": label,
        "note": "Marker frame conflict (another marker already at that frame)" if not success else "",
    }


def tool_clear_markers(ctx: AgentContext, args: dict) -> dict:
    from markers import clear_markers
    color = args.get("color")
    # Snapshot for undo
    try:
        all_markers = dict(ctx.timeline.GetMarkers() or {})
    except Exception:
        all_markers = {}
    to_restore = {
        f: d for f, d in all_markers.items()
        if color is None or d.get("color") == color
    }
    removed = clear_markers(ctx.timeline, color)
    if removed:
        ctx.undo_log.append(UndoEntry(
            op_type="clear",
            data={"restore": to_restore},
            description=f"Cleared {removed} {color or 'all'} markers",
        ))
    return {"removed": removed, "color": color or "all"}


def tool_remove_marker(ctx: AgentContext, args: dict) -> dict:
    from markers import seconds_to_frames
    start_s = args.get("start_seconds")
    color = args.get("color")
    label_contains = (args.get("label_contains") or "").lower().strip() or None

    fps = float(ctx.timeline.GetSetting("timelineFrameRate"))
    all_markers = ctx.timeline.GetMarkers() or {}

    def matches(frame_offset, data):
        if start_s is not None:
            target = seconds_to_frames(float(start_s), fps)
            if abs(frame_offset - target) > 1:
                return False
        if color and data.get("color") != color:
            return False
        if label_contains and label_contains not in (data.get("name", "") or "").lower():
            return False
        return True

    targets = [(f, d) for f, d in all_markers.items() if matches(f, d)]
    removed = 0
    restored = {}
    for frame_offset, data in targets:
        if ctx.timeline.DeleteMarkerAtFrame(frame_offset):
            removed += 1
            restored[frame_offset] = data

    if removed:
        ctx.undo_log.append(UndoEntry(
            op_type="remove",
            data={"restore": restored},
            description=f"Removed {removed} marker(s)",
        ))
    return {"removed": removed}


def _regions_to_markers(regions: list, marker_type) -> list:
    from analyze import EditMarker
    out = []
    for r in regions or []:
        try:
            s = float(r.get("start", 0))
            e = float(r.get("end", 0))
        except Exception:
            continue
        if e > s:
            out.append(EditMarker(
                start_seconds=s, end_seconds=e,
                marker_type=marker_type,
                label=r.get("label", "") or marker_type.name,
                note="",
            ))
    return out


def tool_create_rough_cut(ctx: AgentContext, args: dict) -> dict:
    from analyze import MarkerType
    from markers import create_rough_cut_timeline
    cut_regions = args.get("cut_regions") or []
    name = args.get("name") or f"{ctx.timeline.GetName()} - Rough Cut"
    dead_markers = _regions_to_markers(cut_regions, MarkerType.DEAD_AIR)
    if not dead_markers:
        return {"ok": False, "error": "No valid cut_regions provided"}
    try:
        new_tl = create_rough_cut_timeline(ctx.project, ctx.timeline, dead_markers, name=name)
        ctx.undo_log.append(UndoEntry(
            op_type="timeline_created",
            data={"timeline_name": new_tl.GetName()},
            description=f"Built rough-cut timeline '{new_tl.GetName()}'",
        ))
        return {"ok": True, "new_timeline": new_tl.GetName(), "cuts": len(dead_markers)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_create_shorts_timeline(ctx: AgentContext, args: dict) -> dict:
    from analyze import MarkerType
    from markers import create_subclip_timeline
    keep_regions = args.get("keep_regions") or []
    name = args.get("name") or f"{ctx.timeline.GetName()} - Shorts"
    shorts = _regions_to_markers(keep_regions, MarkerType.SHORT_CLIP)
    if not shorts:
        return {"ok": False, "error": "No valid keep_regions provided"}
    try:
        new_tl = create_subclip_timeline(ctx.project, ctx.timeline, shorts, name=name)
        if new_tl is None:
            return {"ok": False, "error": "Shorts timeline build returned None"}
        ctx.undo_log.append(UndoEntry(
            op_type="timeline_created",
            data={"timeline_name": new_tl.GetName()},
            description=f"Built shorts timeline '{new_tl.GetName()}'",
        ))
        return {"ok": True, "new_timeline": new_tl.GetName(), "clips": len(shorts)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_undo_last(ctx: AgentContext, args: dict) -> dict:
    if not ctx.undo_log:
        return {"ok": False, "error": "Nothing to undo"}
    entry = ctx.undo_log.pop()
    try:
        if entry.op_type == "add":
            frame = entry.data["frame_offset"]
            ctx.timeline.DeleteMarkerAtFrame(frame)
            return {"ok": True, "reverted": entry.description}
        elif entry.op_type in ("clear", "remove"):
            for frame_offset, data in (entry.data.get("restore") or {}).items():
                ctx.timeline.AddMarker(
                    int(frame_offset),
                    data.get("color", "Yellow"),
                    data.get("name", ""),
                    data.get("note", ""),
                    int(data.get("duration", 1)),
                    data.get("customData", ""),
                )
            return {"ok": True, "reverted": entry.description,
                    "restored": len(entry.data.get("restore") or {})}
        elif entry.op_type == "timeline_created":
            return {
                "ok": False,
                "error": "Cannot auto-delete a created timeline from script; "
                         f"please remove '{entry.data.get('timeline_name')}' manually from the media pool.",
            }
        else:
            return {"ok": False, "error": f"Unknown op_type: {entry.op_type}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---------- Phase 3: vision + media intelligence ----------

def tool_analyze_frame(ctx: AgentContext, args: dict) -> dict:
    """Extract a frame at the given timestamp and describe what's visible."""
    from vision import extract_frame, describe_frame
    ts = float(args.get("timestamp_seconds", 0))
    question = args.get("question") or None
    path = extract_frame(ctx.timeline, ts)
    if not path:
        return {"ok": False, "error": "Could not extract frame at that timestamp"}
    try:
        desc = describe_frame(path, prompt=question)
        return {"ok": True, "timestamp": ts, "description": desc.strip(), "frame_path": path}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_suggest_thumbnails(ctx: AgentContext, args: dict) -> dict:
    """Score frames for thumbnail potential. Returns ranked list."""
    from vision import extract_frame, score_thumbnail
    count = int(args.get("count") or 3)
    timestamps = args.get("timestamps")

    # If no timestamps given, use existing green (HIGHLIGHT) markers
    if not timestamps:
        try:
            all_markers = ctx.timeline.GetMarkers() or {}
            fps = float(ctx.timeline.GetSetting("timelineFrameRate") or 24)
            timestamps = [
                frame / fps
                for frame, data in sorted(all_markers.items())
                if data.get("color") == "Green"
            ]
        except Exception:
            timestamps = []

    if not timestamps:
        return {
            "ok": False,
            "error": "No timestamps given and no green highlight markers on timeline. "
                     "Run Analyze first or pass explicit timestamps.",
        }

    # Limit how many frames we score (each is a vision API call)
    timestamps = list(dict.fromkeys(timestamps))[: max(count * 2, 5)]

    results = []
    for ts in timestamps:
        ctx.emit("tool_step", {"tool": "suggest_thumbnails", "step": f"scoring {ts:.1f}s"})
        path = extract_frame(ctx.timeline, ts)
        if not path:
            continue
        # Give the vision model the surrounding transcript as context
        context = ""
        if ctx.transcript:
            for seg in ctx.transcript.segments:
                if seg.start <= ts <= seg.end:
                    context = seg.text.strip()
                    break
        scored = score_thumbnail(path, context=context)
        scored["timestamp"] = ts
        scored["frame_path"] = path
        results.append(scored)

    results.sort(key=lambda r: -int(r.get("score", 0)))
    return {"ok": True, "count": len(results), "ranked": results[:count]}


def tool_identify_speakers(ctx: AgentContext, args: dict) -> dict:
    """LLM-based speaker clustering from transcript context."""
    if not ctx.transcript:
        return {"ok": False, "error": "No transcript available"}

    from analyze import llm_complete

    tt = ctx.transcript.to_timestamped_text()
    prompt = f"""Analyze this video transcript and identify distinct speakers based on conversational patterns (who asks questions vs answers, first-person claims, topic ownership).

Return ONLY JSON, no prose:
```json
{{
  "speakers": [
    {{"label": "Host", "role": "Interviewer / moderator", "segments": [{{"start": 0.0, "end": 15.2}}]}},
    {{"label": "Guest A", "role": "Interviewee / subject expert", "segments": [{{"start": 15.2, "end": 60.0}}]}}
  ],
  "confidence": "low|medium|high",
  "notes": "Brief explanation of how you split them."
}}
```

TRANSCRIPT:
{tt}"""

    try:
        raw = llm_complete(prompt, max_tokens=2048).strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        import json as _json
        data = _json.loads(raw)
        return {"ok": True, **data}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_suggest_broll(ctx: AgentContext, args: dict) -> dict:
    """Propose b-roll insertion points with descriptions."""
    if not ctx.transcript:
        return {"ok": False, "error": "No transcript available"}

    from analyze import llm_complete
    max_count = int(args.get("max_count") or 8)
    style = args.get("style_hint") or "natural documentary"

    tt = ctx.transcript.to_timestamped_text()
    prompt = f"""Analyze this video transcript and propose b-roll insertion points. For each, give:
- start_seconds: when the b-roll should begin
- end_seconds: when it should end (typically 3-8 seconds)
- description: what visual would work (subject, angle, mood)
- reason: why this moment benefits from b-roll

Style: {style}. Max {max_count} suggestions. Prefer moments where the speaker describes something concrete (a place, object, event) — those are perfect for b-roll.

Return ONLY JSON:
```json
{{
  "suggestions": [
    {{"start_seconds": 12.5, "end_seconds": 17.0, "description": "Close-up of laptop screen showing code", "reason": "Speaker mentions writing the algorithm"}}
  ]
}}
```

TRANSCRIPT:
{tt}"""

    try:
        raw = llm_complete(prompt, max_tokens=3000).strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        import json as _json
        data = _json.loads(raw)
        return {"ok": True, **data}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def tool_list_media_pool(ctx: AgentContext, args: dict) -> dict:
    """Enumerate video clips in the media pool."""
    try:
        media_pool = ctx.project.GetMediaPool()
    except Exception as e:
        return {"ok": False, "error": f"No media pool: {e}"}

    bin_name = args.get("bin_name")

    def walk_folder(folder, out):
        try:
            clips = folder.GetClipList() or []
        except Exception:
            clips = []
        for c in clips:
            try:
                props = c.GetClipProperty() or {}
                path = props.get("File Path") or ""
                if not path:
                    continue
                # Only video-bearing clips
                clip_type = props.get("Type", "").lower()
                if "audio" == clip_type or "still" == clip_type:
                    continue
                out.append({
                    "name": props.get("Clip Name") or os.path.basename(path),
                    "duration": props.get("Duration"),
                    "fps": props.get("FPS"),
                    "resolution": props.get("Resolution"),
                    "file_path": path,
                })
            except Exception:
                continue
        try:
            subs = folder.GetSubFolderList() or []
        except Exception:
            subs = []
        for sf in subs:
            walk_folder(sf, out)

    try:
        root = media_pool.GetRootFolder()
    except Exception as e:
        return {"ok": False, "error": f"{e}"}

    clips = []
    if bin_name:
        target = None
        try:
            for sf in (root.GetSubFolderList() or []):
                if sf.GetName() == bin_name:
                    target = sf
                    break
        except Exception:
            target = None
        if not target:
            return {"ok": False, "error": f"Bin '{bin_name}' not found"}
        walk_folder(target, clips)
    else:
        walk_folder(root, clips)

    return {"ok": True, "count": len(clips), "clips": clips[:50]}


# ---------- Phase 4: delivery + audio ----------

def tool_list_render_presets(ctx: AgentContext, args: dict) -> dict:
    from delivery import list_resolve_presets, list_our_presets
    return {
        "platform_presets": list_our_presets(),
        "resolve_builtin_presets": list_resolve_presets(ctx.project)[:40],
    }


def tool_render_timeline(ctx: AgentContext, args: dict) -> dict:
    from delivery import queue_render, start_renders
    preset_id = args.get("preset_id")
    if not preset_id:
        return {"ok": False, "error": "preset_id is required"}

    result = queue_render(
        ctx.project,
        preset_id=preset_id,
        output_dir=args.get("output_dir"),
        filename=args.get("filename"),
    )
    if result.get("error"):
        return {"ok": False, **result}

    if args.get("start_now"):
        sr = start_renders(ctx.project, [result["job_id"]])
        result["render_started"] = sr.get("ok", False)
        if sr.get("error"):
            result["start_error"] = sr["error"]

    return {"ok": True, **result}


def tool_render_status(ctx: AgentContext, args: dict) -> dict:
    from delivery import render_status
    return render_status(ctx.project)


def tool_analyze_audio_levels(ctx: AgentContext, args: dict) -> dict:
    from audio_analysis import analyze_timeline_audio
    try:
        report = analyze_timeline_audio(ctx.timeline)
        return {"ok": True, **report}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---------- Phase 5: profiles + batch render + audio normalize ----------

def tool_get_active_profile(ctx: AgentContext, args: dict) -> dict:
    from profiles import get_active_profile
    p = get_active_profile()
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "tone": p.tone,
        "pacing": p.pacing,
        "max_shot_seconds": p.max_shot_seconds,
        "target_platforms": p.target_platforms,
        "target_lufs": p.target_lufs,
        "filler_sensitivity": p.filler_sensitivity,
        "dead_air_threshold": p.dead_air_threshold,
        "style_notes": p.style_notes,
    }


def tool_list_profiles(ctx: AgentContext, args: dict) -> dict:
    from profiles import list_all, get_active_id
    return {"active_id": get_active_id(), "profiles": list_all()}


def tool_set_active_profile(ctx: AgentContext, args: dict) -> dict:
    from profiles import set_active_id, load_profile
    pid = args.get("profile_id")
    if not pid:
        return {"ok": False, "error": "profile_id required"}
    if load_profile(pid) is None:
        return {"ok": False, "error": f"Profile '{pid}' not found"}
    set_active_id(pid)
    return {"ok": True, "active_id": pid}


def tool_batch_render_shorts(ctx: AgentContext, args: dict) -> dict:
    """Render each SHORT_CLIP marker as its own video file."""
    from delivery import queue_render, start_renders

    preset_id = args.get("preset_id") or "tiktok_vertical"
    output_dir = args.get("output_dir")
    start_now = bool(args.get("start_now"))

    # Find the shorts regions from blue markers
    try:
        fps = float(ctx.timeline.GetSetting("timelineFrameRate") or 24)
        all_markers = ctx.timeline.GetMarkers() or {}
    except Exception as e:
        return {"ok": False, "error": f"Could not read markers: {e}"}

    shorts = []
    for frame_offset, data in sorted(all_markers.items()):
        if data.get("color") != "Blue":
            continue
        start = frame_offset / fps
        duration = (data.get("duration") or 1) / fps
        shorts.append({
            "start": round(start, 2),
            "duration": round(duration, 2),
            "label": data.get("name", ""),
        })

    if not shorts:
        return {
            "ok": False,
            "error": "No SHORT_CLIP (Blue) markers on the timeline. Run Analyze or "
                     "add some via the agent first.",
        }

    # For each short, we queue a separate render job. Resolve's render API
    # renders the full timeline — per-region rendering requires changing the
    # in/out markers before each job. We use SetCurrentTimeline's Mark In/Out.
    tl_name = ctx.timeline.GetName() if ctx.timeline else "timeline"
    queued = []
    errors = []
    try:
        tl_start = ctx.timeline.GetStartFrame()
    except Exception:
        tl_start = 0

    for i, short in enumerate(shorts, start=1):
        in_frame = int(tl_start + short["start"] * fps)
        out_frame = int(in_frame + short["duration"] * fps)
        try:
            # Set in/out points so this render job covers only this region
            ctx.timeline.SetCurrentTimecode
            # Newer Resolve APIs use SetInOutRange; try both
            set_in_out = getattr(ctx.timeline, "SetInOutRange", None)
            if callable(set_in_out):
                set_in_out(in_frame - tl_start, out_frame - tl_start)
            else:
                # Fallback: some versions expect SetSetting for render-in/out
                ctx.project.SetSetting("markIn", str(in_frame))
                ctx.project.SetSetting("markOut", str(out_frame))
        except Exception as e:
            errors.append(f"clip {i}: could not set in/out: {e}")

        filename = f"{_safe_filename(tl_name)}_short_{i:02d}"
        result = queue_render(ctx.project, preset_id=preset_id,
                              output_dir=output_dir, filename=filename)
        if result.get("ok"):
            queued.append({
                "index": i,
                "label": short["label"],
                "start_seconds": short["start"],
                "duration_seconds": short["duration"],
                "job_id": result["job_id"],
                "output": result["output_base"],
            })
        else:
            errors.append(f"clip {i}: {result.get('error', 'unknown')}")

    if start_now and queued:
        sr = start_renders(ctx.project, [q["job_id"] for q in queued])
        started = sr.get("ok", False)
    else:
        started = False

    return {
        "ok": len(queued) > 0,
        "queued_count": len(queued),
        "jobs": queued,
        "errors": errors,
        "render_started": started,
    }


def tool_normalize_audio_render(ctx: AgentContext, args: dict) -> dict:
    """Extract timeline audio and render a loudnorm-ized version."""
    import os as _os, tempfile, subprocess
    from transcribe import _ffmpeg, extract_audio_from_timeline

    target_lufs = float(args.get("target_lufs", -14.0))
    true_peak = float(args.get("true_peak_dbfs", -1.0))
    out_path = args.get("output_path")

    if not out_path:
        renders_dir = _os.path.expanduser("~/.resolve-ai-assistant/renders")
        _os.makedirs(renders_dir, exist_ok=True)
        tl_name = "timeline"
        try:
            tl_name = ctx.timeline.GetName()
        except Exception:
            pass
        safe = _safe_filename(tl_name)
        out_path = _os.path.join(renders_dir, f"{safe}_normalized.wav")

    # Extract source audio to temp wav
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        extract_audio_from_timeline(ctx.timeline, tmp.name)
        # Apply loudnorm in one pass
        cmd = [
            _ffmpeg(), "-y",
            "-i", tmp.name,
            "-filter:a", f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=7",
            "-ar", "48000", "-ac", "2",
            out_path,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr[:400]}
        return {
            "ok": True,
            "output_path": out_path,
            "target_lufs": target_lufs,
            "true_peak_dbfs": true_peak,
        }
    finally:
        try:
            _os.unlink(tmp.name)
        except Exception:
            pass


def _safe_filename(name: str) -> str:
    """File-system-safe filename (no /, :, illegal chars)."""
    import re as _re
    out = _re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip())
    return out[:80] or "timeline"


# ---------- Phase 6: memory + plan approval ----------

def tool_remember(ctx: AgentContext, args: dict) -> dict:
    from memory import remember_fact
    key = (args.get("key") or "").strip()
    value = (args.get("value") or "").strip()
    if not key or not value:
        return {"ok": False, "error": "Both key and value are required"}
    tl_name = ctx.timeline.GetName() if ctx.timeline else None
    remember_fact(tl_name, key, value)
    return {"ok": True, "key": key, "saved_under_timeline": tl_name}


def tool_forget(ctx: AgentContext, args: dict) -> dict:
    from memory import forget_fact
    key = (args.get("key") or "").strip()
    tl_name = ctx.timeline.GetName() if ctx.timeline else None
    existed = forget_fact(tl_name, key)
    return {"ok": True, "existed": existed}


def tool_recall(ctx: AgentContext, args: dict) -> dict:
    from memory import recall
    tl_name = ctx.timeline.GetName() if ctx.timeline else None
    query = args.get("query")
    max_results = int(args.get("max_results") or 10)
    return recall(tl_name, query, max_results)


def tool_submit_plan(ctx: AgentContext, args: dict) -> dict:
    """Request user approval for a multi-step plan. If approved, execute it."""
    description = (args.get("description") or "(no description)").strip()
    actions = args.get("actions") or []

    if not actions:
        return {"ok": False, "error": "No actions in plan"}

    # Filter out any unknown tools before asking for approval, to avoid
    # surprising the user with an action that would fail anyway.
    cleaned = []
    for a in actions:
        tool = (a.get("tool") or "").strip()
        if tool in {"submit_plan", "finish"}:
            continue  # forbidden inside a plan
        if tool not in _TOOL_IMPLS:
            return {
                "ok": False,
                "error": f"Unknown tool in plan: '{tool}'. "
                         f"Valid tools: {sorted(_TOOL_IMPLS.keys())}",
            }
        cleaned.append({
            "tool": tool,
            "args": a.get("args") or {},
            "reason": a.get("reason", ""),
        })

    approved = True
    if ctx.plan_approval_cb:
        try:
            approved = bool(ctx.plan_approval_cb(description, cleaned))
        except Exception as e:
            return {"ok": False, "error": f"Approval handler crashed: {e}"}

    if not approved:
        return {"ok": True, "approved": False,
                "message": "User rejected the plan. Ask what they'd prefer instead."}

    # Execute the cleaned actions in order
    results = []
    for i, a in enumerate(cleaned, start=1):
        tool_name = a["tool"]
        tool_args = a["args"]
        ctx.emit("plan_step", {"index": i, "tool": tool_name, "args": tool_args})
        res = execute_tool(ctx, tool_name, tool_args)
        results.append({"step": i, "tool": tool_name, "result": res})

    return {
        "ok": True,
        "approved": True,
        "executed_count": len(results),
        "results": results,
    }


# ---------- Dispatcher ----------

_TOOL_IMPLS: Dict[str, Callable[[AgentContext, dict], dict]] = {
    "search_transcript": tool_search_transcript,
    "get_timeline_info": tool_get_timeline_info,
    "list_markers": tool_list_markers,
    "add_marker": tool_add_marker,
    "clear_markers": tool_clear_markers,
    "remove_marker": tool_remove_marker,
    "create_rough_cut": tool_create_rough_cut,
    "create_shorts_timeline": tool_create_shorts_timeline,
    "analyze_frame": tool_analyze_frame,
    "suggest_thumbnails": tool_suggest_thumbnails,
    "identify_speakers": tool_identify_speakers,
    "suggest_broll": tool_suggest_broll,
    "list_media_pool": tool_list_media_pool,
    "list_render_presets": tool_list_render_presets,
    "render_timeline": tool_render_timeline,
    "render_status": tool_render_status,
    "analyze_audio_levels": tool_analyze_audio_levels,
    "get_active_profile": tool_get_active_profile,
    "list_profiles": tool_list_profiles,
    "set_active_profile": tool_set_active_profile,
    "batch_render_shorts": tool_batch_render_shorts,
    "normalize_audio_render": tool_normalize_audio_render,
    "remember": tool_remember,
    "forget": tool_forget,
    "recall": tool_recall,
    "submit_plan": tool_submit_plan,
    "undo_last": tool_undo_last,
}


def execute_tool(ctx: AgentContext, name: str, args: dict) -> dict:
    """Dispatch a tool call. Returns a JSON-serializable result dict."""
    if name == "finish":
        # handled at the agent-loop level
        return {"summary": args.get("summary", "")}
    fn = _TOOL_IMPLS.get(name)
    if fn is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = fn(ctx, args or {})
        ctx.emit("tool_result", {"name": name, "result": result})
        return result
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        err = {"error": f"{type(e).__name__}: {e}"}
        ctx.emit("tool_error", {"name": name, "traceback": tb})
        return err
