"""Offline recording with real approval selection; never contacts an external marketplace."""
import asyncio
import json
from .config import DATA
from .orchestrator import Hunt


class ReplayHunt(Hunt):
    def __init__(self, path=DATA / "demo_run.json", speed=1.0, owner="local"):
        rec = json.loads(path.read_text())
        super().__init__(rec["request"], owner=owner)
        self.market = None
        self.source = "replay"
        self.recorded, self.speed = rec["events"], speed
        self.gates = {"approve": asyncio.Event(), "confirm": asyncio.Event()}
        self.selected = None

    async def run(self):
        previous = 0
        for ev in self.recorded:
            if self.closed:
                return
            if ev["type"] == "message" and ev.get("action") == "release":
                continue
            if ev["type"] == "listing" and ev.get("state") in ("confirmed", "released"):
                continue
            await asyncio.sleep(min(max(0, (ev["t"] - previous) / self.speed), 3))
            previous = ev["t"]
            if self.selected is not None and ev.get("id") and ev["id"] not in self.selected:
                continue
            data = {k: v for k, v in ev.items() if k not in ("seq", "t", "type", "calls")}
            self.budget.calls = max(self.budget.calls, ev.get("calls", 0))
            lid = ev.get("id")
            if ev["type"] == "found":
                self.items[lid] = {"id": lid, "listing": ev["listing"], "state": "found", "thread": []}
            elif ev["type"] == "listing" and lid in self.items:
                self.items[lid].update({k: v for k, v in data.items() if k != "id"})
            elif ev["type"] == "draft":
                self.items[lid]["draft"] = data
            elif ev["type"] == "message":
                self.items[lid]["thread"].append({k: v for k, v in data.items() if k != "id"})
            elif ev["type"] == "requirements":
                self.req = ev["req"]
            elif ev["type"] == "handoff":
                data["ids"] = [i for i in data["ids"] if i in (self.selected or set())]
                data["best"] = data["ids"][0] if data["ids"] else None
            elif ev["type"] == "phase":
                self.phase = ev["phase"]
            await self.emit(ev["type"], **data)
            if ev["type"] == "phase" and self.phase == "awaiting_approval":
                await self.gates["approve"].wait()
            elif ev["type"] == "phase" and self.phase == "awaiting_confirmation":
                await self.gates["confirm"].wait()
                return

    async def approve(self, ids):
        async with self.lock:
            self.validate_approval(ids)
            if self.selected is not None:
                raise ValueError("replay selection already approved")
            self.selected = set(ids)
            for lid in ids:
                await self.set_state(lid, "approved")
            self.gates["approve"].set()

    async def confirm(self, lid):
        await super().confirm(lid)
        self.gates["confirm"].set()
