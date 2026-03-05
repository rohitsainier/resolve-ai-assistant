#!/usr/bin/env python3
"""
Transcription module using OpenAI Whisper.
Extracts audio from timeline and transcribes with timestamps.
"""

import os
import tempfile
import subprocess
import json
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TranscriptSegment:
    """A segment of transcribed audio."""
    start: float  # seconds
    end: float    # seconds
    text: str
    

@dataclass 
class Transcript:
    """Full transcript with segments."""
    segments: List[TranscriptSegment]
    language: str
    duration: float  # total duration in seconds
    
    def to_text(self) -> str:
        """Get plain text of entire transcript."""
        return " ".join(seg.text for seg in self.segments)
    
    def to_timestamped_text(self) -> str:
        """Get text with timestamps for each segment."""
        lines = []
        for seg in self.segments:
            timestamp = f"[{format_timestamp(seg.start)} -> {format_timestamp(seg.end)}]"
            lines.append(f"{timestamp} {seg.text}")
        return "\n".join(lines)


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS.mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def parse_timestamp(ts: str) -> float:
    """Parse HH:MM:SS.mmm to seconds."""
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    else:
        return float(parts[0])


def extract_audio_from_timeline(timeline, output_path: str) -> str:
    """
    Extract audio from a DaVinci Resolve timeline.
    Returns path to the extracted audio file.
    """
    # Get the first video item to find the media path
    video_track = timeline.GetItemListInTrack("video", 1)
    if not video_track:
        raise ValueError("No video items in timeline")
    
    first_clip = video_track[0]
    media_pool_item = first_clip.GetMediaPoolItem()
    
    if not media_pool_item:
        raise ValueError("Could not get media pool item")
    
    clip_info = media_pool_item.GetClipProperty()
    file_path = clip_info.get("File Path", "")
    
    if not file_path or not os.path.exists(file_path):
        raise ValueError(f"Media file not found: {file_path}")
    
    # Extract audio using ffmpeg
    cmd = [
        "ffmpeg", "-y",
        "-i", file_path,
        "-vn",  # no video
        "-acodec", "pcm_s16le",
        "-ar", "16000",  # 16kHz for Whisper
        "-ac", "1",  # mono
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr}")
    
    return output_path


def extract_audio_from_file(video_path: str, output_path: str) -> str:
    """Extract audio from a video file."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr}")
    
    return output_path


def transcribe_audio(audio_path: str, model_name: str = "base") -> Transcript:
    """
    Transcribe audio file using Whisper.
    
    Args:
        audio_path: Path to audio file (wav, mp3, etc.)
        model_name: Whisper model to use (tiny, base, small, medium, large)
    
    Returns:
        Transcript object with segments and timestamps
    """
    import whisper
    
    model = whisper.load_model(model_name)
    result = model.transcribe(audio_path, word_timestamps=True)
    
    segments = []
    for seg in result["segments"]:
        segments.append(TranscriptSegment(
            start=seg["start"],
            end=seg["end"],
            text=seg["text"].strip()
        ))
    
    # Calculate total duration from last segment
    duration = segments[-1].end if segments else 0
    
    return Transcript(
        segments=segments,
        language=result.get("language", "en"),
        duration=duration
    )


def transcribe_timeline_audio(timeline, model_name: str = "base") -> Transcript:
    """
    Transcribe audio from a DaVinci Resolve timeline.
    
    Args:
        timeline: DaVinci Resolve Timeline object
        model_name: Whisper model to use
    
    Returns:
        Transcript object
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name
    
    try:
        extract_audio_from_timeline(timeline, audio_path)
        return transcribe_audio(audio_path, model_name)
    finally:
        if os.path.exists(audio_path):
            os.unlink(audio_path)


def transcribe_video_file(video_path: str, model_name: str = "base") -> Transcript:
    """
    Transcribe audio from a video file.
    
    Args:
        video_path: Path to video file
        model_name: Whisper model to use
    
    Returns:
        Transcript object
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name
    
    try:
        extract_audio_from_file(video_path, audio_path)
        return transcribe_audio(audio_path, model_name)
    finally:
        if os.path.exists(audio_path):
            os.unlink(audio_path)


if __name__ == "__main__":
    # Test with a video file
    import sys
    if len(sys.argv) > 1:
        video = sys.argv[1]
        print(f"Transcribing: {video}")
        transcript = transcribe_video_file(video)
        print(transcript.to_timestamped_text())
