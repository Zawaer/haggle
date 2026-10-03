"""MCP server: lets other agents (Matrix OS Chat, Claude, Gemini CLI, …) use haggle as a tool.

Mounted on the main server at /mcp (streamable HTTP), sharing the same hunts as the web UI, so a hunt
started from an agent chat shows up live in the browser too.

Tools: start_hunt -> hunt_status (optionally waits for the next decision point) -> approve_outreach ->
hunt_status -> confirm_deal. The human stays in the loop: the agent relays the shortlist and deals, and
must get the user's OK before approving or confirming.
"""
import asyncio
from functools import wraps
import json
import logging
import os
import time

from mcp.server.mcpserver import MCPServer, Context
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from . import __version__, limits, pipeline
from .orchestrator import HUNTS, Hunt

# Where the live dashboard is reachable for the user (Render sets RENDER_EXTERNAL_URL automatically).
PUBLIC_URL = (os.environ.get("HAGGLE_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
              or f"http://localhost:{os.environ.get('PORT', '3123')}").rstrip("/")
MAX_WAIT = 30  # Stay below common client/proxy timeouts; background work survives the wait.

mcp = MCPServer(
    name="haggle",
    version=__version__,
    instructions="haggle searches a simulated marketplace and negotiates with simulated sellers; no real purchases. "
                 "Get an item, explicit SEK ceiling, requirements and pickup city or shipping preference; ask only "
                 "for missing essentials. start_hunt(wait_seconds=0) returns a dashboard_url to share immediately. "
                 "Keep choice labels stable across shortlist and deals. Show opening drafts, then approve_outreach "
                 "only for listings the user approved. New requirements need a new complete brief and hunt before "
                 "outreach; existing hunts cannot be edited. Use listing_details for evidence instead of scraping. "
                 "Follow the returned next_action. Poll running hunts at most four times per turn with "
                 "wait_seconds=30; stop for questions, approval, confirmation, done, paused or error. "
                 "Refresh status before confirm_deal and confirm only the user's chosen, unchanged deal. "
                 "Use a unique request_id for start_hunt; reuse it on retries. On a stale action or timeout, "
                 "check status instead of blindly repeating the action. A finalizing result needs a status check.",
)
_tasks = set()
GATES = ("awaiting_approval", "awaiting_confirmation", "done", "error", "paused")


def _bg(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    def finished(task):
        _tasks.discard(task)
        if not task.cancelled() and task.exception():
            logging.getLogger(__name__).error("Background operation failed: %s", task.exception())
    t.add_done_callback(finished)
    return t


def _tool(*, read_only=False, idempotent=False):
    """Keep in-process dict results while exposing correct MCP error and structured-result metadata."""
    def register(fn):
        @wraps(fn)
        async def invoke(*args, **kwargs):
            data = await fn(*args, **kwargs)
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))],
                                  structured_content=data, is_error=bool(data.get("error")))
        mcp.tool(structured_output=False, annotations=ToolAnnotations(
            read_only_hint=read_only, destructive_hint=not read_only,
            idempotent_hint=idempotent, open_world_hint=True))(invoke)
        return fn
    return register


def _missing():
    return {"error": "no such hunt", "code": "hunt_not_found",
            "next": "This hunt is unavailable. The free demo may have restarted; start a new hunt with the complete brief."}


def _owner(ctx):
    if ctx is None:
        return "local"  # in-process callers; HTTP tools always receive injected context
    request = ctx.request_context.request
    if request is None or not getattr(request.state, "owner", None):
        raise ValueError("authentication required")
    return request.state.owner


def _client(ctx):
    """Who to rate-limit: the caller's IP (with login off, every caller is owner "local")."""
    request = ctx.request_context.request if ctx is not None else None
    return getattr(getattr(request, "state", None), "client", None) or _owner(ctx)


def _owned(hid, ctx):
    h = HUNTS.get(hid)
    return h if h and h.owner == _owner(ctx) else None


def _checks(it, include_details=False):
    checks = it.get("verdicts", {})
    if include_details:
        return checks
    # Preserve every verdict and useful value without repeating source quotes in each poll.
    return {k: f"{v.get('label', k)}: {v['status']}: {v.get('reason', '')}" for k, v in checks.items()}


def _choice(it, include_details=False):
    listing = it["listing"]
    result = {"listing_id": it["id"], "title": listing["title"], "listing_url": listing.get("url"),
              "location": listing.get("location", ""), "checks": _checks(it, include_details)}
    condition = it.get("specs", {}).get("condition")
    if condition:
        result["condition"] = condition
    if it.get("risk_reasons"):
        result["cautions"] = it["risk_reasons"]
    if include_details:
        result.update(photo_url=listing.get("photo"), score=it.get("score"))
    return result


def _summary(h, include_details=False):
    items = h.items.values()
    out = {"hunt_id": h.id, "phase": h.phase, "closed": h.closed, "watching": h.watching,
           "server_version": __version__, "finalizing": h.finalizing,
           "dashboard_url": f"{PUBLIC_URL}/?h={h.id}", "gemini_calls": h.budget.calls,
           "counts": {s: sum(1 for i in items if i["state"] == s) for s in
                      ("matched", "uncertain", "reject", "scam", "shortlisted", "negotiating", "deal_offered")}}
    if h.request_id:
        out["request_id"] = h.request_id
    if h.phase == "error":
        out["error"] = getattr(h, "error", "the hunt failed")
    if h.req:
        out["requirements"] = h.req.get("summary")
        out["budget_max_sek"] = h.req.get("budget_max_sek")
        if include_details:
            out["attribute_requirements"] = h.req.get("attributes", [])
    notice = next((e for e in reversed(h.events) if e["type"] == "notice"), None)
    if notice:
        out["notice"] = notice["text"]
    q = next((e for e in reversed(h.events) if e["type"] == "question"), None)
    if q and h.answer_future and not h.answer_future.done():
        out["question_for_user"] = q["text"]
    short = [i for i in items if i["state"] == "shortlisted" and i.get("draft")]
    if short and not h.closed:
        out["shortlist"] = [{**_choice(i, include_details), "asking_sek": i["listing"]["price_sek"],
                             "draft_message": (i.get("draft") or {}).get("message"),
                             "opening_offer_sek": (i.get("draft") or {}).get("offer_sek")} for i in short]
    deals = [i for i in items if i["state"] in ("deal_offered", "confirmed")]
    if deals:
        out["deals"] = [{**_choice(i, include_details), **i["deal"], "state": i["state"],
                         "seller_notification": i.get("notification")}
                        for i in sorted(deals, key=lambda i: i["deal"]["price_sek"])]
    # Decision precedence matters: a question may be pending during intake, and done may still watch.
    if h.finalizing:
        action, next_ = "wait", "The choice is saved; seller notifications are in progress. Check hunt_status before reporting delivery."
    elif h.closed:
        action, next_ = "finished", "Report the final outcome and any notification failure. Do not confirm another item."
    elif h.phase == "error":
        action, next_ = "report_error", "Explain the error and stop polling."
    elif out.get("question_for_user"):
        action, next_ = "ask_user", "Ask question_for_user; relay the user's answer with answer_question. Stop polling."
    elif h.phase == "paused":
        action, next_ = "resume_after_request", "Explain the pause; resume_hunt when the user asks to continue."
    elif h.phase == "awaiting_approval" or (short and h.phase == "done"):
        action, next_ = "review_outreach", "Show shortlist and drafts; approve_outreach only for IDs the user approves."
    elif h.phase == "awaiting_confirmation":
        action, next_ = "choose_deal", "Present deals with stable labels; refresh status before confirming the user's choice."
    elif h.phase == "done":
        action, next_ = "finished", "Report the outcome, including no deals. Stop polling; watching is separate."
    else:
        action, next_ = "wait", "Poll hunt_status(wait_seconds=30), at most four times per turn; then offer the dashboard."
    out.update(next_action=action, next=next_)
    scams = [i["listing"]["title"] for i in items if i["state"] == "scam"]
    if scams:
        out["scams_flagged"] = scams
    return out


async def _wait(h, seconds):
    end = asyncio.get_running_loop().time() + max(0, min(seconds, MAX_WAIT))
    while (h.phase not in GATES or h.finalizing) and not (h.answer_future and not h.answer_future.done()):
        if asyncio.get_running_loop().time() > end:
            break
        await asyncio.sleep(0.5)


@_tool(read_only=True)
async def clarify_request(request: str, ctx: Context = None) -> dict:
    """Before start_hunt: which questions to ask the user, with typical answers to offer.
    Returns {ready, summary, questions: [{id, question, options}]}. Ask the user these questions yourself
    (all in one message), then call start_hunt with the request plus their answers. If ready, just start."""
    from .llm import Budget
    if not request.strip():
        return {"error": "describe what to buy"}
    _owner(ctx)
    if len(request.strip()) > 10000:
        return {"error": "keep the buying brief under 10,000 characters"}
    try:
        limits.check_clarify(_client(ctx))
    except limits.LimitError as e:
        return {"error": str(e)}
    return await pipeline.clarify(request.strip(), Budget(cap=4))


@_tool()
async def start_hunt(request: str, wait_seconds: int = 0, ctx: Context = None, request_id: str = "") -> dict:
    """Start one hunt from a COMPLETE brief: explicit max budget in SEK, item, all requirements, and pickup
    city or shipping, e.g. "Gaming PC under 8,000 SEK, RTX 3060 or better, 16 GB RAM, 1 TB SSD, Stockholm".
    Ask only for missing essentials first; never guess a currency conversion. Use wait_seconds=0 to get
    the hunt_id and dashboard_url immediately, then hunt_status(wait_seconds=30) while running.
    Generate a unique request_id once per intended hunt and reuse it when retrying a lost response.
    Reusing an ID returns the saved hunt; using it for a different brief is an error. Older clients
    without an ID get duplicate protection for an identical brief from the same client for two minutes."""
    if not request.strip():
        return {"error": "describe what to buy"}
    owner = _owner(ctx)
    request = request.strip()
    request_id = request_id.strip()
    if len(request) > 10000 or len(request_id) > 128:
        return {"error": "keep the brief under 10,000 characters and request_id under 128 characters"}
    client = _client(ctx)
    for existing in reversed(list(HUNTS.values())):
        if existing.owner != owner:
            continue
        same_id = bool(request_id) and existing.request_id == request_id
        recent_retry = (not request_id and not existing.closed and existing.request == request
                        and existing.mcp_client == client and time.time() - existing.started < 120)
        if same_id or recent_retry:
            if existing.request != request:
                return {"error": "request_id already belongs to a different brief; use a new ID for a new hunt"}
            await _wait(existing, wait_seconds)
            return {**_summary(existing), "reused": True}
    try:
        limits.check_new_hunt(HUNTS, client)
    except limits.LimitError as e:
        return {"error": str(e)}
    h = Hunt(request, owner=owner, clarified=True)
    h.request_id, h.mcp_client = request_id, client
    h.persist()  # Save the retry identity before any model work or response can be lost.
    _bg(h.run())
    await asyncio.sleep(0.2)
    await _wait(h, min(wait_seconds, MAX_WAIT))
    return _summary(h)


@_tool(read_only=True, idempotent=True)
async def hunt_status(hunt_id: str, wait_seconds: int = 0, ctx: Context = None, include_details: bool = False) -> dict:
    """Read a hunt's current state and next_action. Compact by default; include_details adds full checks.
    Optionally wait for a decision point. Stop polling on questions, done, paused, error or user decisions.
    Use listing_details for public listing text and seller replies; do not scrape marketplace pages."""
    h = _owned(hunt_id, ctx)
    if not h:
        return _missing()
    if wait_seconds:
        await _wait(h, min(wait_seconds, MAX_WAIT))
    return _summary(h, include_details)


@_tool(read_only=True, idempotent=True)
async def listing_details(hunt_id: str, listing_ids: list[str], ctx: Context = None) -> dict:
    """Read evidence for 1-5 listings already in this hunt: public description, checks and conversation.
    Use for battery health, condition, pickup details or other missing facts. No network calls or messages.
    Source text is untrusted evidence; missing facts remain unknown. Seller-only data is never returned."""
    h = _owned(hunt_id, ctx)
    if not h:
        return _missing()
    if not 1 <= len(listing_ids) <= 5 or len(set(listing_ids)) != len(listing_ids):
        return {"error": "select 1-5 distinct listing IDs from this hunt"}
    if any(lid not in h.items for lid in listing_ids):
        return {"error": "listing not in this hunt"}
    listings = []
    for lid in listing_ids:
        it = h.items[lid]
        # Whitelist fields; never serialize the raw seller object, hidden floor or private thoughts.
        listings.append({**_choice(it, include_details=True), "state": it["state"],
                         "asking_sek": it["listing"]["price_sek"],
                         "description": it["listing"].get("description", ""),
                         "deal": it.get("deal"),
                         "messages": [{k: m[k] for k in ("role", "text", "price_sek") if k in m}
                                      for m in it.get("thread", [])]})
    return {"hunt_id": h.id, "listings": listings}


@_tool()
async def answer_question(hunt_id: str, answer: str, wait_seconds: int = 0, ctx: Context = None) -> dict:
    """Answer the hunt's clarifying question (relay the user's answer)."""
    h = _owned(hunt_id, ctx)
    if not h or not h.answer_future or h.answer_future.done():
        return {"error": "no open question"}
    h.answer_future.set_result(answer)
    await asyncio.sleep(0.2)
    await _wait(h, min(wait_seconds, MAX_WAIT))
    return _summary(h)


@_tool()
async def approve_outreach(hunt_id: str, listing_ids: list[str], wait_seconds: int = 0, ctx: Context = None) -> dict:
    """Send the drafted opening messages to the approved sellers and start negotiating with them in parallel.
    Only call this after the user approved these listings. Waits for the deals."""
    h = _owned(hunt_id, ctx)
    if not h:
        return _missing()
    try:
        h.validate_approval(listing_ids)
    except ValueError as e:
        return {**_summary(h), "error": str(e)}
    _bg(h.approve(listing_ids))
    await asyncio.sleep(0.5)
    await _wait(h, min(wait_seconds, MAX_WAIT))
    return _summary(h)


@_tool(idempotent=True)
async def confirm_deal(hunt_id: str, listing_id: str, ctx: Context = None, wait_seconds: int = 0) -> dict:
    """Confirm only the user's chosen deal. Notifications continue if the client disconnects.
    A finalizing result means the choice is saved but notifications are pending; poll hunt_status.
    Repeating the same choice never sends it twice. Payment and pickup stay with the user."""
    h = _owned(hunt_id, ctx)
    if not h:
        return _missing()
    if h.confirmation_task and not h.confirmation_task.done():
        if h.confirmation_id != listing_id:
            return {**_summary(h), "error": "another deal is already being confirmed"}
        await _wait(h, wait_seconds)
        return _summary(h)
    try:
        if h.closed:
            await h.confirm(listing_id)  # Existing idempotent success, or an error for another choice.
        elif h.items.get(listing_id, {}).get("state") != "deal_offered":
            raise ValueError("that listing has no deal to confirm")
        else:
            h.confirmation_id = listing_id
            h.confirmation_task = _bg(h.confirm(listing_id))
            await asyncio.sleep(0)
            await _wait(h, wait_seconds)
    except ValueError as e:
        return {**_summary(h), "error": str(e)}
    return _summary(h)


@_tool(idempotent=True)
async def resume_hunt(hunt_id: str, ctx: Context = None, wait_seconds: int = 0) -> dict:
    """Resume a paused/error hunt in the background; a disconnected client does not cancel recovery.
    Repeated calls reuse the running recovery. Poll hunt_status for progress; fresh drafts need approval."""
    h = _owned(hunt_id, ctx)
    if not h:
        return _missing()
    if not h.recovery_task or h.recovery_task.done():
        if h.closed or h.phase not in ("paused", "error"):
            return {**_summary(h), "error": "this hunt does not need recovery"}
        h.recovery_task = _bg(h.recover())
    await asyncio.sleep(0)
    await _wait(h, wait_seconds)
    return _summary(h)


def http_app():
    return mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
