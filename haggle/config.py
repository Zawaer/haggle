"""Central configuration: model names, limits and guardrail numbers live here and nowhere else."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

# Models (Gemini). The fallback is used when the main model returns 503/overloaded.
MODEL = os.environ.get("HAGGLE_MODEL", "gemini-3.8-flash")
FALLBACK_MODEL = os.environ.get("HAGGLE_FALLBACK_MODEL", "gemini-3.5-flash-lite")
FAST_MODEL = os.environ.get("HAGGLE_FAST_MODEL", "gemini-3.5-flash-lite")  # simulated sellers

# Guardrails
MAX_PARALLEL_LLM = int(os.environ.get("HAGGLE_MAX_PARALLEL", "8"))
MAX_LLM_CALLS_PER_HUNT = int(os.environ.get("HAGGLE_MAX_CALLS", "250"))  # stay far from "abuse" territory
MAX_MESSAGES_PER_SELLER = 6     # buyer messages per negotiation thread
SHORTLIST_SIZE = 5

# External marketplace (teammate's mock site). Empty = use the built-in in-process mock.
MARKET_URL = os.environ.get("HAGGLE_MARKET_URL", "").rstrip("/")
HUMAN_REPLY_TIMEOUT = int(os.environ.get("HAGGLE_HUMAN_TIMEOUT", "180"))  # seconds to wait for a seller reply

# Watch mode: after the first deals, keep checking the marketplace for new matching listings.
WATCH_INTERVAL = int(os.environ.get("HAGGLE_WATCH_INTERVAL", "20"))      # seconds between searches
WATCH_MINUTES = int(os.environ.get("HAGGLE_WATCH_MINUTES", "180"))       # stop watching after this long
