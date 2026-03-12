#!/bin/zsh
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if [ -x ".venv/bin/python" ]; then
  .venv/bin/python jklm_local_server.py
else
  python3 jklm_local_server.py
fi
