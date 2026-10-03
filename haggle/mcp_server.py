"""MCP server: lets other agents (Matrix OS Chat, Claude, Gemini CLI, …) use haggle as a tool.

Mounted on the main server at /mcp (streamable HTTP), sharing the same hunts as the web UI, so a hunt
started from an agent chat shows up live in the browser too.

Tools: start_hunt -> hunt_status (optionally waits for the next decision point) -> approve_outreach ->
hunt_status -> confirm_deal. The human stays in the loop: the agent relays the shortlist and deals, and
must get the user's OK before approving or confirming.
"""
import asyncio
import os

from mcp.server.mcpserver import MCPServer, Context
from mcp.server.transport_security import TransportSecuritySettings

from . import limits, pipeline
from .orchestrator import HUNTS, Hunt

# Where the live dashboard is reachable for the user (Render sets RENDER_EXTERNAL_URL automatically).
PUBLIC_URL = (os.environ.get("HAGGLE_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
              or f"http://localhost:{os.environ.get('PORT', '3123')}").rstrip("/")
MAX_WAIT = 75  # seconds per tool call: stays under typical proxy timeouts (~100 s); poll hunt_status for more

mcp = MCPServer(
    name="haggle",
    instructions="haggle finds, vets and negotiates second-hand purchases on mockbay, a simulated marketplace with "
                 "simulated sellers. Flow: make sure you know the max budget (SEK), the kind of item (desktop PC / laptop / "
                 "graphics card), what it's for or the minimum specs, and pickup city or shipping; ask the user for "
                 "anything missing in ONE message (clarify_request suggests the questions) -> start_hunt with the "
                 "complete brief -> show the user the shortlist "
                 "and drafted messages -> approve_outreach ONLY after the user explicitly agrees -> show the deals -> "
                 "confirm_deal ONLY with the deal the user picks. Each call waits at most ~75 s; if 'phase' is not yet "
                 "awaiting_approval / awaiting_confirmation / done, call hunt_status with wait_seconds=60 until it is. "
                 "Always give the user the dashboard_url so they can watch the negotiations live.",
)
_tasks = set()
GATES = ("awaiting_approval", "awaiting_confirmation", "done", "error", "paused")


def _bg(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def _owner(ctx):
    if ctx is None:
        return "local"  # in-process callers; HTTP tools always receive injected context
    request = ctx.request_context.request
    if request is None or not getattr(request.state, "owner", None):
        raise ValueError("authentication required")
    return request.state.owner


def _owned(hid, ctx):
    h = HUNTS.get(hid)
    return h if h and h.owner == _owner(ctx) else None


def _summary(h):
    items = h.items.values()
    out = {"hunt_id": h.id, "phase": h.phase, "dashboard_url": f"{PUBLIC_URL}/?h={h.id}", "gemini_calls": h.budget.calls,
           "counts": {s: sum(1 for i in items if i["state"] == s) for s in
                      ("matched", "uncertain", "reject", "scam", "shortlisted", "negotiating", "deal_offered")}}
    if h.phase == "error":
        out["error"] = getattr(h, "error", "the hunt failed")
    if h.req:
        out["requirements"] = h.req.get("summary")
    q = next((e for e in reversed(h.events) if e["type"] == "question"), None)
    if q and h.answer_future and not h.answer_future.done():
        out["question_for_user"] = q["text"]
    short = [i for i in items if i["state"] == "shortlisted" and i.get("draft")]
    if short and not h.closed:
        out["shortlist"] = [{"listing_id": i["id"], "title": i["listing"]["title"], "photo_url": i["listing"].get("photo"),
                             "listing_url": i["listing"].get("url"), "asking_sek": i["listing"]["price_sek"],
                             "location": i["listing"]["location"], "score": i.get("score"),
                             "draft_message": (i.get("draft") or {}).get("message"),
                             "opening_offer_sek": (i.get("draft") or {}).get("offer_sek")} for i in short]
        out["next"] = "Show the shortlist and drafts to the user; call approve_outreach with the ids they approve."
    deals = [i for i in items if i["state"] in ("deal_offered", "confirmed")]
    if deals:
        out["deals"] = [{"listing_id": i["id"], "title": i["listing"]["title"], "photo_url": i["listing"].get("photo"),
                         **i["deal"], "state": i["state"]}
                        for i in sorted(deals, key=lambda i: i["deal"]["price_sek"])]
    if h.phase == "awaiting_confirmation":
        out["next"] = "Present the deals; confirm the user's choice, or approve new shortlisted listings after consent."
    scams = [i["listing"]["title"] for i in items if i["state"] == "scam"]
    if scams:
        out["scams_flagged"] = scams
    return out


async def _wait(h, seconds):
    end = asyncio.get_running_loop().time() + seconds
    while h.phase not in GATES and not (h.answer_future and not h.answer_future.done()):
        if asyncio.get_running_loop().time() > end:
            break
        await asyncio.sleep(0.5)


@mcp.tool()
async def clarify_request(request: str, ctx: Context = None) -> dict:
    """Before start_hunt: which questions to ask the user, with typical answers to offer.
    Returns {ready, summary, questions: [{id, question, options}]}. Ask the user these questions yourself
    (all in one message), then call start_hunt with the request plus their answers. If ready, just start."""
    from .llm import Budget
    if not request.strip():
        return {"error": "describe what to buy"}
    owner = _owner(ctx)
    try:
        limits.check_clarify(owner)
    except limits.LimitError as e:
        return {"error": str(e)}
    return await pipeline.clarify(request.strip()[:2000], Budget(cap=4))


@mcp.tool()
async def start_hunt(request: str, wait_seconds: int = 60, ctx: Context = None) -> dict:
    """Start a hunt from a COMPLETE brief: max budget in SEK, kind of item, minimum specs or use, and pickup
    city or shipping, e.g. "Gaming PC under 8,000 SEK, RTX 3060 or better, 16 GB RAM, 1 TB SSD, Stockholm".
    Ask the user for missing details first; haggle does not ask follow-up questions itself.
    Waits up to wait_seconds (max 75) for the shortlist, then returns the status; if not there yet,
    poll hunt_status(wait_seconds=60). Give the user the dashboard_url to watch live."""
    if not request.strip():
        return {"error": "describe what to buy"}
    owner = _owner(ctx)
    try:
        limits.check_new_hunt(HUNTS, owner)
    except limits.LimitError as e:
        return {"error": str(e)}
    h = Hunt(request.strip()[:2000], owner=owner, clarified=True)
    _bg(h.run())
    await asyncio.sleep(0.2)
    await _wait(h, min(wait_seconds, MAX_WAIT))
    return _summary(h)


@mcp.tool()
async def hunt_status(hunt_id: str, wait_seconds: int = 0, ctx: Context = None) -> dict:
    """Current status of a hunt: phase, shortlist + drafted messages, deals. Optionally wait for the next decision point."""
    h = _owned(hunt_id, ctx)
    if not h:
        return {"error": "no such hunt"}
    if wait_seconds:
        await _wait(h, min(wait_seconds, MAX_WAIT))
    return _summary(h)


@mcp.tool()
async def answer_question(hunt_id: str, answer: str, wait_seconds: int = 60, ctx: Context = None) -> dict:
    """Answer the hunt's clarifying question (relay the user's answer)."""
    h = _owned(hunt_id, ctx)
    if not h or not h.answer_future or h.answer_future.done():
        return {"error": "no open question"}
    h.answer_future.set_result(answer)
    await asyncio.sleep(0.2)
    await _wait(h, min(wait_seconds, MAX_WAIT))
    return _summary(h)


@mcp.tool()
async def approve_outreach(hunt_id: str, listing_ids: list[str], wait_seconds: int = 60, ctx: Context = None) -> dict:
    """Send the drafted opening messages to the approved sellers and start negotiating with them in parallel.
    Only call this after the user approved these listings. Waits for the deals."""
    h = _owned(hunt_id, ctx)
    if not h:
        return {"error": "no such hunt"}
    try:
        h.validate_approval(listing_ids)
    except ValueError as e:
        return {"error": str(e)}
    _bg(h.approve(listing_ids))
    await asyncio.sleep(0.5)
    await _wait(h, min(wait_seconds, MAX_WAIT))
    return _summary(h)


@mcp.tool()
async def confirm_deal(hunt_id: str, listing_id: str, ctx: Context = None) -> dict:
    """Confirm the deal the user picked. Other sellers are released politely. Payment and pickup stay with the user."""
    h = _owned(hunt_id, ctx)
    if not h:
        return {"error": "no such hunt"}
    try:
        await h.confirm(listing_id)
    except ValueError as e:
        return {"error": str(e)}
    return _summary(h)


@mcp.tool()
async def resume_hunt(hunt_id: str, ctx: Context = None) -> dict:
    """Recover a paused hunt without resending uncertain messages. Fresh drafts require approval."""
    h = _owned(hunt_id, ctx)
    if not h:
        return {"error": "no such hunt"}
    try:
        await h.recover()
    except ValueError as e:
        return {"error": str(e)}
    return _summary(h)


def http_app():
    return mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
