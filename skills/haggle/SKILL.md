---
name: haggle
description: Buy second-hand products of any kind for the user with the haggle MCP server. Use when the user wants to buy something used, including electronics, furniture, bicycles, clothing and appliances ("I want a gaming PC", "find me a used laptop under 6000 kr"). Gathers the missing details by asking the user, then lets haggle find, vet, scam-check and negotiate with sellers in parallel, with the user approving every outreach and deal.
---

# haggle: second-hand buying agent

haggle is an MCP server (tools `clarify_request`, `start_hunt`, `hunt_status`, `approve_outreach`,
`confirm_deal`). It searches mockbay, a simulated Swedish marketplace with simulated sellers. Nothing real
is bought or sent. Your job is the conversation with the user; haggle does the searching, vetting and
negotiating, and never asks follow-up questions itself.

## 1. Get a complete brief (you ask, not haggle)

A hunt needs four things:
- **max budget in SEK** (required, never guess it)
- **kind of item**: any product type (for example a MacBook, camera, bicycle, sofa or shoes)
- **required attributes** (brand/model, processor, size, dimensions, material, color, compatibility, or other needs)
- **pickup city, or whether shipping is fine**

If anything is missing, call `clarify_request` with the user's words. It returns up to 3 questions with
typical answers. Ask them **all in one message**, offering the answers as quick picks, in the user's
language. Don't ask about anything already stated. If `ready` is true, go straight on.

## 2. Start the hunt

Call `start_hunt` with one complete brief, e.g. *"Gaming PC under 8,000 SEK, RTX 3060 or equivalent,
16 GB RAM, 1 TB SSD, pickup in Stockholm or shipping, used is fine."*

Immediately give the user the `dashboard_url` so they can watch it live. If `phase` isn't
`awaiting_approval` yet, call `hunt_status` with `wait_seconds=60` until it is.

## 3. Shortlist → user approval (required)

Show the shortlist compactly: title, asking price, location, and the opening offer and drafted message for
each. Mention scams it flagged. Listings marked over budget are still worth a try: haggle never offers
above the budget. **Ask which sellers to contact.** Only after the user says yes, call
`approve_outreach` with exactly the listing ids they approved.

## 4. Deals → user picks (required)

Poll `hunt_status` (`wait_seconds=60`) until `phase` is `awaiting_confirmation`. Present the deals:
agreed price, saving versus asking, pickup. Recommend the best value, then **ask which one to confirm**.
Call `confirm_deal` only with the deal the user picked. haggle releases the other sellers politely.
Payment and pickup stay with the user.

## Rules

- Never call `approve_outreach` or `confirm_deal` without the user's explicit OK in this conversation.
- Never invent listings, prices or deals; report only what haggle returns.
- If a tool returns `error`, tell the user plainly. For a missing budget, ask for it, then start a new hunt.
- Keep messages short: the user may be on a phone.

Do not redirect users to Windows PCs or reject a product because its attributes differ from PC hardware. Preserve every explicit requirement, including Apple Silicon generation and screen size. Unknown facts must be clarified with sellers before a deal. If the marketplace has no matching inventory, report that accurately.
