"""Seller bot for the external marketplace: plays every seller whose listing is in "bot" mode.

Polls the marketplace; whenever a buyer message is waiting for a reply, it answers in character using the
listing's hidden personality, true specs and minimum price from data/listings.json (never below the minimum).
Toggle a listing to "human" mode in the marketplace's seller inbox and a teammate takes over live.

    HAGGLE_MARKET_URL=http://localhost:3140 .venv/bin/python seller_bot.py
"""
import asyncio
import logging

import httpx

from haggle import config, marketplace, negotiation

logging.basicConfig(level=logging.INFO, format="%(asctime)s seller-bot %(message)s")
log = logging.getLogger("seller_bot")
BUSY = set()


async def reply(http, lid, conversation="local"):
    try:
        listing = marketplace.get(lid)
    except StopIteration:
        return
    msgs = (await http.get(f"/api/listings/{lid}/messages", params={"after": 0, "conversation": conversation})).json()
    if not msgs or msgs[-1]["from"] != "buyer":
        return
    thread = [{"role": m["from"], "text": m["text"], "price_sek": m.get("price_sek")} for m in msgs]
    await asyncio.sleep(1.0)  # feel human
    s = await negotiation.seller_turn(listing, thread, None)
    floor = listing["hidden"].get("min_price_sek") or listing["price_sek"]
    price = s.get("price_sek") or None
    if price and price < floor:
        price = floor
    await http.post(f"/api/listings/{lid}/messages",
                    json={"conversation": conversation, "from": "seller", "text": s["message"], "price_sek": price, "thoughts": s["private_thoughts"]})
    log.info("%s replied (%s %s)", lid, s["action"], price)


async def main():
    async with httpx.AsyncClient(base_url=config.MARKET_URL, timeout=15) as http:
        log.info("watching %s", config.MARKET_URL)
        while True:
            try:
                convs = (await http.get("/api/conversations")).json()
                for c in convs:
                    lid = c.get("id") or c.get("listing_id") or c.get("listing", {}).get("id")
                    last = c.get("last_message") or {}
                    conversation = c.get("conversation", "local")
                    key = (lid, conversation)
                    if not lid or key in BUSY or last.get("from") != "buyer":
                        continue
                    mode = c.get("seller_mode") or (await http.get(f"/api/listings/{lid}")).json().get("seller_mode", "bot")
                    if mode != "bot":
                        continue
                    BUSY.add(key)
                    task = asyncio.create_task(reply(http, lid, conversation))
                    task.add_done_callback(lambda t, key=key: BUSY.discard(key))
            except Exception as e:
                log.warning("poll failed: %s", e)
            await asyncio.sleep(1.0)


if __name__ == "__main__":
    asyncio.run(main())
