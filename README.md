# haggle

**Your agent finds it, vets it, and haggles for it.**

Buying used is cheaper and better for the planet, but it's miserable: dozens of messy listings in Swedish
and English, specs that are missing or wrong, scams that look like bargains, and then haggling with
strangers. haggle turns one sentence into a negotiated deal:

> "I want a gaming PC for under 8,000 SEK. At least an RTX 3060 or equivalent, 16 GB RAM, 1 TB SSD.
> Pickup in Stockholm or shipping. Used is fine."

…and about a minute later: *"Seller in Huddinge accepted 5,500 kr (asking 6,500). Confirm?"*

Built at the {Tech: Europe} × Google DeepMind Agentic AI Hack, Stockholm, 3 October 2026.

## What the agent does

```
User request
  1. Intake      Gemini turns free text into structured requirements, limits and search queries
                 (asks one clarifying question if something essential is ambiguous)
  2. Search      several Swedish + English queries across Blocket, Tradera, Facebook Marketplace (mock)
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
The rules are enforced in code, not in prompts:

- **No message without approval.** Drafts are shown; the user approves which sellers to contact.
- **Budget ceiling.** Offers above the user's limit are capped and the agent must rewrite its move.
- **No false leverage.** The agent may only cite a competing offer that really exists in another live
  thread; otherwise the claim is blocked (shown in the UI as a guardrail event).
- **Specs re-checked mid-chat.** When a seller reveals a spec ("it's a GTX 1070"), the listing is
  re-matched and drops out automatically.
- **Message limit** per seller, **no prepayment** to unverified sellers, and **never commits to buy**:
  an agreed price is "reserved pending my client's confirmation".
- **Call budget** per hunt and retries with a fallback model on 503s.

## Results

Evaluated against the mock marketplace's hidden ground truth (`eval/eval_vetting.py`):

| | |
|---|---|
| Vetting verdicts correct | **41 / 42 (98%)** |
| Scams caught | **5 / 5**, 0 false alarms |
| Real matches kept | **12 / 12** |

A full hunt (42 listings searched, 38 vetted, 5 parallel negotiations) takes **~50 seconds and ~60
Gemini calls**. In recorded runs the agent negotiated 600–1,400 kr below asking per deal, usually
landing on the seller's hidden minimum.

## Why a mock marketplace

Scraping and automated messaging on real marketplaces conflict with their terms of service, and bots
messaging real people is spam. So the demo runs on a realistic mock: 42 listings (Swedish and English,
good, mismatched, vague, lying and scammy) with hidden ground truth, and **simulated sellers** played by
Gemini, each with a hidden minimum price, a personality and the true specs of their item. The buyer agent
never sees the hidden data. Swapping in a real source means implementing `marketplace.search` against a
partner API.

Tomorrow the seller side may be an agent too: the same orchestrator then acts as a neutral referee
between two agents.

## Tech

- **Google Gemini** via the Interactions API (`google-genai` Python SDK):
  - `gemini-3.8-flash`: intake, listing extraction, buyer negotiation agent (structured JSON output,
    low thinking for speed)
  - `gemini-3.5-flash-lite`: simulated sellers and fallback model on 503s
- Python 3.11, FastAPI, Server-Sent Events for the live UI, asyncio for parallel threads
- Vanilla HTML/CSS/JS frontend (no build step)
- Partner technologies: Google DeepMind (Gemini), and _TBD: Matrix OS / condense.chat_

## Run it

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt   # or: scripts/run.sh
echo "GEMINI_API_KEY=your-key" > .env          # never commit this; a pre-commit hook blocks keys
.venv/bin/uvicorn haggle.server:app --host 0.0.0.0 --port 3123
```

Open http://localhost:3123. Add `?replay=1` to replay a recorded run with no API calls (offline demo).

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
web/                    frontend
data/listings.json      mock marketplace with hidden ground truth (data/gen_listings.py generates it)
eval/eval_vetting.py    accuracy against ground truth
```

## Team

Oscar, Sumhua, Toivo, Wilmer, René.
