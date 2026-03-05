#!/bin/bash

# Install Resolve AI Assistant to DaVinci Resolve Scripts folder

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOLVE_SCRIPTS_DIR="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Edit"

# Create directory if it doesn't exist
mkdir -p "$RESOLVE_SCRIPTS_DIR"

# Create symlink to our script
ln -sf "$SCRIPT_DIR/src/ai_edit_assistant.py" "$RESOLVE_SCRIPTS_DIR/AI Edit Assistant.py"

echo "✅ Installed AI Edit Assistant to DaVinci Resolve"
echo "   Restart Resolve, then find it under: Workspace → Scripts → Edit → AI Edit Assistant"
