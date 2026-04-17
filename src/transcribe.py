#!/usr/bin/env python3
"""
Transcription module using OpenAI Whisper.
Extracts audio from timeline and transcribes with timestamps.
"""

import os
import shutil
import tempfile
import subprocess
import json
from dataclasses import dataclass
from typing import List, Optional, Callable


def _find_ffmpeg() -> str:
    """Locate ffmpeg even when PATH is stripped (e.g. inside Resolve).

    Also prepends ffmpeg's directory to os.environ['PATH'] so that
    libraries which shell out to bare 'ffmpeg' (Whisper does this) work.
    """
    found = shutil.which("ffmpeg")
    if not found:
        for cand in (
            "/opt/homebrew/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "/opt/local/bin/ffmpeg",
            "/usr/bin/ffmpeg",
        ):
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                found = cand
                break
    if not found:
        raise RuntimeError(
            "ffmpeg not found. Install with `brew install ffmpeg` or set "
            "FFMPEG_BIN env var to the full path."
        )
    # Make sure libraries that bare-call 'ffmpeg' can find it too
    ffmpeg_dir = os.path.dirname(found)
    cur_path = os.environ.get("PATH", "")
    if ffmpeg_dir not in cur_path.split(os.pathsep):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + cur_path
    return found


FFMPEG_BIN = os.environ.get("FFMPEG_BIN") or None
def _ffmpeg() -> str:
    global FFMPEG_BIN
    if not FFMPEG_BIN:
        FFMPEG_BIN = _find_ffmpeg()
    return FFMPEG_BIN


@dataclass
class Word:
    """A single word with precise timing."""
    start: float
    end: float
    text: str


@dataclass
class TranscriptSegment:
    """A segment of transcribed audio."""
    start: float  # seconds
    end: float    # seconds
    text: str
    words: Optional[List[Word]] = None


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

    def iter_words(self):
        """Yield every word across all segments (if word timestamps were captured)."""
        for seg in self.segments:
            if seg.words:
                for w in seg.words:
                    yield w

    def to_srt(self) -> str:
        """Export as SubRip (.srt) subtitle text."""
        lines = []
        for i, seg in enumerate(self.segments, start=1):
            lines.append(str(i))
            lines.append(f"{_srt_ts(seg.start)} --> {_srt_ts(seg.end)}")
            lines.append(seg.text.strip())
            lines.append("")
        return "\n".join(lines)

    def to_vtt(self) -> str:
        """Export as WebVTT (.vtt) subtitle text."""
        lines = ["WEBVTT", ""]
        for seg in self.segments:
            lines.append(f"{_vtt_ts(seg.start)} --> {_vtt_ts(seg.end)}")
            lines.append(seg.text.strip())
            lines.append("")
        return "\n".join(lines)


def _srt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        s, ms = s + 1, 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _vtt_ts(seconds: float) -> str:
    return _srt_ts(seconds).replace(",", ".")


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


def get_all_media_paths(timeline) -> List[str]:
    """
    Get paths to all media files in the timeline.
    Handles multi-track, multi-clip timelines.
    """
    media_paths = []
    seen_paths = set()
    
    # Check all video tracks
    track_count = timeline.GetTrackCount("video")
    for track_idx in range(1, track_count + 1):
        items = timeline.GetItemListInTrack("video", track_idx)
        if items:
            for clip in items:
                media_item = clip.GetMediaPoolItem()
                if media_item:
                    props = media_item.GetClipProperty()
                    file_path = props.get("File Path", "")
                    if file_path and file_path not in seen_paths and os.path.exists(file_path):
                        media_paths.append(file_path)
                        seen_paths.add(file_path)
    
    # Also check audio tracks
    audio_track_count = timeline.GetTrackCount("audio")
    for track_idx in range(1, audio_track_count + 1):
        items = timeline.GetItemListInTrack("audio", track_idx)
        if items:
            for clip in items:
                media_item = clip.GetMediaPoolItem()
                if media_item:
                    props = media_item.GetClipProperty()
                    file_path = props.get("File Path", "")
                    if file_path and file_path not in seen_paths and os.path.exists(file_path):
                        media_paths.append(file_path)
                        seen_paths.add(file_path)
    
    return media_paths


def extract_audio_from_timeline(timeline, output_path: str) -> str:
    """
    Extract audio from a DaVinci Resolve timeline.
    Handles multiple clips by concatenating audio.
    Returns path to the extracted audio file.
    """
    media_paths = get_all_media_paths(timeline)
    
    if not media_paths:
        raise ValueError("No media files found in timeline")
    
    if len(media_paths) == 1:
        # Single file - simple extraction
        return extract_audio_from_file(media_paths[0], output_path)
    
    # Multiple files - need to concatenate
    # Create temp files for each, then concat
    temp_files = []
    try:
        for i, path in enumerate(media_paths):
            temp_audio = output_path.replace(".wav", f"_part{i}.wav")
            extract_audio_from_file(path, temp_audio)
            temp_files.append(temp_audio)
        
        # Concatenate with ffmpeg
        concat_file = output_path.replace(".wav", "_concat.txt")
        with open(concat_file, "w") as f:
            for tf in temp_files:
                f.write(f"file '{tf}'\n")
        
        cmd = [
            _ffmpeg(), "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat error: {result.stderr[:500]}")
        
        # Cleanup concat file
        os.unlink(concat_file)
        
    finally:
        # Cleanup temp audio files
        for tf in temp_files:
            if os.path.exists(tf):
                os.unlink(tf)
    
    return output_path


def extract_audio_from_file(video_path: str, output_path: str) -> str:
    """Extract audio from a video file."""
    cmd = [
        _ffmpeg(), "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr[:500]}")

    return output_path


def _download_model_with_progress(model_name: str, progress_callback) -> str:
    """Download a Whisper model with byte-level progress reporting.

    Returns the local path to the downloaded model. If the model is already
    cached, this returns instantly without downloading.
    """
    import whisper
    import urllib.request

    url = whisper._MODELS.get(model_name)
    if url is None:
        # Fallback to whisper's internal download (no progress)
        return None

    download_root = os.path.join(os.path.expanduser("~"), ".cache", "whisper")
    os.makedirs(download_root, exist_ok=True)
    target = os.path.join(download_root, os.path.basename(url))

    # Already downloaded?
    if os.path.exists(target):
        return target

    if progress_callback:
        progress_callback(0, f"Downloading {model_name} model (one-time)...")

    last_pct = [-1]
    def hook(blocks, block_size, total):
        if total <= 0:
            return
        pct = int(blocks * block_size * 100 / total)
        if pct != last_pct[0]:
            last_pct[0] = pct
            mb_done = (blocks * block_size) / (1024 * 1024)
            mb_total = total / (1024 * 1024)
            if progress_callback:
                progress_callback(pct, f"Downloading {model_name}: {mb_done:.0f}/{mb_total:.0f} MB")

    tmp = target + ".tmp"
    urllib.request.urlretrieve(url, tmp, reporthook=hook)
    os.rename(tmp, target)
    return target


def _audio_duration_seconds(path: str) -> float:
    try:
        result = subprocess.run(
            [_ffmpeg(), "-i", path],
            capture_output=True, text=True, timeout=10,
        )
        # ffmpeg writes "Duration: HH:MM:SS.ms" to stderr
        for line in result.stderr.splitlines():
            line = line.strip()
            if line.startswith("Duration:"):
                ts = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
                h, m, s = ts.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
    except Exception:
        pass
    return 0.0


def transcribe_audio(audio_path: str, model_name: str = "base",
                     progress_callback: Optional[Callable[[int, str], None]] = None) -> Transcript:
    """Transcribe audio file using Whisper, with rich progress reporting.

    Progress band layout:
      0-30%  : model download (only on first use of a given model)
      30-40% : model load into memory
      40-95% : transcription (time-based heartbeat)
      95-100%: assembling result
    """
    import whisper
    import threading
    import time

    log_path = os.path.expanduser("~/.resolve-ai-assistant/whisper.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    def _early_log(msg):
        with open(log_path, "a") as lf:
            lf.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
            lf.flush()
    _early_log(f"=== transcribe_audio called: {audio_path} model={model_name}")

    # Ensure ffmpeg is on PATH (whisper shells out to bare 'ffmpeg' internally)
    try:
        ff = _ffmpeg()
        _early_log(f"ffmpeg located at: {ff}")
    except Exception as e:
        _early_log(f"ffmpeg lookup failed: {e}")
        raise

    # ---- model download (0-30%) ----
    if progress_callback:
        def dl_cb(pct, status):
            mapped = int(pct * 0.30)
            progress_callback(mapped, status)
        _early_log("checking/downloading model file...")
        _download_model_with_progress(model_name, dl_cb)
        _early_log("model file ready on disk")

    # ---- model load (30-40%) ----
    if progress_callback:
        progress_callback(32, f"Loading {model_name} into memory...")
    _early_log("calling whisper.load_model()")
    t_load = time.time()
    model = whisper.load_model(model_name)
    _early_log(f"whisper.load_model finished in {time.time()-t_load:.1f}s")
    if progress_callback:
        progress_callback(40, "Model ready, starting transcription...")

    # ---- transcribe (40-95%) with heartbeat thread ----
    audio_dur = _audio_duration_seconds(audio_path)
    # Whisper realtime factors per model on Apple Silicon CPU.
    speed = {"tiny": 30, "base": 20, "small": 10, "medium": 5, "large": 2}.get(model_name, 10)
    expected_s = max(2.0, (audio_dur or 60) / speed)

    stop_flag = threading.Event()

    def heartbeat():
        start = time.time()
        while not stop_flag.is_set():
            elapsed = time.time() - start
            frac = min(0.95, elapsed / expected_s)
            mapped = 40 + int(frac * 55)
            if progress_callback:
                progress_callback(
                    mapped,
                    f"Transcribing... {int(elapsed)}s / ~{int(expected_s)}s"
                )
            stop_flag.wait(0.5)

    # Diagnostic log — written immediately so we can see where it hangs
    log_path = os.path.expanduser("~/.resolve-ai-assistant/whisper.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def log(msg):
        with open(log_path, "a") as lf:
            lf.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
            lf.flush()

    log(f"--- new run ---")
    log(f"starting transcribe of {audio_path}")
    log(f"audio_dur={audio_dur:.1f}s, expected={expected_s:.1f}s, model={model_name}")

    hb = threading.Thread(target=heartbeat, daemon=True)
    hb.start()
    log("heartbeat started")

    t0 = time.time()

    # Whisper/tqdm write to stdout/stderr; Resolve's captured streams aren't a
    # real TTY and raise a cryptic SystemError. Redirect to /dev/null.
    import contextlib, io
    devnull_out = open(os.devnull, "w")
    devnull_err = open(os.devnull, "w")
    try:
        log("calling model.transcribe() (stdout/stderr suppressed)")
        with contextlib.redirect_stdout(devnull_out), contextlib.redirect_stderr(devnull_err):
            result = model.transcribe(
                audio_path,
                word_timestamps=True,
                fp16=False,
                verbose=None,  # fully silent
            )
        log(f"model.transcribe returned in {time.time()-t0:.1f}s, {len(result.get('segments', []))} segments")
    except Exception as e:
        log(f"transcribe RAISED: {type(e).__name__}: {e}")
        raise
    finally:
        devnull_out.close()
        devnull_err.close()
        stop_flag.set()
        hb.join(timeout=1)
        log("heartbeat joined")

    if progress_callback:
        progress_callback(96, "Processing transcript...")
    
    segments = []
    for seg in result["segments"]:
        words = None
        raw_words = seg.get("words")
        if raw_words:
            words = []
            for w in raw_words:
                # Whisper returns 'word' key with leading space; normalize.
                txt = (w.get("word") or w.get("text") or "").strip()
                if not txt:
                    continue
                words.append(Word(
                    start=float(w.get("start", seg["start"])),
                    end=float(w.get("end", seg["end"])),
                    text=txt,
                ))
        segments.append(TranscriptSegment(
            start=seg["start"],
            end=seg["end"],
            text=seg["text"].strip(),
            words=words,
        ))

    # Calculate total duration from last segment
    duration = segments[-1].end if segments else 0
    
    return Transcript(
        segments=segments,
        language=result.get("language", "en"),
        duration=duration
    )


def transcribe_timeline_audio(timeline, model_name: str = "base",
                              progress_callback: Optional[Callable[[int, str], None]] = None) -> Transcript:
    """
    Transcribe audio from a DaVinci Resolve timeline.
    
    Args:
        timeline: DaVinci Resolve Timeline object
        model_name: Whisper model to use
        progress_callback: Optional callback for progress updates
    
    Returns:
        Transcript object
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name
    
    try:
        if progress_callback:
            progress_callback(0, "Extracting audio from timeline...")
        
        extract_audio_from_timeline(timeline, audio_path)
        
        return transcribe_audio(audio_path, model_name, progress_callback)
    finally:
        if os.path.exists(audio_path):
            os.unlink(audio_path)


def transcribe_video_file(video_path: str, model_name: str = "base",
                          progress_callback: Optional[Callable[[int, str], None]] = None) -> Transcript:
    """
    Transcribe audio from a video file.
    
    Args:
        video_path: Path to video file
        model_name: Whisper model to use
        progress_callback: Optional callback for progress updates
    
    Returns:
        Transcript object
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name
    
    try:
        if progress_callback:
            progress_callback(0, "Extracting audio...")
        
        extract_audio_from_file(video_path, audio_path)
        
        return transcribe_audio(audio_path, model_name, progress_callback)
    finally:
        if os.path.exists(audio_path):
            os.unlink(audio_path)


if __name__ == "__main__":
    # Test with a video file
    import sys
    if len(sys.argv) > 1:
        video = sys.argv[1]
        print(f"Transcribing: {video}")
        
        def progress(pct, status):
            print(f"  [{pct}%] {status}")
        
        transcript = transcribe_video_file(video, progress_callback=progress)
        print(transcript.to_timestamped_text())
