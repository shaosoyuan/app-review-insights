#!/usr/bin/env bash
# Run script for App Review Insights
# Usage: ./run.sh [port]

set -e

PORT=${1:-8000}

echo "============================================"
echo "  App Review Insights - Starting Server"
echo "============================================"
echo ""

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null || true
fi

# Check if dependencies are installed
echo "Checking dependencies..."
pip install -q -r backend/requirements.txt 2>/dev/null

# Check for .env file
if [ ! -f ".env" ]; then
    echo "Note: No .env file found. Running in fallback mode (no LLM)."
    echo "      Copy .env.example to .env and add your API key for full functionality."
    echo ""
fi

echo "Starting server on port $PORT..."
echo "Open http://localhost:$PORT/app in your browser"
echo ""

# Start the server
exec uvicorn backend.main:app --host 0.0.0.0 --port "$PORT" --reload
