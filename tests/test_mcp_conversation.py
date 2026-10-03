"""MCP conversation regressions from the Gemini shopping session; no model or marketplace calls."""
import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from haggle import mcp_server
from test_regressions import Base, fixture


class MCPConversationTests(Base):
    async def test_compact_status_keeps_decisions_and_full_evidence_is_available(self):
        h, lid = fixture()
        h.req["attributes"] = [dict(key="battery", label="Battery at least 80%", operator="min",
                                    value="", values=[], number=80, unit="%")]
        h.items[lid]["verdicts"]["attr_battery"] = dict(status="pass", reason="89 %",
            label="Battery at least 80%", evidence="Battery health is 89%, checked in system settings.")
        for n in range(4):
            it = copy.deepcopy(h.items[lid])
            it["id"] = f"choice-{n}"
            h.items[it["id"]] = it
        compact = await mcp_server.hunt_status(h.id)
        full = await mcp_server.hunt_status(h.id, include_details=True)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(full)))
        self.assertEqual(compact["next_action"], "review_outreach")
        self.assertEqual(compact["budget_max_sek"], 8000)
        self.assertEqual(len(compact["shortlist"]), 5)
        for short, detailed in zip(compact["shortlist"], full["shortlist"]):
            self.assertEqual(short["listing_id"], detailed["listing_id"])
            self.assertEqual(short["draft_message"], detailed["draft_message"])
            self.assertIn("89 %", short["checks"]["attr_battery"])
            self.assertEqual(detailed["checks"]["attr_battery"]["evidence"],
                             h.items[lid]["verdicts"]["attr_battery"]["evidence"])

    async def test_checks_with_same_label_are_not_lost(self):
        h, lid = fixture()
        h.items[lid]["verdicts"] = {
            "width_min": dict(label="Width", status="pass", reason="110 cm"),
            "width_max": dict(label="Width", status="fail", reason="110 cm"),
        }
        checks = (await mcp_server.hunt_status(h.id))["shortlist"][0]["checks"]
        self.assertIn("pass", checks["width_min"])
        self.assertIn("fail", checks["width_max"])

    async def test_listing_details_returns_public_evidence_without_seller_secrets(self):
        h, lid = fixture()
        it = h.items[lid]
        it["listing"].update(description="Battery health: 89%. Charger included.",
                             _hidden={"min_price_sek": 1234}, hidden={"secret": "seller floor"})
        it["thread"] = [dict(role="seller", text="Pickup at the station.", price_sek=6500,
                             thoughts="private seller reasoning", private_thoughts="secret")]
        before = copy.deepcopy(h.items)
        with patch.object(mcp_server.pipeline, "ask_json", AsyncMock()) as model:
            result = await mcp_server.listing_details(h.id, [lid])
        model.assert_not_called()
        self.assertEqual(h.items, before)
        self.assertEqual(h.market.sent, [])
        detail = result["listings"][0]
        self.assertIn("89%", detail["description"])
        self.assertEqual(detail["messages"], [dict(role="seller", text="Pickup at the station.", price_sek=6500)])
        for secret in ("_hidden", "seller floor", "private seller reasoning", "1234"):
            self.assertNotIn(secret, json.dumps(result))

    async def test_listing_details_validates_ownership_ids_and_batch_size(self):
        h, lid = fixture(owner="other")
        self.assertEqual((await mcp_server.listing_details(h.id, [lid]))["error"], "no such hunt")
        ctx = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(state=SimpleNamespace(owner="other"))))
        self.assertEqual((await mcp_server.listing_details(h.id, [lid], ctx))["listings"][0]["listing_id"], lid)
        for ids in ([], [lid, lid], ["missing"], [str(n) for n in range(6)]):
            with self.subTest(ids=ids):
                self.assertIn("error", await mcp_server.listing_details(h.id, ids, ctx))

    async def test_all_decision_states_stop_waiting_and_offer_an_action(self):
        h, lid = fixture()
        h.items.clear()
        for phase, expected in (("awaiting_approval", "review_outreach"),
                                ("awaiting_confirmation", "choose_deal"), ("done", "finished"),
                                ("paused", "resume_after_request"), ("error", "report_error")):
            with self.subTest(phase=phase):
                h.phase = phase
                with patch.object(mcp_server.asyncio, "sleep", AsyncMock()) as sleep:
                    result = await mcp_server.hunt_status(h.id, wait_seconds=30)
                sleep.assert_not_awaited()
                self.assertEqual(result["next_action"], expected)
        h.phase = "intake"
        h.answer_future = asyncio.get_running_loop().create_future()
        h.events.append(dict(type="question", text="What pickup city?"))
        with patch.object(mcp_server.asyncio, "sleep", AsyncMock()) as sleep:
            result = await mcp_server.hunt_status(h.id, wait_seconds=30)
        sleep.assert_not_awaited()
        self.assertEqual(result["next_action"], "ask_user")
        self.assertEqual(result["question_for_user"], "What pickup city?")

    async def test_done_distinguishes_no_deals_watching_and_new_drafts(self):
        h, lid = fixture()
        h.phase = "done"
        h.watching = True
        h.items[lid]["state"] = "walked_away"
        h.events.append(dict(type="notice", text="No qualifying deals."))
        result = await mcp_server.hunt_status(h.id)
        self.assertEqual(result["next_action"], "finished")
        self.assertTrue(result["watching"])
        self.assertFalse(result["closed"])
        self.assertEqual(result["notice"], "No qualifying deals.")
        h.items[lid]["state"] = "shortlisted"
        self.assertEqual((await mcp_server.hunt_status(h.id))["next_action"], "review_outreach")

    async def test_stale_confirmation_reports_actual_winner_without_sending_again(self):
        h, winner = fixture()
        h.items[winner].update(state="confirmed", notification="sent",
            deal=dict(price_sek=6500, asking_sek=7500, saved_sek=1000, logistics=""))
        loser = "different-choice"
        h.items[loser] = dict(copy.deepcopy(h.items[winner]), id=loser, state="released")
        h.closed = True
        h.phase = "done"
        result = await mcp_server.confirm_deal(h.id, loser)
        self.assertIn("error", result)
        self.assertTrue(result["closed"])
        self.assertEqual(result["next_action"], "finished")
        self.assertEqual([d["listing_id"] for d in result["deals"]], [winner])
        self.assertEqual(h.market.sent, [])
        retry = await mcp_server.confirm_deal(h.id, winner)
        self.assertNotIn("error", retry)
        self.assertEqual(h.market.sent, [])

    async def test_deals_keep_checks_and_unknown_logistics_and_report_delivery_failure(self):
        h, lid = fixture()
        h.items[lid].update(state="confirmed", notification="failed",
            deal=dict(price_sek=6500, asking_sek=7500, saved_sek=1000, logistics=""))
        h.phase = "done"
        h.closed = True
        result = await mcp_server.hunt_status(h.id)
        deal = result["deals"][0]
        self.assertEqual(deal["logistics"], "")
        self.assertEqual(deal["location"], "Stockholm")
        self.assertEqual(deal["seller_notification"], "failed")
        self.assertEqual(set(deal["checks"]), set(h.items[lid]["verdicts"]))

    async def test_stale_outreach_returns_status_without_sending(self):
        h, lid = fixture()
        h.items[lid]["state"] = "negotiating"
        h.phase = "negotiate"
        result = await mcp_server.approve_outreach(h.id, [lid], wait_seconds=0)
        self.assertIn("error", result)
        self.assertEqual(result["phase"], "negotiate")
        self.assertEqual(h.market.sent, [])
