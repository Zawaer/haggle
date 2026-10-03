"""HTTP API + live event stream (SSE) + static frontend.

POST /api/hunts                 {"request": "..."}         -> {"id"}   starts steps 1-5
POST /api/hunts/{id}/answer     {"text": "..."}            answer the agent's clarifying question
POST /api/hunts/{id}/approve    {"ids": [...]}             user approves outreach -> negotiations start
POST /api/hunts/{id}/confirm    {"id": "..."}              user picks the deal; other threads released
GET  /api/hunts/{id}                                       snapshot
GET  /api/hunts/{id}/events?from=N                         SSE stream of every event from N
"""
import asyncio
import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT
from .orchestrator import HUNTS, Hunt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
app = FastAPI(title="haggle")
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
    if h.phase != "awaiting_approval":
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
