#!/usr/bin/env bash
# Starts both halves of the web app (Mac and Linux; on Windows use START.bat).
#   API  http://127.0.0.1:8790   Python, does the work
#   UI   http://localhost:3000   Next.js, what you look at
set -euo pipefail
# This file lives in scripts/, and app/ and api/ are one level up.
cd "$(dirname "$0")/.."

# macOS ships python3 and no python.
PY=$(command -v python3 || command -v python) || { echo "Python is not installed: https://python.org"; exit 1; }
command -v node >/dev/null || { echo "Node.js is not installed: https://nodejs.org"; exit 1; }

# The API's packages are separate from the command line's, and nothing
# installed them before.
"$PY" -c "import fastapi, uvicorn" 2>/dev/null || "$PY" -m pip install -q -r api/requirements.txt
[ -d app/node_modules ] || (cd app && npm install)

"$PY" -m uvicorn api.main:app --host 127.0.0.1 --port 8790 &
API=$!
(cd app && npm run dev) &
UI=$!

# Stop both together, so Ctrl+C does not leave a server behind.
trap 'kill $API $UI 2>/dev/null || true' EXIT INT TERM
echo
echo "  App:  http://localhost:3000"
echo "  Ctrl+C to stop."
wait
