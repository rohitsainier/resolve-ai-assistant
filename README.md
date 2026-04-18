# Resolve AI Assistant

AI-powered editing assistant for DaVinci Resolve. Browser-based UI that transcribes your timeline, analyzes it with Claude or OpenAI, and edits the timeline for you — markers, rough cuts, shorts timelines, chapter generation, subtitle export, and natural-language prompt editing.

## Features

### In-Resolve UI (modern, browser-based)
- **Unified dashboard** with tabs — runs in your default browser, served by a tiny local server
- **Live progress** with real-time status + progress bar
- **Marker preview** in a modal — select which markers to apply before they're added

### Analysis
- **Auto-markers** — highlights (green), dead air (red), short clips (blue), chapter markers (yellow)
- **Filler-word detection** at the word level — finds every "um / uh / like / you know"
- **Chapter markers + YouTube description** — one click produces chapters and a ready-to-paste description
- **Subtitle export** — writes `.srt` and `.vtt` files for the timeline

### Timeline rebuilding
- **Rough-cut generation** — new timeline with all detected dead-air regions removed
- **Shorts timeline** — new timeline containing the short-worthy segments, concatenated

### Prompt-based editing 💬
- **Chat with your timeline** — type "Mark every time I mention AI" or "Make a shorts timeline of the best 60 seconds" and the LLM plans + executes the edit via your transcript

### Marker management
- **Clear all** or **clear by color** — pick any of 15 Resolve marker colors

### Smart caching
- Transcript cache keyed on per-clip identity + in/out points, so reordering/trimming invalidates the cache automatically

### Provider-agnostic
- Uses **Claude** (`claude-sonnet-4-6` default) or **OpenAI** (`gpt-4o` default) — auto-detects based on which API key is set, or force one with `AI_PROVIDER`

## Marker Colors

| Color | Meaning |
|-------|---------|
| 🟢 Green | Highlight - keep this |
| 🔴 Red | Dead air or filler - cut this |
| 🔵 Blue | Potential short clip |
| 🟡 Yellow | Chapter marker (review) |

## Requirements

### Software
- **DaVinci Resolve 20** (Free or Studio) — note: the Mac **App Store version is NOT supported** (sandboxing blocks script-level file/process access). Download from [blackmagicdesign.com](https://www.blackmagicdesign.com/products/davinciresolve) directly.
- **Python 3.11** from [python.org](https://www.python.org/downloads/macos/) — Resolve 20 only accepts Python from the official python.org framework installer (not conda, Homebrew, or system Python).
- **ffmpeg** (for audio extraction)

### API Key (pick one)
- **Anthropic API key** (default), OR
- **OpenAI API key** — the app auto-switches based on which key you set

## Installation (macOS)

### 1. Install Python 3.11 (python.org)

Download the macOS 64-bit universal2 installer from https://www.python.org/downloads/macos/ and run the .pkg. Installs to `/Library/Frameworks/Python.framework/Versions/3.11/`.

### 2. Install ffmpeg

```bash
brew install ffmpeg
```

### 3. Clone & install Python dependencies

Install into the **python.org Python 3.11** (this is what Resolve uses):

```bash
git clone https://github.com/<your-fork>/resolve-ai-assistant.git
cd resolve-ai-assistant

/Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
  -m pip install -r requirements.txt
```

(If you also want CLI usage from a conda env, install into that too — see "CLI usage" below.)

### 4. Set up an API key

Create an env file — the app will auto-load it on launch regardless of how Resolve is started:

```bash
mkdir -p ~/.resolve-ai-assistant
cat > ~/.resolve-ai-assistant/.env <<'EOF'
OPENAI_API_KEY=sk-...
# or: ANTHROPIC_API_KEY=sk-ant-...
# AI_PROVIDER=openai           # force if both keys are set
EOF
chmod 600 ~/.resolve-ai-assistant/.env
```

Alternative: set as a shell env var (`export OPENAI_API_KEY=...`), but this only works if you launch Resolve from that same shell via `open -a "DaVinci Resolve"`.

### 5. Install to DaVinci Resolve

```bash
./install.sh
```

This drops a tiny launcher at `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit/AI Edit Assistant.py` that runs the real module from your repo (edits to source files take effect on the next run — no reinstall needed).

### 6. Restart Resolve

Cmd+Q, relaunch.

## Usage

1. Open DaVinci Resolve, load a project with a timeline
2. **Workspace → Scripts → Edit → AI Edit Assistant**
3. Your default browser opens to `http://127.0.0.1:<port>` with the UI
4. Three tabs:
   - **🔍 Analyze** — checkboxes for markers + timeline operations, click Analyze, review, apply
   - **💬 Prompt** — chat-style: describe what you want, LLM plans + executes
   - **🗑 Markers** — clear all / clear by color
5. Close the browser tab when done; the server stops when you quit Resolve

The HTML page can also be opened on another device on your LAN (server binds to 127.0.0.1 by default for safety).

## CLI Usage

Great for batch jobs — runs outside Resolve, uses any Python env.

```bash
# Set up a conda env (any env with the deps works)
conda create -n resolve-ai python=3.11 -y
conda activate resolve-ai
conda install -c conda-forge ffmpeg -y
pip install -r requirements.txt

export OPENAI_API_KEY="sk-..."   # or ANTHROPIC_API_KEY

# Transcribe a video
python src/cli.py transcribe video.mp4 --model base

# Analyze (fillers + chapters optional)
python src/cli.py analyze -v video.mp4 -o markers.json --fillers --chapters

# Export subtitles
python src/cli.py subtitles video.mp4 -o my_subs

# Apply existing markers.json to the open Resolve timeline
python src/cli.py apply markers.json

# Build a rough cut in Resolve
python src/cli.py rough-cut markers.json --name "My Rough Cut"

# Build a shorts timeline
python src/cli.py shorts-timeline markers.json --name "Shorts"
```

### Choosing the model

Defaults: Anthropic → `claude-sonnet-4-6`, OpenAI → `gpt-4o`. Override:

```bash
export CLAUDE_MODEL="claude-opus-4-6"    # higher quality, higher cost
export OPENAI_MODEL="gpt-4o-mini"        # cheaper / faster
```

## Output files

Subtitles, descriptions, and other artifacts written from the UI land in:

```
~/.resolve-ai-assistant/exports/
```

Transcript cache:

```
~/.resolve-ai-assistant/cache/
```

Diagnostic logs (in case something misbehaves):

```
~/.resolve-ai-assistant/whisper.log
~/.resolve-ai-assistant/prompt.log
```

## Troubleshooting

### "Python 3 was not found" in Resolve
You're missing the python.org installer. See step 1 above. Conda / Homebrew / system Python do not satisfy Resolve 20's detection.

### The in-Resolve menu shows "No Scripts" / doesn't show the script
You may be running the Mac App Store version (bundle id `com.blackmagic-design.DaVinciResolveLite`) which is sandboxed. Install the regular free Resolve from blackmagicdesign.com directly.

### "ffmpeg not found" / transcription hangs
Resolve's Python doesn't inherit your shell PATH. Install ffmpeg somewhere the code can find it (`/opt/homebrew/bin/ffmpeg`, `/usr/local/bin/ffmpeg`) or set:
```bash
export FFMPEG_BIN=/full/path/to/ffmpeg
```

### Markers land at wrong timecodes
Fixed in current version — `AddMarker` takes the offset from timeline start, not the absolute frame.

### "Address already in use"
A previous run of the server is still up. Quit Resolve fully (Cmd+Q) and relaunch.

## Known Limitations

- **Rough cut** rebuilds the timeline from source media; per-clip color/effects/speed are not preserved
- **Filler-word detection** requires Whisper word-level timestamps (any model works; tiny is fastest)
- **Chapter generation** does an extra LLM call (~$0.01 per 10-minute video)
- Prompt mode currently uses single-shot generation — a future version will support iterative tool-use for multi-step plans

## License

MIT
