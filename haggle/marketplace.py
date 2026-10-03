"""Mock marketplace: Blocket / Tradera / Facebook Marketplace listings loaded from data/listings.json.

Real marketplaces forbid scraping and bot messaging, so the demo runs against a realistic mock.
`search` behaves like a dumb keyword search (it returns noise: laptops, parts, broken PCs), so the
agent has to do the real filtering. `public_view` strips the hidden ground truth: the buyer agent
never sees it; only the simulated sellers and the evaluation do.
"""
import json
import re
import unicodedata

from .config import DATA

_LISTINGS = None


def listings():
    global _LISTINGS
    if _LISTINGS is None:
        _LISTINGS = json.loads((DATA / "listings.json").read_text())
    return _LISTINGS


def get(listing_id):
    return next(l for l in listings() if l["id"] == listing_id)


def public_view(l):
    return {k: v for k, v in l.items() if k != "hidden"}


def _norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9åäö ]", " ", s)


def search(queries, limit=40):
    """Union of keyword matches over title+description; a listing matches a query if it has
    at least half of the query's words. Returns public views, best-matching first."""
    scored = {}
    for q in queries:
        words = [w for w in _norm(q).split() if len(w) > 1]
        if not words:
            continue
        for l in listings():
            text = _norm(l["title"] + " " + l["description"])
            hits = sum(1 for w in words if w in text)
            if hits * 2 >= len(words):
                scored[l["id"]] = max(scored.get(l["id"], 0), hits / len(words))
    ids = sorted(scored, key=lambda i: -scored[i])[:limit]
    return [public_view(get(i)) for i in ids]
