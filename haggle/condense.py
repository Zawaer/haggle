"""Optional lossy compression; errors use original text, with honest character accounting."""
import asyncio
from collections import OrderedDict
import hashlib
import logging
import os
import time

import httpx

URL = "https://api.condense.chat/v1/compress"
log = logging.getLogger("haggle.condense")
_cache = OrderedDict()
MAX_CACHE_ENTRIES = 512
MAX_CACHE_CHARS = 2_000_000
CACHE_TTL = 3600
_sem = asyncio.Semaphore(8)


def enabled():
    return bool(os.environ.get("CONDENSE_AUTH_TOKEN")) and os.environ.get("HAGGLE_CONDENSE", "1") != "0"


async def compress(texts, budget=None, min_chars=200):
    if not enabled():
        return texts
    model = os.environ.get("HAGGLE_CONDENSE_MODEL", "helene-1")
    now = time.monotonic()
    for key, (_, expires) in list(_cache.items()):
        if expires <= now:
            del _cache[key]
    keys = [(model, hashlib.sha256(t.encode()).hexdigest()) for t in texts]
    out = [(_cache[k][0] if k in _cache and len(t) >= min_chars else t) for k, t in zip(keys, texts)]
    todo = [i for i, t in enumerate(texts) if len(t) >= min_chars and keys[i] not in _cache]
    if todo:
        try:
            async with _sem:
                if budget is not None:
                    if budget.condense_calls >= budget.cap:
                        raise RuntimeError("compression request budget exhausted")
                    budget.condense_calls += 1
                async with httpx.AsyncClient(timeout=8) as http:
                    r = await http.post(URL, headers={"X-Condense-Auth-Token": os.environ["CONDENSE_AUTH_TOKEN"]},
                                        json={"model": model, "messages": [{"role": "user", "content": texts[i]} for i in todo]})
                    r.raise_for_status()
                    messages = r.json()["messages"]
                if not isinstance(messages, list) or len(messages) != len(todo):
                    raise ValueError("invalid compression response count")
                contents = [m.get("content") if isinstance(m, dict) else None for m in messages]
                if any(not isinstance(c, str) for c in contents):
                    raise ValueError("invalid compression response content")
                # Validate the entire response before changing shared cache state.
                for i, c in zip(todo, contents):
                    c = c if c and len(c) < len(texts[i]) else texts[i]
                    out[i] = c
                    _cache[keys[i]] = (c, now + CACHE_TTL)
                    _cache.move_to_end(keys[i])
                while len(_cache) > MAX_CACHE_ENTRIES or sum(len(c) for c, _ in _cache.values()) > MAX_CACHE_CHARS:
                    _cache.popitem(last=False)
        except Exception as e:
            log.warning("condense unavailable (%s); using original uncached text", type(e).__name__)
            if budget is not None:
                budget.condense_failures += 1
    if budget is not None:
        budget.condense_in += sum(map(len, texts))
        budget.condense_out += sum(map(len, out))
    return out
