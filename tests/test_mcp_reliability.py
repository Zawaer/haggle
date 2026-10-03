"""Exercise retries, client cancellation and real MCP HTTP responses without paid model calls."""
import asyncio
from contextlib import contextmanager
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from haggle import mcp_server, server
from haggle.orchestrator import HUNTS, Hunt, restore_hunts
from haggle.server import app
from test_regressions import Base, fixture


def ctx(client):
    return SimpleNamespace(request_context=SimpleNamespace(
        request=SimpleNamespace(state=SimpleNamespace(owner="local", client=client))))


@contextmanager
def http_client():
    # The SDK's session manager is single-use; give each app lifespan a fresh transport.
    with patch.object(mcp_server.mcp._lowlevel_server, "_session_manager", None):
        transport = mcp_server.http_app()
        with patch.object(server._mcp_app, "app", transport), TestClient(app) as client:
            yield client


class ReliabilityTests(Base):
    async def asyncTearDown(self):
        tasks = list(mcp_server._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await super().asyncTearDown()

    async def test_parallel_start_retries_create_one_hunt_and_charge_one_slot(self):
        with patch.object(Hunt, "run", AsyncMock()) as run, \
             patch.object(mcp_server.limits, "check_new_hunt") as quota:
            results = await asyncio.gather(*(mcp_server.start_hunt(
                "MacBook M1, 4500 SEK, Stockholm", request_id="one-shopping-request") for _ in range(3)))
        self.assertEqual(len({r["hunt_id"] for r in results}), 1)
        self.assertEqual(len(HUNTS), 1)
        self.assertEqual(sum(r.get("reused", False) for r in results), 2)
        run.assert_awaited_once()
        quota.assert_called_once()

    async def test_new_request_id_allows_new_hunt_but_reusing_id_for_changed_brief_fails(self):
        with patch.object(Hunt, "run", AsyncMock()), patch.object(mcp_server.limits, "check_new_hunt"):
            first = await mcp_server.start_hunt("A bike under 2000 SEK, Stockholm", request_id="one")
            changed = await mcp_server.start_hunt("A bike under 1000 SEK, Stockholm", request_id="one")
            second = await mcp_server.start_hunt("A bike under 2000 SEK, Stockholm", request_id="two")
        self.assertIn("error", changed)
        self.assertNotEqual(first["hunt_id"], second["hunt_id"])
        self.assertEqual(len(HUNTS), 2)

    async def test_older_clients_get_short_retry_window_scoped_to_client(self):
        with patch.object(Hunt, "run", AsyncMock()), patch.object(mcp_server.limits, "check_new_hunt"):
            first = await mcp_server.start_hunt("A bike under 2000 SEK, Stockholm", ctx=ctx("a"))
            retry = await mcp_server.start_hunt("A bike under 2000 SEK, Stockholm", ctx=ctx("a"))
            other = await mcp_server.start_hunt("A bike under 2000 SEK, Stockholm", ctx=ctx("b"))
            HUNTS[first["hunt_id"]].started -= 121
            later = await mcp_server.start_hunt("A bike under 2000 SEK, Stockholm", ctx=ctx("a"))
        self.assertEqual(first["hunt_id"], retry["hunt_id"])
        self.assertNotEqual(first["hunt_id"], other["hunt_id"])
        self.assertNotEqual(first["hunt_id"], later["hunt_id"])

    async def test_retry_identity_survives_server_restore(self):
        with patch.object(Hunt, "run", AsyncMock()), patch.object(mcp_server.limits, "check_new_hunt") as quota:
            first = await mcp_server.start_hunt("A bike under 2000 SEK, Stockholm", request_id="persist-me")
            HUNTS.clear()
            await restore_hunts()
            retry = await mcp_server.start_hunt("A bike under 2000 SEK, Stockholm", request_id="persist-me")
        self.assertEqual(first["hunt_id"], retry["hunt_id"])
        self.assertEqual(retry["phase"], "paused")
        self.assertTrue(HUNTS[retry["hunt_id"]].clarified)
        quota.assert_called_once()

    async def test_lost_start_response_does_not_lose_the_hunt(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow_wait(h, seconds):
            entered.set()
            await release.wait()
        with patch.object(Hunt, "run", AsyncMock()), patch.object(mcp_server.limits, "check_new_hunt"), \
             patch.object(mcp_server, "_wait", side_effect=slow_wait):
            call = asyncio.create_task(mcp_server.start_hunt("A bike", request_id="lost-response"))
            await asyncio.wait_for(entered.wait(), 2)
            hid = next(iter(HUNTS))
            call.cancel()
            await asyncio.gather(call, return_exceptions=True)
            release.set()
            retry = await mcp_server.start_hunt("A bike", request_id="lost-response")
        self.assertEqual(retry["hunt_id"], hid)

    async def test_recovery_survives_client_cancellation_and_retries_share_work(self):
        h, lid = fixture()
        h.phase = "paused"
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow_run():
            entered.set()
            await release.wait()
            await h.phase_to("awaiting_approval")
        with patch.object(h, "run", side_effect=slow_run) as run:
            call = asyncio.create_task(mcp_server.resume_hunt(h.id, wait_seconds=30))
            await asyncio.wait_for(entered.wait(), 2)
            call.cancel()
            await asyncio.gather(call, return_exceptions=True)
            self.assertFalse(h.recovery_task.done())
            retry = await mcp_server.resume_hunt(h.id)
            self.assertNotIn("error", retry)
            self.assertEqual(retry["phase"], "recovering")
            release.set()
            await asyncio.wait_for(h.recovery_task, 2)
            run.assert_awaited_once()
        self.assertEqual(h.phase, "awaiting_approval")

    async def test_cancelled_recovery_worker_can_be_resumed(self):
        h, lid = fixture()
        h.phase = "paused"
        entered = asyncio.Event()
        async def slow_run():
            entered.set()
            await asyncio.Future()
        with patch.object(h, "run", side_effect=slow_run):
            await mcp_server.resume_hunt(h.id)
            await asyncio.wait_for(entered.wait(), 2)
            h.recovery_task.cancel()
            await asyncio.gather(h.recovery_task, return_exceptions=True)
        self.assertEqual(h.phase, "paused")
        with patch.object(h, "run", AsyncMock()):
            result = await mcp_server.resume_hunt(h.id)
            self.assertNotIn("error", result)

    async def test_confirmation_survives_disconnect_without_duplicate_notifications(self):
        h, lid = fixture()
        h.phase = "awaiting_confirmation"
        h.items[lid].update(state="deal_offered", deal=dict(price_sek=6500, asking_sek=7500, saved_sek=1000, logistics=""))
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow_send(*args, **kwargs):
            entered.set()
            await release.wait()
        with patch.object(h.market, "send", side_effect=slow_send) as send:
            call = asyncio.create_task(mcp_server.confirm_deal(h.id, lid, wait_seconds=30))
            await asyncio.wait_for(entered.wait(), 2)
            call.cancel()
            await asyncio.gather(call, return_exceptions=True)
            self.assertFalse(h.confirmation_task.done())
            retry = await mcp_server.confirm_deal(h.id, lid)
            self.assertTrue(retry["closed"])
            self.assertTrue(retry["finalizing"])
            self.assertEqual(retry["next_action"], "wait")
            wrong = await mcp_server.confirm_deal(h.id, "another-listing")
            self.assertIn("error", wrong)
            release.set()
            await asyncio.wait_for(h.confirmation_task, 2)
            await mcp_server.confirm_deal(h.id, lid)
            send.assert_awaited_once()
        self.assertFalse(h.finalizing)
        self.assertEqual(h.items[lid]["notification"], "sent")

    async def test_tool_errors_are_mcp_errors_with_structured_recovery_information(self):
        for name, args in (("hunt_status", {"hunt_id": "missing"}), ("start_hunt", {"request": ""})):
            result = await mcp_server.mcp.call_tool(name, args)
            self.assertTrue(result.is_error)
            self.assertIn("error", result.structured_content)
            self.assertEqual(json.loads(result.content[0].text), result.structured_content)
        h, lid = fixture()
        with patch.object(mcp_server, "_owner", return_value="local"):
            result = await mcp_server.mcp.call_tool("hunt_status", {"hunt_id": h.id})
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["hunt_id"], h.id)

    async def test_brief_is_not_silently_cut_at_2000_characters(self):
        request = "Details. " * 250 + "Battery MUST be at least 90%. Budget 4500 SEK."
        with patch.object(Hunt, "run", AsyncMock()), patch.object(mcp_server.limits, "check_new_hunt"):
            result = await mcp_server.start_hunt(request)
        self.assertEqual(HUNTS[result["hunt_id"]].request, request)
        self.assertIn("error", await mcp_server.start_hunt("x" * 10001))

    async def test_browser_hunts_do_not_switch_to_simulated_sellers_after_restart(self):
        h, lid = fixture()
        h.market = None
        h.source = "browser"
        h.persist()
        hid = h.id
        HUNTS.clear()
        await restore_hunts()
        restored = HUNTS[hid]
        self.assertTrue(restored.closed)
        self.assertEqual(restored.phase, "done")
        self.assertIn("Browser session ended", restored.events[-1]["text"])

    async def test_browser_preflight_and_both_endpoint_spellings_work_for_public_demo(self):
        with patch.dict(os.environ, {"HAGGLE_USERS": "", "HAGGLE_REQUIRE_LOGIN": "0", "HAGGLE_ACCESS_TOKEN": "audit-test-token-12345"}), http_client() as client:
            for path in ("/mcp", "/mcp/"):
                headers = {"Origin": "https://example.test", "Access-Control-Request-Method": "POST",
                           "Access-Control-Request-Headers": "content-type,mcp-protocol-version"}
                preflight = client.options(path, headers=headers, follow_redirects=False)
                self.assertEqual(preflight.status_code, 200)
                self.assertEqual(preflight.headers["access-control-allow-origin"], "*")
                result = client.post(path, headers={"Origin": "https://example.test", "Accept": "application/json, text/event-stream"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, follow_redirects=False)
                self.assertEqual(result.status_code, 200)
                self.assertIn("listing_details", result.text)
                self.assertEqual(result.headers["access-control-allow-origin"], "*")

    async def test_authenticated_mode_keeps_origin_and_bearer_checks(self):
        with patch.dict(os.environ, {"HAGGLE_MCP_ORIGINS": "https://allowed.test"}), http_client() as client:
            denied = client.options("/mcp/", headers={"Origin": "https://unknown.test", "Access-Control-Request-Method": "POST"})
            self.assertEqual(denied.status_code, 403)
            allowed = client.options("/mcp/", headers={"Origin": "https://allowed.test", "Access-Control-Request-Method": "POST"})
            self.assertEqual(allowed.status_code, 200)
            headers = {"Origin": "https://allowed.test", "Accept": "application/json, text/event-stream"}
            payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
            self.assertEqual(client.post("/mcp/", headers=headers, json=payload).status_code, 401)
            headers["Authorization"] = "Bearer local-test-token-123"
            self.assertEqual(client.post("/mcp/", headers=headers, json=payload).status_code, 200)
