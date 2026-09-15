#!/bin/bash

set -e

echo "🚀 Setting up TaxAssistant monorepo..."

# Frontend setup
echo "📦 Setting up frontend..."
cd packages/frontend
npm install
cd ../..

# Backend setup
echo "🐍 Setting up backend..."
cd packages/backend
/usr/local/opt/python@3.12/bin/python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
cd ../..

echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Add OPENROUTER_API_KEY to packages/backend/.env"
echo "2. Initialize knowledge base: ./scripts/ingest-kb.sh"
echo "3. Run: npm run dev"
