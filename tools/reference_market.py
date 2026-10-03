"""Minimal reference implementation of the marketplace API contract (no UI). For testing the agent
end to end before the real marketplace site exists, and as an executable spec for whoever builds it.

    .venv/bin/uvicorn tools.reference_market:app --host 0.0.0.0 --port 3140
"""
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from haggle import marketplace

app = FastAPI(title="reference marketplace")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
MSGS, MODE = [], {}


class Msg(BaseModel):
    model_config = {"extra": "allow"}
    text: str
    price_sek: float | None = None


class Mode(BaseModel):
    mode: str


def _pub(l):
    return {**marketplace.public_view(l), "seller_mode": MODE.get(l["id"], "bot")}


@app.get("/api/listings")
def listings(q: str = ""):
    return [{**l, "seller_mode": MODE.get(l["id"], "bot")} for l in marketplace.search([q])] if q else \
        [_pub(l) for l in marketplace.listings()]


@app.get("/api/listings/{lid}")
def one(lid: str):
    try:
        return _pub(marketplace.get(lid))
    except StopIteration:
        raise HTTPException(404)


@app.post("/api/listings/{lid}/messages")
def post(lid: str, m: Msg):
    d = m.model_dump()
    rec = {"seq": len(MSGS) + 1, "listing_id": lid, "from": d.pop("from", None) or getattr(m, "from", "buyer"),
           "created_at": time.time(), **d}
    MSGS.append(rec)
    return rec


@app.get("/api/listings/{lid}/messages")
def get(lid: str, after: int = 0, conversation: str = "local"):
    return [m for m in MSGS if m["listing_id"] == lid and m.get("conversation", "local") == conversation and m["seq"] > after]


@app.put("/api/listings/{lid}/seller-mode")
def mode(lid: str, m: Mode):
    MODE[lid] = m.mode
    return {"ok": True}


@app.get("/api/conversations")
def convs():
    out = {}
    for m in MSGS:
        out[(m["listing_id"], m.get("conversation", "local"))] = {"id": m["listing_id"], "conversation": m.get("conversation", "local"), "last_message": m, "seller_mode": MODE.get(m["listing_id"], "bot")}
    return list(out.values())
