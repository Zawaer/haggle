"""Headless end-to-end run (no UI): discover -> auto-approve shortlist -> negotiate -> print deals.

    .venv/bin/python run_cli.py "I want a gaming PC under 8000 SEK..."
"""
import asyncio
import sys

from haggle.orchestrator import Hunt

DEFAULT = ("I want a gaming PC for under 8,000 SEK. At least an RTX 3060 or equivalent, 16 GB RAM, 1 TB SSD. "
           "Pickup in Stockholm or shipping. Used is fine.")


async def main():
    h = Hunt(sys.argv[1] if len(sys.argv) > 1 else DEFAULT)
    seen = 0

    async def printer():
        nonlocal seen
        while True:
            while seen < len(h.events):
                e = h.events[seen]; seen += 1
                t = e["type"]
                if t == "listing" and e["state"] not in ("extracted",):
                    it = h.items[e["id"]]
                    print(f"  [{e['state']:>13}] {e['id']} {it['listing']['title'][:55]!r} "
                          f"{it['listing']['price_sek']} kr risk={e.get('risk')} score={e.get('score')}")
                elif t == "message":
                    p = f" ({e['price_sek']:,.0f} kr)" if e.get("price_sek") else ""
                    print(f"    {e['id']} {e['role']:>6}{p}: {e['text'][:160]}")
                elif t in ("phase", "status", "guardrail", "question", "handoff", "error", "shortlist"):
                    print(f"== {t}: { {k: v for k, v in e.items() if k not in ('seq', 'type')} }")
            await asyncio.sleep(0.2)

    pt = asyncio.create_task(printer())
    await h.run()
    while h.phase not in ("awaiting_approval", "done"):
        if h.answer_future and not h.answer_future.done():
            h.answer_future.set_result("Just use your best judgement.")
        await asyncio.sleep(0.3)
    ids = [it["id"] for it in h.items.values() if it["state"] == "shortlisted"]
    await h.approve(ids)
    await asyncio.sleep(0.5)
    pt.cancel()
    print("\n==== DEALS ====")
    for it in h.items.values():
        if it["state"] in ("deal_offered", "no_deal", "walked_away", "dropped", "seller_declined"):
            true_min = __import__("haggle.marketplace", fromlist=["get"]).get(it["id"])["hidden"]["min_price_sek"]
            print(f"{it['id']} {it['state']}: {it.get('deal')} reason={it.get('reason')} (hidden min {true_min})")
    print(f"LLM calls: {h.budget.calls}, wall time {h.events[-1]['t']}s")
    best = next((e["best"] for e in h.events if e["type"] == "handoff"), None)
    if best and "--confirm" in sys.argv:
        await h.confirm(best)
    import json, os
    os.makedirs("runs", exist_ok=True)
    json.dump({"request": h.request, "events": h.events}, open("runs/last_events.json", "w"), ensure_ascii=False)
    print("events saved to runs/last_events.json")


asyncio.run(main())
