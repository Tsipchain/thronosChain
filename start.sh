#!/usr/bin/env bash
set -e

echo "=== Starting Stratum server on TCP port 3333 ==="
python stratum_mini_server.py &    # ensure this listens on 3333
STRATUM_PID=$!

echo "=== Starting Flask app on HTTP port 8000 ==="
python server.py

echo "=== Stopping Stratum server (PID $STRATUM_PID) ==="
kill $STRATUM_PID
