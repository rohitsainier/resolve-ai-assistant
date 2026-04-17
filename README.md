# Resolve AI Assistant

AI-powered editing assistant for DaVinci Resolve. Analyzes your timeline, adds markers for highlights and cuts, extracts shorts, and generates rough cuts.

## Features

- **Auto-markers**: Transcribes video, identifies highlights and dead air, adds color-coded markers to timeline
- **Shorts extraction**: Finds the best 60-90 second clips for vertical video and **builds a separate Shorts timeline automatically**
- **Rough-cut generation**: Builds a new timeline with all detected dead-air regions removed
- **Filler-word detection**: Word-level timing finds every "um / uh / like / you know" so they show up as red markers (or get removed by the rough cut)
- **Chapter markers + YouTube description**: One click produces chapter markers and writes a ready-to-paste description file
- **Subtitle export**: One click writes `.srt` and `.vtt` files for the timeline
- **Preview before apply**: Review and approve/reject markers before they're added
- **Smart transcript caching**: Cache key includes per-clip identity + in/out points, so reordering or trimming clips invalidates the cache automatically
- **Live progress**: Whisper progress is reported in real-time inside Resolve
- **Clear by color**: Pick any marker color and remove just those markers
- **In-app UI**: Runs directly from Resolve's Scripts menu

## Marker Colors

| Color | Meaning |
|-------|---------|
| 🟢 Green | Highlight - keep this |
| 🔴 Red | Dead air or filler - cut this |
| 🔵 Blue | Potential short clip |
| 🟡 Yellow | Chapter marker (review) |

## Requirements

### Software
- **DaVinci Resolve 18+** (Free or Studio)
- **Python 3.10+**
- **ffmpeg** (for audio extraction)

### API Key (pick one)
- **Anthropic API key** (default), OR
- **OpenAI API key** — set `OPENAI_API_KEY` and the app auto-switches

## Installation

### 1. Install ffmpeg

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt update && sudo apt install ffmpeg
```

**Windows:**
```bash
# Using Chocolatey
choco install ffmpeg

# Or download from https://ffmpeg.org/download.html
# Add to PATH
```

### 2. Clone and install dependencies

```bash
git clone https://github.com/Kilo-Loco/resolve-ai-assistant.git
cd resolve-ai-assistant

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Set up an API key

Pick whichever provider you already have credit with.

**Anthropic Claude (default):**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```
Get a key at [console.anthropic.com](https://console.anthropic.com).

**OpenAI:**
```bash
export OPENAI_API_KEY="sk-..."
```
Get a key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys).

The app auto-detects which key you've set. If you have both, force one with:
```bash
export AI_PROVIDER=openai     # or "anthropic"
```

**Or use a .env file:**

The app auto-loads `.env` from these locations (first match wins, real env vars always win):

1. `~/.resolve-ai-assistant/.env`  ← **recommended for the in-Resolve script**
2. `<repo>/.env`
3. `./.env`

```bash
# Recommended for in-Resolve usage (Resolve doesn't see your shell env)
mkdir -p ~/.resolve-ai-assistant
cat > ~/.resolve-ai-assistant/.env <<'EOF'
OPENAI_API_KEY=sk-...
# AI_PROVIDER=openai
EOF
```

### 4. Install to DaVinci Resolve

**macOS:**
```bash
./install.sh
```

**Windows (manual):**
```
Copy src/ai_edit_assistant.py to:
%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Edit\AI Edit Assistant.py
```

**Linux (manual):**
```
Copy src/ai_edit_assistant.py to:
~/.local/share/DaVinciResolve/Fusion/Scripts/Edit/AI Edit Assistant.py
```

### 5. Enable external scripting in Resolve

1. Open DaVinci Resolve
2. Go to **Preferences** → **System** → **General**
3. Set **External scripting using** to **Local** (or Network if needed)
4. Restart DaVinci Resolve

## Usage

1. Open DaVinci Resolve
2. Import your video and create a timeline
3. Go to **Workspace → Scripts → Edit → AI Edit Assistant**
4. Select your options:
   - Whisper model (tiny=fast, large=accurate)
   - What to find (highlights, dead air, shorts)
5. Click **Analyze**
6. Review markers in the preview window
7. Click **Apply Selected**

## CLI Usage

You can also use the command-line interface:

```bash
# Activate virtual environment
source venv/bin/activate

# Transcribe a video
python src/cli.py transcribe video.mp4 --model base

# Analyze and generate markers (now supports fillers + chapters)
python src/cli.py analyze -v video.mp4 -o markers.json --fillers --chapters

# Apply markers to Resolve (Resolve must be open)
python src/cli.py apply markers.json

# Export subtitles from a video or saved transcript
python src/cli.py subtitles video.mp4 -o my_subs

# Build a "dead air removed" rough cut into Resolve
python src/cli.py rough-cut markers.json --name "My Rough Cut"

# Build a shorts timeline from SHORT_CLIP markers
python src/cli.py shorts-timeline markers.json --name "Shorts"
```

### Choosing the model

Default models:
- Anthropic → `claude-sonnet-4-6`
- OpenAI → `gpt-4o`

Override with:
```bash
export CLAUDE_MODEL="claude-opus-4-6"     # higher quality, higher cost
export OPENAI_MODEL="gpt-4o-mini"         # cheaper / faster
```

### Output files

Subtitles, descriptions, and other artifacts written from the in-app UI land in:

```
~/.resolve-ai-assistant/exports/
```

## Troubleshooting

### "No module named 'anthropic'"
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### "ANTHROPIC_API_KEY not set"
```bash
export ANTHROPIC_API_KEY="your-key-here"
```

### Script not appearing in Resolve
- Make sure you ran `./install.sh` (macOS) or copied the file manually
- Restart DaVinci Resolve completely
- Check that external scripting is enabled in Preferences

### First run is slow
- Whisper downloads the model on first use (~150MB for "base")
- Subsequent runs use the cached model
- Use "tiny" model for faster (less accurate) transcription

### ffmpeg errors
```bash
# Verify ffmpeg is installed
ffmpeg -version

# If not found, install it (see Installation section)
```

## Known Limitations

- Rough-cut generation rebuilds the timeline from the source media; per-clip color/effects/speed are not yet preserved
- Filler-word detection requires the `tiny` model or larger (uses Whisper word-level timestamps)
- Chapter generation does an extra Claude call (~$0.01 per 10-minute video)

## License

MIT
