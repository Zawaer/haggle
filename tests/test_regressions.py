import asyncio
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi.testclient import TestClient

from haggle import condense, config, guardrails, inbox, marketplace, negotiation, pipeline, storage
from haggle.llm import Budget
from haggle.orchestrator import HUNTS, Hunt, restore_hunts

REQ = dict(category="desktop_pc", summary="Gaming PC", budget_max_sek=8000, target_price_sek=7000,
           gpu_min="RTX 3060", gpu_allow_equivalent=True, ram_gb_min=16, storage_gb_min=1000,
           storage_ssd_required=True, city="Stockholm", shipping_ok=True, used_ok=True,
           search_queries=["gaming pc"], clarifying_question="", unsupported_requirements=[])
SPECS = dict(category="desktop_pc", gpu="RTX 3060", gpu_is_laptop_variant=False, ram_gb=16,
             ssd_gb=1000, hdd_gb=0, storage_type_unclear_gb=0, working="yes", condition="used",
             is_for_sale=True, language="en", risk_signals=[], contradictions="")


def move(**kw):
    return dict(dict(action="offer", offer_sek=6500, message="I offer 6500 SEK.",
                     claims_competing_offer_sek=0, learned_specs={}, private_thoughts="test",
                     pickup_or_shipping=""), **kw)


def reading(**kw):
    return dict(dict(action="decline", price_sek=0, summary="Declines", manipulation="",
                     learned_specs={}, working="unknown", condition="unknown",
                     requires_prepayment=False, terms_clear=True), **kw)


class Market:
    def __init__(self):
        self.cursor = {}
        self.sent = []
        self.reply = {"text": "No thanks, I decline.", "price_sek": 0}

    async def send(self, lid, role, text, price=None):
        self.sent.append(dict(id=lid, text=text, price_sek=price))
        return {"seq": len(self.sent)}

    async def wait_seller(self, lid):
        return self.reply


def fixture(owner="local"):
    h = Hunt("review fixture", owner=owner)
    h.req = copy.deepcopy(REQ)
    l = copy.deepcopy(marketplace.public_view(marketplace.listings()[0]))
    l.update(price_sek=7500, location="Stockholm", shipping=False)
    lid = l["id"]
    h.items[lid] = dict(id=lid, listing=l, state="shortlisted", thread=[], specs=copy.deepcopy(SPECS),
                       verdicts=pipeline.match(l, SPECS, REQ), draft=move())
    h.market = Market()
    h.phase = "awaiting_approval"
    return h, lid


class Base(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"HAGGLE_DB": str(Path(self.temp.name) / "test.db"),
                         "HAGGLE_USERS": json.dumps({"local": "local-test-token-123", "other": "other-test-token-123"}),
                         "HAGGLE_CONDENSE": "0"})
        env.start(); self.addCleanup(env.stop)
        for key, value in (("MARKET_URL", ""), ("MARKET", "local"), ("WATCH_MINUTES", 0)):
            p = patch.object(config, key, value); p.start(); self.addCleanup(p.stop)
        HUNTS.clear(); inbox.THREADS.clear(); inbox.MODES.clear(); condense._cache.clear()

    async def asyncTearDown(self):
        tasks = [t for h in HUNTS.values() for t in [*h.tasks.values(), h.watch_task] if t and not t.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class NegotiationTests(Base):
    async def test_rounding_cannot_create_zero_or_over_budget_price(self):
        for value, maximum in ((0.001, 8000), (1.006, 1.006)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                guardrails.money(value, maximum)


    async def test_opening_budget_text_is_rendered_from_validated_price(self):
        h, lid = fixture()
        with patch.object(negotiation, "buyer_turn", AsyncMock(return_value=move(message="I offer 9000 SEK. Another seller offers 1 SEK."))):
            await h._draft(h.items[lid])
        self.assertNotIn("9000", h.items[lid]["draft"]["message"])
        self.assertNotIn("Another seller", h.items[lid]["draft"]["message"])
        self.assertIn("6 500", h.items[lid]["draft"]["message"])

    async def test_rewrite_rechecks_every_guardrail(self):
        h, lid = fixture()
        h.items[lid]["draft"] = move(claims_competing_offer_sek=5000)
        with patch.object(negotiation, "buyer_turn", AsyncMock(return_value=move(offer_sek=9000))), \
             patch.object(negotiation, "read_seller", AsyncMock(return_value=reading())):
            await h.approve([lid])
        self.assertTrue(h.market.sent)
        self.assertTrue(all(m["price_sek"] is None or m["price_sek"] <= 8000 for m in h.market.sent))
        self.assertFalse(any("9000" in m["text"] for m in h.market.sent))

    async def test_repeated_false_claim_is_not_sent(self):
        h, lid = fixture()
        false = move(claims_competing_offer_sek=5000, message="Another seller offered 5000 SEK.")
        with patch.object(negotiation, "buyer_turn", AsyncMock(return_value=false)):
            out = await h._safe_proposal(lid, false)
        self.assertEqual(out["claims_competing_offer_sek"], 0)
        self.assertNotIn("Another seller", out["message"])

    async def test_nonfinite_negative_and_zero_prices_rejected(self):
        for price in (float("nan"), float("inf"), -1, 0, True):
            with self.subTest(price=price), self.assertRaises(ValueError):
                guardrails.render(move(offer_sek=price), REQ, {}, {}, lambda p: True)

    async def test_decimal_price_matches_rendered_message(self):
        out = guardrails.render(move(offer_sek=6500.50), REQ, {}, {}, lambda p: True)
        self.assertIn("6 500.5", out["message"])

    async def test_acceptance_rechecks_disclosed_gpu(self):
        h, lid = fixture()
        h.market.reply = dict(text="Accepted, but it actually has a GTX 1070.", price_sek=6500)
        r = reading(action="accept", price_sek=6500, learned_specs={"gpu": "GTX 1070"})
        with patch.object(negotiation, "read_seller", AsyncMock(return_value=r)):
            await h.approve([lid])
        self.assertEqual(h.items[lid]["state"], "dropped")
        self.assertNotIn("deal", h.items[lid])

    async def test_acceptance_rechecks_zero_storage(self):
        h, lid = fixture()
        h.market.reply = dict(text="Accepted, but I removed the SSD.", price_sek=6500)
        with patch.object(negotiation, "read_seller", AsyncMock(return_value=reading(action="accept", price_sek=6500, learned_specs={"ssd_gb": 0}))):
            await h.approve([lid])
        self.assertEqual(h.items[lid]["state"], "dropped")

    async def test_acceptance_with_prepayment_is_blocked(self):
        h, lid = fixture()
        h.market.reply = dict(text="Accepted, pay first by bank transfer.", price_sek=6500)
        with patch.object(negotiation, "read_seller", AsyncMock(return_value=reading(action="accept", price_sek=6500, requires_prepayment=True))):
            await h.approve([lid])
        self.assertEqual(h.items[lid]["state"], "walked_away")
        self.assertNotIn("deal", h.items[lid])

    async def test_unknown_specs_and_extra_shipping_never_become_deals(self):
        for unknown in (True, False):
            h, lid = fixture()
            if unknown:
                h.items[lid]["verdicts"]["gpu"]["status"] = "uncertain"
            h.market.reply = dict(text="Accepted, shipping is extra.", price_sek=6500)
            with patch.object(negotiation, "read_seller", AsyncMock(return_value=reading(action="accept", price_sek=6500, terms_clear=unknown))), \
                 patch.object(negotiation, "buyer_turn", AsyncMock(return_value=move(action="accept"))):
                await h.approve([lid])
            self.assertEqual(h.items[lid]["state"], "no_deal")
            self.assertLessEqual(len(h.market.sent), config.MAX_MESSAGES_PER_SELLER)

    async def test_verified_acceptance_produces_deal(self):
        h, lid = fixture()
        h.market.reply = dict(text="Accepted, 6500 SEK total.", price_sek=6500)
        with patch.object(negotiation, "read_seller", AsyncMock(return_value=reading(action="accept", price_sek=6500))):
            await h.approve([lid])
        self.assertEqual(h.items[lid]["deal"]["price_sek"], 6500)

    async def test_message_limit_does_not_fabricate_acceptance(self):
        h, lid = fixture()
        h.market.reply = dict(text="My price is 7000 SEK total.", price_sek=7000)
        with patch.object(negotiation, "read_seller", AsyncMock(return_value=reading(action="counter", price_sek=7000))), \
             patch.object(negotiation, "buyer_turn", AsyncMock(return_value=move())):
            await h.approve([lid])
        self.assertEqual(h.items[lid]["state"], "no_deal")
        self.assertEqual(len(h.market.sent), config.MAX_MESSAGES_PER_SELLER)

    async def test_confirmation_cancels_pending_seller_and_notifies_chosen(self):
        h, lid = fixture()
        h.items["chosen"] = {**copy.deepcopy(h.items[lid]), "id": "chosen", "state": "deal_offered",
                              "deal": {"price_sek": 6000, "asking_sek": 7500, "saved_sek": 1500}}
        entered = asyncio.Event()
        async def waiting(_):
            entered.set()
            await asyncio.Event().wait()
        h.market.wait_seller = waiting
        approval = asyncio.create_task(h.approve([lid]))
        await asyncio.wait_for(entered.wait(), 2)
        await h.confirm("chosen")
        await approval
        self.assertEqual(h.items[lid]["state"], "released")
        self.assertTrue(h.tasks[lid].cancelled())
        self.assertEqual(h.phase, "done")
        self.assertTrue(any(m["id"] == "chosen" and "confirmed" in m["text"] for m in h.market.sent))
        count = len(h.market.sent)
        await h.confirm("chosen")
        self.assertEqual(len(h.market.sent), count)
        with self.assertRaises(ValueError):
            await h.approve([lid])

    async def test_invalid_and_duplicate_approval_are_rejected(self):
        h, lid = fixture()
        for ids in ([], [lid, lid], ["missing"]):
            with self.assertRaises(ValueError):
                await h.approve(ids)
        self.assertEqual(h.items[lid]["state"], "shortlisted")
        self.assertFalse(h.market.sent)

    async def test_thread_failure_is_visible_and_handoff_completes(self):
        h, lid = fixture()
        h.market.send = AsyncMock(side_effect=RuntimeError("seller API failed"))
        await h.approve([lid])
        self.assertEqual(h.items[lid]["state"], "error")
        self.assertEqual(h.phase, "done")
        self.assertTrue(any(e["type"] == "error" for e in h.events))

    async def test_watch_retries_failed_listing(self):
        h, lid = fixture(); listing = h.items[lid]["listing"]; h.items = {}; h.market = None
        h.watch_deadline = time.time() + 2
        extraction = AsyncMock(side_effect=[RuntimeError("temporary"), SPECS])
        async def draft(it):
            it["draft"] = move()
            h.watching = False
        with patch.object(config, "WATCH_INTERVAL", 0), patch.object(h, "_search", AsyncMock(return_value=[listing])), \
             patch.object(pipeline, "extract", extraction), patch.object(h, "_draft", draft):
            await h.watch()
        self.assertEqual(extraction.call_count, 2)
        self.assertEqual(h.items[lid]["state"], "shortlisted")
        self.assertTrue(any(e["type"] == "watch_hit" for e in h.events))

    async def test_mcp_reports_and_approves_watch_shortlist(self):
        from haggle.mcp_server import _summary, approve_outreach
        h, lid = fixture(); h.phase = "awaiting_confirmation"
        self.assertEqual(_summary(h)["shortlist"][0]["listing_id"], lid)
        with patch.object(negotiation, "read_seller", AsyncMock(return_value=reading())):
            result = await approve_outreach(h.id, [lid], wait_seconds=0)
        self.assertNotIn("error", result)
        self.assertEqual(h.items[lid]["state"], "seller_declined")


class RequirementsTests(Base):
    async def test_missing_budget_can_be_clarified_before_validation(self):
        req = dict(REQ, budget_max_sek=0, clarifying_question="What is your budget?")
        with patch.object(pipeline, "ask_json", AsyncMock(return_value=req)):
            self.assertEqual((await pipeline.intake("Gaming PC", Budget()))["clarifying_question"], "What is your budget?")


    async def test_requested_city_and_equivalence_are_enforced(self):
        h, lid = fixture(); l = h.items[lid]["listing"]
        v = pipeline.match(l, dict(SPECS, gpu="RX 6700 XT"), dict(REQ, city="Gothenburg", shipping_ok=False, gpu_allow_equivalent=False))
        self.assertEqual(v["location"]["status"], "fail")
        self.assertEqual(v["gpu"]["status"], "fail")
        l["location"] = "Göteborg centrum"
        self.assertEqual(pipeline.match(l, SPECS, dict(REQ, city="Gothenburg"))["location"]["status"], "pass")

    async def test_unknown_requirement_gpu_does_not_default_to_3060(self):
        h, lid = fixture()
        v = pipeline.match(h.items[lid]["listing"], SPECS, dict(REQ, gpu_min="RTX 9999"))
        self.assertEqual(v["gpu"]["status"], "uncertain")

    async def test_new_only_rejects_used(self):
        h, lid = fixture()
        v = pipeline.match(h.items[lid]["listing"], SPECS, dict(REQ, used_ok=False))
        self.assertEqual(v["condition"]["status"], "fail")

    async def test_unsupported_constraints_are_not_silently_dropped(self):
        with patch.object(pipeline, "ask_json", AsyncMock(return_value=dict(REQ, unsupported_requirements=["CPU model"]))):
            req = await pipeline.intake("specific CPU", Budget())
            self.assertEqual(req["attributes"][0]["label"], "CPU model")
            self.assertEqual(req["attributes"][0]["value"], "yes")


class CompressionTests(Base):
    def client(self, messages=None, error=None):
        response = Mock(); response.json.return_value = {"messages": messages}
        client = AsyncMock(); client.__aenter__.return_value = client
        client.post = AsyncMock(return_value=response, side_effect=error)
        return client

    async def test_disabled_makes_no_request(self):
        with patch.object(condense.httpx, "AsyncClient") as client:
            self.assertEqual(await condense.compress(["A" * 200]), ["A" * 200])
            client.assert_not_called()

    async def test_fallback_is_counted_and_cache_reused(self):
        h = Hunt("compression stats")
        client = self.client([{"content": "B" * 100}])
        with patch.dict(os.environ, {"CONDENSE_AUTH_TOKEN": "test", "HAGGLE_CONDENSE": "1"}):
            with patch.object(condense.httpx, "AsyncClient", return_value=client):
                self.assertEqual(await condense.compress(["A" * 200], h.budget), ["B" * 100])
                await condense.compress(["A" * 200], Budget())
                self.assertEqual(client.post.call_count, 1)
            with patch.object(condense.httpx, "AsyncClient", return_value=self.client(error=httpx.ReadTimeout("outage"))):
                self.assertEqual(await condense.compress(["C" * 200], h.budget), ["C" * 200])
        self.assertEqual(h._condense_stats()["saved_pct"], 25)
        self.assertEqual(h.budget.condense_failures, 1)
        self.assertEqual(h.budget.condense_calls, 2)

    async def test_malformed_response_does_not_poison_cache(self):
        with patch.dict(os.environ, {"CONDENSE_AUTH_TOKEN": "test", "HAGGLE_CONDENSE": "1"}):
            for messages in ([{"content": 123}], [], [{"content": "ok"}, {"content": []}]):
                with self.subTest(messages=messages), patch.object(condense.httpx, "AsyncClient", return_value=self.client(messages)):
                    self.assertEqual(await condense.compress(["A" * 200], Budget()), ["A" * 200])
                    self.assertFalse(condense._cache)

    async def test_cache_bounded(self):
        with patch.dict(os.environ, {"CONDENSE_AUTH_TOKEN": "test", "HAGGLE_CONDENSE": "1"}), \
             patch.object(condense, "MAX_CACHE_ENTRIES", 2), \
             patch.object(condense.httpx, "AsyncClient", return_value=self.client([{"content": "short"}])):
            for text in ("A" * 200, "B" * 200, "C" * 200):
                await condense.compress([text], Budget())
        self.assertEqual(len(condense._cache), 2)

    async def test_latest_messages_prices_and_original_transcript_preserved(self):
        h, lid = fixture()
        thread = [dict(role="buyer" if i % 2 == 0 else "seller", text=f"original-{i}", price_sek=6500+i) for i in range(4)]
        original = copy.deepcopy(thread)
        ai = AsyncMock(return_value=move())
        with patch.object(condense, "compress", AsyncMock(return_value=["description", "old-zero", "old-one"])), \
             patch.object(negotiation, "ask_json", ai):
            await negotiation.buyer_turn(REQ, h.items[lid]["listing"], {}, thread, "verified offer", h.budget, note="correction")
        prompt = ai.call_args.args[0]
        for text in ("old-zero", "original-2", "original-3", "6,500", "verified offer", "correction"):
            self.assertIn(text, prompt)
        self.assertEqual(thread, original)


class PersistenceTests(Base):
    async def test_inboxes_isolated_and_idempotent(self):
        h, lid = fixture(); l = h.items[lid]["listing"]
        a = inbox.open_thread(lid, l, "hunt-a")
        await inbox.post(a, "buyer", "First buyer")
        b = inbox.open_thread(lid, l, "hunt-b")
        inbox.open_thread(lid, l, "hunt-a")
        self.assertNotEqual(a, b)
        self.assertEqual(len(inbox.THREADS[a]["messages"]), 1)
        self.assertFalse(inbox.THREADS[b]["messages"])
        inbox.THREADS.clear(); inbox.restore()
        self.assertEqual(inbox.THREADS[a]["messages"][0]["text"], "First buyer")

    async def test_restart_preserves_owner_history_and_pauses_sending(self):
        h, lid = fixture(owner="other"); h.market = None; h.phase = "negotiate"
        h.items[lid]["state"] = "negotiating"
        await h._send(lid, "buyer", "Already sent", 6500)
        hid = h.id
        HUNTS.clear()
        await restore_hunts()
        restored = HUNTS[hid]
        self.assertEqual(restored.owner, "other")
        self.assertEqual(restored.phase, "paused")
        self.assertEqual(restored.items[lid]["state"], "interrupted")
        self.assertEqual(len(restored.items[lid]["thread"]), 1)
        await restored.recover()
        self.assertEqual(restored.phase, "awaiting_approval")
        self.assertEqual(restored.items[lid]["draft"]["action"], "ask")
        self.assertEqual(len(restored.items[lid]["thread"]), 1)

    async def test_recovery_at_message_limit_finishes_without_empty_approval(self):
        h, lid = fixture(); h.market = None; h.phase = "paused"
        h.items[lid]["state"] = "interrupted"
        h.items[lid]["thread"] = [{"role": "buyer", "text": "sent"}] * config.MAX_MESSAGES_PER_SELLER
        await h.recover()
        self.assertEqual(h.phase, "done")
        self.assertEqual(h.items[lid]["state"], "no_deal")

    async def test_restore_keeps_original_market_endpoint(self):
        from haggle.market_http import HttpMarket
        h, lid = fixture(); h.source = "http"
        h.market = HttpMarket("https://original.example", conversation=h.id)
        h.market.cursor[lid] = 7
        h.persist(); hid = h.id
        await h.market.http.aclose()
        HUNTS.clear()
        await restore_hunts()
        restored = HUNTS[hid]
        self.assertEqual(restored.market.base, "https://original.example")
        self.assertEqual(restored.market.conversation, hid)
        self.assertEqual(restored.market.cursor[lid], 7)
        await restored.market.http.aclose()

    async def test_api_authentication_ownership_and_csrf(self):
        from haggle.server import app
        h, lid = fixture(owner="other"); h.market = None
        tid = inbox.open_thread(lid, h.items[lid]["listing"], h.id)
        with TestClient(app) as c:
            self.assertEqual(c.get("/healthz").json(), {"status": "ok"})
            self.assertEqual(c.get(f"/api/hunts/{h.id}").status_code, 401)
            self.assertEqual(c.post("/api/login", json={"token": "wrong"}).status_code, 401)
            self.assertEqual(c.post("/api/login", json={"token": "local-test-token-123"}).status_code, 200)
            self.assertEqual(c.get(f"/api/hunts/{h.id}").status_code, 404)
            self.assertEqual(c.post(f"/api/inbox/{tid}/messages", json={"text": "intruder"}).status_code, 404)
            self.assertEqual(c.get("/api/inbox").json()["threads"], [])
            self.assertEqual(c.post("/api/hunts", json={"request": "test"}, headers={"origin": "https://attacker.invalid"}).status_code, 403)
            self.assertEqual(c.get(f"/api/hunts/{h.id}", headers={"authorization": "Bearer other-test-token-123"}).status_code, 200)

    async def test_inbox_list_never_leaks_private_thoughts(self):
        from haggle.server import app
        h, lid = fixture(); h.market = None
        tid = inbox.open_thread(lid, h.items[lid]["listing"], h.id)
        await inbox.post(tid, "seller", "Hello", thoughts="hidden floor")
        c = TestClient(app)
        self.addCleanup(c.close)
        r = c.get("/api/inbox", headers={"authorization": "Bearer local-test-token-123"})
        self.assertNotIn("thoughts", r.json()["threads"][0]["last"])


class IntegrationTests(Base):
    async def test_mcp_start_keeps_owner_limits_link_and_bounded_wait(self):
        from types import SimpleNamespace
        from haggle import mcp_server
        ctx = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(state=SimpleNamespace(owner="other"))))
        with patch.object(mcp_server.limits, "check_new_hunt") as check, \
             patch.object(Hunt, "run", AsyncMock()), \
             patch.object(mcp_server, "_wait", AsyncMock()) as wait:
            result = await mcp_server.start_hunt("gaming PC", wait_seconds=1000, ctx=ctx)
        h = HUNTS[result["hunt_id"]]
        self.assertEqual(h.owner, "other")
        check.assert_called_once_with(HUNTS, "other")
        wait.assert_awaited_once_with(h, 75)
        self.assertTrue(result["dashboard_url"].endswith("/?h=" + h.id))

    async def test_usage_limits_keep_saved_hunts_and_enforce_owner_quota(self):
        from haggle import limits
        from collections import deque
        hunts = {}
        for i in range(85):
            h = Hunt("saved", owner="local")
            h.phase = "paused"
            hunts[h.id] = h
        with patch.object(limits, "_starts", deque()), patch.object(limits, "_calls", deque()), \
             patch.object(limits, "PER_CLIENT_HOUR", 1):
            limits.check_new_hunt(hunts, "local")
            self.assertEqual(len(hunts), 85)
            with self.assertRaises(limits.LimitError):
                limits.check_new_hunt(hunts, "local")
            limits.check_new_hunt(hunts, "other")


    async def wait_phase(self, h, phase):
        async def wait():
            while h.phase != phase:
                await asyncio.sleep(0)
        # Replay persists every event; shared CI disks can take several seconds.
        await asyncio.wait_for(wait(), 30)

    async def test_replay_respects_subset_and_confirms_only_selected(self):
        from haggle.replay import ReplayHunt
        h = ReplayHunt(speed=1e9)
        task = asyncio.create_task(h.run())
        await self.wait_phase(h, "awaiting_approval")
        selected = next(lid for lid, it in h.items.items() if it.get("draft"))
        await h.approve([selected])
        await self.wait_phase(h, "awaiting_confirmation")
        handoff = next(e for e in reversed(h.events) if e["type"] == "handoff")
        self.assertEqual(handoff["ids"], [selected])
        self.assertFalse(any(e["type"] == "message" and e["id"] != selected for e in h.events))
        self.assertFalse(any(it["thread"] for lid, it in h.items.items() if lid != selected))
        with self.assertRaises(ValueError):
            await h.confirm("missing")
        await h.confirm(selected)
        await asyncio.wait_for(task, 3)
        self.assertEqual(h.items[selected]["state"], "confirmed")
        self.assertTrue(h.closed)

    async def test_complete_local_hunt_with_mocked_language_models(self):
        h = Hunt("Gaming PC under 8000 SEK")
        listing = copy.deepcopy(marketplace.public_view(marketplace.listings()[0]))
        listing.update(price_sek=7000, shipping=False, location="Stockholm")
        with patch.object(pipeline, "intake", AsyncMock(return_value=REQ)), \
             patch.object(pipeline, "extract", AsyncMock(return_value=SPECS)), \
             patch.object(h, "_search", AsyncMock(return_value=[listing])), \
             patch.object(negotiation, "buyer_turn", AsyncMock(return_value=move(offer_sek=7000))), \
             patch.object(negotiation, "seller_turn", AsyncMock(return_value={"action": "accept", "price_sek": 7000, "message": "Accepted at 7000 total", "private_thoughts": "test"})), \
             patch.object(negotiation, "read_seller", AsyncMock(return_value=reading(action="accept", price_sek=7000))):
            await h.run()
            self.assertEqual(h.phase, "awaiting_approval")
            self.assertFalse(inbox.THREADS)
            await h.approve([listing["id"]])
            self.assertEqual(h.phase, "awaiting_confirmation")
            await h.confirm(listing["id"])
        self.assertEqual(h.phase, "done")
        self.assertTrue(any(m["action"] == "confirm" for m in h.items[listing["id"]]["thread"]))

    async def test_mcp_cannot_read_or_approve_another_owners_hunt(self):
        from types import SimpleNamespace
        from haggle.mcp_server import hunt_status, approve_outreach
        h, lid = fixture(owner="other")
        ctx = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(state=SimpleNamespace(owner="local"))))
        self.assertIn("error", await hunt_status(h.id, ctx=ctx))
        self.assertIn("error", await approve_outreach(h.id, [lid], ctx=ctx))
        self.assertFalse(h.market.sent)

    async def test_external_market_conversations_are_isolated(self):
        from haggle.market_http import HttpMarket
        from tools.reference_market import app, MSGS
        MSGS.clear()
        a = HttpMarket("http://market", conversation="a")
        b = HttpMarket("http://market", conversation="b")
        await a.http.aclose(); await b.http.aclose()
        a.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://market")
        b.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://market")
        try:
            await a.send("bl-001", "buyer", "Buyer A", 6000)
            await b.send("bl-001", "buyer", "Buyer B", 6500)
            ra = await a.http.get("/api/listings/bl-001/messages", params={"conversation": "a"})
            rb = await b.http.get("/api/listings/bl-001/messages", params={"conversation": "b"})
            self.assertEqual([m["text"] for m in ra.json()], ["Buyer A"])
            self.assertEqual([m["text"] for m in rb.json()], ["Buyer B"])
        finally:
            await a.http.aclose(); await b.http.aclose()

    async def test_external_market_rejects_cross_conversation_reply(self):
        from haggle.market_http import HttpMarket
        market = HttpMarket("http://market", conversation="mine")
        await market.http.aclose()
        message = {"seq": 1, "from": "seller", "text": "Wrong buyer", "conversation": "someone-else"}
        market.http = httpx.AsyncClient(base_url="http://market", transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json=[message])))
        try:
            with self.assertRaisesRegex(ValueError, "conversation isolation"):
                await market.wait_seller("bl-001", timeout=1)
            self.assertEqual(market.cursor, {})
        finally:
            await market.http.aclose()

    async def test_mockbay_reads_pagination_and_strips_hidden_data(self):
        from haggle import mockbay
        requests = []
        def reply(request):
            requests.append(request)
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json={"pages": 2, "listings": [{"id": f"pc-{page}", "title": "PC", "price": 7000}]})
        original = httpx.AsyncClient
        with patch.object(mockbay.httpx, "AsyncClient", side_effect=lambda **kw: original(transport=httpx.MockTransport(reply), **kw)):
            results = await mockbay.search(["PC"])
        self.assertEqual([l["id"] for l in results], ["pc-1", "pc-2"])
        self.assertEqual(len(requests), 2)
        self.assertTrue(all("_hidden" not in l for l in results))

    async def test_provider_failure_does_not_silently_switch_market(self):
        h = Hunt("PC"); h.req = REQ; h.source = "mockbay"
        with patch("haggle.mockbay.search", AsyncMock(side_effect=RuntimeError("outage"))), \
             patch.object(config, "ALLOW_LOCAL_FALLBACK", False):
            with self.assertRaisesRegex(RuntimeError, "mockbay is unreachable"):
                await h._search()
        self.assertEqual(h.source, "mockbay")


if __name__ == "__main__":
    unittest.main()
