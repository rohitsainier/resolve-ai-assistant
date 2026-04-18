#!/usr/bin/env python3
"""Audio quality analysis via ffmpeg filters.

Uses ffmpeg's loudnorm (EBU R128), silencedetect, and astats filters to
produce a picture of audio problems — loudness vs broadcast standards,
clipping, silence patches, and per-segment RMS. No extra ML models.
"""

import json
import os
import re
import subprocess
import tempfile
from typing import List, Optional

from transcribe import _ffmpeg, extract_audio_from_timeline


# Broadcast loudness reference points
YOUTUBE_LUFS = -14.0
BROADCAST_LUFS = -23.0
CLIP_TP_DBFS = -1.0   # true peak threshold that flags near-clipping


def _run_ffmpeg_analysis(audio_path: str, filter_str: str, timeout: int = 120) -> str:
    """Run ffmpeg with a filter, return the captured stderr (which holds the stats).

    Output is piped to /dev/null; ffmpeg prints filter output on stderr.
    """
    cmd = [
        _ffmpeg(), "-nostats", "-hide_banner",
        "-i", audio_path,
        "-filter:a", filter_str,
        "-f", "null",
        "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stderr or ""


def analyze_loudness(audio_path: str) -> dict:
    """Return EBU R128 integrated / true peak / LRA etc. via loudnorm.

    loudnorm's 'print_format=json' dumps stats as the last JSON block on stderr.
    """
    out = _run_ffmpeg_analysis(
        audio_path,
        "loudnorm=I=-23:LRA=7:TP=-2:print_format=json",
    )
    # The JSON is the last {...} block in the output
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", out, re.DOTALL)
    if not m:
        return {"error": "Could not parse loudnorm output"}
    try:
        data = json.loads(m.group(0))
        return {
            "integrated_lufs": float(data.get("input_i", 0)),
            "true_peak_dbfs": float(data.get("input_tp", 0)),
            "loudness_range": float(data.get("input_lra", 0)),
            "threshold": float(data.get("input_thresh", 0)),
        }
    except Exception as e:
        return {"error": f"JSON parse: {e}"}


def detect_silence(audio_path: str, noise_db: float = -35, min_duration: float = 1.5) -> List[dict]:
    """Return list of silence regions: [{start, end, duration}, ...]."""
    out = _run_ffmpeg_analysis(
        audio_path,
        f"silencedetect=noise={noise_db}dB:d={min_duration}",
    )
    regions = []
    start = None
    for line in out.splitlines():
        m1 = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        m2 = re.search(r"silence_end:\s*(-?[\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)", line)
        if m1:
            start = float(m1.group(1))
        elif m2 and start is not None:
            end = float(m2.group(1))
            dur = float(m2.group(2))
            regions.append({
                "start": round(max(0, start), 2),
                "end": round(end, 2),
                "duration": round(dur, 2),
            })
            start = None
    return regions


def detect_clipping(audio_path: str, threshold_dbfs: float = -1.0) -> dict:
    """Run astats; extract peak level and report if over threshold."""
    out = _run_ffmpeg_analysis(
        audio_path,
        "astats=measure_overall=Peak_level+Max_level+RMS_level:measure_perchannel=0",
    )
    peak_db = None
    rms_db = None
    for line in out.splitlines():
        m = re.search(r"Peak level dB:\s*(-?[\d.]+|-inf)", line)
        if m and peak_db is None:
            val = m.group(1)
            peak_db = float("-inf") if val == "-inf" else float(val)
        m = re.search(r"RMS level dB:\s*(-?[\d.]+|-inf)", line)
        if m and rms_db is None:
            val = m.group(1)
            rms_db = float("-inf") if val == "-inf" else float(val)
    clipping = peak_db is not None and peak_db > threshold_dbfs
    return {
        "peak_dbfs": peak_db,
        "rms_dbfs": rms_db,
        "clipping": bool(clipping),
        "threshold_dbfs": threshold_dbfs,
    }


def full_audio_report(audio_path: str) -> dict:
    """Run all three analyses and produce a single report."""
    try:
        loud = analyze_loudness(audio_path)
    except Exception as e:
        loud = {"error": str(e)}
    try:
        clip = detect_clipping(audio_path)
    except Exception as e:
        clip = {"error": str(e)}
    try:
        sil = detect_silence(audio_path)
    except Exception as e:
        sil = [{"error": str(e)}]

    # Build a plain-English summary with recommendations
    recs = []
    if isinstance(loud, dict) and "integrated_lufs" in loud:
        lufs = loud["integrated_lufs"]
        if lufs > YOUTUBE_LUFS + 1:
            recs.append(
                f"Audio is louder than YouTube's {YOUTUBE_LUFS} LUFS target "
                f"(currently {lufs:.1f}). YouTube will turn it down anyway — "
                f"apply a -{abs(YOUTUBE_LUFS - lufs):.1f} dB gain for cleaner playback."
            )
        elif lufs < YOUTUBE_LUFS - 3:
            recs.append(
                f"Audio is quieter than YouTube's {YOUTUBE_LUFS} LUFS target "
                f"(currently {lufs:.1f}). Consider +{abs(YOUTUBE_LUFS - lufs):.1f} dB gain."
            )
    if isinstance(clip, dict) and clip.get("clipping"):
        recs.append(
            f"Peak level ({clip['peak_dbfs']:.1f} dBFS) exceeds the safe threshold "
            f"of {clip['threshold_dbfs']} dBFS — risk of clipping. Reduce gain or "
            f"apply a limiter."
        )
    if isinstance(sil, list) and len(sil) > 0:
        total_sil = sum(r.get("duration", 0) for r in sil if "duration" in r)
        recs.append(
            f"{len(sil)} silence regions over 1.5s found, totaling "
            f"{total_sil:.1f}s. These are good candidates for the rough-cut tool."
        )

    return {
        "loudness": loud,
        "clipping": clip,
        "silence_regions": sil[:20],
        "silence_total_count": len(sil) if isinstance(sil, list) else 0,
        "recommendations": recs,
    }


def analyze_timeline_audio(timeline) -> dict:
    """End-to-end: extract audio from timeline, run analyses, clean up."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        extract_audio_from_timeline(timeline, tmp.name)
        return full_audio_report(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
