#!/usr/bin/env bash
set -euo pipefail

PORT="8081"

echo "1. Showing matching processes (before)"
ps aux | grep -E "python3 -m src\.main|livekit\.agents" | grep -v grep || true

echo "2. Killing 'python3 -m src.main' processes"
pkill -f "python3 -m src.main" || true

echo "3. Killing 'livekit.agents' processes"
pkill -f "livekit.agents" || true

echo "4. Checking who is listening on TCP port ${PORT}"
# Show listeners (your original command)
sudo lsof -iTCP:${PORT} -sTCP:LISTEN || true

echo "5. Extracting PIDs from lsof and force-killing them"
# Extract unique PIDs for listeners on the port
PIDS="$(sudo lsof -t -iTCP:${PORT} -sTCP:LISTEN 2>/dev/null | sort -u || true)"

if [[ -z "${PIDS}" ]]; then
  echo "No process is listening on port ${PORT}."
else
  echo "Found PID(s) listening on port ${PORT}: ${PIDS}"
  for pid in ${PIDS}; do
    echo "Killing PID ${pid}..."
    sudo kill -9 "${pid}" || true
  done
fi

echo "Done. Showing matching processes (after)"
ps aux | grep -E "python3 -m src\.main|livekit\.agents" | grep -v grep || true
