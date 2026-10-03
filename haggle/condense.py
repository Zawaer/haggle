"""condense.chat context compression for the negotiation agents.

Every buyer turn re-sends the listing text and the whole chat so far, and haggle-overnight chats with real
sellers grow long. Before the Gemini call we compress the parts that are old or already digested (the
listing description, whose specs were extracted and verified earlier; chat messages older than the last
two) with condense's /v1/compress endpoint. The latest messages stay verbatim, and listing extraction never
uses compression, because condense is lossy (it can drop a model number) and vetting accuracy matters more.

Fails open: if condense is slow or down, the original text is used.
"""
import hashlib
import logging
import os

import httpx

URL = "https://api.condense.chat/v1/compress"
MODEL = os.environ.get("HAGGLE_CONDENSE_MODEL", "helene-1")
log = logging.getLogger("haggle.condense")
_cache = {}


def enabled():
    return bool(os.environ.get("CONDENSE_AUTH_TOKEN")) and os.environ.get("HAGGLE_CONDENSE", "1") != "0"


async def compress(texts, budget=None, min_chars=200):
    """Compress each text independently; short texts and failures come back unchanged."""
    if not enabled():
        return texts
    todo = [i for i, t in enumerate(texts) if len(t) >= min_chars and hashlib.sha1(t.encode()).hexdigest() not in _cache]
    if todo:
        try:
            async with httpx.AsyncClient(timeout=8) as http:
                r = await http.post(URL, headers={"X-Condense-Auth-Token": os.environ["CONDENSE_AUTH_TOKEN"]},
                                    json={"model": MODEL, "messages": [{"role": "user", "content": texts[i]} for i in todo]})
                r.raise_for_status()
                for i, m in zip(todo, r.json()["messages"]):
                    _cache[hashlib.sha1(texts[i].encode()).hexdigest()] = m["content"] or texts[i]
                if budget is not None:
                    budget.condense_calls += 1
        except Exception as e:
            log.warning("condense failed, using original text: %s", e)
            return texts
    out = []
    for t in texts:
        c = _cache.get(hashlib.sha1(t.encode()).hexdigest(), t) if len(t) >= min_chars else t
        if budget is not None:
            budget.condense_in += len(t)
            budget.condense_out += len(c)
        out.append(c)
    return out
