#!/bin/bash

echo "🚀 Starting TaxAssistant development server..."
echo ""
echo "Frontend: http://localhost:3000"
echo "Backend:  http://localhost:8000"
echo "API Docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

# Check if we can use tmux (better UX)
if command -v tmux &> /dev/null; then
  SESSION_NAME="tax-assistant"

  # Kill existing session if any
  tmux kill-session -t $SESSION_NAME 2>/dev/null || true

  # Create new session
  tmux new-session -d -s $SESSION_NAME -x 120 -y 40

  # Split into two windows
  tmux send-keys -t $SESSION_NAME "cd packages/backend && source venv/bin/activate && uvicorn main:app --reload --port 8000" C-m
  tmux new-window -t $SESSION_NAME -n frontend
  tmux send-keys -t $SESSION_NAME:frontend "cd packages/frontend && npm run dev" C-m

  # Select frontend window
  tmux select-window -t $SESSION_NAME:frontend

  # Attach to session
  tmux attach-session -t $SESSION_NAME
else
  # Fallback: run both in background and show instructions
  echo "Running backend and frontend..."
  echo ""

  # Start backend
  (cd packages/backend && source venv/bin/activate && uvicorn main:app --reload --port 8000) &
  BACKEND_PID=$!

  # Wait a second for backend to start
  sleep 2

  # Start frontend
  (cd packages/frontend && npm run dev) &
  FRONTEND_PID=$!

  # Trap Ctrl+C to kill both processes
  trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT

  # Wait for both processes
  wait
fi
