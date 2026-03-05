# Resolve AI Assistant

AI-powered editing assistant for DaVinci Resolve. Analyzes your timeline, adds markers for highlights and cuts, extracts shorts, and generates rough cuts.

## Features

- **Auto-markers**: Transcribes video, identifies highlights and dead air, adds markers to timeline
- **Shorts extraction**: Finds the best 60-90 second clips for vertical video
- **Rough cut**: Removes silence and filler, creates a clean timeline
- **In-app UI**: Runs directly from Resolve's Scripts menu

## Requirements

- DaVinci Resolve 18+ (Free or Studio)
- Python 3.10+
- ffmpeg (for audio extraction)
- OpenAI Whisper (for transcription)

## Installation

```bash
# Clone the repo
git clone https://github.com/Kilo-Loco/resolve-ai-assistant.git
cd resolve-ai-assistant

# Install dependencies
pip install -r requirements.txt

# Install to DaVinci Resolve Scripts folder
./install.sh
```

## Usage

1. Open DaVinci Resolve
2. Import your video and create a timeline
3. Go to **Workspace → Scripts → Edit → AI Edit Assistant**
4. Select your options and click **Analyze**
5. Markers appear on your timeline

## Marker Colors

- 🟢 **Green**: Highlight - keep this
- 🔴 **Red**: Dead air - cut this  
- 🔵 **Blue**: Potential short clip
- 🟡 **Yellow**: Needs review

## License

MIT
