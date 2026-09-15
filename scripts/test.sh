#!/bin/bash

set -e

echo "🧪 Running tests..."

# Backend tests
echo ""
echo "📋 Backend tests..."
cd packages/backend
source venv/bin/activate
pytest --cov=core --cov=api --cov=services
cd ../..

# Frontend tests
echo ""
echo "🎨 Frontend tests..."
cd packages/frontend
npm run test
cd ../..

echo ""
echo "✅ All tests passed!"
