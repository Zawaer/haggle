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
import os
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__, limits, pipeline
from .config import ROOT
from . import auth, inbox
from .orchestrator import HUNTS, Hunt, restore_hunts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
from .mcp_server import http_app as _mcp_http_app, mcp as _mcp

_mcp_app = CORSMiddleware(
    _mcp_http_app(), allow_origins=["*"], allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "Mcp-Protocol-Version", "Mcp-Session-Id", "Last-Event-ID"],
    expose_headers=["Mcp-Session-Id", "Mcp-Protocol-Version"],
)


@contextlib.asynccontextmanager
async def _lifespan(app):
    auth.users()  # validate credentials before accepting traffic
    await restore_hunts()
    async with _mcp.session_manager.run():
        try:
            yield
        finally:
            for h in list(HUNTS.values()):
                h.persist()
                h.suspending = True
            from .mcp_server import _tasks as mcp_tasks
            pending = list(_tasks) + list(mcp_tasks)
            for h in HUNTS.values():
                pending += [*h.tasks.values(), h.watch_task]
            pending = [t for t in pending if t and not t.done()]
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for h in HUNTS.values():
                if h.market:
                    await h.market.http.aclose()


app = FastAPI(title="haggle", lifespan=_lifespan)
app.mount("/mcp", _mcp_app)  # MCP (streamable HTTP) for other agents, e.g. Matrix OS
_tasks = set()


def _bg(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    def finished(task):
        _tasks.discard(task)
        if not task.cancelled() and task.exception():
            logging.error("Background operation failed: %s", task.exception())
    t.add_done_callback(finished)


def _hunt(hid, request):
    if hid not in HUNTS or HUNTS[hid].owner != request.state.owner:
        raise HTTPException(404, "no such hunt")
    return HUNTS[hid]


@app.middleware("http")
async def access_control(request: Request, call_next):
    path = request.url.path
    if path == "/mcp":
        # Both common endpoint spellings work without a redirect (including CORS preflight).
        request.scope["path"] = "/mcp/"
        request.scope["raw_path"] = b"/mcp/"
    is_mcp = path in ("/mcp", "/mcp/")
    # Reject cross-origin writes, including cookie-authenticated MCP calls.
    origin = request.headers.get("origin")
    same_origin = not origin or origin.rstrip("/") == str(request.base_url).rstrip("/")
    allowed_origins = {o.strip().rstrip("/") for o in os.environ.get("HAGGLE_MCP_ORIGINS", "").split(",") if o.strip()}
    public_mcp = is_mcp and (not auth.required() or (origin or "").rstrip("/") in allowed_origins)
    if not same_origin and not public_mcp and (is_mcp or request.method not in ("GET", "HEAD", "OPTIONS")):
        return JSONResponse({"detail": "cross-origin writes are not allowed"}, status_code=403)
    if is_mcp and request.method == "OPTIONS":
        return await call_next(request)  # CORS preflight carries no bearer token.
    fwd = request.headers.get("x-forwarded-for", "")
    request.state.client = fwd.split(",")[0].strip() or (request.client.host if request.client else "?")
    if not auth.required():  # open demo: no login, everyone shares owner "local"; abuse limits are per IP
        if path == "/login":
            return RedirectResponse("/", status_code=303)
        request.state.owner = "local"
        return await call_next(request)
    if path == "/healthz" or path == "/login" or path.startswith("/static/") or path == "/api/login":
        return await call_next(request)
    owner = auth.identity(request)
    if not owner:
        if path in ("/", "/inbox"):
            # keep the query so a deep link (e.g. /?go=1&q=... from the Gemini skill) survives signing in
            target = path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
        return JSONResponse({"detail": "sign in or provide a bearer token"}, status_code=401)
    request.state.owner = owner
    return await call_next(request)


class Login(BaseModel):
    token: str = Field(min_length=1, max_length=1000)


@app.post("/api/login")
async def login(body: Login, request: Request):
    owner = auth.authenticate(body.token)
    if not owner:
        raise HTTPException(401, "invalid access token")
    response = JSONResponse({"ok": True})
    # lax (not strict): links from other sites (the Gemini app skill) must arrive signed in; cross-site writes
    # stay blocked by the Origin check above and lax cookies are never sent on cross-site POSTs
    response.set_cookie("haggle_session", auth.session(owner), httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", max_age=86400)
    return response


@app.get("/login")
async def login_page():
    return FileResponse(ROOT / "web" / "login.html")


@app.post("/api/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie("haggle_session")
    return response


@app.get("/api/hunts")
async def hunts(request: Request):
    return [{"id": h.id, "request": h.request, "phase": h.phase} for h in HUNTS.values() if h.owner == request.state.owner]


@app.post("/api/hunts/{hid}/resume")
async def resume(hid: str, request: Request):
    h = _hunt(hid, request)
    if h.phase not in ("paused", "error") or h.closed:
        raise HTTPException(400, "hunt is not recoverable")
    _bg(h.recover())
    return {"ok": True}


class Answer(BaseModel):
    question: str = Field(default="", max_length=500)
    answer: str = Field(default="", max_length=500)


class Req(BaseModel):
    model_config = {"str_strip_whitespace": True}
    request: str = Field(max_length=10000)
    replay: bool = False
    answers: list[Answer] = Field(default_factory=list, max_length=6)  # answers to /api/clarify questions
    clarified: bool = False   # questions were already asked: the hunt must not ask again


class ClarifyReq(BaseModel):
    model_config = {"str_strip_whitespace": True}
    request: str = Field(min_length=1, max_length=10000)


class Text(BaseModel):
    model_config = {"str_strip_whitespace": True}
    text: str = Field(min_length=1, max_length=2000)


class Ids(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=20)


class One(BaseModel):
    id: str = Field(min_length=1, max_length=200)


@app.post("/api/hunts")
async def start(body: Req, request: Request):
    if body.replay:
        from .replay import ReplayHunt
        h = ReplayHunt(owner=request.state.owner)
    else:
        if not body.request.strip():
            raise HTTPException(400, "Describe what you want to buy.")
        try:
            limits.check_new_hunt(HUNTS, request.state.client)
        except limits.LimitError as e:
            raise HTTPException(429, str(e))
        text = pipeline.with_answers(body.request, [a.model_dump() for a in body.answers])
        h = Hunt(text, owner=request.state.owner, clarified=body.clarified or bool(body.answers))
    _bg(h.run())
    return {"id": h.id}


@app.post("/api/clarify")
async def clarify(body: ClarifyReq, request: Request):
    """Questions to ask before a hunt: {ready, summary, questions: [{id, question, options}]}."""
    try:
        limits.check_clarify(request.state.client)
    except limits.LimitError as e:
        raise HTTPException(429, str(e))
    from .llm import Budget
    try:
        return await pipeline.clarify(body.request, Budget(cap=4))
    except Exception as e:  # never block a hunt on this: the web app falls back to starting directly
        logging.getLogger("haggle").warning("clarify failed: %s", e)
        return {"ready": True, "summary": "", "questions": [], "error": "clarify unavailable"}


@app.post("/api/hunts/{hid}/answer")
async def answer(hid: str, body: Text, request: Request):
    h = _hunt(hid, request)
    if not h.answer_future or h.answer_future.done():
        raise HTTPException(400, "no open question")
    h.answer_future.set_result(body.text)
    return {"ok": True}


@app.post("/api/hunts/{hid}/approve")
async def approve(hid: str, body: Ids, request: Request):
    h = _hunt(hid, request)
    try:
        h.validate_approval(body.ids)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _bg(h.approve(body.ids))
    return {"ok": True}


@app.post("/api/hunts/{hid}/confirm")
async def confirm(hid: str, body: One, request: Request):
    h = _hunt(hid, request)
    try:
        await h.confirm(body.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ---- seller inbox (haggle's message hub): a person can play any seller live at /inbox

class SellerMsg(BaseModel):
    model_config = {"str_strip_whitespace": True, "allow_inf_nan": False}
    text: str = Field(min_length=1, max_length=2000)
    price_sek: float | None = Field(default=None, gt=0)


class ModeBody(BaseModel):
    mode: str


def _inbox_thread(tid, request):
    thread = inbox.THREADS.get(tid)
    h = HUNTS.get((thread or {}).get("hunt"))
    if not thread or not h or h.owner != request.state.owner:
        raise HTTPException(404, "no such conversation")
    return thread


@app.get("/api/inbox")
async def inbox_list(request: Request):
    claimable = []
    for h in HUNTS.values():
        if h.owner != request.state.owner or h.closed:
            continue
        for it in h.items.values():
            if it["state"] == "shortlisted":
                tid = inbox.open_thread(it["id"], it["listing"], h.id)
                if not inbox.THREADS[tid]["messages"]:
                    l = it["listing"]
                    claimable.append({"id": tid, "title": l["title"], "price_sek": l["price_sek"],
                                      "seller": (l.get("seller") or {}).get("name"), "mode": inbox.mode(tid)})
    threads = []
    for tid, t in inbox.THREADS.items():
        h = HUNTS.get(t["hunt"])
        if not h or h.owner != request.state.owner:
            continue
        last = {k: v for k, v in t["messages"][-1].items() if k != "thoughts"} if t["messages"] else None
        threads.append({"id": tid, "title": t["listing"].get("title", tid), "price_sek": t["listing"].get("price_sek"),
                        "location": t["listing"].get("location"), "seller": (t["listing"].get("seller") or {}).get("name"),
                        "mode": inbox.mode(tid), "n": len(t["messages"]), "last": last})
    threads.sort(key=lambda t: -(t["last"] or {}).get("seq", 0))
    return {"threads": threads, "claimable": claimable}


@app.get("/api/inbox/{tid}/messages")
async def inbox_messages(tid: str, request: Request, after: int = 0):
    t = _inbox_thread(tid, request)
    return [{k: v for k, v in m.items() if k != "thoughts"} for m in t["messages"] if m["seq"] > after]


@app.post("/api/inbox/{tid}/messages")
async def inbox_reply(tid: str, body: SellerMsg, request: Request):
    t = _inbox_thread(tid, request)
    if HUNTS[t["hunt"]].closed:
        raise HTTPException(400, "hunt is closed")
    inbox.set_mode(tid, "human")
    return await inbox.post(tid, "seller", body.text.strip()[:2000], body.price_sek)


@app.put("/api/inbox/{tid}/mode")
async def inbox_mode(tid: str, body: ModeBody, request: Request):
    _inbox_thread(tid, request)
    if body.mode not in ("human", "bot"):
        raise HTTPException(400, "mode must be human or bot")
    inbox.set_mode(tid, body.mode)
    return {"id": tid, "mode": inbox.mode(tid)}


class NewListing(BaseModel):
    model_config = {"str_strip_whitespace": True}
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=10000)
    price_sek: int = Field(gt=0)
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


@app.get("/healthz")
async def health():
    return {"status": "ok"}


@app.get("/api/info")
async def info():
    """Where this instance runs (shown in the footer), e.g. HAGGLE_HOST_LABEL="Matrix OS" in .env."""
    return {"host_label": os.environ.get("HAGGLE_HOST_LABEL", ""), "version": __version__}


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
    if len(data) > 256_000 or not 0 <= i <= 400 or len(_AUDIO) > 50:
        raise HTTPException(400, "chunk too large")
    _AUDIO.setdefault((request.state.owner, id), {})[i] = data
    return {"ok": True}


@app.post("/api/transcribe/finish")
async def transcribe_finish(request: Request, id: str, mime: str = "audio/webm"):
    from .voice import transcribe as tr
    parts = _AUDIO.pop((request.state.owner, id), None)
    if not parts:
        raise HTTPException(400, "no audio uploaded")
    data = b"".join(parts[k] for k in sorted(parts))
    if len(data) > 10_000_000:
        raise HTTPException(400, "audio exceeds 10 MB")
    try:
        return {"text": await tr(data, mime)}
    except Exception as e:
        raise HTTPException(502, f"transcription failed: {str(e)[:200]}")


@app.get("/api/hunts/{hid}")
async def snapshot(hid: str, request: Request):
    return _hunt(hid, request).snapshot()


def _shot_dir(hid):
    from .market_browser import SHOTS
    return SHOTS / hid


@app.get("/api/hunts/{hid}/browser")
async def browser_state(hid: str, request: Request):
    """Browser mode: what the agent's browser is doing right now (label + timestamp of the latest screenshot)."""
    _hunt(hid, request)
    f = _shot_dir(hid) / "latest.txt"
    if not f.exists():
        return {"active": False}
    t, _, label = f.read_text().partition(" ")
    return {"active": True, "t": int(t), "label": label}


@app.get("/api/hunts/{hid}/browser.jpg")
async def browser_shot(hid: str, request: Request):
    _hunt(hid, request)
    f = _shot_dir(hid) / "latest.jpg"
    if not f.exists():
        raise HTTPException(404, "no browser view")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/hunts/{hid}/events")
async def events(hid: str, request: Request, start: int = 0):
    h = _hunt(hid, request)

    async def gen():
        i = max(0, start)
        while not await request.is_disconnected():
            while i < len(h.events):
                yield f"data: {json.dumps(h.events[i], ensure_ascii=False)}\n\n"
                i += 1
            if h.closed and not getattr(h, "finalizing", False) and i >= len(h.events):
                return
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
