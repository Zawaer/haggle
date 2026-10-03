"""HTTP API + live event stream (SSE) + static frontend.

POST /api/hunts                 {"request": "..."}         -> {"id"}   starts steps 1-5
POST /api/hunts/{id}/answer     {"text": "..."}            answer the agent's clarifying question
POST /api/hunts/{id}/approve    {"ids": [...]}             user approves outreach -> negotiations start
POST /api/hunts/{id}/confirm    {"id": "..."}              user picks the deal; other threads released
GET  /api/hunts/{id}                                       snapshot
GET  /api/hunts/{id}/events?from=N                         SSE stream of every event from N
"""
import asyncio
import contextlib
import json
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT
from .orchestrator import HUNTS, Hunt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
from .mcp_server import http_app as _mcp_http_app, mcp as _mcp

_mcp_app = _mcp_http_app()


@contextlib.asynccontextmanager
async def _lifespan(app):
    async with _mcp.session_manager.run():
        yield


app = FastAPI(title="haggle", lifespan=_lifespan)
app.mount("/mcp", _mcp_app)  # MCP (streamable HTTP) for other agents, e.g. Matrix OS
_tasks = set()


def _bg(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def _hunt(hid):
    if hid not in HUNTS:
        raise HTTPException(404, "no such hunt")
    return HUNTS[hid]


class Req(BaseModel):
    request: str
    replay: bool = False


class Text(BaseModel):
    text: str


class Ids(BaseModel):
    ids: list[str]


class One(BaseModel):
    id: str


@app.post("/api/hunts")
async def start(body: Req):
    if body.replay:
        from .replay import ReplayHunt
        h = ReplayHunt()
    else:
        h = Hunt(body.request.strip())
    _bg(h.run())
    return {"id": h.id}


@app.post("/api/hunts/{hid}/answer")
async def answer(hid: str, body: Text):
    h = _hunt(hid)
    if not h.answer_future or h.answer_future.done():
        raise HTTPException(400, "no open question")
    h.answer_future.set_result(body.text)
    return {"ok": True}


@app.post("/api/hunts/{hid}/approve")
async def approve(hid: str, body: Ids):
    h = _hunt(hid)
    ok = h.phase == "awaiting_approval" or any(
        h.items.get(i, {}).get("state") == "shortlisted" and h.items[i].get("draft") for i in body.ids)
    if not ok:
        raise HTTPException(400, f"can't approve in phase {h.phase}")
    _bg(h.approve(body.ids))
    return {"ok": True}


@app.post("/api/hunts/{hid}/confirm")
async def confirm(hid: str, body: One):
    h = _hunt(hid)
    try:
        await h.confirm(body.id)  # replay hunts accept any id
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


class NewListing(BaseModel):
    title: str
    description: str
    price_sek: int
    location: str = "Stockholm"
    source: str = "Blocket"
    shipping: bool = False
    min_price_sek: int | None = None
    personality: str = "Friendly, a bit chatty, wants a quick sale this week."


@app.post("/api/market/listings")
async def post_listing(body: NewListing):
    """Demo helper: publish a new listing on the BUILT-IN mock marketplace (watch mode picks it up)."""
    from . import marketplace
    ls = marketplace.listings()
    prefix = {"Blocket": "bl", "Tradera": "tr"}.get(body.source, "fb")
    lid = f"{prefix}-new{sum(1 for l in ls if '-new' in l['id']) + 1}"
    ls.append({"id": lid, "source": body.source, "title": body.title, "description": body.description,
               "price_sek": body.price_sek, "location": body.location, "shipping": body.shipping, "posted_days_ago": 0,
               "seller": {"name": "Nils A.", "account_age_days": 2100, "num_reviews": 14, "rating": 4.9},
               "hidden": {"true_specs": None, "category": "desktop_pc",
                          "min_price_sek": body.min_price_sek or int(body.price_sek * 0.85), "personality": body.personality,
                          "language": "sv", "is_scam": False, "scam_signals": [], "expected_verdict": "match",
                          "notes": "posted live during the demo"}})
    return {"id": lid}


@app.get("/api/info")
async def info():
    """Where this instance runs (shown in the footer), e.g. HAGGLE_HOST_LABEL="Matrix OS" in .env."""
    import os
    import socket
    return {"host_label": os.environ.get("HAGGLE_HOST_LABEL", ""), "hostname": socket.gethostname()}


@app.post("/api/transcribe")
async def transcribe(request: Request):
    """Voice input: raw audio bytes in the body (Content-Type = the recording's mime type) -> {"text"}."""
    from .voice import transcribe as tr
    data = await request.body()
    if not data or len(data) > 10_000_000:
        raise HTTPException(400, "send 1 byte to 10 MB of audio")
    try:
        return {"text": await tr(data, request.headers.get("content-type", "audio/webm"))}
    except Exception as e:
        raise HTTPException(502, f"transcription failed: {str(e)[:200]}")


@app.get("/api/hunts/{hid}")
async def snapshot(hid: str):
    return _hunt(hid).snapshot()


@app.get("/api/hunts/{hid}/events")
async def events(hid: str, start: int = 0):
    h = _hunt(hid)

    async def gen():
        i = start
        while True:
            while i < len(h.events):
                yield f"data: {json.dumps(h.events[i], ensure_ascii=False)}\n\n"
                i += 1
            async with h.cond:
                try:
                    await asyncio.wait_for(h.cond.wait(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


@app.get("/")
async def index():
    return FileResponse(ROOT / "web" / "index.html")
