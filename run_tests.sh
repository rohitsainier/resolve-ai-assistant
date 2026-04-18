#!/bin/bash
#
# Run the full test suite.
#
# Tries, in order:
#   1. The python.org Python at /Library/Frameworks/... (used in Resolve)
#   2. Active conda env
#   3. System python3
#
# Usage:
#   ./run_tests.sh              # run everything
#   ./run_tests.sh tests/test_profiles.py   # run one file
#   ./run_tests.sh -k filler    # run matching tests only
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Pick the most likely Python with our deps installed
if [ -x "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" ]; then
    PY="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
elif [ -n "$CONDA_PREFIX" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
    PY="$CONDA_PREFIX/bin/python"
else
    PY="$(command -v python3)"
fi

if [ -z "$PY" ]; then
    echo "❌ No python3 found"
    exit 1
fi

echo "Running with: $PY"

# Check pytest is installed
if ! "$PY" -c "import pytest" 2>/dev/null; then
    echo "⚠  pytest not installed; installing now..."
    "$PY" -m pip install --quiet pytest pytest-mock
fi

cd "$SCRIPT_DIR"
exec "$PY" -m pytest "$@"
