#!/usr/bin/env python3
"""
AI Edit Assistant for DaVinci Resolve
Analyzes timeline, adds markers, extracts shorts, generates rough cuts.
"""

import sys
import os
import json
import hashlib
from pathlib import Path
from datetime import datetime

# Add our modules to path. Use realpath so the symlink installed by
# install.sh resolves back to the repo's src/ folder where the sibling
# modules (transcribe, analyze, markers, env_loader) actually live.
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Load .env so Resolve picks up API keys without needing launchctl/setenv.
try:
    from env_loader import load_env
    load_env()
except Exception as _e:
    print(f"env_loader skipped: {_e}")

# Cache directory for transcripts
CACHE_DIR = Path.home() / ".resolve-ai-assistant" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Output directory for exported subtitles, descriptions, etc.
EXPORTS_DIR = Path.home() / ".resolve-ai-assistant" / "exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:80]


def _export_subtitles(timeline, transcript):
    """Write .srt and .vtt for the timeline. Returns (srt_path, vtt_path)."""
    base = EXPORTS_DIR / _safe_name(timeline.GetName() or "timeline")
    srt_path = str(base) + ".srt"
    vtt_path = str(base) + ".vtt"
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(transcript.to_srt())
    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write(transcript.to_vtt())
    return srt_path, vtt_path


def _save_description(timeline, description: str) -> str:
    """Save a YouTube-style description file."""
    base = EXPORTS_DIR / (_safe_name(timeline.GetName() or "timeline") + "_description.txt")
    with open(base, "w", encoding="utf-8") as f:
        f.write(description)
    return str(base)


def get_resolve():
    """Get the Resolve application object.

    When this script is launched from Workspace -> Scripts, Resolve injects
    `fusion` as a global. We prefer that path because `scriptapp("Resolve")`
    returns None in that context. For external/CLI runs we fall back to the
    DaVinciResolveScript module.
    """
    # 1. Resolve-injected fusion global (in-app Workspace -> Scripts)
    try:
        import builtins
        f = getattr(builtins, "fusion", None) or globals().get("fusion")
        if f is not None:
            r = f.GetResolve()
            if r is not None:
                return r
    except Exception:
        pass

    # 2. Standard DaVinciResolveScript path
    try:
        import DaVinciResolveScript as dvr
        r = dvr.scriptapp("Resolve")
        if r is not None:
            return r
    except ImportError:
        pass

    # 3. External run: set up env vars then import again
    if sys.platform == "darwin":
        script_api = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        script_lib = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
    elif sys.platform == "win32":
        script_api = os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"),
                                  "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting")
        script_lib = os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"),
                                  "Blackmagic Design", "DaVinci Resolve", "fusionscript.dll")
    elif sys.platform.startswith("linux"):
        script_api = "/opt/resolve/Developer/Scripting"
        script_lib = "/opt/resolve/libs/Fusion/fusionscript.so"
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")

    os.environ["RESOLVE_SCRIPT_API"] = script_api
    os.environ["RESOLVE_SCRIPT_LIB"] = script_lib
    sys.path.append(os.path.join(script_api, "Modules"))

    import DaVinciResolveScript as dvr
    return dvr.scriptapp("Resolve")


def get_current_timeline(resolve):
    """Get the current project and timeline."""
    pm = resolve.GetProjectManager()
    project = pm.GetCurrentProject()
    if not project:
        return None, None, "No project open"
    
    timeline = project.GetCurrentTimeline()
    if not timeline:
        return project, None, "No timeline selected"
    
    return project, timeline, None


def get_timeline_cache_key(timeline):
    """Generate a cache key for the timeline based on its content.

    Hashes per-clip identity + in/out points across all video and audio
    tracks, in order. Reordering, trimming, or swapping clips invalidates
    the cache.
    """
    name = timeline.GetName()
    parts = [name]

    for track_kind in ("video", "audio"):
        try:
            track_count = timeline.GetTrackCount(track_kind) or 0
        except Exception:
            track_count = 0
        for track_idx in range(1, track_count + 1):
            items = timeline.GetItemListInTrack(track_kind, track_idx) or []
            for clip in items:
                try:
                    mp_item = clip.GetMediaPoolItem()
                    item_id = mp_item.GetUniqueId() if mp_item else "?"
                except Exception:
                    item_id = "?"
                try:
                    s, e, off = clip.GetStart(), clip.GetEnd(), clip.GetLeftOffset()
                except Exception:
                    s = e = off = 0
                parts.append(f"{track_kind}{track_idx}:{item_id}:{s}:{e}:{off}")

    return hashlib.md5(":".join(parts).encode()).hexdigest()[:12]


def get_cached_transcript(cache_key):
    """Load transcript from cache if available."""
    cache_file = CACHE_DIR / f"{cache_key}.json"
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                data = json.load(f)
            from transcribe import Transcript, TranscriptSegment, Word
            segs = []
            for s in data["segments"]:
                words = None
                if s.get("words"):
                    words = [Word(w["start"], w["end"], w["text"]) for w in s["words"]]
                segs.append(TranscriptSegment(s["start"], s["end"], s["text"], words))
            return Transcript(
                segments=segs,
                language=data.get("language", "en"),
                duration=data.get("duration", 0)
            )
        except Exception:
            pass
    return None


def save_transcript_cache(cache_key, transcript):
    """Save transcript to cache."""
    cache_file = CACHE_DIR / f"{cache_key}.json"
    data = {
        "language": transcript.language,
        "duration": transcript.duration,
        "segments": [
            {
                "start": s.start,
                "end": s.end,
                "text": s.text,
                "words": (
                    [{"start": w.start, "end": w.end, "text": w.text} for w in s.words]
                    if s.words else None
                ),
            }
            for s in transcript.segments
        ],
        "cached_at": datetime.now().isoformat()
    }
    with open(cache_file, "w") as f:
        json.dump(data, f, indent=2)


def estimate_duration_minutes(timeline):
    """Estimate timeline duration in minutes for cost estimation."""
    try:
        fps = float(timeline.GetSetting("timelineFrameRate") or 24)
        end_frame = timeline.GetEndFrame()
        start_frame = timeline.GetStartFrame()
        duration_seconds = (end_frame - start_frame) / fps
        return duration_seconds / 60
    except Exception:
        return 10  # Default estimate


def estimate_cost(duration_minutes, whisper_model="base"):
    """Estimate processing cost (provider-aware)."""
    # Whisper is local, no cost
    # Rough estimate: 150 words/min speech, ~200 tokens/min input
    estimated_tokens = int(duration_minutes * 200) + 500  # + prompt overhead

    # Per-1M token rates (approximate, in USD)
    rates = {
        "anthropic": {"in": 3.0, "out": 15.0},   # Claude Sonnet 4.6
        "openai":    {"in": 2.5, "out": 10.0},   # GPT-4o
    }
    provider = os.environ.get("AI_PROVIDER", "").lower() or (
        "openai" if os.environ.get("OPENAI_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY")
        else "anthropic"
    )
    rate = rates.get(provider, rates["anthropic"])
    input_cost = (estimated_tokens / 1_000_000) * rate["in"]
    output_cost = (1000 / 1_000_000) * rate["out"]
    return {
        "provider": provider,
        "estimated_input_tokens": estimated_tokens,
        "estimated_cost_usd": round(input_cost + output_cost, 4),
        "whisper_model": whisper_model,
        "duration_minutes": round(duration_minutes, 1),
    }


def create_ui(resolve, fusion):
    """Create the UI dialog for the assistant."""
    ui = fusion.UIManager
    disp = ui.UIDispatcher(fusion)
    
    # Window definition - larger to accommodate new features
    win = disp.AddWindow({
        "ID": "AIEditAssistant",
        "WindowTitle": "AI Edit Assistant",
        "Geometry": [100, 100, 480, 640],
    }, [
        ui.VGroup({"Spacing": 8}, [
            # Header
            ui.Label({
                "ID": "Header",
                "Text": "🎬 AI Edit Assistant",
                "Alignment": {"AlignHCenter": True},
                "Font": ui.Font({"PixelSize": 18, "Bold": True}),
            }),
            
            # Marker legend
            ui.Label({
                "ID": "Legend",
                "Text": "🟢 Highlight  🔴 Dead Air  🔵 Short Clip",
                "Alignment": {"AlignHCenter": True},
            }),
            
            ui.HGroup([
                ui.Label({"Text": "Timeline:", "Weight": 0.3}),
                ui.Label({"ID": "TimelineName", "Text": "(none)", "Weight": 0.7}),
            ]),
            
            ui.HGroup([
                ui.Label({"Text": "Duration:", "Weight": 0.3}),
                ui.Label({"ID": "Duration", "Text": "0 min", "Weight": 0.35}),
                ui.Label({"Text": "Est. Cost:", "Weight": 0.15}),
                ui.Label({"ID": "EstCost", "Text": "$0.00", "Weight": 0.2}),
            ]),
            
            ui.VGap(5),
            
            # Whisper model selection
            ui.HGroup([
                ui.Label({"Text": "Whisper Model:", "Weight": 0.35}),
                ui.ComboBox({
                    "ID": "WhisperModel",
                    "Weight": 0.65,
                }),
            ]),
            
            ui.VGap(5),
            
            # Analysis options
            ui.Label({"Text": "Analysis Options:", "Font": ui.Font({"Bold": True})}),
            
            ui.CheckBox({"ID": "AddHighlights", "Text": "Find highlights (green markers)", "Checked": True}),
            ui.CheckBox({"ID": "MarkDeadAir", "Text": "Mark dead air for removal (red markers)", "Checked": True}),
            ui.CheckBox({"ID": "FindShorts", "Text": "Identify potential shorts (blue markers)", "Checked": True}),
            
            ui.VGap(5),
            
            # Actions (rough cut disabled until implemented)
            ui.Label({"Text": "Actions:", "Font": ui.Font({"Bold": True})}),
            
            ui.CheckBox({"ID": "CreateShortsTimeline", "Text": "Create separate Shorts timeline", "Checked": False}),
            ui.CheckBox({"ID": "CreateRoughCut", "Text": "Generate rough cut (dead air removed)", "Checked": False}),
            ui.CheckBox({"ID": "DetectFillers", "Text": "Detect filler words (um, uh, like)", "Checked": False}),
            ui.CheckBox({"ID": "GenerateChapters", "Text": "Generate chapters + YouTube description", "Checked": False}),
            ui.CheckBox({"ID": "ExportSRT", "Text": "Export subtitles (.srt + .vtt)", "Checked": False}),

            ui.VGap(5),
            
            # Cache info
            ui.HGroup([
                ui.CheckBox({"ID": "UseCache", "Text": "Use cached transcript if available", "Checked": True}),
            ]),
            
            ui.VGap(5),
            
            # Status
            ui.Label({"ID": "Status", "Text": "", "Alignment": {"AlignHCenter": True}}),
            
            # Progress with percentage
            ui.HGroup([
                ui.ProgressBar({"ID": "Progress", "Value": 0, "Maximum": 100, "Weight": 0.85}),
                ui.Label({"ID": "ProgressPct", "Text": "0%", "Weight": 0.15}),
            ]),
            
            # ETA
            ui.Label({"ID": "ETA", "Text": "", "Alignment": {"AlignHCenter": True}}),
            
            ui.VGap(5),
            
            # Buttons row 1
            ui.HGroup([
                ui.Button({"ID": "Analyze", "Text": "🔍 Analyze", "Weight": 0.5}),
                ui.Button({"ID": "Cancel", "Text": "Cancel", "Weight": 0.5}),
            ]),
            
            # Buttons row 2 - Clear markers
            ui.HGroup([
                ui.Button({"ID": "ClearAll", "Text": "🗑️ Clear All AI Markers", "Weight": 0.5}),
                ui.Button({"ID": "ClearByColor", "Text": "Clear by Color...", "Weight": 0.5}),
            ]),
        ]),
    ])
    
    return win, disp


def _prompt_color(fusion):
    """Tiny modal asking which marker color to clear. Returns Resolve color name or None."""
    ui = fusion.UIManager
    disp = ui.UIDispatcher(fusion)
    win = disp.AddWindow({
        "ID": "ClearByColor",
        "WindowTitle": "Clear by color",
        "Geometry": [200, 200, 280, 220],
    }, [
        ui.VGroup({"Spacing": 8}, [
            ui.Label({"Text": "Pick marker color to clear:"}),
            ui.ComboBox({"ID": "ColorCombo"}),
            ui.HGroup([
                ui.Button({"ID": "OK", "Text": "Clear"}),
                ui.Button({"ID": "Cancel", "Text": "Cancel"}),
            ]),
        ]),
    ])
    items = win.GetItems()
    for c in ["Green", "Red", "Blue", "Yellow", "Cyan", "Purple",
              "Fuchsia", "Rose", "Lavender", "Sky", "Mint", "Lemon",
              "Sand", "Cocoa", "Cream"]:
        items["ColorCombo"].AddItem(c)
    result = {"color": None}

    def on_ok(ev):
        result["color"] = items["ColorCombo"].CurrentText
        disp.ExitLoop()

    def on_cancel(ev):
        disp.ExitLoop()

    win.On.OK.Clicked = on_ok
    win.On.Cancel.Clicked = on_cancel
    win.On.ClearByColor.Close = on_cancel
    win.Show()
    disp.RunLoop()
    win.Hide()
    return result["color"]


def create_preview_window(fusion, markers):
    """Create a preview window to review markers before applying."""
    ui = fusion.UIManager
    disp = ui.UIDispatcher(fusion)
    
    # Build marker list items
    marker_items = []
    for i, m in enumerate(markers):
        from analyze import MarkerType
        color_emoji = {"HIGHLIGHT": "🟢", "DEAD_AIR": "🔴", "SHORT_CLIP": "🔵", "REVIEW": "🟡"}
        emoji = color_emoji.get(m.marker_type.name, "⚪")
        time_str = f"{int(m.start_seconds//60)}:{int(m.start_seconds%60):02d}"
        marker_items.append(f"{emoji} [{time_str}] {m.label}")
    
    win = disp.AddWindow({
        "ID": "MarkerPreview",
        "WindowTitle": "Review Markers",
        "Geometry": [150, 150, 500, 400],
    }, [
        ui.VGroup({"Spacing": 10}, [
            ui.Label({
                "Text": f"Found {len(markers)} markers. Review and apply:",
                "Font": ui.Font({"Bold": True}),
            }),
            
            ui.Tree({
                "ID": "MarkerList",
                "Weight": 1.0,
                "HeaderHidden": True,
                "SelectionMode": "ExtendedSelection",
            }),
            
            ui.Label({"Text": "Shift+Click to select multiple. Selected markers will be applied."}),
            
            ui.HGroup([
                ui.Button({"ID": "SelectAll", "Text": "Select All", "Weight": 0.25}),
                ui.Button({"ID": "SelectNone", "Text": "Select None", "Weight": 0.25}),
                ui.Button({"ID": "ApplySelected", "Text": "✅ Apply Selected", "Weight": 0.25}),
                ui.Button({"ID": "CancelPreview", "Text": "Cancel", "Weight": 0.25}),
            ]),
        ]),
    ])
    
    items = win.GetItems()
    
    # Populate tree
    tree = items["MarkerList"]
    header = tree.NewItem()
    header.Text[0] = "Markers"
    tree.SetHeaderItem(header)
    
    tree_items = []
    for i, text in enumerate(marker_items):
        item = tree.NewItem()
        item.Text[0] = text
        tree.AddTopLevelItem(item)
        item.Selected = True  # Select all by default
        tree_items.append(item)
    
    # Result storage
    result = {"selected_indices": list(range(len(markers))), "cancelled": False}
    
    def on_select_all(ev):
        for item in tree_items:
            item.Selected = True
    
    def on_select_none(ev):
        for item in tree_items:
            item.Selected = False
    
    def on_apply(ev):
        result["selected_indices"] = [i for i, item in enumerate(tree_items) if item.Selected]
        disp.ExitLoop()
    
    def on_cancel(ev):
        result["cancelled"] = True
        disp.ExitLoop()
    
    def on_close(ev):
        result["cancelled"] = True
        disp.ExitLoop()
    
    win.On.SelectAll.Clicked = on_select_all
    win.On.SelectNone.Clicked = on_select_none
    win.On.ApplySelected.Clicked = on_apply
    win.On.CancelPreview.Clicked = on_cancel
    win.On.MarkerPreview.Close = on_close
    
    win.Show()
    disp.RunLoop()
    win.Hide()
    
    return result


def on_analyze(resolve, fusion, win, items, state):
    """Handle the Analyze button click."""
    from transcribe import transcribe_timeline_audio, transcribe_video_file
    from analyze import (
        analyze_transcript, analyze_for_silence, analyze_for_fillers,
        generate_chapters,
    )
    from markers import apply_markers, create_subclip_timeline, create_rough_cut_timeline
    import time
    
    project, timeline, err = get_current_timeline(resolve)
    if err:
        items["Status"].Text = f"❌ {err}"
        return
    
    def update_progress(value, status=None, eta=None):
        items["Progress"].Value = value
        items["ProgressPct"].Text = f"{value}%"
        if status:
            items["Status"].Text = status
        if eta:
            items["ETA"].Text = eta
        else:
            items["ETA"].Text = ""
    
    whisper_model = items["WhisperModel"].CurrentText or "base"
    use_cache = items["UseCache"].Checked
    
    try:
        state["analyzing"] = True
        start_time = time.time()
        
        # Check cache first
        cache_key = get_timeline_cache_key(timeline)
        transcript = None
        
        if use_cache:
            transcript = get_cached_transcript(cache_key)
            if transcript:
                update_progress(30, "📋 Using cached transcript...")
        
        if not transcript:
            update_progress(5, "📝 Extracting audio from timeline...")
            
            # Estimate time based on duration
            duration_min = estimate_duration_minutes(timeline)
            # Whisper processes ~10-30x realtime depending on model
            speed_factor = {"tiny": 30, "base": 20, "small": 10, "medium": 5, "large": 2}.get(whisper_model, 10)
            eta_seconds = int((duration_min * 60) / speed_factor)
            eta_str = f"⏱️ Estimated: {eta_seconds//60}m {eta_seconds%60}s"
            
            update_progress(10, f"🎤 Transcribing with {whisper_model} model...", eta_str)

            # Map Whisper's 0-100 progress into the 10-50 band of overall progress
            def whisper_progress(pct, status):
                mapped = 10 + int(pct * 0.4)
                update_progress(mapped, f"🎤 {status}", eta_str)

            # Transcribe (this takes time)
            transcript = transcribe_timeline_audio(
                timeline, model_name=whisper_model, progress_callback=whisper_progress
            )

            # Cache the result
            save_transcript_cache(cache_key, transcript)
            update_progress(50, "📋 Transcript cached for future use")
        
        # Check if cancelled
        if state.get("cancelled"):
            update_progress(0, "⚠️ Cancelled")
            return
        
        # Analyze with AI
        update_progress(55, "🧠 Analyzing content with AI...")
        
        options = {
            "add_highlights": items["AddHighlights"].Checked,
            "mark_dead_air": items["MarkDeadAir"].Checked,
            "find_shorts": items["FindShorts"].Checked,
        }
        
        markers = []
        
        # Get AI analysis if any options selected
        if any(options.values()):
            try:
                markers = analyze_transcript(transcript, options)
            except Exception as e:
                update_progress(60, f"⚠️ AI analysis failed: {str(e)[:50]}...")
                # Fall back to silence detection only
                if options.get("mark_dead_air"):
                    markers = analyze_for_silence(transcript)
        
        # Also detect silence gaps (fast, no API)
        if options.get("mark_dead_air"):
            silence_markers = analyze_for_silence(transcript)
            # Merge, avoiding duplicates
            existing_ranges = set((m.start_seconds, m.end_seconds) for m in markers)
            for sm in silence_markers:
                if (sm.start_seconds, sm.end_seconds) not in existing_ranges:
                    markers.append(sm)
        
        if state.get("cancelled"):
            update_progress(0, "⚠️ Cancelled")
            return
        
        update_progress(75, f"✅ Found {len(markers)} markers")
        
        if not markers:
            update_progress(100, "✅ Analysis complete - no markers to add")
            return
        
        # Show preview window for user to review
        update_progress(80, "👀 Review markers...")
        preview_result = create_preview_window(fusion, markers)
        
        if preview_result["cancelled"]:
            update_progress(0, "⚠️ Cancelled")
            return
        
        # Filter to selected markers
        selected_indices = preview_result["selected_indices"]
        selected_markers = [markers[i] for i in selected_indices]
        
        if not selected_markers:
            update_progress(100, "✅ No markers selected")
            return
        
        # Apply markers
        update_progress(88, f"🎯 Adding {len(selected_markers)} markers...")
        added = apply_markers(timeline, selected_markers)
        extras = []

        from analyze import MarkerType

        # Filler-word markers (cheap, word-level)
        if items["DetectFillers"].Checked:
            update_progress(90, "🪶 Scanning for filler words...")
            filler_markers = analyze_for_fillers(transcript)
            if filler_markers:
                apply_markers(timeline, filler_markers)
                extras.append(f"{len(filler_markers)} fillers")

        # Subtitle export
        if items["ExportSRT"].Checked:
            update_progress(92, "💬 Exporting subtitles...")
            try:
                srt_path, vtt_path = _export_subtitles(timeline, transcript)
                extras.append(f"subs → {os.path.basename(srt_path)}")
            except Exception as e:
                extras.append(f"subs failed: {e}")

        # Chapter markers + YouTube description
        if items["GenerateChapters"].Checked:
            update_progress(94, "📚 Generating chapters...")
            try:
                chapter_markers, description = generate_chapters(transcript)
                if chapter_markers:
                    apply_markers(timeline, chapter_markers)
                    desc_path = _save_description(timeline, description)
                    extras.append(f"{len(chapter_markers)} chapters → {os.path.basename(desc_path)}")
            except Exception as e:
                extras.append(f"chapters failed: {e}")

        # Shorts timeline
        if items["CreateShortsTimeline"].Checked:
            update_progress(96, "✂️ Creating shorts timeline...")
            shorts = [m for m in selected_markers if m.marker_type == MarkerType.SHORT_CLIP]
            if shorts:
                try:
                    new_tl = create_subclip_timeline(project, timeline, shorts,
                                                    name=f"{timeline.GetName()} - Shorts")
                    if new_tl:
                        extras.append(f"shorts timeline ({len(shorts)} clips)")
                except Exception as e:
                    extras.append(f"shorts failed: {e}")

        # Rough cut
        if items["CreateRoughCut"].Checked:
            update_progress(98, "✂️ Building rough cut...")
            dead = [m for m in selected_markers if m.marker_type == MarkerType.DEAD_AIR]
            if dead:
                try:
                    new_tl = create_rough_cut_timeline(project, timeline, dead,
                                                      name=f"{timeline.GetName()} - Rough Cut")
                    if new_tl:
                        extras.append("rough cut timeline")
                except Exception as e:
                    extras.append(f"rough cut failed: {e}")

        elapsed = int(time.time() - start_time)
        suffix = (" (" + ", ".join(extras) + ")") if extras else ""
        update_progress(100, f"✅ Done! Added {added} markers in {elapsed}s{suffix}")
        
    except Exception as e:
        items["Status"].Text = f"❌ Error: {str(e)}"
        items["Progress"].Value = 0
        items["ProgressPct"].Text = "0%"
        items["ETA"].Text = ""
        import traceback
        traceback.print_exc()
    finally:
        state["analyzing"] = False


def on_clear_markers(timeline, color=None):
    """Clear AI-added markers from timeline."""
    from markers import clear_markers
    return clear_markers(timeline, color)


def run_analysis_tk(resolve, timeline, dlg, options):
    """Worker thread — runs transcription + analysis + applies markers.

    Communicates with the Tk dialog via dlg.update_all(pct, status, eta).
    """
    from transcribe import transcribe_timeline_audio
    from analyze import (
        analyze_transcript, analyze_for_silence, analyze_for_fillers,
        generate_chapters, MarkerType,
    )
    from markers import apply_markers, create_subclip_timeline, create_rough_cut_timeline
    from tk_ui import show_marker_preview
    import time

    try:
        start = time.time()
        project, tl, err = get_current_timeline(resolve)
        if err:
            dlg.update_all(0, f"❌ {err}")
            dlg.reenable()
            return

        use_cache = options["use_cache"]
        whisper_model = options["whisper_model"]

        # Cache check
        cache_key = get_timeline_cache_key(tl)
        transcript = None
        if use_cache:
            transcript = get_cached_transcript(cache_key)
            if transcript:
                dlg.update_all(30, "📋 Using cached transcript")

        if not transcript:
            dlg.update_all(5, "📝 Extracting audio...")
            duration_min = estimate_duration_minutes(tl)
            speed = {"tiny": 30, "base": 20, "small": 10,
                     "medium": 5, "large": 2}.get(whisper_model, 10)
            eta_s = int((duration_min * 60) / speed)
            eta = f"⏱ est. {eta_s // 60}m {eta_s % 60}s"

            dlg.update_all(10, f"🎤 Transcribing ({whisper_model})...", eta)

            # Whisper reports 0-100 across its whole pipeline (download/load/transcribe).
            # Map that into the 10-55 band of overall progress.
            def wp(pct, status):
                dlg.update_all(10 + int(pct * 0.45), f"🎤 {status}", eta)

            transcript = transcribe_timeline_audio(
                tl, model_name=whisper_model, progress_callback=wp
            )
            save_transcript_cache(cache_key, transcript)
            dlg.update_all(55, "📋 Transcript cached")

        # AI analysis
        dlg.update_all(60, "🧠 Analyzing...")
        ai_opts = {
            "add_highlights": options["add_highlights"],
            "mark_dead_air": options["mark_dead_air"],
            "find_shorts": options["find_shorts"],
        }
        markers = []
        if any(ai_opts.values()):
            try:
                markers = analyze_transcript(transcript, ai_opts)
            except Exception as e:
                dlg.update_all(65, f"⚠ AI failed: {str(e)[:60]}")
                if ai_opts["mark_dead_air"]:
                    markers = analyze_for_silence(transcript)

        if ai_opts["mark_dead_air"]:
            sil = analyze_for_silence(transcript)
            existing = {(m.start_seconds, m.end_seconds) for m in markers}
            for sm in sil:
                if (sm.start_seconds, sm.end_seconds) not in existing:
                    markers.append(sm)

        dlg.update_all(75, f"✅ Found {len(markers)} markers")

        if not markers:
            dlg.update_all(100, "No markers found")
            dlg.reenable()
            return

        # Preview — show_marker_preview is a Tk Toplevel, must run on main thread
        dlg.update_all(80, "👀 Review in preview window...")
        result_holder = {"indices": None, "done": False}

        def show_preview():
            try:
                result_holder["indices"] = show_marker_preview(markers)
            finally:
                result_holder["done"] = True

        dlg.run_on_main(show_preview)
        # Wait for the preview to close
        while not result_holder["done"] and not dlg._closing:
            time.sleep(0.1)
        if dlg._closing:
            return
        selected_idx = result_holder["indices"] or []
        if not selected_idx:
            dlg.update_all(100, "No markers selected")
            dlg.reenable()
            return
        selected = [markers[i] for i in selected_idx]

        dlg.update_all(88, f"🎯 Adding {len(selected)} markers...")
        added = apply_markers(tl, selected)
        extras = []

        if options["detect_fillers"]:
            dlg.update_all(90, "🪶 Scanning fillers...")
            fill = analyze_for_fillers(transcript)
            if fill:
                apply_markers(tl, fill)
                extras.append(f"{len(fill)} fillers")

        if options["export_subs"]:
            dlg.update_all(92, "💬 Exporting subtitles...")
            try:
                srt, _ = _export_subtitles(tl, transcript)
                extras.append(f"subs → {os.path.basename(srt)}")
            except Exception as e:
                extras.append(f"subs failed: {e}")

        if options["generate_chapters"]:
            dlg.update_all(94, "📚 Generating chapters...")
            try:
                cm, desc = generate_chapters(transcript)
                if cm:
                    apply_markers(tl, cm)
                    p = _save_description(tl, desc)
                    extras.append(f"{len(cm)} chapters → {os.path.basename(p)}")
            except Exception as e:
                extras.append(f"chapters failed: {e}")

        if options["create_shorts_timeline"]:
            dlg.update_all(96, "✂ Creating shorts timeline...")
            shorts = [m for m in selected if m.marker_type == MarkerType.SHORT_CLIP]
            if shorts:
                try:
                    new_tl = create_subclip_timeline(project, tl, shorts,
                                                    name=f"{tl.GetName()} - Shorts")
                    if new_tl:
                        extras.append(f"shorts tl ({len(shorts)} clips)")
                except Exception as e:
                    extras.append(f"shorts failed: {e}")

        if options["create_rough_cut"]:
            dlg.update_all(98, "✂ Building rough cut...")
            dead = [m for m in selected if m.marker_type == MarkerType.DEAD_AIR]
            if dead:
                try:
                    new_tl = create_rough_cut_timeline(project, tl, dead,
                                                      name=f"{tl.GetName()} - Rough Cut")
                    if new_tl:
                        extras.append("rough cut tl")
                except Exception as e:
                    extras.append(f"rough cut failed: {e}")

        elapsed = int(time.time() - start)
        suffix = " (" + ", ".join(extras) + ")" if extras else ""
        dlg.update_all(100, f"✅ Added {added} markers in {elapsed}s{suffix}")
        dlg.reenable()

    except Exception as e:
        import traceback
        traceback.print_exc()
        dlg.update_all(0, f"❌ {e}")
        dlg.reenable()


def main():
    """Main entry point — uses Tkinter for the UI (works in Resolve Free)."""
    resolve = get_resolve()
    if not resolve:
        print("Error: Could not connect to DaVinci Resolve")
        return

    from tk_ui import AssistantDialog

    # Timeline metadata for header
    _, timeline, err = get_current_timeline(resolve)
    if timeline:
        tl_name = timeline.GetName()
        duration = estimate_duration_minutes(timeline)
        cost = estimate_cost(duration).get("estimated_cost_usd", 0)
    else:
        tl_name = "(no timeline)"
        duration = 0
        cost = 0

    dlg = AssistantDialog(tl_name, duration, cost)

    def on_analyze():
        if not timeline:
            dlg.set_status("❌ No timeline open")
            dlg.reenable()
            return
        run_analysis_tk(resolve, timeline, dlg, dlg.options)

    def on_clear_all():
        from markers import clear_markers
        _, tl, err = get_current_timeline(resolve)
        if not tl:
            dlg.set_status("❌ No timeline")
            return
        removed = clear_markers(tl)
        dlg.set_status(f"🗑 Cleared {removed} markers")

    def on_clear_color():
        from markers import clear_markers
        from tk_ui import prompt_clear_color
        _, tl, err = get_current_timeline(resolve)
        if not tl:
            dlg.set_status("❌ No timeline")
            return

        # prompt_clear_color must run on main thread (Tk Toplevel)
        result = {"color": None, "done": False}
        def show():
            try:
                result["color"] = prompt_clear_color()
            finally:
                result["done"] = True
        dlg.run_on_main(show)
        # Wait briefly for the modal to return
        import time as _t
        while not result["done"]:
            _t.sleep(0.05)

        color = result["color"]
        if not color:
            dlg.set_status("Cancelled")
            return
        removed = clear_markers(tl, color)
        dlg.set_status(f"🗑 Cleared {removed} {color} markers")

    dlg.on_analyze(on_analyze)
    dlg.on_clear_all(on_clear_all)
    dlg.on_clear_color(on_clear_color)
    dlg.run()


if __name__ == "__main__":
    main()
