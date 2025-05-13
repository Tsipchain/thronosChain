#!/usr/bin/env bash
set -e

echo "=== Starting Stratum server on TCP port 433 ==="
python stratum_mini_server.py &          # τρέχει Stratum background
STRATUM_PID=$!

echo "=== Starting Flask app on HTTP port 8000 ==="
python server.py                         # τρέχει Flask

echo "=== Stopping Stratum server (PID $STRATUM_PID) ==="
kill $STRATUM_PID                        # καθαρίζει στο τέλος
