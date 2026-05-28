#!/bin/sh
set -e

echo ""
echo "=== Starting Frontend ==="

node server.js &
NODE_PID=$!

until curl -sf http://localhost:3000 > /dev/null 2>&1; do
  sleep 0.5
done

echo "✓ Frontend health check: OK"
echo "✓ Frontend (UI) is accessible on host at http://localhost:3000"
echo ""

wait $NODE_PID
