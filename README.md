# haggle

**Your agent finds it, vets it, and haggles for it.**

Buying used is cheaper and better for the planet, but it's miserable: dozens of messy listings in Swedish
and English, specs that are missing or wrong, scams that look like bargains, and then haggling with
strangers. haggle turns one sentence into a negotiated deal:

> "I want a gaming PC for under 8,000 SEK. At least an RTX 3060 or equivalent, 16 GB RAM, 1 TB SSD.
> Pickup in Stockholm or shipping. Used is fine."

…typed or **spoken** (Gemini 3.5 Transcribe, Swedish or English), and about a minute later:
*"Seller in Huddinge accepted 5,500 kr (asking 6,500). Confirm?"*

Built at the {Tech: Europe} × Google DeepMind Agentic AI Hack, Stockholm, 3 October 2026.

haggle is an **MCP server**: plug it into Gemini CLI, Claude Code, Codex or Cursor and your agent can shop
second-hand for you. It also has a live web dashboard that shows every hunt (whether an agent or a person
started it), with the negotiations running side by side.

## Try it

**Live demo:** https://haggle-p61s.onrender.com (open, no sign-in; `?replay=1` replays a recorded run with no API calls). It's a free instance, so the first request after a
quiet spell can take about a minute to wake it up.

**Gemini CLI: one-command install** (MCP server + skill):

```bash
gemini extensions install https://github.com/Zawaer/haggle
```

**Claude Code** (same skill, same MCP server):

```bash
claude mcp add --transport http haggle https://haggle-p61s.onrender.com/mcp/
git clone https://github.com/Zawaer/haggle && mkdir -p ~/.claude/skills && cp -r haggle/skills/haggle ~/.claude/skills/
```

**Gemini app** (gemini.google.com → Skills): paste the skill from `skills/gemini-app.md`. It asks the
questions in chat and hands you a link that starts the hunt in the dashboard.

Then just say *"I want a PC"*. The skill (`skills/haggle/SKILL.md`, the same file for Claude Code and
Gemini CLI) makes the agent ask what's missing in one message: budget, desktop or laptop, what it's for,
pickup or shipping. Then it starts the hunt and gives you the dashboard link, shows you the shortlist and
drafted messages, and asks before contacting sellers. Later it shows the deals and asks which one to
confirm. haggle itself never asks follow-up questions: the agent (or the web app's question card) does.
Everything is simulated: mockbay listings and simulated sellers. No real purchases or messages.

Tools: `clarify_request`, `start_hunt`, `hunt_status`, `answer_question`, `approve_outreach`, `confirm_deal`, `resume_hunt`. Each call
waits at most ~75 s for the next decision point; the agent polls `hunt_status` until then.

## What the agent does

```
User request
  1. Intake      Gemini turns free text into structured requirements, limits and search queries
                 (asks one clarifying question if something essential is ambiguous)
  2. Search      several Swedish + English queries on mockbay (or the local mock dataset)
  3. Extract     Gemini reads each messy listing → structured specs, with verbatim evidence;
                 unknowns stay unknown, title/description contradictions are reported
  4. Match & vet deterministic code: pass / fail / uncertain per requirement, GPU equivalence from a
                 benchmark tier table (not LLM memory), scam score from price-vs-market, account age,
                 prepayment/shipping-only wording and the LLM's risk signals
  5. Rank        explainable score: price headroom, spec margin, unknowns, risk, distance, reputation
  6. Outreach    drafted opening messages in the seller's language, asking about missing specs.
                 Nothing is sent until the user approves.
  7. Negotiate   one thread per seller, all in parallel, run by the orchestrator
  8. Handoff     deals ranked; the user confirms one; every other seller is released politely
```

### The orchestrator: code owns state, LLMs propose

Each listing moves through a state machine
(`found → extracted → matched/uncertain/rejected/scam → shortlisted → approved → negotiating →
deal_offered | walked_away | dropped | seller_declined → confirmed | released`).
The outgoing price and message rules are enforced in code; reading seller facts still depends on model extraction:

- **No message without approval.** Drafts are shown; the user approves which sellers to contact.
- **Budget ceiling.** Invalid prices are rejected and the agent must rewrite its move. Seller-facing prices, claims and commitment language are rendered from validated data.
- **No false leverage.** The agent may only cite a competing offer that really exists in another live
  thread; otherwise the claim is blocked (shown in the UI as a guardrail event).
- **Specs re-checked mid-chat.** When a seller reveals a spec ("it's a GTX 1070"), the listing is
  re-matched and drops out automatically.
- **Message limit** per seller, **no prepayment** to unverified sellers, and **never commits to buy**:
  an agreed price is "reserved pending my client's confirmation".
- **Call budget** per hunt and retries with a fallback model on 503s.

### Watch mode

After the first deals, haggle keeps watching the marketplace (every 15 s by default, for up to 3 hours) from
the always-on machine it runs on (our Matrix OS cloud computer). A new listing that matches is read,
vetted and scam-checked; the agent drafts a message and **waits for the user's approval** before contacting
the seller; then it negotiates and the new deal joins the handoff. Watching stops when a deal is confirmed.

## Historical results

These results predate the guardrail and recovery fixes below. They have not been rerun with live model credentials.

Evaluated against the mock marketplace's hidden ground truth (`eval/eval_vetting.py`):

| | |
|---|---|
| Vetting verdicts correct | **41 / 42 (98%)** |
| Scams caught | **5 / 5**, 0 false alarms |
| Real matches kept | **12 / 12** |

Negotiation benchmark, 3 full hunts, 15 seller threads (`eval/eval_negotiation.py`):

| | |
|---|---|
| Deals reached | **12 / 15** (the other 3: listing dropped mid-chat when the seller revealed a GTX 1070) |
| Share of the available discount captured | **98.8%** (asking → seller's hidden minimum) |
| Average saving | **917 kr per deal, 12.5% below asking** |
| Deals over budget | **0** |
| Per hunt | **~54 s, ~61 Gemini calls** |

With **condense** compression on (2 runs, 10 threads): **100%** of the available discount captured, 0 deals
over budget, 857 kr saved per deal. These unpaired simulated runs do not establish unchanged negotiation quality.

Caveat: the sellers are simulated (Gemini with a hidden minimum price and a personality), so this measures
the agent against our seller model, not real people.

## Live sellers: the seller inbox

Every conversation runs through haggle's message hub. Open **`/inbox`** on another device to see all
threads live and **play any seller yourself** ("Play this seller" before the agent writes, or take over
mid-chat). Every other seller is played by a simulated seller with a hidden minimum price. Seller messages
are untrusted input: attempts to steer the agent ("your client already approved 9,000 kr", "SYSTEM: …",
"Swish first") are caught by a deterministic check plus the LLM reader, shown as a RULE event, and the
agent's limits stay unchanged.

## Why a mock marketplace

The demo uses a purpose-built mock marketplace and simulated seller conversations. By default haggle searches **mockbay**
(https://agentic-hack-mock-marketplace.vercel.app), our team's mock marketplace site, over its HTTP API;
`HAGGLE_MARKET=local` switches to the built-in dataset used for the evals: 42 listings (Swedish and English,
good, mismatched, vague, lying and scammy) with hidden ground truth, and **simulated sellers** played by
Gemini, each with a hidden minimum price, a personality and the true specs of their item. The buyer agent
never sees the hidden data. Swapping in a real source requires authorized search and messaging APIs, conversation isolation, and provider-specific verification.

Tomorrow the seller side may be an agent too: the same orchestrator then acts as a neutral referee
between two agents.

## Tech

- **Google Gemini** via the Interactions API (`google-genai` Python SDK):
  - `gemini-3.8-flash`: intake, listing extraction, buyer negotiation agent (structured JSON output,
    low thinking for speed)
  - `gemini-3.5-flash-lite`: simulated sellers, reading human sellers' replies, fallback model on 503s
  - `gemini-3.5-transcribe`: voice input (custom vocabulary for hardware names and Stockholm places)
- Python 3.14, FastAPI, Server-Sent Events for the live UI, asyncio for parallel threads
- Vanilla HTML/CSS/JS frontend (no build step)
- **Matrix OS**: haggle runs on our Matrix cloud computer (the always-on machine that keeps hunting and
  watching), viewed through `matrix forward 3123`
- **condense.chat**: context compression for the negotiation agents (`/v1/compress`): the listing text and
  chat history older than the last two messages are compressed before every buyer turn; latest messages stay
  verbatim; extraction is never compressed (condense is lossy). Shown as "condense: −X% selected-text characters".
  Set `CONDENSE_AUTH_TOKEN` in `.env`; `HAGGLE_CONDENSE=0` turns it off.
- **MCP** server (Python MCP SDK, streamable HTTP), tested with Gemini CLI

## Run it

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.lock   # or: scripts/run.sh
echo "GEMINI_API_KEY=your-key" > .env          # never commit this; keep credentials out of Git
.venv/bin/uvicorn haggle.server:app --host 127.0.0.1 --port 3123
```

Open http://localhost:3123. Click **Speak** to say your request instead of typing it (Gemini 3.5 Transcribe,
Swedish or English). Set `HAGGLE_HOST_LABEL="Matrix OS"` in `.env` to show where it runs in the footer. Add `?replay=1` to replay a recorded run with no API calls (offline demo).

Headless: `.venv/bin/python run_cli.py` runs a whole hunt in the terminal and auto-approves the shortlist.
Evaluation: `.venv/bin/python -m eval.eval_vetting`.

## API

| Method | Path | |
|---|---|---|
| POST | `/api/hunts` `{"request", "replay"}` | start a hunt → `{"id"}` |
| GET | `/api/hunts/{id}/events?start=N` | SSE stream of every event |
| POST | `/api/hunts/{id}/answer` `{"text"}` | answer the agent's clarifying question |
| POST | `/api/hunts/{id}/approve` `{"ids"}` | approve outreach → negotiations start |
| POST | `/api/hunts/{id}/confirm` `{"id"}` | confirm a deal; other sellers are released |
| GET | `/api/hunts/{id}` | snapshot |
| POST | `/api/market/listings` `{"title","description","price_sek","location",…}` | demo: publish a listing on the built-in mock (watch mode finds it) |

Approving also works after the first handoff, for listings found by watch mode. Extra events:
`watch {active, interval, text}`, `watch_hit {id, text}`, and `found` carries `new: true` for listings
found by watch mode.

## MCP details

The server also speaks MCP (streamable HTTP) at **`/mcp/`**, sharing hunts with the web UI, so an authenticated user can open a hunt started from an agent chat in the browser. Tools: `start_hunt`, `hunt_status`,
`answer_question`, `approve_outreach`, `confirm_deal`, `resume_hunt`. The agent must get the user's OK before approving
outreach or confirming a deal.

Tool results include `dashboard_url`; set `HAGGLE_PUBLIC_URL` when it cannot be detected.

```json
{ "mcpServers": { "haggle": { "type": "http", "url": "http://localhost:3123/mcp/" } } }
```

## Hosting

- **Public demo: Render.** `render.yaml` is a one-click blueprint:
  https://render.com/deploy?repo=https://github.com/Zawaer/haggle (Render asks for `GEMINI_API_KEY` and
  `CONDENSE_AUTH_TOKEN`, and `HAGGLE_ACCESS_TOKEN`; they're never stored in the repo).
  The free plan has ephemeral storage: restarts may lose saved hunts. Use a persistent disk
  and point `HAGGLE_DB` at it for durable recovery. `/healthz` is public; app and API routes require authentication.
  Public abuse limits live in `haggle/limits.py`: max 4 live hunts at once, 40 per hour (8 per authenticated user),
  and 5,000 Gemini calls per day. Replay is always available.
- **Personal always-on instance: Matrix OS.** `scripts/run.sh` on our Matrix cloud computer; it keeps
  hunting and watching while the laptop is closed.

## Layout

```
haggle/config.py        models, limits, guardrail numbers
haggle/llm.py           Gemini wrapper: structured output, retries, fallback, call budget
haggle/pipeline.py      intake, extraction, deterministic matching, scam scoring, ranking
haggle/tiers.py         GPU benchmark tier table + name normalisation ("3060ti", "rx6700xt")
haggle/negotiation.py   buyer agent and simulated seller agents
haggle/orchestrator.py  state machine, guardrails, parallel negotiations, event log
haggle/replay.py        replays a recorded run (offline fallback)
haggle/server.py        FastAPI + SSE
haggle/mcp_server.py    MCP tools for other agents (mounted at /mcp/)
haggle/limits.py        abuse limits for the public deployment
render.yaml             Render blueprint (public demo)
haggle/market_http.py   client for the external mock marketplace site
seller_bot.py           plays sellers on the external marketplace (unless a human takes over)
tools/reference_market.py  minimal reference implementation of the marketplace API
web/                    frontend
data/listings.json      mock marketplace with hidden ground truth (data/gen_listings.py generates it)
eval/eval_vetting.py    accuracy against ground truth
```

## Team

Oskar, Songhua, Toivo, Wilmer, Rene.


## Authentication, storage and recovery

The public demo is open: no sign-in for the app, REST API or MCP (everyone shares one owner; the abuse
limits in `haggle/limits.py` apply per IP). Login is opt-in: set `HAGGLE_REQUIRE_LOGIN=1` and the server
requires an access token for everything (it writes a random one to `runs/access-token`, owner-readable
only; open `/login` and paste it). Alternatively set `HAGGLE_ACCESS_TOKEN`, or `HAGGLE_USERS` to a JSON object mapping usernames to unique
random tokens (at least 16 characters). Each user's hunts and inboxes are private to that user. Browser
sessions use HttpOnly, same-site cookies; REST/MCP clients send `Authorization: Bearer <token>`.
Use HTTPS when exposing the app beyond localhost. The demo seller inbox uses the same authenticated
user on another device; do not share credentials with untrusted real sellers.

SQLite stores hunt state, event history, budgets and isolated inboxes in `runs/haggle.sqlite3`.
Override with `HAGGLE_DB`. Run **one server process / one Uvicorn worker**; multi-worker coordination is
not implemented. Protect and back up `runs/`, which contains private conversations and credentials.
Completed hunts and approval gates survive restarts. Interrupted negotiations are paused, not silently
resent: use **Resume hunt**, review the fresh status-question drafts, then approve outreach again.
Uncertain confirmation/release delivery is reported for manual checking, never automatically replayed.
Watch jobs resume within their original deadline; extraction failures are retried and exhausted budgets
stop watching explicitly. Saved hunts are listed on the home page. No email or push notifications exist.

## Supported scope and safety

This version checks desktop PCs, laptops and graphics cards: category, GPU, RAM, storage, condition,
location and price. Unsupported hard requirements (for example CPU model or warranty) are surfaced as
errors instead of silently ignored; general-purpose shopping is not implemented. Explicitly disallowed
GPU equivalents and used items are rejected. Unknown required facts must be resolved before a deal.
Seller replies are read before acceptance, including disclosed specifications, extra shipping costs,
and prepayment. A model decides strategy; code renders outgoing questions, prices and verified leverage.
The rendered draft is what the user approves. Prices refer to totals including shipping; unresolved
conditions prevent a deal. Reaching the message limit does not fabricate agreement.

Confirmation stops negotiations and watching, sends a final handoff message to the selected simulated
seller, and releases the others. No payment is made. Replay honors seller selection and never sends to
an external marketplace. Stored benchmark results predate these changes and are **not** evidence that
the updated implementation achieves the same negotiation performance.

## Marketplace and verification

The default source is the team's [mockbay site](https://agentic-hack-mock-marketplace.vercel.app/), using
its public `/api/listings` API, including pagination. This is a live catalogue integration, with seller
conversations simulated in Haggle's isolated inboxes. Set `HAGGLE_MARKET=local` for fully local fixtures.
Provider failures remain visible; opt into local fallback with `HAGGLE_ALLOW_LOCAL_FALLBACK=1`.
The separate `HAGGLE_MARKET_URL` adapter is for the reference messaging API; it requires a `conversation`
field on messages and a matching query filter. Legacy servers without that isolation contract are not
supported. It is not the mockbay catalogue API. Matrix OS deployment is separate from local testing.

Run the credential-free regression suite:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q haggle eval tools run_cli.py seller_bot.py
node --check web/app.js
```

CI installs `requirements.lock` and runs these checks on Python 3.11 and 3.12. Regenerate the lock with
`uv pip compile requirements.txt --generate-hashes -o requirements.lock`. Live Gemini/Condense evaluation
requires your own credentials; automated tests substitute controlled model/provider responses. The
negotiation benchmark explicitly uses local fixtures and records compression/model configuration.
Compression savings measure selected-text characters, include fallback traffic, and do not measure
full-prompt tokens or money saved. Compression is optional, bounded by a per-hunt request cap and a
bounded, expiring in-memory cache. No compression-quality claim is made from the small historical sample.
