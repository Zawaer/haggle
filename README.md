# haggle.

**Your agent finds it, vets it, and haggles for it.**

![How haggle works](docs/architecture.png)

## The problem

Buying second-hand is cheaper and better for the planet, but it's a pain:

- dozens of messy listings, in Swedish and English
- specs that are missing or wrong
- scams that look like bargains
- haggling with strangers, one chat at a time

## Our solution

Describe what you want in one sentence, typed or spoken. haggle searches the marketplace, reads and
vets every listing, flags scams and shows you the best fits. Once you approve, it negotiates with
several sellers in parallel. Nothing is sent and nothing is bought without your OK.

Two parts, kept strictly apart:

- **Shopper** – a Gemini agent that searches, reads listings and haggles.
- **Referee** – plain code that checks every move the Shopper proposes: budget cap, no false claims,
  message limits, and your approval before anything is sent.

You can use haggle from an AI chat (Gemini CLI, Claude Code, Codex via MCP) or from our own web page.

## Try it

**Web page:** https://haggle-p61s.onrender.com/

It runs on a free instance, so the first visit after a quiet spell can take about a minute to wake up.
Add `?replay=1` to watch a recorded hunt.

**From your AI chat (MCP):** connect haggle and just ask for what you want.

```bash
# Gemini CLI (extension: MCP connection + shopping skill + /haggle command)
gemini extensions install https://github.com/Zawaer/haggle

# Claude Code (plugin: MCP connection + shopping skill)
claude plugin marketplace add Zawaer/haggle
claude plugin install haggle@haggle-marketplace --scope user

# or add the MCP server directly
claude mcp add --transport http haggle https://haggle-p61s.onrender.com/mcp/
gemini mcp add --scope user --transport http --timeout 600000 haggle https://haggle-p61s.onrender.com/mcp/
codex mcp add haggle --url https://haggle-p61s.onrender.com/mcp/
```

Then ask:

> "Use haggle to find me a used gaming PC under 8,000 kr in Stockholm, at least an RTX 3060."

Your agent starts a hunt, sends you a link to watch it live, and asks you before contacting sellers
and before confirming a deal. [Setup, updates and troubleshooting](docs/mcp.md).

## Tech

- **Google Gemini** (Interactions API, `google-genai`): intake, listing extraction, buyer agent,
  simulated sellers, voice input (Gemini Transcribe)
- **MCP** server (streamable HTTP), so any AI chat can use haggle as a tool
- **Python + FastAPI**, Server-Sent Events for the live dashboard, asyncio for parallel negotiations
- **Vanilla HTML/CSS/JS** web page, no build step
- **Matrix OS** – the always-on cloud computer haggle runs on
- **condense.chat** – compresses negotiation context before each buyer turn
- **mockbay** – our mock second-hand marketplace with simulated sellers (no real purchases or messages)

## Team

Oskar, Songhua, Toivo, Wilmer, Rene. Built at the {Tech: Europe} × Google DeepMind Agentic AI Hack,
Stockholm, 3 October 2026.
