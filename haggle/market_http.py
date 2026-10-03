"""Client for the external mock marketplace website (see the contract in README "Marketplace API").

The buyer agent posts its messages there and waits for the seller's reply, which comes either from a
human (a teammate in the marketplace's seller inbox, live on stage) or from seller_bot.py.
"""
import asyncio
import time

import httpx

from . import config


class HttpMarket:
    def __init__(self, base=config.MARKET_URL, conversation="local"):
        self.base = base
        self.conversation = conversation
        self.http = httpx.AsyncClient(base_url=base, timeout=15)
        self.cursor = {}  # listing id -> last seen message seq

    async def search(self, queries, limit=40):
        seen, out = set(), []
        for q in queries:
            r = await self.http.get("/api/listings", params={"q": q})
            r.raise_for_status()
            for l in r.json():
                if l["id"] not in seen:
                    seen.add(l["id"])
                    out.append({k: v for k, v in l.items() if k != "hidden"})
        return out[:limit]

    def _validate_message(self, message):
        if message.get("conversation") != self.conversation:
            raise ValueError("Marketplace did not preserve conversation isolation")
        return message

    async def send(self, lid, frm, text, price=None):
        r = await self.http.post(f"/api/listings/{lid}/messages",
                                 json={"from": frm, "text": text, "price_sek": price, "conversation": self.conversation})
        r.raise_for_status()
        m = self._validate_message(r.json())
        self.cursor[lid] = max(self.cursor.get(lid, 0), m.get("seq", 0))
        return m

    async def wait_seller(self, lid, timeout=config.HUMAN_REPLY_TIMEOUT):
        """Poll until the seller has replied (all new seller messages joined), or None on timeout."""
        deadline = time.time() + timeout
        got = []
        while time.time() < deadline:
            r = await self.http.get(f"/api/listings/{lid}/messages", params={"after": self.cursor.get(lid, 0), "conversation": self.conversation})
            r.raise_for_status()
            for m in r.json():
                self._validate_message(m)
                self.cursor[lid] = max(self.cursor.get(lid, 0), m["seq"])
                if m["from"] == "seller":
                    got.append(m)
            if got:
                await asyncio.sleep(1.5)  # humans often send two messages in a row
                r = await self.http.get(f"/api/listings/{lid}/messages", params={"after": self.cursor[lid], "conversation": self.conversation})
                r.raise_for_status()
                for m in r.json():
                    self._validate_message(m)
                    self.cursor[lid] = max(self.cursor[lid], m["seq"])
                    if m["from"] == "seller":
                        got.append(m)
                price = next((m["price_sek"] for m in reversed(got) if m.get("price_sek")), None)
                return {"text": "\n".join(m["text"] for m in got), "price_sek": price,
                        "thoughts": next((m.get("thoughts") for m in reversed(got) if m.get("thoughts")), None)}
            await asyncio.sleep(1.0)
        return None
