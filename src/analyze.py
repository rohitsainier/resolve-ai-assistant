#!/usr/bin/env python3
"""
Analysis module using Claude to identify highlights, dead air, and shorts.
"""

import os
import json
from dataclasses import dataclass, asdict
from typing import List, Optional
from enum import Enum


class MarkerType(Enum):
    HIGHLIGHT = "highlight"      # Green - good content, keep
    DEAD_AIR = "dead_air"        # Red - silence, filler, cut
    SHORT_CLIP = "short"         # Blue - potential short/clip
    REVIEW = "review"            # Yellow - needs human review


@dataclass
class EditMarker:
    """A marker to be placed on the timeline."""
    start_seconds: float
    end_seconds: float
    marker_type: MarkerType
    label: str
    note: str = ""
    confidence: float = 1.0


def get_marker_color(marker_type: MarkerType) -> str:
    """Get DaVinci Resolve marker color for marker type."""
    colors = {
        MarkerType.HIGHLIGHT: "Green",
        MarkerType.DEAD_AIR: "Red",
        MarkerType.SHORT_CLIP: "Blue",
        MarkerType.REVIEW: "Yellow",
    }
    return colors.get(marker_type, "Yellow")


def _detect_provider() -> str:
    """Pick the LLM provider.

    Order:
    1. AI_PROVIDER env var ("anthropic" or "openai")
    2. Whichever API key is present
    3. Default to anthropic
    """
    explicit = os.environ.get("AI_PROVIDER", "").lower().strip()
    if explicit in ("anthropic", "claude"):
        return "anthropic"
    if explicit in ("openai", "gpt"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"


def _default_model(provider: str) -> str:
    if provider == "openai":
        return os.environ.get("OPENAI_MODEL", "gpt-4o")
    return os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")


def llm_complete(prompt: str, max_tokens: int = 4096, max_retries: int = 3) -> str:
    """Provider-agnostic single-shot completion. Returns response text."""
    import time
    provider = _detect_provider()
    model = _default_model(provider)

    last_error = None
    for attempt in range(max_retries):
        try:
            if provider == "anthropic":
                from anthropic import (
                    Anthropic, APIError, APIConnectionError, RateLimitError,
                )
                client = Anthropic()
                resp = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.content[0].text
            else:
                # OpenAI (chat completions)
                from openai import OpenAI, APIError, APIConnectionError, RateLimitError
                client = OpenAI()
                resp = client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content

        except Exception as e:
            last_error = e
            name = type(e).__name__
            if "RateLimit" in name:
                wait = (attempt + 1) * 30
                print(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
            elif "Connection" in name:
                wait = (attempt + 1) * 5
                print(f"Connection error, waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"{provider} API error: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)

    raise RuntimeError(f"LLM call failed after {max_retries} attempts: {last_error}")


def analyze_transcript(transcript, options: dict, max_retries: int = 3) -> List[EditMarker]:
    """Analyze transcript via the configured LLM provider.

    Args:
        transcript: Transcript object from transcribe module
        options: Dict with add_highlights / mark_dead_air / find_shorts
        max_retries: Number of retries on API failure

    Returns:
        List of EditMarker objects
    """
    prompt = build_analysis_prompt(transcript, options)
    content = llm_complete(prompt, max_tokens=4096, max_retries=max_retries)
    return parse_analysis_response(content)


def build_analysis_prompt(transcript, options: dict) -> str:
    """Build the prompt for Claude to analyze the transcript."""
    
    timestamped_text = transcript.to_timestamped_text()
    
    tasks = []
    if options.get("add_highlights"):
        tasks.append("- HIGHLIGHT: Key insights, reactions, memorable moments, quotable lines")
    if options.get("mark_dead_air"):
        tasks.append("- DEAD_AIR: Long pauses, filler words (um, uh), off-topic tangents, technical issues")
    if options.get("find_shorts"):
        tasks.append("- SHORT_CLIP: Self-contained 60-90 second segments that work standalone (reactions, tips, stories)")
    
    tasks_text = "\n".join(tasks)
    
    prompt = f"""Analyze this video transcript and identify edit points.

TRANSCRIPT:
{timestamped_text}

IDENTIFY THE FOLLOWING:
{tasks_text}

For each item, provide:
1. Start timestamp (HH:MM:SS.mmm)
2. End timestamp (HH:MM:SS.mmm)
3. Type (HIGHLIGHT, DEAD_AIR, or SHORT_CLIP)
4. Brief label (5-10 words)
5. Optional note

FORMAT YOUR RESPONSE AS JSON:
```json
[
  {{
    "start": "00:01:23.500",
    "end": "00:01:45.200",
    "type": "HIGHLIGHT",
    "label": "Great reaction to feature",
    "note": "Strong emotional response, good thumbnail potential"
  }},
  ...
]
```

Be selective. Only mark genuinely notable moments, not everything.
For DEAD_AIR, only mark segments longer than 3 seconds.
For SHORT_CLIP, ensure the segment is self-contained and engaging.

Return ONLY the JSON array, no other text."""

    return prompt


def parse_analysis_response(response_text: str) -> List[EditMarker]:
    """Parse Claude's response into EditMarker objects."""
    
    # Extract JSON from response
    json_text = response_text.strip()
    
    # Handle markdown code blocks
    if "```json" in json_text:
        json_text = json_text.split("```json")[1].split("```")[0]
    elif "```" in json_text:
        json_text = json_text.split("```")[1].split("```")[0]
    
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"Failed to parse response: {e}")
        print(f"Response was: {response_text[:500]}")
        return []
    
    markers = []
    for item in data:
        try:
            marker_type = MarkerType[item["type"].upper()]
            
            markers.append(EditMarker(
                start_seconds=parse_timestamp(item["start"]),
                end_seconds=parse_timestamp(item["end"]),
                marker_type=marker_type,
                label=item.get("label", ""),
                note=item.get("note", ""),
                confidence=item.get("confidence", 1.0)
            ))
        except (KeyError, ValueError) as e:
            print(f"Skipping invalid marker: {e}")
            continue
    
    return markers


def parse_timestamp(ts: str) -> float:
    """Parse HH:MM:SS.mmm to seconds."""
    parts = ts.replace(",", ".").split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    else:
        return float(parts[0])


# Common English filler words. Tweak per creator preference.
DEFAULT_FILLERS = {
    "um", "uh", "uhh", "umm", "er", "erm",
    "like", "actually", "basically", "literally",
    "you know", "i mean", "sort of", "kind of",
}


def analyze_for_fillers(transcript, fillers=None, padding: float = 0.05) -> List[EditMarker]:
    """Find filler words/phrases using word-level Whisper timestamps.

    Returns one DEAD_AIR marker per occurrence so they show up red and can
    be batch-deleted by the rough-cut feature.
    """
    if fillers is None:
        fillers = DEFAULT_FILLERS

    single = {f for f in fillers if " " not in f}
    multi = sorted([f for f in fillers if " " in f], key=lambda s: -len(s.split()))

    markers: List[EditMarker] = []

    for seg in transcript.segments:
        if not seg.words:
            continue

        # Normalize once for matching.
        norm = []
        for w in seg.words:
            stripped = "".join(c for c in w.text.lower() if c.isalpha() or c == "'")
            norm.append(stripped)

        i = 0
        while i < len(seg.words):
            matched_len = 0
            matched_phrase = ""
            # Try longest multi-word phrase first
            for phrase in multi:
                parts = phrase.split()
                if i + len(parts) <= len(seg.words):
                    if all(norm[i + k] == parts[k] for k in range(len(parts))):
                        matched_len = len(parts)
                        matched_phrase = phrase
                        break
            if not matched_len and norm[i] in single:
                matched_len = 1
                matched_phrase = norm[i]

            if matched_len:
                start = max(0.0, seg.words[i].start - padding)
                end = seg.words[i + matched_len - 1].end + padding
                markers.append(EditMarker(
                    start_seconds=start,
                    end_seconds=end,
                    marker_type=MarkerType.DEAD_AIR,
                    label=f"Filler: {matched_phrase}",
                    note="Auto-detected filler word",
                    confidence=0.85,
                ))
                i += matched_len
            else:
                i += 1

    return markers


def generate_chapters(transcript, target_count_per_10min: int = 4):
    """Ask Claude to produce YouTube-style chapter markers + a description.

    Returns (markers, description_text). markers use the REVIEW (yellow)
    marker type so they stand out from highlights/dead-air/shorts.
    """
    duration_min = max(1, transcript.duration / 60)
    target_chapters = max(3, int(duration_min / 10 * target_count_per_10min))

    prompt = f"""You are a YouTube editor. Given this video transcript, produce:

1. A chapter list (~{target_chapters} chapters) covering the full video.
2. A YouTube description: 2-3 sentence hook, then the chapter list, then 5 hashtags.

TRANSCRIPT:
{transcript.to_timestamped_text()}

Return JSON only, no preamble:
```json
{{
  "chapters": [
    {{"start": "00:00:00.000", "title": "Intro"}},
    {{"start": "00:01:30.000", "title": "Main idea"}}
  ],
  "description": "Full YouTube description text here, including chapters and hashtags."
}}
```

Each chapter title should be 3-7 words, punchy, no clickbait."""

    text = llm_complete(prompt, max_tokens=4096).strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"Chapter JSON parse failed: {e}")
        return [], ""

    markers: List[EditMarker] = []
    for ch in data.get("chapters", []):
        try:
            start = parse_timestamp(ch["start"])
        except Exception:
            continue
        markers.append(EditMarker(
            start_seconds=start,
            end_seconds=start + 1.0,  # 1s marker so it's visible
            marker_type=MarkerType.REVIEW,
            label=ch.get("title", "Chapter"),
            note="Generated chapter marker",
            confidence=0.9,
        ))

    return markers, data.get("description", "")


def analyze_for_silence(transcript, threshold_seconds: float = 3.0) -> List[EditMarker]:
    """
    Detect silence/gaps in transcript based on segment timing.
    Doesn't require AI - just looks for gaps between segments.
    """
    markers = []
    
    for i in range(len(transcript.segments) - 1):
        current = transcript.segments[i]
        next_seg = transcript.segments[i + 1]
        
        gap = next_seg.start - current.end
        
        if gap >= threshold_seconds:
            markers.append(EditMarker(
                start_seconds=current.end,
                end_seconds=next_seg.start,
                marker_type=MarkerType.DEAD_AIR,
                label=f"Silence ({gap:.1f}s)",
                note="Detected gap in speech",
                confidence=0.9
            ))
    
    return markers


if __name__ == "__main__":
    # Test with sample data
    from transcribe import Transcript, TranscriptSegment
    
    sample = Transcript(
        segments=[
            TranscriptSegment(0.0, 5.0, "Hey everyone, welcome back to the channel."),
            TranscriptSegment(5.5, 15.0, "Today we're going to talk about something really exciting."),
            TranscriptSegment(20.0, 35.0, "So I just discovered this amazing feature and I can't believe it works."),
            TranscriptSegment(35.5, 50.0, "Let me show you exactly how to use it step by step."),
        ],
        language="en",
        duration=50.0
    )
    
    options = {
        "add_highlights": True,
        "mark_dead_air": True,
        "find_shorts": True,
    }
    
    # Test silence detection (no API needed)
    silence_markers = analyze_for_silence(sample)
    print("Silence markers:", silence_markers)
