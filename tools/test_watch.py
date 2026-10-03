"""Watch-mode test on the built-in mock: full hunt -> deals -> a new listing is posted -> watch mode finds and
vets it, drafts a message, waits for approval -> approve -> negotiation -> new deal joins the handoff.

    HAGGLE_WATCH_INTERVAL=5 .venv/bin/python -m tools.test_watch
"""
import asyncio

from fastapi.testclient import TestClient

from haggle.orchestrator import Hunt
from haggle.server import app
from haggle import auth


async def main():
    h = Hunt("I want a gaming PC for under 8,000 SEK. At least an RTX 3060 or equivalent, 16 GB RAM, 1 TB SSD. "
             "Pickup in Stockholm or shipping. Used is fine.")
    await h.run()
    await h.approve([i["id"] for i in h.items.values() if i["state"] == "shortlisted"])
    print("first round deals:", [i["id"] for i in h.items.values() if i["state"] == "deal_offered"], "watching:", h.watching)
    with TestClient(app, headers={"Authorization": "Bearer " + auth.users()["local"]}) as c:
        r = c.post("/api/market/listings", json={
            "title": "Speldator RTX 3060 Ti / Ryzen 5 5600 / 16GB / 1TB NVMe",
            "description": "Säljer min speldator, funkar perfekt. RTX 3060 Ti, Ryzen 5 5600, 16 GB DDR4, 1 TB NVMe SSD. "
                           "Hämtas i Solna, kan mötas upp i stan. Pris kan diskuteras lite.",
            "price_sek": 6800, "location": "Solna, Stockholm", "min_price_sek": 6000})
        lid = r.json()["id"]
    print("posted", lid)
    for _ in range(60):
        if any(e["type"] == "watch_hit" for e in h.events):
            break
        await asyncio.sleep(1)
    hit = next(e for e in h.events if e["type"] == "watch_hit")
    print("WATCH HIT:", hit["text"], "| draft:", h.items[lid]["draft"]["message"][:100])
    await h.approve([lid])
    it = h.items[lid]
    print("result:", it["state"], it.get("deal"))
    for e in h.events:
        if e.get("id") == lid and e["type"] == "message":
            print(f"  {e['role']:>6}: {e['text'][:120]}")
    print("handoff ids:", [e for e in h.events if e["type"] == "handoff"][-1]["ids"], "calls:", h.budget.calls)
    h.watching = False


asyncio.run(main())
