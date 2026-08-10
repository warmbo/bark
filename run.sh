#!/bin/bash
# Bark development launcher — starts bot + dashboard with auto-restart
# Usage: ./run.sh

set -e

cd "$(dirname "$0")"
source .venv/bin/activate

# Load .env if present
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Explicitly set dashboard host to 0.0.0.0 for LAN access
export BARK_DASHBOARD_HOST="${BARK_DASHBOARD_HOST:-0.0.0.0}"
export BARK_DASHBOARD_PORT="${BARK_DASHBOARD_PORT:-8090}"

if [ -z "$BARK_BOT_TOKEN" ]; then
    if [ -f .env ]; then
        echo "ERROR: .env exists but BARK_BOT_TOKEN is empty."
        exit 1
    fi
    echo "First-time setup — starting the setup wizard (no .env needed)."
    echo "Open http://localhost:${BARK_DASHBOARD_PORT}/setup in your browser"
    python app.py
    echo "Setup wizard exited. Restarting Bark with your configuration..."
    exec ./run.sh
fi

echo "Bark v$(python -c 'from bark_version import __version__; print(__version__)') — starting..."
echo "Dashboard: ${BARK_PUBLIC_URL:-http://127.0.0.1:8090}"
echo "Press Ctrl+C to stop"
echo ""

# Loop for auto-restart on crash
while true; do
    python app.py
    EXIT_CODE=$?
    echo "Bark exited with code $EXIT_CODE"
    if [ $EXIT_CODE -eq 0 ]; then
        echo "Clean exit. Stopped."
        break
    fi
    echo "Restarting in 3 seconds..."
    sleep 3
done
