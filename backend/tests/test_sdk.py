"""Real official SDK + official proxy; isolated upstream fixture, never product output."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from aiohttp import web
from aiohttp.test_utils import TestServer
from comfy_api_proxy.app import make_app
import httpx

from app.comfy import ComfyError
from app.db import Database, encode, now, uid
from app.jobs import JobHub, JobWorker
from app.sdk_comfy import SDKComfyClient, official_sdk
from app.sdk_proxy import LocalEngineStack, SDKProxyManager
from app.settings import Settings
from app.storage import Storage
from app.workflows import WorkflowAdapter
from test_api import GRAPH, MAPPING, SCHEMA, png


def job_response(job_id="11111111-1111-4111-8111-111111111111", status="queued", outputs=None):
    return {"id": job_id, "status": status, "created_at": now(), "started_at": None,
            "completed_at": None, "expires_at": "2027-01-01T00:00:00Z", "queue_position": None,
            "progress": None, "outputs": outputs or [], "error": None,
            "urls": {key: f"http://127.0.0.1:8189/api/v2/jobs/{job_id}" for key in ("self", "cancel", "events")}}


class SDKTransportTests(unittest.IsolatedAsyncioTestCase):
    async def client(self, handler, **kwargs):
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        # HTTP is the only double: workflow construction, submit, parsing and
        # error translation all execute inside the installed official SDK.
        with patch("comfy_low.transport.httpx.AsyncClient", return_value=http):
            sdk = official_sdk("http://127.0.0.1:8189", 1)
        client = SDKComfyClient("http://127.0.0.1:8188", "http://127.0.0.1:8189", sdk=sdk, http_client=http, **kwargs)
        self.addAsyncCleanup(client.close)
        return client

    async def test_official_submit_stable_key_local_target_and_no_ambient_credentials(self):
        requests = []
        async def handler(request):
            requests.append(request)
            return httpx.Response(201, json=job_response())
        with patch.dict(os.environ, {"COMFY_API_KEY": "private-test-key", "COMFY_BASE_URL": "https://cloud.comfy.org"}):
            client = await self.client(handler)
            self.assertEqual(os.environ["COMFY_API_KEY"], "private-test-key")
            self.assertEqual(os.environ["COMFY_BASE_URL"], "https://cloud.comfy.org")
            result = await client.submit(GRAPH, "durable-client-key")
        self.assertEqual(result["transport"], "comfy-sdk")
        self.assertEqual(str(requests[0].url), "http://127.0.0.1:8189/api/v2/jobs")
        self.assertEqual(requests[0].headers["Idempotency-Key"], "durable-client-key")
        self.assertNotIn("authorization", requests[0].headers)
        self.assertEqual(json.loads(requests[0].content), {"workflow": GRAPH})

    async def test_ambiguous_submission_is_sent_once(self):
        calls = []
        async def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout("isolated timeout", request=request)
        client = await self.client(handler)
        with self.assertRaises(ComfyError) as caught:
            await client.submit(GRAPH, "stable-key")
        self.assertTrue(caught.exception.details["submission_uncertain"])
        self.assertEqual(len(calls), 1)

    async def test_definite_rejection_and_duplicate_key_are_distinguished(self):
        for code, uncertain in (("invalid_workflow", False), ("idempotency_key_reuse", True)):
            client = await self.client(lambda request: httpx.Response(422, json={"error": {"code": code, "message": "isolated rejection", "details": {"node_errors": {"2": "fixture"}}}}))
            with self.assertRaises(ComfyError) as caught:
                await client.submit(GRAPH, "key")
            self.assertEqual(caught.exception.details["submission_uncertain"], uncertain)
            self.assertEqual(caught.exception.details["code"], code)

    async def test_ui_graph_never_reaches_transport(self):
        calls = []
        client = await self.client(lambda request: calls.append(request))
        with self.assertRaises(ComfyError):
            await client.submit({"nodes": []})
        self.assertEqual(calls, [])

    async def test_missing_history_and_wrong_proxy_not_ready(self):
        async def handler(request):
            if request.url.path.endswith("health"):
                return httpx.Response(200, json={"status": "healthy", "upstream": "http://127.0.0.1:9999"})
            return httpx.Response(404, json={"error": {"code": "not_found", "message": "missing fixture"}})
        client = await self.client(handler)
        self.assertFalse(await client.proxy_health())
        self.assertEqual(await client.history(str(uuid.uuid4())), {})

    async def test_live_sdk_progress_ignores_indeterminate_snapshot(self):
        response = job_response(status="running")
        response["urls"]["events"] += "/events"
        frames = ("event: status\ndata: {\"status\":\"running\"}\n\n"
                  "event: progress\ndata: {\"value\":0,\"nodes_done\":0,\"nodes_total\":0}\n\n"
                  "event: progress\ndata: {\"value\":0.4,\"nodes_done\":1,\"nodes_total\":4,\"current_node\":\"12\",\"step\":4,\"steps\":10}\n\n"
                  "event: status\ndata: {\"status\":\"succeeded\"}\n\n")
        async def handler(request):
            if request.url.path.endswith("/events"):
                return httpx.Response(200, text=frames, headers={"content-type": "text/event-stream"})
            return httpx.Response(200, json=response)
        client = await self.client(handler)
        async def collect():
            return [event async for event in client.progress_events(response["id"])]
        events = await asyncio.wait_for(collect(), 2)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["phase"], "running")
        self.assertNotIn("value", events[0])
        self.assertEqual(events[1]["value"], 0.4)
        self.assertEqual(events[1]["current_node"], "12")
        self.assertEqual((events[1]["step"], events[1]["steps"]), (4, 10))

    async def test_output_unknown_size_still_has_hard_stream_limit(self):
        response = job_response(status="succeeded")
        response["outputs"] = [{"node_id": "2", "name": "fixture.png", "type": "image", "content_type": "image/png",
                                "size_bytes": 0, "id": "asset-fixture", "hash": None,
                                "url": "http://127.0.0.1:8189/api/v2/assets/asset-fixture/content",
                                "url_expires_at": "2027-01-01T00:00:00Z"}]
        async def handler(request):
            if request.url.path.endswith("content"):
                return httpx.Response(200, content=b"oversized fixture")
            return httpx.Response(200, json=response)
        client = await self.client(handler, max_output_bytes=4)
        history = await client.history(response["id"])
        descriptor = history[response["id"]]["outputs"]["2"]["images"][0]
        with self.assertRaises(ComfyError):
            await client.download_output(descriptor)
        descriptor["sdk_asset_id"] = "forged-asset"
        with self.assertRaises(ComfyError):
            await client.download_output(descriptor)


class SDKProxyIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.histories, self.submissions = {}, []
        self.rejected = False
        async def prompt(request):
            body = await request.json()
            if self.rejected:
                return web.json_response({"error": {"message": "fixture rejected"}, "node_errors": {}}, status=400)
            self.submissions.append(body)
            self.histories[body["prompt_id"]] = {"status": {"status_str": "success", "completed": True},
                                                "outputs": {"2": {"images": [{"filename": "fixture.png", "subfolder": "actual-subfolder", "type": "output"}]}}}
            return web.json_response({"prompt_id": body["prompt_id"]})
        async def history(request):
            job_id = request.match_info["id"]
            return web.json_response({job_id: self.histories[job_id]} if job_id in self.histories else {})
        async def view(request):
            self.assertEqual(request.query["subfolder"], "actual-subfolder")
            return web.Response(body=png(), content_type="image/png")
        async def info(request):
            return web.json_response(SCHEMA)
        async def queue(request):
            return web.json_response({"queue_running": [], "queue_pending": []})
        upstream = web.Application()
        upstream.add_routes([web.post("/prompt", prompt), web.get("/history/{id}", history), web.get("/view", view), web.get("/object_info", info), web.get("/queue", queue)])
        self.upstream = TestServer(upstream)
        await self.upstream.start_server()
        self.proxy = TestServer(make_app(str(self.upstream.make_url("/")).rstrip("/"), state_dir=self.root / "proxy-state"))
        await self.proxy.start_server()
        self.client = SDKComfyClient(str(self.upstream.make_url("/")).rstrip("/"), str(self.proxy.make_url("/")).rstrip("/"))
        self.db = Database(self.root / "characterlock.sqlite3")
        self.storage = Storage(self.root, self.db, 1024 * 1024)
        self.worker = JobWorker(self.db, self.storage, self.client, JobHub(), 0.001)
        self.character_id, self.workflow_id = uid(), uid()
        self.db.execute("INSERT INTO characters(id,name,consent_confirmed,created_at,updated_at) VALUES(?,?,?,?,?)", (self.character_id, "Isolated fixture", 1, now(), now()))
        self.db.execute("INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?,?,?)", (self.workflow_id, "Isolated fixture", "character_lab", encode(GRAPH), encode(MAPPING), encode(WorkflowAdapter(GRAPH, MAPPING).inspect()), None, "fixture.json", "fixture", now()))

    async def asyncTearDown(self):
        await self.worker.close()
        await self.client.close()
        await self.proxy.close()
        await self.upstream.close()
        self.temp.cleanup()

    def add_job(self, status="queued", prompt_id=None):
        job_id = uid()
        self.db.execute("INSERT INTO jobs(id,module,character_id,workflow_id,status,parameters,asset_inputs,prompt_id,client_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (job_id, "character_lab", self.character_id, self.workflow_id, status, encode({"prompt": "Isolated fixture"}), "{}", prompt_id, uid(), now(), now()))
        return self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))

    async def test_worker_sdk_proxy_output_storage_and_resume_without_new_submit(self):
        self.assertTrue(await self.client.proxy_health())
        row = self.add_job()
        await asyncio.wait_for(self.worker.execute(row), 5)
        result = self.db.one("SELECT * FROM jobs WHERE id=?", (row["id"],))
        self.assertEqual(result["status"], "succeeded", result)
        self.assertEqual(len(self.submissions), 1)
        asset_id = json.loads(result["output_assets"])[0]
        _, saved = self.storage.asset_path(asset_id)
        self.assertEqual(saved.read_bytes(), png())
        event = self.db.one("SELECT detail FROM job_events WHERE job_id=? AND status='running'", (row["id"],))
        self.assertEqual(json.loads(event["detail"])["transport"], "comfy-sdk")
        # Persisted upstream ID is observed with a fresh SDK client, never re-run.
        resumed = self.add_job("running", result["prompt_id"])
        await self.client.close()
        self.client = SDKComfyClient(str(self.upstream.make_url("/")).rstrip("/"), str(self.proxy.make_url("/")).rstrip("/"))
        self.worker.comfy = self.client
        await asyncio.wait_for(self.worker.observe(resumed, resumed=True), 5)
        self.assertEqual(len(self.submissions), 1)
        self.assertEqual(self.db.one("SELECT status FROM jobs WHERE id=?", (resumed["id"],))["status"], "succeeded")

    async def test_proxy_persists_idempotency_and_outputs_across_restart(self):
        result = await self.client.submit(GRAPH, "persisted-key")
        await self.proxy.close()
        self.proxy = TestServer(make_app(str(self.upstream.make_url("/")).rstrip("/"), state_dir=self.root / "proxy-state"))
        await self.proxy.start_server()
        await self.client.close()
        self.client = SDKComfyClient(str(self.upstream.make_url("/")).rstrip("/"), str(self.proxy.make_url("/")).rstrip("/"))
        with self.assertRaises(ComfyError) as caught:
            await self.client.submit(GRAPH, "persisted-key")
        self.assertTrue(caught.exception.details["submission_uncertain"])
        self.assertEqual(len(self.submissions), 1)
        history = await self.client.history(result["prompt_id"])
        output = history[result["prompt_id"]]["outputs"]["2"]["images"][0]
        self.assertEqual(await self.client.download_output(output), png())

    async def test_definite_upstream_rejection_marks_failed_without_unknown_submission(self):
        self.rejected = True
        row = self.add_job()
        await asyncio.wait_for(self.worker.execute(row), 5)
        result = self.db.one("SELECT * FROM jobs WHERE id=?", (row["id"],))
        self.assertEqual(result["status"], "failed", result)
        self.assertIsNone(result["prompt_id"])


class SDKProxyLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_hidden_start_reuse_and_shutdown_preserves_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = Settings(data_dir=Path(temporary))
            class Client:
                ready = False
                async def proxy_health(self):
                    return self.ready
            class Process:
                pid = 987654
                def poll(self):
                    return None
            client, calls = Client(), []
            def factory(command, **kwargs):
                calls.append((command, kwargs))
                client.ready = True
                return Process()
            async def closed():
                return False
            proxy = SDKProxyManager(settings, client, process_factory=factory, port_probe=closed)
            self.assertTrue(await proxy.ensure_running())
            self.assertTrue(await proxy.ensure_running())
            self.assertEqual(len(calls), 1)
            command, options = calls[0]
            self.assertIn("comfy_api_proxy.cli", command)
            self.assertIn("--state-dir", command)
            self.assertNotIn("--comfyui-base-dir", command)
            self.assertFalse(options["shell"])
            if os.name == "nt":
                self.assertTrue(options["creationflags"] & 0x08000000)
            await proxy.close()
            self.assertIsNone(proxy.process.poll())

    async def test_settings_refuse_cloud_target_and_shared_ports(self):
        for url in ("https://cloud.comfy.org", "http://127.0.0.1:8188", "http://0.0.0.0:8189"):
            with self.assertRaises(ValueError):
                Settings(comfy_proxy_url=url)
