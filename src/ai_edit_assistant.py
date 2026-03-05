#!/usr/bin/env python3
"""
AI Edit Assistant for DaVinci Resolve
Analyzes timeline, adds markers, extracts shorts, generates rough cuts.
"""

import sys
import os

# Add our modules to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# DaVinci Resolve scripting setup
def get_resolve():
    """Get the Resolve application object."""
    try:
        import DaVinciResolveScript as dvr
        return dvr.scriptapp("Resolve")
    except ImportError:
        # Set up environment for external execution
        if sys.platform == "darwin":
            script_api = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
            script_lib = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
        else:
            raise RuntimeError("Unsupported platform")
        
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


def add_marker(timeline, frame, color, name, note=""):
    """Add a marker to the timeline at the specified frame."""
    # Marker colors: Blue, Cyan, Green, Yellow, Red, Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream
    timeline.AddMarker(frame, color, name, note, 1)


def create_ui(resolve, fusion):
    """Create the UI dialog for the assistant."""
    ui = fusion.UIManager
    disp = ui.UIDispatcher(fusion)
    
    # Window definition
    win = disp.AddWindow({
        "ID": "AIEditAssistant",
        "WindowTitle": "AI Edit Assistant",
        "Geometry": [100, 100, 400, 350],
    }, [
        ui.VGroup({"Spacing": 10}, [
            # Header
            ui.Label({
                "ID": "Header",
                "Text": "🎬 AI Edit Assistant",
                "Alignment": {"AlignHCenter": True},
                "Font": ui.Font({"PixelSize": 18, "Bold": True}),
            }),
            
            ui.HGroup([
                ui.Label({"Text": "Timeline:", "Weight": 0.3}),
                ui.Label({"ID": "TimelineName", "Text": "(none)", "Weight": 0.7}),
            ]),
            
            ui.VGap(10),
            
            # Options
            ui.Label({"Text": "Analysis Options:", "Font": ui.Font({"Bold": True})}),
            
            ui.CheckBox({"ID": "AddHighlights", "Text": "Add highlight markers (green)", "Checked": True}),
            ui.CheckBox({"ID": "MarkDeadAir", "Text": "Mark dead air for removal (red)", "Checked": True}),
            ui.CheckBox({"ID": "FindShorts", "Text": "Identify potential shorts (blue)", "Checked": True}),
            
            ui.VGap(10),
            
            ui.Label({"Text": "Actions:", "Font": ui.Font({"Bold": True})}),
            
            ui.CheckBox({"ID": "CreateShortsTimeline", "Text": "Create separate Shorts timeline", "Checked": False}),
            ui.CheckBox({"ID": "CreateRoughCut", "Text": "Generate rough cut (remove dead air)", "Checked": False}),
            
            ui.VGap(10),
            
            # Status
            ui.Label({"ID": "Status", "Text": "", "Alignment": {"AlignHCenter": True}}),
            
            # Progress
            ui.ProgressBar({"ID": "Progress", "Value": 0, "Maximum": 100}),
            
            ui.VGap(10),
            
            # Buttons
            ui.HGroup([
                ui.Button({"ID": "Analyze", "Text": "🔍 Analyze", "Weight": 0.5}),
                ui.Button({"ID": "Cancel", "Text": "Cancel", "Weight": 0.5}),
            ]),
        ]),
    ])
    
    return win, disp


def on_analyze(resolve, win, items):
    """Handle the Analyze button click."""
    from transcribe import transcribe_timeline_audio
    from analyze import analyze_transcript
    from markers import apply_markers
    
    project, timeline, err = get_current_timeline(resolve)
    if err:
        items["Status"].Text = f"❌ {err}"
        return
    
    items["Status"].Text = "📝 Extracting audio..."
    items["Progress"].Value = 10
    
    # Get timeline video path
    # For now, we'll use a workaround - export audio or get media path
    # This is a simplified version
    
    try:
        # Step 1: Get audio from timeline
        items["Status"].Text = "🎤 Transcribing audio..."
        items["Progress"].Value = 30
        
        transcript = transcribe_timeline_audio(timeline)
        
        # Step 2: Analyze with AI
        items["Status"].Text = "🧠 Analyzing content..."
        items["Progress"].Value = 60
        
        options = {
            "add_highlights": items["AddHighlights"].Checked,
            "mark_dead_air": items["MarkDeadAir"].Checked,
            "find_shorts": items["FindShorts"].Checked,
        }
        
        markers = analyze_transcript(transcript, options)
        
        # Step 3: Apply markers
        items["Status"].Text = "🎯 Adding markers..."
        items["Progress"].Value = 80
        
        apply_markers(timeline, markers)
        
        # Step 4: Create additional timelines if requested
        if items["CreateShortsTimeline"].Checked:
            items["Status"].Text = "✂️ Creating shorts timeline..."
            items["Progress"].Value = 90
            # create_shorts_timeline(project, timeline, markers)
        
        items["Status"].Text = f"✅ Done! Added {len(markers)} markers"
        items["Progress"].Value = 100
        
    except Exception as e:
        items["Status"].Text = f"❌ Error: {str(e)}"
        items["Progress"].Value = 0


def main():
    """Main entry point."""
    resolve = get_resolve()
    if not resolve:
        print("Error: Could not connect to DaVinci Resolve")
        return
    
    fusion = resolve.Fusion()
    
    # Update timeline name in UI
    project, timeline, err = get_current_timeline(resolve)
    
    win, disp = create_ui(resolve, fusion)
    items = win.GetItems()
    
    if timeline:
        items["TimelineName"].Text = timeline.GetName()
    else:
        items["TimelineName"].Text = "(no timeline)"
    
    # Event handlers
    def on_close(ev):
        disp.ExitLoop()
    
    def on_analyze_click(ev):
        on_analyze(resolve, win, items)
    
    def on_cancel_click(ev):
        disp.ExitLoop()
    
    win.On.AIEditAssistant.Close = on_close
    win.On.Analyze.Clicked = on_analyze_click
    win.On.Cancel.Clicked = on_cancel_click
    
    win.Show()
    disp.RunLoop()
    win.Hide()


if __name__ == "__main__":
    main()
