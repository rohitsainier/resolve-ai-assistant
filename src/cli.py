#!/usr/bin/env python3
"""
CLI tool for AI Edit Assistant.
Can be used standalone or to generate markers for Resolve.
"""

import argparse
import json
import sys
import os
from pathlib import Path

# Load .env files (does not override real env vars)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from env_loader import load_env
    load_env()
except Exception as _e:
    print(f"env_loader skipped: {_e}")


def cmd_transcribe(args):
    """Transcribe a video file."""
    from transcribe import transcribe_video_file
    
    print(f"🎤 Transcribing: {args.video}")
    print(f"   Model: {args.model}")
    
    transcript = transcribe_video_file(args.video, args.model)
    
    if args.output:
        output_path = args.output
    else:
        output_path = Path(args.video).with_suffix(".transcript.json")
    
    # Save transcript
    data = {
        "language": transcript.language,
        "duration": transcript.duration,
        "segments": [
            {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text
            }
            for seg in transcript.segments
        ]
    }
    
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ Saved transcript to: {output_path}")
    
    if args.text:
        print("\n" + "=" * 50)
        print(transcript.to_timestamped_text())


def cmd_analyze(args):
    """Analyze a transcript or video for edit points."""
    from transcribe import transcribe_video_file, Transcript, TranscriptSegment, Word
    from analyze import (
        analyze_transcript, analyze_for_silence, analyze_for_fillers,
        generate_chapters,
    )

    # Load or create transcript
    if args.transcript:
        print(f"📄 Loading transcript: {args.transcript}")
        with open(args.transcript) as f:
            data = json.load(f)

        segs = []
        for s in data["segments"]:
            words = None
            if s.get("words"):
                words = [Word(w["start"], w["end"], w["text"]) for w in s["words"]]
            segs.append(TranscriptSegment(s["start"], s["end"], s["text"], words))
        transcript = Transcript(
            segments=segs,
            language=data.get("language", "en"),
            duration=data.get("duration", 0)
        )
    else:
        print(f"🎤 Transcribing: {args.video}")
        transcript = transcribe_video_file(args.video, args.model)

    print(f"🧠 Analyzing ({len(transcript.segments)} segments)...")

    options = {
        "add_highlights": args.highlights,
        "mark_dead_air": args.dead_air,
        "find_shorts": args.shorts,
    }

    # Get AI analysis
    markers = []
    if any(options.values()):
        markers = analyze_transcript(transcript, options)

    # Also detect silence gaps
    if args.dead_air:
        silence_markers = analyze_for_silence(transcript)
        markers.extend(silence_markers)

    # Filler words (uses word-level Whisper output)
    if args.fillers:
        markers.extend(analyze_for_fillers(transcript))

    # Chapter markers (writes description alongside)
    if args.chapters:
        chapter_markers, description = generate_chapters(transcript)
        markers.extend(chapter_markers)
        if description:
            base = args.video if args.video else args.transcript
            desc_path = Path(base).with_suffix(".description.txt")
            with open(desc_path, "w", encoding="utf-8") as f:
                f.write(description)
            print(f"📝 Saved description to: {desc_path}")

    print(f"✅ Found {len(markers)} edit points")
    
    # Output markers
    if args.output:
        output_path = args.output
    else:
        base = args.video if args.video else args.transcript
        output_path = Path(base).with_suffix(".markers.json")
    
    data = [
        {
            "start": m.start_seconds,
            "end": m.end_seconds,
            "type": m.marker_type.value,
            "label": m.label,
            "note": m.note,
            "confidence": m.confidence
        }
        for m in markers
    ]
    
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"💾 Saved markers to: {output_path}")
    
    # Print summary
    print("\n📊 Summary:")
    from collections import Counter
    type_counts = Counter(m.marker_type.value for m in markers)
    for marker_type, count in type_counts.items():
        print(f"   {marker_type}: {count}")


def cmd_apply(args):
    """Apply markers to DaVinci Resolve timeline."""
    import json
    from analyze import EditMarker, MarkerType
    
    print(f"📄 Loading markers: {args.markers}")
    with open(args.markers) as f:
        data = json.load(f)
    
    markers = [
        EditMarker(
            start_seconds=m["start"],
            end_seconds=m["end"],
            marker_type=MarkerType(m["type"]),
            label=m.get("label", ""),
            note=m.get("note", ""),
            confidence=m.get("confidence", 1.0)
        )
        for m in data
    ]
    
    print(f"🎬 Connecting to DaVinci Resolve...")
    
    from ai_edit_assistant import get_resolve, get_current_timeline
    from markers import apply_markers
    
    resolve = get_resolve()
    if not resolve:
        print("❌ Could not connect to DaVinci Resolve")
        print("   Make sure Resolve is running and scripting is enabled")
        sys.exit(1)
    
    project, timeline, err = get_current_timeline(resolve)
    if err:
        print(f"❌ {err}")
        sys.exit(1)
    
    print(f"📍 Timeline: {timeline.GetName()}")
    
    added = apply_markers(timeline, markers)
    print(f"✅ Added {added} markers to timeline")


def _load_transcript(path: str):
    from transcribe import Transcript, TranscriptSegment, Word
    with open(path) as f:
        data = json.load(f)
    segs = []
    for s in data["segments"]:
        words = None
        if s.get("words"):
            words = [Word(w["start"], w["end"], w["text"]) for w in s["words"]]
        segs.append(TranscriptSegment(s["start"], s["end"], s["text"], words))
    return Transcript(
        segments=segs,
        language=data.get("language", "en"),
        duration=data.get("duration", 0),
    )


def _load_markers(path: str):
    from analyze import EditMarker, MarkerType
    with open(path) as f:
        data = json.load(f)
    return [
        EditMarker(
            start_seconds=m["start"],
            end_seconds=m["end"],
            marker_type=MarkerType(m["type"]),
            label=m.get("label", ""),
            note=m.get("note", ""),
            confidence=m.get("confidence", 1.0),
        )
        for m in data
    ]


def cmd_subtitles(args):
    """Export .srt + .vtt for a video or an existing transcript JSON."""
    if args.source.endswith(".json"):
        transcript = _load_transcript(args.source)
        base = args.output or str(Path(args.source).with_suffix(""))
    else:
        from transcribe import transcribe_video_file
        print(f"🎤 Transcribing: {args.source}")
        transcript = transcribe_video_file(args.source, args.model)
        base = args.output or str(Path(args.source).with_suffix(""))

    srt_path = base + ".srt"
    vtt_path = base + ".vtt"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(transcript.to_srt())
    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write(transcript.to_vtt())
    print(f"✅ Wrote {srt_path}")
    print(f"✅ Wrote {vtt_path}")


def cmd_rough_cut(args):
    """Build a rough-cut timeline (dead air removed) in Resolve."""
    from ai_edit_assistant import get_resolve, get_current_timeline
    from markers import create_rough_cut_timeline

    markers_list = _load_markers(args.markers)
    resolve = get_resolve()
    if not resolve:
        print("❌ Could not connect to DaVinci Resolve")
        sys.exit(1)
    project, timeline, err = get_current_timeline(resolve)
    if err:
        print(f"❌ {err}")
        sys.exit(1)

    new_tl = create_rough_cut_timeline(project, timeline, markers_list, name=args.name)
    print(f"✅ Created rough cut timeline: {new_tl.GetName() if new_tl else '(failed)'}")


def cmd_shorts_timeline(args):
    """Build a Shorts timeline in Resolve from SHORT_CLIP markers."""
    from ai_edit_assistant import get_resolve, get_current_timeline
    from markers import create_subclip_timeline

    markers_list = _load_markers(args.markers)
    resolve = get_resolve()
    if not resolve:
        print("❌ Could not connect to DaVinci Resolve")
        sys.exit(1)
    project, timeline, err = get_current_timeline(resolve)
    if err:
        print(f"❌ {err}")
        sys.exit(1)

    new_tl = create_subclip_timeline(project, timeline, markers_list, name=args.name)
    if new_tl is None:
        print("⚠️ No SHORT_CLIP markers found; nothing to create.")
    else:
        print(f"✅ Created shorts timeline: {new_tl.GetName()}")


def main():
    parser = argparse.ArgumentParser(
        description="AI Edit Assistant - Analyze videos and add edit markers"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Transcribe command
    p_transcribe = subparsers.add_parser("transcribe", help="Transcribe a video file")
    p_transcribe.add_argument("video", help="Path to video file")
    p_transcribe.add_argument("-m", "--model", default="base", 
                              choices=["tiny", "base", "small", "medium", "large"],
                              help="Whisper model to use")
    p_transcribe.add_argument("-o", "--output", help="Output path for transcript JSON")
    p_transcribe.add_argument("-t", "--text", action="store_true",
                              help="Also print timestamped text")
    p_transcribe.set_defaults(func=cmd_transcribe)
    
    # Analyze command
    p_analyze = subparsers.add_parser("analyze", help="Analyze video for edit points")
    p_analyze.add_argument("-v", "--video", help="Path to video file")
    p_analyze.add_argument("-t", "--transcript", help="Path to transcript JSON")
    p_analyze.add_argument("-m", "--model", default="base",
                           choices=["tiny", "base", "small", "medium", "large"],
                           help="Whisper model for transcription")
    p_analyze.add_argument("-o", "--output", help="Output path for markers JSON")
    p_analyze.add_argument("--highlights", action="store_true", default=True,
                           help="Find highlights (default: true)")
    p_analyze.add_argument("--no-highlights", action="store_false", dest="highlights")
    p_analyze.add_argument("--dead-air", action="store_true", default=True,
                           help="Mark dead air (default: true)")
    p_analyze.add_argument("--no-dead-air", action="store_false", dest="dead_air")
    p_analyze.add_argument("--shorts", action="store_true", default=True,
                           help="Find short clips (default: true)")
    p_analyze.add_argument("--no-shorts", action="store_false", dest="shorts")
    p_analyze.add_argument("--fillers", action="store_true",
                           help="Detect filler words (um, uh, like) at word level")
    p_analyze.add_argument("--chapters", action="store_true",
                           help="Generate chapter markers + YouTube description")
    p_analyze.set_defaults(func=cmd_analyze)

    # Subtitle export
    p_subs = subparsers.add_parser("subtitles", help="Export .srt + .vtt subtitles")
    p_subs.add_argument("source", help="Path to video OR transcript JSON")
    p_subs.add_argument("-m", "--model", default="base",
                        choices=["tiny", "base", "small", "medium", "large"])
    p_subs.add_argument("-o", "--output", help="Output base path (no extension)")
    p_subs.set_defaults(func=cmd_subtitles)

    # Rough cut from a markers file
    p_rough = subparsers.add_parser("rough-cut",
        help="Build a 'dead-air-removed' timeline in Resolve from markers JSON")
    p_rough.add_argument("markers", help="Path to markers JSON file")
    p_rough.add_argument("--name", default="Rough Cut", help="New timeline name")
    p_rough.set_defaults(func=cmd_rough_cut)

    # Shorts timeline from a markers file
    p_shorts_tl = subparsers.add_parser("shorts-timeline",
        help="Build a Shorts timeline in Resolve from markers JSON")
    p_shorts_tl.add_argument("markers", help="Path to markers JSON file")
    p_shorts_tl.add_argument("--name", default="Shorts", help="New timeline name")
    p_shorts_tl.set_defaults(func=cmd_shorts_timeline)
    
    # Apply command
    p_apply = subparsers.add_parser("apply", help="Apply markers to Resolve timeline")
    p_apply.add_argument("markers", help="Path to markers JSON file")
    p_apply.set_defaults(func=cmd_apply)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    args.func(args)


if __name__ == "__main__":
    main()
