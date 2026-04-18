#!/usr/bin/env python3
"""Render/delivery utilities.

Wraps Resolve's render API for a cleaner agent-facing surface, plus
platform-specific preset definitions (YouTube, TikTok, Instagram, etc.)
that work across Free and Studio.
"""

import os
from typing import Optional


# Platform-specific render settings (format / codec / dimensions / fps).
# These are pure-API settings — no file-on-disk presets required, so they
# work in Resolve Free which can't import XML preset files from script.
PLATFORM_PRESETS = {
    "youtube_1080p": {
        "label": "YouTube 1080p (H.264)",
        "TargetDir": "",          # caller fills in
        "CustomName": "",
        "ExportVideo": True,
        "ExportAudio": True,
        "FormatWidth": 1920,
        "FormatHeight": 1080,
        "VideoQuality": 0,        # 0 = Automatic
        "FrameRate": "30",
        "PixelAspectRatio": 1.0,
        "VideoCodec": "H.264",
        "AudioCodec": "AAC",
        "AudioBitDepth": 16,
        "AudioSampleRate": 48000,
    },
    "youtube_4k": {
        "label": "YouTube 4K (H.265)",
        "TargetDir": "",
        "CustomName": "",
        "ExportVideo": True,
        "ExportAudio": True,
        "FormatWidth": 3840,
        "FormatHeight": 2160,
        "VideoQuality": 0,
        "FrameRate": "30",
        "VideoCodec": "H.265",
        "AudioCodec": "AAC",
        "AudioSampleRate": 48000,
    },
    "tiktok_vertical": {
        "label": "TikTok/Reels/Shorts (1080×1920, H.264)",
        "TargetDir": "",
        "CustomName": "",
        "ExportVideo": True,
        "ExportAudio": True,
        "FormatWidth": 1080,
        "FormatHeight": 1920,
        "VideoQuality": 0,
        "FrameRate": "30",
        "VideoCodec": "H.264",
        "AudioCodec": "AAC",
        "AudioSampleRate": 48000,
    },
    "instagram_square": {
        "label": "Instagram Square (1080×1080, H.264)",
        "TargetDir": "",
        "CustomName": "",
        "ExportVideo": True,
        "ExportAudio": True,
        "FormatWidth": 1080,
        "FormatHeight": 1080,
        "VideoQuality": 0,
        "FrameRate": "30",
        "VideoCodec": "H.264",
        "AudioCodec": "AAC",
        "AudioSampleRate": 48000,
    },
    "proxy_540p": {
        "label": "Quick proxy (960×540, H.264, low bitrate)",
        "TargetDir": "",
        "CustomName": "",
        "ExportVideo": True,
        "ExportAudio": True,
        "FormatWidth": 960,
        "FormatHeight": 540,
        "VideoQuality": 5000,     # ~5 Mbps
        "FrameRate": "30",
        "VideoCodec": "H.264",
        "AudioCodec": "AAC",
    },
}


DEFAULT_OUTPUT_DIR = os.path.expanduser("~/.resolve-ai-assistant/renders")


def ensure_output_dir(path: Optional[str] = None) -> str:
    p = path or DEFAULT_OUTPUT_DIR
    os.makedirs(p, exist_ok=True)
    return p


def list_resolve_presets(project) -> list:
    """Return Resolve's built-in render preset list."""
    try:
        return list(project.GetRenderPresetList() or [])
    except Exception:
        return []


def list_our_presets() -> list:
    """Return the social/platform presets we ship."""
    return [
        {"id": pid, "label": cfg["label"]}
        for pid, cfg in PLATFORM_PRESETS.items()
    ]


def queue_render(
    project,
    preset_id: str,
    output_dir: str = None,
    filename: str = None,
) -> dict:
    """Queue a render job using one of our platform presets.

    Returns {job_id, output_path, preset_id} or {error}.
    """
    if preset_id not in PLATFORM_PRESETS:
        return {"error": f"Unknown preset '{preset_id}'. Try list_render_presets."}

    settings = dict(PLATFORM_PRESETS[preset_id])
    settings.pop("label", None)

    out_dir = ensure_output_dir(output_dir)
    settings["TargetDir"] = out_dir

    if filename:
        # Resolve uses CustomName without extension; it adds the right one
        base = os.path.splitext(os.path.basename(filename))[0]
        settings["CustomName"] = base
    else:
        try:
            tl = project.GetCurrentTimeline()
            tl_name = tl.GetName() if tl else "timeline"
        except Exception:
            tl_name = "timeline"
        settings["CustomName"] = f"{tl_name}_{preset_id}"

    # Apply settings
    try:
        ok = project.SetRenderSettings(settings)
        if not ok:
            return {"error": "SetRenderSettings returned False"}
    except Exception as e:
        return {"error": f"SetRenderSettings crashed: {e}"}

    # Add job to the queue
    try:
        job_id = project.AddRenderJob()
        if not job_id:
            return {"error": "AddRenderJob returned empty id"}
    except Exception as e:
        return {"error": f"AddRenderJob crashed: {e}"}

    output_path = os.path.join(out_dir, settings["CustomName"])
    return {
        "ok": True,
        "job_id": job_id,
        "preset_id": preset_id,
        "output_dir": out_dir,
        "output_base": output_path,
    }


def start_renders(project, job_ids: Optional[list] = None) -> dict:
    """Kick off rendering. If job_ids omitted, starts all queued jobs."""
    try:
        if job_ids:
            ok = project.StartRendering(*job_ids)
        else:
            ok = project.StartRendering()
        return {"ok": bool(ok), "started": job_ids or "all"}
    except Exception as e:
        return {"ok": False, "error": f"StartRendering crashed: {e}"}


def render_status(project) -> dict:
    """Snapshot of current render state."""
    try:
        rendering = bool(project.IsRenderingInProgress())
    except Exception:
        rendering = False
    try:
        jobs = project.GetRenderJobList() or []
    except Exception:
        jobs = []
    try:
        statuses = []
        for j in jobs:
            jid = j.get("JobId") if isinstance(j, dict) else None
            if jid:
                st = project.GetRenderJobStatus(jid) or {}
                statuses.append({"JobId": jid, **st})
        return {"rendering": rendering, "jobs": statuses[:20]}
    except Exception:
        return {"rendering": rendering, "jobs": []}
