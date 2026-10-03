"""mockbay: our team's mock marketplace website (https://agentic-hack-mock-marketplace.vercel.app).

haggle searches it over its real HTTP API and normalises its listings to haggle's format. mockbay is a
static catalogue (no chat), so the conversations run through haggle's own message hub (inbox.py), where a
teammate can play any seller live at /inbox and the rest are played by the seller bot.

mockbay's structured fields (gpu, ram, storage) are the ground truth for the simulated sellers: the buyer
agent never sees them as structured data, only the listing text.
"""
import hashlib
import os
from datetime import datetime, timezone

import httpx

BASE = os.environ.get("HAGGLE_MOCKBAY_URL", "https://agentic-hack-mock-marketplace.vercel.app").rstrip("/")
PERSONALITIES = [
    "Friendly student, chatty, wants a quick sale before the weekend, will drop a bit for fast pickup.",
    "Grumpy old-timer, short Swedish replies, hates lowballs, firm but will move a little for cash today.",
    "Busy parent, wants it gone this week, replies briefly, OK with a fair offer.",
    "Proud enthusiast who built it himself, talks about the parts, defends his price but can be charmed.",
    "Moving abroad soon, a bit stressed, flexible on price if pickup is quick.",
    "Polite but firm: 'priset är nästan fast', moves only a few hundred kronor.",
]
_CACHE = {}


def _h(s, n):
    return int(hashlib.sha1(s.encode()).hexdigest(), 16) % n


def normalize(x):
    s = x.get("seller") or {}
    since = s.get("since") or 2020
    posted = x.get("posted")
    days = 0
    if posted:
        try:
            days = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(posted.replace("Z", "+00:00"))).days)
        except ValueError:
            pass
    photos = x.get("photos") or []
    lid = x["id"]
    l = {
        "id": lid, "source": "mockbay", "title": x.get("title") or x.get("productName") or lid,
        "description": x.get("description") or "", "price_sek": int(x.get("price") or 0),
        "location": x.get("location") or "", "shipping": bool(x.get("shipping")), "posted_days_ago": days,
        "seller": {"name": s.get("name") or "seller", "account_age_days": max(1, (datetime.now(timezone.utc) - datetime(int(since), 1, 1, tzinfo=timezone.utc)).days),
                   "num_reviews": s.get("sales") or 0, "rating": s.get("rating")},
        "url": f"{BASE}/listing/{lid}", "photo": (BASE + photos[0]) if photos and photos[0].startswith("/") else None,
    }
    price = l["price_sek"]
    # hidden data for the simulated seller (deterministic per listing; never shown to the buyer agent)
    l["_hidden"] = {
        "true_specs": {"gpu": x.get("gpu"), "ram_gb": x.get("ram"), "storage": x.get("storage"),
                       "cpu": (x.get("attributes") or {}).get("Processor"), "condition": x.get("condition")},
        "min_price_sek": int(round(price * (0.80 + _h(lid, 12) / 100) / 50) * 50) if price else None,
        "personality": PERSONALITIES[_h(lid + "p", len(PERSONALITIES))],
        "language": "sv", "is_scam": since >= 2026 and (s.get("rating") or 5) < 2,
    }
    _CACHE[lid] = l
    return l


async def search(queries, limit=40):
    """mockbay's search needs every word to match, so a query that finds nothing is retried with fewer
    words ("macbook air m1" -> "macbook air" -> "macbook"). No category filter: vetting removes the noise."""
    seen, out = set(), []
    async with httpx.AsyncClient(base_url=BASE, timeout=15) as http:
        for q in queries:
            words = q.split()
            while words:
                r = await http.get("/api/listings", params={"q": " ".join(words)})
                r.raise_for_status()
                got = r.json().get("listings", [])
                if got:
                    break
                words = words[:-1]
            page, pages = 1, int(r.json().get("pages", 1)) if words else 0
            while words:
                for x in got:
                    if x["id"] not in seen:
                        seen.add(x["id"])
                        out.append(normalize(x))
                        if len(out) >= limit:
                            return [{k: v for k, v in l.items() if k != "_hidden"} for l in out]
                if page >= pages:
                    break
                page += 1
                r = await http.get("/api/listings", params={"q": " ".join(words), "page": page})
                r.raise_for_status()
                got = r.json().get("listings", [])
                if not got:
                    break
    return [{k: v for k, v in l.items() if k != "_hidden"} for l in out[:limit]]


def full(lid):
    """Listing incl. hidden seller data, in the shape negotiation.seller_system expects."""
    l = _CACHE[lid]
    return {**{k: v for k, v in l.items() if k != "_hidden"}, "hidden": l["_hidden"]}
