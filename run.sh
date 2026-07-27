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
    echo "ERROR: BARK_BOT_TOKEN not set. Create a .env file or export it."
    echo "  echo 'BARK_BOT_TOKEN=your_token_here' > .env"
    exit 1
fi

echo "Bark v$(python -c 'import __init__; print(__init__.__version__)') — starting..."
echo "Dashboard: ${BARK_PUBLIC_URL:-https://bark.warx.org}"
echo "Press Ctrl+C to stop"
echo ""

# Loop for auto-restart on crash
while true; do
    python app.py --dev
    EXIT_CODE=$?
    echo "Bark exited with code $EXIT_CODE"
    if [ $EXIT_CODE -eq 0 ]; then
        echo "Clean exit. Stopped."
        break
    fi
    echo "Restarting in 3 seconds..."
    sleep 3
done
