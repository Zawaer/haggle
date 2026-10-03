"""Replay a recorded hunt (no API calls): for frontend development and as the offline demo fallback.

Behaves like a live Hunt for the UI: events stream with their original timing (sped up), and the run
pauses at the approval and confirmation steps until the user clicks.
"""
import asyncio
import json
import time

from .config import DATA
from .orchestrator import HUNTS, Hunt

PAUSE_AT = {"awaiting_approval": "approve", "awaiting_confirmation": "confirm"}


class ReplayHunt(Hunt):
    def __init__(self, path=DATA / "demo_run.json", speed=1.0):
        rec = json.loads(open(path).read())
        super().__init__(rec["request"])
        self.recorded, self.speed = rec["events"], speed
        self.gates = {"approve": asyncio.Event(), "confirm": asyncio.Event()}
        self.confirm_id = None

    async def run(self):
        t_prev, offset = 0.0, 0.0
        for ev in self.recorded:
            if ev["type"] in ("message",) and ev.get("action") == "release":
                continue
            wait = max(0.0, (ev["t"] - t_prev) / self.speed)
            await asyncio.sleep(min(wait, 3.0))
            t_prev = ev["t"]
            data = {k: v for k, v in ev.items() if k not in ("seq", "t", "type")}
            if ev["type"] == "listing" and ev["id"] in self.items:
                self.items[ev["id"]].update({k: v for k, v in data.items() if k != "id"})
            if ev["type"] == "found":
                self.items[ev["id"]] = {"id": ev["id"], "listing": ev["listing"], "state": "found", "thread": []}
            if ev["type"] == "requirements":
                self.req = ev["req"]
            if ev["type"] == "phase":
                self.phase = ev["phase"]
            if ev["type"] == "listing" and ev["state"] == "confirmed":
                break
            await self.emit(ev["type"], **data)
            gate = PAUSE_AT.get(data.get("phase")) if ev["type"] == "phase" else None
            if gate:
                await self.gates[gate].wait()
        if self.confirm_id:
            await Hunt.confirm(self, self.confirm_id)

    async def approve(self, ids):
        self.gates["approve"].set()

    async def confirm(self, lid):
        self.confirm_id = lid
        self.gates["confirm"].set()
