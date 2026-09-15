#!/bin/bash

set -e

echo "📚 Initializing Knowledge Base..."

# Navigate to backend
cd "$(dirname "$0")/../packages/backend"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Run ./scripts/setup.sh first"
    exit 1
fi

# Activate venv
source venv/bin/activate

# Check if OPENROUTER_API_KEY is set
if [ -z "$OPENROUTER_API_KEY" ] && ! grep -q "OPENROUTER_API_KEY=" .env; then
    echo "⚠️  OPENROUTER_API_KEY not found in .env"
    echo "Please add your API key to packages/backend/.env and run this script again"
    exit 1
fi

# Run ingestion
echo "⏳ Ingesting documents (this may take a few minutes)..."
python ingest.py --reset

echo "✅ Knowledge base ready!"
echo ""
echo "Run the development servers:"
echo "  npm run dev"
