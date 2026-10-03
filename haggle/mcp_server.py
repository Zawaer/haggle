"""MCP server: lets other agents (Matrix OS Chat, Claude, Gemini CLI, …) use haggle as a tool.

Mounted on the main server at /mcp (streamable HTTP), sharing the same hunts as the web UI, so a hunt
started from an agent chat shows up live in the browser too.

Tools: start_hunt -> hunt_status (optionally waits for the next decision point) -> approve_outreach ->
hunt_status -> confirm_deal. The human stays in the loop: the agent relays the shortlist and deals, and
must get the user's OK before approving or confirming.
"""
import asyncio

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from .orchestrator import HUNTS, Hunt

mcp = MCPServer(
    name="haggle",
    instructions="haggle finds, vets and negotiates second-hand purchases (mock Blocket/Tradera/Facebook Marketplace). "
                 "Start a hunt, show the user the shortlist and drafted messages, and ONLY call approve_outreach / "
                 "confirm_deal after the user explicitly agrees.",
)
_tasks = set()
GATES = ("awaiting_approval", "awaiting_confirmation", "done")


def _bg(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def _summary(h):
    items = h.items.values()
    out = {"hunt_id": h.id, "phase": h.phase, "gemini_calls": h.budget.calls,
           "counts": {s: sum(1 for i in items if i["state"] == s) for s in
                      ("matched", "uncertain", "reject", "scam", "shortlisted", "negotiating", "deal_offered")}}
    if h.req:
        out["requirements"] = h.req.get("summary")
    q = next((e for e in reversed(h.events) if e["type"] == "question"), None)
    if q and h.answer_future and not h.answer_future.done():
        out["question_for_user"] = q["text"]
    short = [i for i in items if i["state"] in ("shortlisted",) or i.get("draft")]
    if h.phase == "awaiting_approval":
        out["shortlist"] = [{"listing_id": i["id"], "title": i["listing"]["title"], "asking_sek": i["listing"]["price_sek"],
                             "location": i["listing"]["location"], "score": i.get("score"),
                             "draft_message": (i.get("draft") or {}).get("message"),
                             "opening_offer_sek": (i.get("draft") or {}).get("offer_sek")} for i in short]
        out["next"] = "Show the shortlist and drafts to the user; call approve_outreach with the ids they approve."
    deals = [i for i in items if i["state"] in ("deal_offered", "confirmed")]
    if deals:
        out["deals"] = [{"listing_id": i["id"], "title": i["listing"]["title"], **i["deal"], "state": i["state"]}
                        for i in sorted(deals, key=lambda i: i["deal"]["price_sek"])]
    if h.phase == "awaiting_confirmation":
        out["next"] = "Present the deals; call confirm_deal with the one the user picks. The agent never pays."
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
async def start_hunt(request: str, wait_seconds: int = 90) -> dict:
    """Start a hunt for a second-hand item described in plain language (budget, specs, location).
    Waits up to wait_seconds for the shortlist (or a clarifying question) and returns the status."""
    h = Hunt(request.strip())
    _bg(h.run())
    await asyncio.sleep(0.2)
    await _wait(h, min(wait_seconds, 120))
    return _summary(h)


@mcp.tool()
async def hunt_status(hunt_id: str, wait_seconds: int = 0) -> dict:
    """Current status of a hunt: phase, shortlist + drafted messages, deals. Optionally wait for the next decision point."""
    h = HUNTS.get(hunt_id)
    if not h:
        return {"error": "no such hunt"}
    if wait_seconds:
        await _wait(h, min(wait_seconds, 120))
    return _summary(h)


@mcp.tool()
async def answer_question(hunt_id: str, answer: str, wait_seconds: int = 90) -> dict:
    """Answer the hunt's clarifying question (relay the user's answer)."""
    h = HUNTS.get(hunt_id)
    if not h or not h.answer_future or h.answer_future.done():
        return {"error": "no open question"}
    h.answer_future.set_result(answer)
    await asyncio.sleep(0.2)
    await _wait(h, min(wait_seconds, 120))
    return _summary(h)


@mcp.tool()
async def approve_outreach(hunt_id: str, listing_ids: list[str], wait_seconds: int = 110) -> dict:
    """Send the drafted opening messages to the approved sellers and start negotiating with them in parallel.
    Only call this after the user approved these listings. Waits for the deals."""
    h = HUNTS.get(hunt_id)
    if not h:
        return {"error": "no such hunt"}
    if h.phase != "awaiting_approval":
        return {"error": f"can't approve in phase {h.phase}"}
    _bg(h.approve(listing_ids))
    await asyncio.sleep(0.5)
    await _wait(h, min(wait_seconds, 120))
    return _summary(h)


@mcp.tool()
async def confirm_deal(hunt_id: str, listing_id: str) -> dict:
    """Confirm the deal the user picked. Other sellers are released politely. Payment and pickup stay with the user."""
    h = HUNTS.get(hunt_id)
    if not h:
        return {"error": "no such hunt"}
    try:
        await h.confirm(listing_id)
    except ValueError as e:
        return {"error": str(e)}
    return _summary(h)


def http_app():
    return mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
