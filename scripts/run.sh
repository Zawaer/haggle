#!/usr/bin/env bash
# One-command start (works on a fresh Linux box, e.g. a Matrix OS cloud computer).
#   GEMINI_API_KEY=... scripts/run.sh            # web app on :3123
#   HAGGLE_MARKET_URL=http://localhost:3140 scripts/run.sh   # use the external mock marketplace
set -euo pipefail
cd "$(dirname "$0")/.."
# (re)install when requirements.lock changed, so `git pull && scripts/run.sh` always works
stamp=".venv/.req-$(cksum < requirements.lock | cut -d' ' -f1)"
if [ ! -f "$stamp" ]; then
  if command -v uv >/dev/null; then [ -x .venv/bin/python ] || uv venv -q .venv; uv pip install -q --python .venv/bin/python -r requirements.lock
  else [ -x .venv/bin/python ] || python3 -m venv .venv; .venv/bin/pip install -q -r requirements.lock; fi
  touch "$stamp"
fi
if [ -z "${GEMINI_API_KEY:-}" ] && [ ! -f .env ]; then echo "Set GEMINI_API_KEY or create .env" >&2; exit 1; fi
if [ -n "${HAGGLE_MARKET_URL:-}" ]; then .venv/bin/python seller_bot.py & fi

if [ "${HAGGLE_AUTOPULL:-}" = "1" ]; then
  # Dev mode: follow the repo. Pull every 20 s; uvicorn --reload restarts on engine changes (this wipes
  # in-progress hunts, so don't use it for the real demo). UI changes need only a browser refresh.
  echo "autopull: following origin every 20 s (Ctrl+C stops everything)"
  ( while sleep 20; do
      out=$(git pull --ff-only -q 2>&1) || echo "autopull: $out"
      stamp=".venv/.req-$(cksum < requirements.lock | cut -d' ' -f1)"
      if [ ! -f "$stamp" ]; then
        if command -v uv >/dev/null; then uv pip install -q --python .venv/bin/python -r requirements.lock
        else .venv/bin/pip install -q -r requirements.lock; fi
        touch "$stamp"
      fi
    done ) &
  trap 'kill 0' EXIT
  .venv/bin/uvicorn haggle.server:app --host "${HAGGLE_BIND:-127.0.0.1}" --port "${PORT:-3123}" --reload --reload-dir haggle
else
  exec .venv/bin/uvicorn haggle.server:app --host "${HAGGLE_BIND:-127.0.0.1}" --port "${PORT:-3123}"
fi
