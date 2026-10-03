"""Message hub + seller inbox: the conversation layer between the buyer agent and sellers.

Every buyer and seller message of every negotiation is posted here, so the seller inbox (/inbox) shows
all threads live. Each listing has a seller mode: "bot" (the simulated seller answers) or "human" (a
person replies from /inbox, e.g. a teammate live on stage). Sellers can be claimed before the agent writes.
"""
import asyncio
import time

THREADS = {}   # listing id -> {"listing": {...}, "messages": [...], "mode": "bot"|"human", "hunt": id}
MODES = {}     # listing id -> mode (survives thread resets, so a seller can be claimed in advance)
_seq = 0
_cond = asyncio.Condition()


def mode(lid):
    return MODES.get(lid, "bot")


def set_mode(lid, m):
    MODES[lid] = "human" if m == "human" else "bot"
    if lid in THREADS:
        THREADS[lid]["mode"] = MODES[lid]


def open_thread(lid, listing, hunt_id):
    THREADS[lid] = {"listing": listing, "messages": [], "mode": mode(lid), "hunt": hunt_id}


async def post(lid, frm, text, price=None, thoughts=None):
    global _seq
    _seq += 1
    m = {"seq": _seq, "from": frm, "text": text, "price_sek": price, "t": time.time()}
    if thoughts:
        m["thoughts"] = thoughts
    THREADS.setdefault(lid, {"listing": {}, "messages": [], "mode": mode(lid), "hunt": None})["messages"].append(m)
    async with _cond:
        _cond.notify_all()
    return m


async def wait_seller(lid, after_seq, timeout):
    """Wait for the human seller's reply (joins messages sent in quick succession)."""
    end = time.time() + timeout
    while time.time() < end:
        got = [m for m in THREADS.get(lid, {}).get("messages", []) if m["seq"] > after_seq and m["from"] == "seller"]
        if got:
            await asyncio.sleep(1.5)
            got = [m for m in THREADS[lid]["messages"] if m["seq"] > after_seq and m["from"] == "seller"]
            price = next((m["price_sek"] for m in reversed(got) if m.get("price_sek")), None)
            return {"text": "\n".join(m["text"] for m in got), "price_sek": price, "seq": got[-1]["seq"]}
        async with _cond:
            try:
                await asyncio.wait_for(_cond.wait(), timeout=min(2.0, max(0.1, end - time.time())))
            except asyncio.TimeoutError:
                pass
    return None


def last_seq(lid):
    msgs = THREADS.get(lid, {}).get("messages", [])
    return msgs[-1]["seq"] if msgs else 0
