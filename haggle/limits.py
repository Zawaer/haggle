"""Abuse limits for a public deployment (the Gemini key is ours, the URL is public).

Checked whenever a live hunt is started (web or MCP). Replay hunts make no API calls and are exempt.
All numbers can be changed with env vars; the defaults are generous for a demo and judges.
"""
import os
import time
from collections import deque

MAX_ACTIVE = int(os.environ.get("HAGGLE_MAX_ACTIVE_HUNTS", "4"))      # live hunts running at once
PER_HOUR = int(os.environ.get("HAGGLE_HUNTS_PER_HOUR", "40"))         # live hunts per hour, all users
PER_CLIENT_HOUR = int(os.environ.get("HAGGLE_HUNTS_PER_CLIENT_HOUR", "8"))
DAILY_CALLS = int(os.environ.get("HAGGLE_DAILY_CALL_CAP", "5000"))    # Gemini calls per 24 h, all users

CLARIFY_PER_CLIENT_HOUR = int(os.environ.get("HAGGLE_CLARIFY_PER_CLIENT_HOUR", "40"))

_starts = deque()        # (time, client)
_clarifies = deque()     # (time, client)
_calls = deque()         # time of every Gemini call


class LimitError(Exception):
    pass


def count_call():
    _calls.append(time.time())


def _trim(now):
    while _starts and now - _starts[0][0] > 3600:
        _starts.popleft()
    while _calls and now - _calls[0] > 86400:
        _calls.popleft()


def _active(hunts, now):
    # a hunt counts as active while it is working (not waiting on the user) and younger than 15 minutes
    return sum(1 for h in hunts.values() if not getattr(h, "is_replay", False)
               and h.phase not in ("awaiting_approval", "awaiting_confirmation", "done", "error", "paused")
               and not (h.answer_future and not h.answer_future.done())
               and now - h.started < 900)


def check_new_hunt(hunts, client=None):
    now = time.time()
    _trim(now)
    # Durable hunts remain addressable; never evict active tasks or saved approval gates.
    busy = "haggle is busy with other people's hunts right now"
    if len(_calls) >= DAILY_CALLS:
        raise LimitError("Today's Gemini budget for this public demo is used up. Try the recorded replay (?replay=1).")
    if _active(hunts, now) >= MAX_ACTIVE:
        raise LimitError(f"{busy}. Try again in a minute, or watch the recorded replay (?replay=1).")
    if len(_starts) >= PER_HOUR:
        raise LimitError(f"{busy} (hourly limit). Try the recorded replay (?replay=1).")
    if client and sum(1 for _, c in _starts if c == client) >= PER_CLIENT_HOUR:
        raise LimitError("You've started a lot of hunts this hour. Try again later, or watch the recorded replay (?replay=1).")
    _starts.append((now, client))


def check_clarify(client=None):
    """One cheap Gemini call per request; still capped so a public URL can't be looped."""
    now = time.time()
    _trim(now)
    while _clarifies and now - _clarifies[0][0] > 3600:
        _clarifies.popleft()
    if len(_calls) >= DAILY_CALLS:
        raise LimitError("Today's Gemini budget for this public demo is used up. Try the recorded replay (?replay=1).")
    if sum(1 for _, c in _clarifies if c == client) >= CLARIFY_PER_CLIENT_HOUR:
        raise LimitError("Too many requests this hour. Try again later.")
    _clarifies.append((now, client))
