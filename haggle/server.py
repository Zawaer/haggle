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

from . import limits
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


def _client(request: Request):
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else None)


@app.post("/api/hunts")
async def start(body: Req, request: Request):
    if body.replay:
        from .replay import ReplayHunt
        h = ReplayHunt()
    else:
        if not body.request.strip():
            raise HTTPException(400, "Describe what you want to buy.")
        try:
            limits.check_new_hunt(HUNTS, _client(request))
        except limits.LimitError as e:
            raise HTTPException(429, str(e))
        h = Hunt(body.request.strip()[:2000])
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


# ---- seller inbox (haggle's message hub): a person can play any seller live at /inbox

class SellerMsg(BaseModel):
    text: str
    price_sek: float | None = None


class ModeBody(BaseModel):
    mode: str


@app.get("/api/inbox")
async def inbox_list():
    from . import inbox
    threads = [{"id": lid, "title": t["listing"].get("title", lid), "price_sek": t["listing"].get("price_sek"),
                "location": t["listing"].get("location"), "seller": (t["listing"].get("seller") or {}).get("name"),
                "mode": inbox.mode(lid), "n": len(t["messages"]), "last": t["messages"][-1] if t["messages"] else None}
               for lid, t in inbox.THREADS.items()]
    threads.sort(key=lambda x: -(x["last"] or {}).get("seq", 0))
    claimable = []
    if HUNTS:
        h = list(HUNTS.values())[-1]
        for it in h.items.values():
            if it["state"] in ("shortlisted", "approved", "negotiating") and it["id"] not in inbox.THREADS:
                l = it["listing"]
                claimable.append({"id": it["id"], "title": l["title"], "price_sek": l["price_sek"],
                                  "seller": (l.get("seller") or {}).get("name"), "mode": inbox.mode(it["id"])})
    return {"threads": threads, "claimable": claimable}


@app.get("/api/inbox/{lid}/messages")
async def inbox_messages(lid: str, after: int = 0):
    from . import inbox
    t = inbox.THREADS.get(lid)
    msgs = [m for m in (t or {}).get("messages", []) if m["seq"] > after]
    return [{k: v for k, v in m.items() if k != "thoughts"} for m in msgs]  # a seller never sees the agent's thoughts


@app.post("/api/inbox/{lid}/messages")
async def inbox_reply(lid: str, body: SellerMsg):
    from . import inbox
    if inbox.mode(lid) != "human":
        inbox.set_mode(lid, "human")  # typing a reply takes over this seller from the bot
    return await inbox.post(lid, "seller", body.text.strip()[:2000], body.price_sek)


@app.put("/api/inbox/{lid}/mode")
async def inbox_mode(lid: str, body: ModeBody):
    from . import inbox
    inbox.set_mode(lid, body.mode)
    return {"id": lid, "mode": inbox.mode(lid)}


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


_AUDIO = {}  # upload id -> list of chunks (chunked so it survives tunnels with small message limits)


@app.post("/api/transcribe/chunk")
async def transcribe_chunk(request: Request, id: str, i: int):
    data = await request.body()
    if len(data) > 256_000 or i > 400 or len(_AUDIO) > 50:
        raise HTTPException(400, "chunk too large")
    _AUDIO.setdefault(id, {})[i] = data
    return {"ok": True}


@app.post("/api/transcribe/finish")
async def transcribe_finish(id: str, mime: str = "audio/webm"):
    from .voice import transcribe as tr
    parts = _AUDIO.pop(id, None)
    if not parts:
        raise HTTPException(400, "no audio uploaded")
    data = b"".join(parts[k] for k in sorted(parts))
    try:
        return {"text": await tr(data, mime)}
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


@app.get("/inbox")
async def inbox_page():
    return FileResponse(ROOT / "web" / "inbox.html")


@app.get("/")
async def index():
    return FileResponse(ROOT / "web" / "index.html")
