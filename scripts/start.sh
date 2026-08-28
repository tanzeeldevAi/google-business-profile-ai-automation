#!/usr/bin/env bash
# Starts both halves of the web app (Mac and Linux; on Windows use START.bat).
#   API  http://127.0.0.1:8790   Python, does the work
#   UI   http://localhost:3000   Next.js, what you look at
set -euo pipefail
cd "$(dirname "$0")"

command -v node >/dev/null || { echo "Node.js is not installed: https://nodejs.org"; exit 1; }
[ -d app/node_modules ] || (cd app && npm install)

python -m uvicorn api.main:app --host 127.0.0.1 --port 8790 &
API=$!
(cd app && npm run dev) &
UI=$!

# Stop both together, so Ctrl+C does not leave a server behind.
trap 'kill $API $UI 2>/dev/null || true' EXIT INT TERM
echo
echo "  App:  http://localhost:3000"
echo "  Ctrl+C to stop."
wait
