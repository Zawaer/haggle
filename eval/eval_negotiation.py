"""Negotiation benchmark: run N full hunts (auto-approving the shortlist) and measure how much of the
available discount the buyer agent captured.

  discount captured = (asking - agreed) / (asking - seller's hidden minimum)
  100% = the agent found the seller's true floor; 0% = paid asking.

    .venv/bin/python -m eval.eval_negotiation 3
"""
import asyncio
import json
import statistics
import sys

from haggle import marketplace
from haggle.orchestrator import Hunt

REQ = ("I want a gaming PC for under 8,000 SEK. At least an RTX 3060 or equivalent, 16 GB RAM, 1 TB SSD. "
       "Pickup in Stockholm or shipping. Used is fine.")


async def one():
    h = Hunt(REQ)
    await h.run()
    while h.phase != "awaiting_approval":
        if h.answer_future and not h.answer_future.done():
            h.answer_future.set_result("Use your best judgement.")
        await asyncio.sleep(0.3)
    await h.approve([i["id"] for i in h.items.values() if i["state"] == "shortlisted"])
    rows = []
    for it in h.items.values():
        if "thread" not in it or not it["thread"]:
            continue
        hid = marketplace.get(it["id"])["hidden"]
        ask, floor = it["listing"]["price_sek"], hid.get("min_price_sek")
        d = it.get("deal")
        rows.append({"id": it["id"], "state": it["state"], "ask": ask, "floor": floor,
                     "agreed": d["price_sek"] if d else None, "msgs": len(it["thread"]),
                     "over_budget": bool(d and d["price_sek"] > h.req["budget_max_sek"])})
    return rows, h.budget.calls, h.events[-1]["t"]


async def main(n):
    allrows, calls, secs = [], [], []
    for i in range(n):
        rows, c, t = await one()
        allrows += rows; calls.append(c); secs.append(t)
        print(f"run {i+1}: {[(r['id'], r['state'], r['agreed']) for r in rows]}  calls={c} t={t:.0f}s", flush=True)
    deals = [r for r in allrows if r["agreed"] and r["floor"] and r["ask"] > r["floor"]]
    cap = [(r["ask"] - r["agreed"]) / (r["ask"] - r["floor"]) for r in deals]
    off = [(r["ask"] - r["agreed"]) / r["ask"] for r in deals]
    res = {
        "runs": n, "threads": len(allrows), "deals": len(deals),
        "avg_discount_captured": round(statistics.mean(cap), 3) if cap else None,
        "avg_pct_below_asking": round(statistics.mean(off), 3) if off else None,
        "avg_saved_sek": round(statistics.mean(r["ask"] - r["agreed"] for r in deals)) if deals else None,
        "over_budget_deals": sum(r["over_budget"] for r in allrows),
        "walked_or_dropped": sum(r["state"] in ("walked_away", "dropped") for r in allrows),
        "avg_calls_per_hunt": round(statistics.mean(calls)), "avg_seconds_per_hunt": round(statistics.mean(secs)),
    }
    print(json.dumps(res, indent=1))
    json.dump(res, open("eval/negotiation_result.json", "w"), indent=1)


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))
