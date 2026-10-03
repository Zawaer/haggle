#!/usr/bin/env bash
# One-command start (works on a fresh Linux box, e.g. a Matrix OS cloud computer).
#   GEMINI_API_KEY=... scripts/run.sh            # web app on :3123
#   HAGGLE_MARKET_URL=http://localhost:3140 scripts/run.sh   # use the external mock marketplace
set -euo pipefail
cd "$(dirname "$0")/.."
# (re)install when requirements.txt changed, so `git pull && scripts/run.sh` always works
stamp=".venv/.req-$(cksum < requirements.txt | cut -d' ' -f1)"
if [ ! -f "$stamp" ]; then
  if command -v uv >/dev/null; then [ -x .venv/bin/python ] || uv venv -q .venv; uv pip install -q --python .venv/bin/python -r requirements.txt
  else [ -x .venv/bin/python ] || python3 -m venv .venv; .venv/bin/pip install -q -r requirements.txt; fi
  touch "$stamp"
fi
if [ -z "${GEMINI_API_KEY:-}" ] && [ ! -f .env ]; then echo "Set GEMINI_API_KEY or create .env" >&2; exit 1; fi
if [ -n "${HAGGLE_MARKET_URL:-}" ]; then .venv/bin/python seller_bot.py & fi
exec .venv/bin/uvicorn haggle.server:app --host 0.0.0.0 --port "${PORT:-3123}"
