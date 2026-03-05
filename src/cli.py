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
    from transcribe import transcribe_video_file, Transcript, TranscriptSegment
    from analyze import analyze_transcript, analyze_for_silence
    
    # Load or create transcript
    if args.transcript:
        print(f"📄 Loading transcript: {args.transcript}")
        with open(args.transcript) as f:
            data = json.load(f)
        
        transcript = Transcript(
            segments=[
                TranscriptSegment(s["start"], s["end"], s["text"])
                for s in data["segments"]
            ],
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
    p_analyze.set_defaults(func=cmd_analyze)
    
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
