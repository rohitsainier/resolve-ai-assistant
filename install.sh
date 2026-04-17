#!/bin/bash
#
# Install Resolve AI Assistant into DaVinci Resolve's Scripts folder.
#
# - macOS:  symlinks src/ai_edit_assistant.py into ~/Library/.../Edit/
# - Linux:  symlinks into ~/.local/share/DaVinciResolve/Fusion/Scripts/Edit/
# - Windows: prints manual instructions
#
# Symlink (not copy) so edits in this repo are picked up by Resolve immediately.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_FILE="$SCRIPT_DIR/src/ai_edit_assistant.py"

if [ ! -f "$SOURCE_FILE" ]; then
    echo "❌ Cannot find $SOURCE_FILE"
    exit 1
fi

# ---- Detect platform ---------------------------------------------------------
case "$(uname -s)" in
    Darwin)
        RESOLVE_SCRIPTS_DIR="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit"
        PLATFORM="macOS"
        ;;
    Linux)
        RESOLVE_SCRIPTS_DIR="$HOME/.local/share/DaVinciResolve/Fusion/Scripts/Edit"
        PLATFORM="Linux"
        ;;
    MINGW*|MSYS*|CYGWIN*)
        echo "⚠️  Windows detected. Please install manually:"
        echo ""
        echo "  Source: $SOURCE_FILE"
        echo "  Target: %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Edit\\AI Edit Assistant.py"
        echo ""
        echo "Then restart DaVinci Resolve."
        exit 0
        ;;
    *)
        echo "❌ Unsupported platform: $(uname -s)"
        exit 1
        ;;
esac

mkdir -p "$RESOLVE_SCRIPTS_DIR"
DEST="$RESOLVE_SCRIPTS_DIR/AI Edit Assistant.py"
SRC_PATH="$SCRIPT_DIR/src"

# Resolve 20 doesn't follow symlinks for script discovery, so we install a tiny
# launcher that runs the real module from the repo. Edits to source files take
# effect on the next script run with no reinstall needed.
rm -f "$DEST"
cat > "$DEST" <<EOF
#!/usr/bin/env python3
"""Launcher for AI Edit Assistant.

Uses exec() so Resolve-injected globals (fusion, bmd, app, etc.) propagate
into the real script's namespace.
"""
import sys, os

# Make DaVinciResolveScript importable from inside Resolve
RESOLVE_API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
RESOLVE_LIB = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
os.environ.setdefault("RESOLVE_SCRIPT_API", RESOLVE_API)
os.environ.setdefault("RESOLVE_SCRIPT_LIB", RESOLVE_LIB)
mods = os.path.join(RESOLVE_API, "Modules")
if mods not in sys.path:
    sys.path.insert(0, mods)

REPO_SRC = "$SRC_PATH"
if REPO_SRC not in sys.path:
    sys.path.insert(0, REPO_SRC)

SCRIPT_PATH = os.path.join(REPO_SRC, "ai_edit_assistant.py")
with open(SCRIPT_PATH, "rb") as f:
    src = f.read().decode("utf-8")
code = compile(src, SCRIPT_PATH, "exec")

g = globals().copy()
g["__file__"] = SCRIPT_PATH
g["__name__"] = "__main__"
exec(code, g)
EOF

echo "✅ Installed AI Edit Assistant ($PLATFORM)"
echo "   Launcher: $DEST"
echo "   Targets:  $SRC_PATH/ai_edit_assistant.py"
echo ""

# ---- Sanity-check Python deps ------------------------------------------------
PY_BIN="${RESOLVE_PY:-$(command -v python3 || true)}"

# Prefer the active conda env if one is active
if [ -n "$CONDA_PREFIX" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
    PY_BIN="$CONDA_PREFIX/bin/python"
fi

if [ -n "$PY_BIN" ] && [ -x "$PY_BIN" ]; then
    echo "🔍 Checking Python deps with: $PY_BIN"
    MISSING=$("$PY_BIN" - <<'PY'
import importlib, sys
missing = []
for mod in ("whisper", "anthropic", "openai"):
    try:
        importlib.import_module(mod)
    except Exception:
        missing.append(mod)
print(",".join(missing))
PY
)
    if [ -n "$MISSING" ]; then
        echo "   ⚠️  Missing: $MISSING"
        echo "   Run: $PY_BIN -m pip install -r $SCRIPT_DIR/requirements.txt"
    else
        echo "   ✅ whisper, anthropic, openai all importable"
    fi

    if ! command -v ffmpeg >/dev/null 2>&1; then
        echo "   ⚠️  ffmpeg not on PATH. Install with: brew install ffmpeg"
    else
        echo "   ✅ ffmpeg: $(ffmpeg -version | head -n1)"
    fi
else
    echo "⚠️  No python3 found; skipping dep check."
fi

echo ""

# ---- API key hint ------------------------------------------------------------
ENV_DIR="$HOME/.resolve-ai-assistant"
ENV_FILE="$ENV_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    mkdir -p "$ENV_DIR"
    cat > "$ENV_FILE" <<'EOF'
# AI Edit Assistant environment.
# Set ONE of these (whichever provider you use). The app auto-detects.

# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...

# Force a specific provider when both keys are set:
# AI_PROVIDER=openai

# Optional model overrides:
# OPENAI_MODEL=gpt-4o
# CLAUDE_MODEL=claude-sonnet-4-6
EOF
    chmod 600 "$ENV_FILE"
    echo "📝 Created template at: $ENV_FILE"
    echo "   Edit it and add your API key."
else
    echo "📝 Existing env file: $ENV_FILE"
fi

echo ""
echo "Next steps:"
echo "  1. Add your API key to $ENV_FILE"
if [ "$PLATFORM" = "macOS" ]; then
    if [ -n "$CONDA_PREFIX" ]; then
        echo "  2. Resolve → Preferences → System → General → set Python install to:"
        echo "       $CONDA_PREFIX/bin/python"
    else
        echo "  2. Resolve → Preferences → System → General → set Python install"
        echo "       (point at python3 with whisper/anthropic/openai installed)"
    fi
fi
echo "  3. Quit Resolve fully (Cmd+Q) and reopen"
echo "  4. Workspace → Scripts → Edit → AI Edit Assistant"
