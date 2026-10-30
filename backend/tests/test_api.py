"""Isolated contract tests. All Comfy responses here are test fixtures, never product data."""
import asyncio
from copy import deepcopy
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from app.comfy import ComfyError
from app.db import Database, InstanceLock, SCHEMA as DATABASE_SCHEMA, encode, now, uid
from app.jobs import JobHub, JobWorker
from app.main import create_app
from app.settings import Settings
from app.storage import Storage


GRAPH = {
    "1": {"class_type": "FixtureImageSource", "inputs": {"text": "test fixture"}},
    "2": {"class_type": "FixtureSaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "test"}},
}
MAPPING = {"parameters": {"prompt": {"node_id": "1", "input": "text", "type": "string", "required": True, "kind": "prompt"}}, "output_nodes": ["2"]}
SCHEMA = {
    "FixtureImageSource": {"input": {"required": {"text": ["STRING", {}]}}, "output": ["IMAGE"], "output_node": False},
    "FixtureSaveImage": {"input": {"required": {"images": ["IMAGE", {}], "filename_prefix": ["STRING", {}]}}, "output": [], "output_node": True},
    "FixtureLoadImage": {"input": {"required": {"image": [["fixture.png"], {"image_upload": True}]}}, "output": ["IMAGE"], "output_node": False},
}


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


class FixtureComfy:
    def __init__(self, offline=False, ambiguous=False, complete=True):
        self.offline, self.ambiguous, self.complete = offline, ambiguous, complete
        self.submissions = []
        self.histories = {}
        self.closed = False
        self.uploaded_names = ["fixture.png"]

    async def system_stats(self):
        if self.offline:
            raise ComfyError("Test fixture offline")
        return {"system": {"comfyui_version": "fixture", "python_version": "fixture"}, "devices": []}

    async def object_info(self):
        if self.offline:
            raise ComfyError("Test fixture offline")
        schema = deepcopy(SCHEMA)
        schema["FixtureLoadImage"]["input"]["required"]["image"][0] = list(self.uploaded_names)
        return schema

    async def submit(self, prompt, client_id=None):
        self.submissions.append(prompt)
        if self.ambiguous:
            raise ComfyError("Test fixture timed out after upstream accepted")
        prompt_id = f"fixture-{len(self.submissions)}"
        if self.complete:
            self.histories[prompt_id] = {"status": {"completed": True, "status_str": "success", "messages": []}, "outputs": {"2": {"images": [{"filename": "fixture.png", "subfolder": "", "type": "output"}]}, "unselected": {"images": [{"filename": "ignored.png", "type": "output"}]}}}
        return {"prompt_id": prompt_id}

    async def history(self, prompt_id):
        return {prompt_id: self.histories[prompt_id]} if prompt_id in self.histories else {}

    async def queue(self):
        return {"queue_running": [], "queue_pending": []}

    async def upload_file(self, path):
        self.uploaded_names.append(path.name)
        return {"name": path.name, "subfolder": "", "type": "input"}

    async def download_output(self, descriptor):
        return png()

    async def close(self):
        self.closed = True


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.temp.name), start_worker=False, poll_seconds=0.01, comfy_autostart=False)
        self.comfy = FixtureComfy()
        self.app = create_app(self.settings, comfy=self.comfy)
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8000")
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def character(self, name="Authorized fixture"):
        response = self.client.post("/api/characters", json={"name": name, "prompt": "A fictional character", "consent_confirmed": True})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def workflow(self, graph=GRAPH, mapping=MAPPING):
        response = self.client.post("/api/workflows", json={"name": "Isolated fixture", "module": "character_lab", "workflow": graph, "mapping": mapping})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def job(self, character=None, workflow=None):
        character, workflow = character or self.character(), workflow or self.workflow()
        response = self.client.post("/api/jobs", json={"module": "character_lab", "character_id": character["id"], "workflow_id": workflow["id"], "parameters": {"prompt": "Fixture request"}, "consent_confirmed": True})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def test_identity_consent_and_library_persistence(self):
        self.assertEqual(self.client.post("/api/characters", json={"name": "x", "consent_confirmed": False}).status_code, 422)
        character = self.character()
        result = self.client.patch(f"/api/characters/{character['id']}", json={"description": "Updated"})
        self.assertEqual(result.json()["description"], "Updated")
        profile = self.settings.data_dir / "characters" / character["id"] / "profile.json"
        self.assertEqual(json.loads(profile.read_text(encoding="utf-8"))["description"], "Updated")
        fresh = Database(self.settings.data_dir / "characterlock.sqlite3")
        self.assertEqual(fresh.one("SELECT name FROM characters WHERE id=?", (character["id"],))["name"], character["name"])
        preset = self.client.post(f"/api/characters/{character['id']}/presets", json={"name": "Portrait", "parameters": {"prompt": "A portrait"}})
        self.assertEqual(preset.status_code, 201)
        self.assertEqual(len(self.client.get(f"/api/characters/{character['id']}/presets").json()), 1)

    def test_system_success_reconciles_failed_lifecycle_without_autostart(self):
        engine = self.app.state.engine
        engine.set_state("failed", "Fixture service was previously offline")
        self.assertEqual(self.client.get("/api/engine/status").json()["state"], "failed")
        response = self.client.get("/api/system")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["comfy"]["connected"])
        self.assertEqual(response.json()["comfy"]["lifecycle"]["state"], "ready")
        self.assertEqual(self.client.get("/api/engine/status").json()["state"], "ready")
        self.assertIsNone(engine.task)
        self.assertIsNone(engine.process)
        self.assertFalse(engine.owned_process)

    def test_unrelated_http_response_does_not_reconcile_failed_lifecycle(self):
        engine = self.app.state.engine
        engine.set_state("failed", "Fixture service was previously offline")

        async def unrelated_stats():
            return {"system": {"comfyui_version": "fixture"}, "devices": []}

        self.comfy.system_stats = unrelated_stats
        response = self.client.get("/api/system")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["comfy"]["connected"])
        self.assertEqual(response.json()["comfy"]["lifecycle"]["state"], "failed")
        self.assertIsNone(engine.task)

    def test_character_catalog_complete_defaults_and_adult_ages(self):
        response = self.client.get("/api/character-options")
        self.assertEqual(response.status_code, 200)
        catalog = response.json()
        self.assertEqual([section["id"] for section in catalog["sections"]], ["identity", "appearance", "style"])
        self.assertEqual(len(catalog["fields"]), 22)
        fields = {field["key"]: field for field in catalog["fields"]}
        self.assertEqual([option["value"] for option in fields["age"]["options"]], [str(age) for age in range(18, 81)])
        self.assertGreaterEqual(len(fields["country"]["options"]), 50)
        for field in catalog["fields"]:
            self.assertIn(catalog["defaults"][field["key"]], {option["value"] for option in field["options"]})

    def test_character_create_without_typing_and_deterministic_composition(self):
        body = {"attributes": {}, "consent_confirmed": True}
        first = self.client.post("/api/characters", json=body)
        second = self.client.post("/api/characters", json=body)
        self.assertEqual(first.status_code, 201, first.text)
        character = first.json()
        self.assertEqual(character["name"], "Sofia Reis")
        self.assertEqual(len(character["attributes"]), 22)
        self.assertEqual(character["attributes_catalog_version"], 1)
        self.assertEqual(character["prompt"], second.json()["prompt"])
        self.assertIn("original fictional adult", character["prompt"])
        profile_path = self.settings.data_dir / "characters" / character["id"] / "profile.json"
        self.assertEqual(json.loads(profile_path.read_text(encoding="utf-8"))["attributes"], character["attributes"])

    def test_independent_country_appearance_and_language(self):
        attributes = {"artistic_name": "Kai Ellis", "country": "JP", "age": "80", "eye_color": "blue", "hair_color": "red", "content_language": "pt_BR", "distinguishing_features": "freckles"}
        result = self.client.post("/api/characters", json={"attributes": attributes, "consent_confirmed": True})
        self.assertEqual(result.status_code, 201, result.text)
        character = result.json()
        for key, value in attributes.items():
            self.assertEqual(character["attributes"][key], value)
        self.assertEqual(character["name"], "Kai Ellis")
        self.assertIn("based in Japan", character["prompt"])
        self.assertIn("blue eyes", character["prompt"])
        self.assertIn("Brazilian Portuguese", character["prompt"])
        self.assertIn("subtle freckles", character["prompt"])

    def test_invalid_attributes_rejected_before_persistence(self):
        for attributes in ({"age": "17"}, {"age": "81"}, {"country": "ZZ"}, {"hair_color": "arbitrary injected text"}, {"not_in_catalog": "x"}):
            response = self.client.post("/api/characters", json={"attributes": attributes, "consent_confirmed": True})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get("/api/characters").json(), [])

    def test_attribute_patch_merges_and_recomposes_only_when_explicit(self):
        character = self.client.post("/api/characters", json={"attributes": {"country": "CA", "hair_color": "black"}, "consent_confirmed": True}).json()
        result = self.client.patch(f"/api/characters/{character['id']}", json={"attributes": {"age": "42"}})
        self.assertEqual(result.status_code, 200, result.text)
        changed = result.json()
        self.assertEqual(changed["attributes"]["age"], "42")
        self.assertEqual(changed["attributes"]["country"], "CA")
        self.assertEqual(changed["attributes"]["hair_color"], "black")
        self.assertIn("42 years old", changed["prompt"])
        renamed = self.client.patch(f"/api/characters/{character['id']}", json={"name": "Custom legacy-compatible name"}).json()
        self.assertEqual(renamed["prompt"], changed["prompt"])
        self.assertEqual(self.client.patch(f"/api/characters/{character['id']}", json={"attributes": {"age": "16"}}).status_code, 422)
        self.assertEqual(self.client.get(f"/api/characters/{character['id']}").json(), renamed)

    def test_legacy_edit_preserves_original_prompt_and_empty_attributes(self):
        legacy = self.character()
        updated = self.client.patch(f"/api/characters/{legacy['id']}", json={"name": "Renamed existing character"}).json()
        self.assertEqual(updated["prompt"], legacy["prompt"])
        self.assertEqual(updated["attributes"], {})
        self.assertIsNone(updated["attributes_catalog_version"])
        structured = self.client.patch(f"/api/characters/{legacy['id']}", json={"attributes": {"hair_color": "blonde"}}).json()
        self.assertEqual(structured["name"], "Renamed existing character")
        self.assertIn("Renamed existing character", structured["prompt"])
        changed_name = self.client.patch(f"/api/characters/{legacy['id']}", json={"attributes": {"artistic_name": "Amara Vale"}}).json()
        self.assertEqual(changed_name["name"], "Amara Vale")

    def test_upload_validates_content_and_guards_paths(self):
        character = self.character()
        url = f"/api/characters/{character['id']}/assets"
        self.assertEqual(self.client.post(url, files={"file": ("x.png", png(), "image/png")}, data={"category": "identity"}).status_code, 422)
        response = self.client.post(url, files={"file": ("../../face.png", png(), "image/png")}, data={"category": "identity", "consent_confirmed": "true"})
        self.assertEqual(response.status_code, 201, response.text)
        asset = response.json()
        self.assertEqual(asset["filename"], "face.png")
        self.assertNotIn("relative_path", asset)
        downloaded = self.client.get(asset["url"])
        self.assertEqual(downloaded.content, png())
        self.assertEqual(downloaded.headers["x-content-type-options"], "nosniff")
        self.assertEqual(self.client.post(url, files={"file": ("x.png", b"malicious", "image/png")}, data={"category": "identity", "consent_confirmed": "true"}).status_code, 422)
        self.assertEqual(self.client.post(url, files={"file": ("x.png", png(), "image/png")}, data={"category": "../../escape", "consent_confirmed": "true"}).status_code, 422)
        self.assertEqual(list((self.settings.data_dir / "tmp").iterdir()), [])
        self.assertEqual(self.client.get("/api/assets/not-an-id/file").status_code, 404)

    def test_local_boundary_cors_and_body_limit(self):
        self.assertEqual(self.client.get("/api/health", headers={"Host": "evil.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/characters", json={"name": "x", "consent_confirmed": True}, headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.get("/api/health", headers={"Origin": "null"}).status_code, 403)
        self.assertEqual(self.client.post("/api/characters", content=b"{}", headers={"Content-Length": str(17 * 1024 * 1024)}).status_code, 413)
        result = self.client.options("/api/characters", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["access-control-allow-origin"], "http://localhost:5173")

    def test_streamed_request_limit_without_content_length(self):
        chunks = (chunk for chunk in [b'{"name":"', b"x" * (16 * 1024 * 1024), b'","consent_confirmed":true}'])
        result = self.client.post("/api/characters", content=chunks, headers={"Content-Type": "application/json"})
        self.assertEqual(result.status_code, 413, result.text)

    def test_owned_asset_binding_stages_image_and_rechecks_choices(self):
        character, other = self.character(), self.character("Other fixture")
        asset = self.client.post(f"/api/characters/{character['id']}/assets", files={"file": ("ref.png", png(), "image/png")}, data={"category": "identity", "consent_confirmed": "true"}).json()
        graph = {"1": {"class_type": "FixtureLoadImage", "inputs": {"image": ""}}, "2": GRAPH["2"]}
        mapping = {"parameters": {"reference": {"node_id": "1", "input": "image", "type": "string", "kind": "image", "required": True}}, "output_nodes": ["2"]}
        workflow = self.workflow(graph, mapping)
        body = {"module": "character_lab", "character_id": other["id"], "workflow_id": workflow["id"], "asset_inputs": {"reference": asset["id"]}, "consent_confirmed": True}
        self.assertEqual(self.client.post("/api/jobs", json=body).status_code, 422)
        body["character_id"] = character["id"]
        response = self.client.post("/api/jobs", json=body)
        self.assertEqual(response.status_code, 202, response.text)
        row = self.app.state.db.one("SELECT * FROM jobs WHERE id=?", (response.json()["id"],))
        asyncio.run(self.app.state.worker.execute(row))
        final = self.client.get(f"/api/jobs/{row['id']}").json()
        self.assertEqual(final["status"], "succeeded", final)
        self.assertTrue(self.comfy.submissions[0]["1"]["inputs"]["image"].endswith(".png"))
        body["asset_inputs"] = {}
        body["parameters"] = {"reference": "C:/secret/image.png"}
        self.assertEqual(self.client.post("/api/jobs", json=body).status_code, 422)

    def test_workflow_import_preserves_original_and_rejects_ui_execution(self):
        workflow = self.workflow()
        original = self.settings.data_dir / "workflows" / workflow["id"] / "original.json"
        before = original.read_bytes()
        report = self.client.post(f"/api/workflows/{workflow['id']}/validate").json()
        self.assertTrue(report["valid"], report)
        self.job(workflow=workflow)
        self.assertEqual(original.read_bytes(), before)
        ui = self.workflow(graph={"nodes": [{"id": 1, "type": "FixtureImageSource"}], "links": []}, mapping={"parameters": {}, "output_nodes": []})
        self.assertFalse(ui["executable"])
        response = self.client.post("/api/jobs", json={"module": "character_lab", "character_id": self.character()["id"], "workflow_id": ui["id"], "parameters": {}, "consent_confirmed": True})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.comfy.submissions, [])

    def test_queued_cancel_and_explicit_retry(self):
        job = self.job()
        self.assertEqual(job["status"], "queued")
        self.assertEqual(self.client.post(f"/api/jobs/{job['id']}/cancel").json()["status"], "cancelled")
        retry = self.client.post(f"/api/jobs/{job['id']}/retry")
        self.assertEqual(retry.status_code, 202, retry.text)
        self.assertNotEqual(retry.json()["id"], job["id"])
        self.app.state.db.transition(retry.json()["id"], "needs_attention")
        self.assertEqual(self.client.post(f"/api/jobs/{retry.json()['id']}/retry").status_code, 409)
        self.assertEqual(self.client.post(f"/api/jobs/{retry.json()['id']}/cancel").status_code, 409)

    def test_offline_system_disables_generation_truthfully(self):
        self.comfy.offline = True
        system = self.client.get("/api/system").json()
        self.assertFalse(system["comfy"]["connected"])
        self.assertTrue(all(not spec["available"] for spec in system["capabilities"].values()))
        response = self.client.post("/api/jobs", json={"module": "character_lab", "character_id": self.character()["id"], "workflow_id": self.workflow()["id"], "parameters": {"prompt": "x"}, "consent_confirmed": True})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.client.get("/api/jobs").json(), [])

    def test_websocket_snapshot(self):
        with self.client.websocket_connect("ws://127.0.0.1:8000/api/ws/jobs") as ws:
            snapshot = ws.receive_json()
            self.assertEqual(snapshot, {"type": "snapshot", "jobs": []})
        with self.assertRaises(Exception):
            with self.client.websocket_connect("ws://127.0.0.1:8000/api/ws/jobs", headers={"Origin": "https://evil.example"}):
                pass

    def test_two_servers_cannot_share_library_lock(self):
        second = InstanceLock(self.settings.data_dir / ".server.lock")
        with self.assertRaises(RuntimeError):
            second.acquire()


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Database(self.root / "characterlock.sqlite3")
        self.storage = Storage(self.root, self.db, 1024 * 1024)
        self.comfy = FixtureComfy()
        self.worker = JobWorker(self.db, self.storage, self.comfy, JobHub(), 0.001)
        self.character_id, self.workflow_id = uid(), uid()
        self.db.execute("INSERT INTO characters(id,name,description,prompt,consent_confirmed,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (self.character_id, "fixture", "", "", 1, now(), now()))
        from app.workflows import WorkflowAdapter
        self.db.execute("INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?,?,?)", (self.workflow_id, "fixture", "character_lab", encode(GRAPH), encode(MAPPING), encode(WorkflowAdapter(GRAPH, MAPPING).inspect()), None, "workflows/fixture/original.json", "fixture", now()))

    async def asyncTearDown(self):
        await self.worker.close()
        self.temp.cleanup()

    def add_job(self, status="queued", prompt_id=None):
        job_id = uid()
        self.db.execute("INSERT INTO jobs(id,module,character_id,workflow_id,status,parameters,asset_inputs,prompt_id,client_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (job_id, "character_lab", self.character_id, self.workflow_id, status, encode({"prompt": "fixture"}), "{}", prompt_id, uid(), now(), now()))
        return self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))

    async def test_real_protocol_result_registered_and_snapshots_saved(self):
        row = self.add_job()
        await self.worker.execute(row)
        result = self.db.one("SELECT * FROM jobs WHERE id=?", (row["id"],))
        self.assertEqual(result["status"], "succeeded", result)
        self.assertEqual(len(json.loads(result["output_assets"])), 1)  # Unselected node ignored.
        self.assertEqual(len(self.comfy.submissions), 1)
        prompt = json.loads((self.root / "jobs" / row["id"] / "prompt.json").read_text())
        self.assertEqual(prompt["1"]["inputs"]["text"], "fixture")
        self.assertTrue((self.root / "jobs" / row["id"] / "history.json").is_file())

    async def test_ambiguous_submission_never_auto_replays(self):
        self.comfy.ambiguous = True
        row = self.add_job()
        await self.worker.execute(row)
        self.assertEqual(self.db.one("SELECT status FROM jobs WHERE id=?", (row["id"],))["status"], "needs_attention")
        self.worker.start()
        await asyncio.sleep(0.01)
        await self.worker.close()
        self.assertEqual(len(self.comfy.submissions), 1)

    async def test_restart_reconciles_persisted_ids_without_submission(self):
        unknown = self.add_job("submitting")
        persisted = self.add_job("running", "fixture-existing")
        self.comfy.histories["fixture-existing"] = {"status": {"completed": True, "status_str": "success"}, "outputs": {}}
        self.worker.start()
        for _ in range(100):
            if self.db.one("SELECT status FROM jobs WHERE id=?", (persisted["id"],))["status"] == "succeeded":
                break
            await asyncio.sleep(0.001)
        self.assertEqual(self.db.one("SELECT status FROM jobs WHERE id=?", (unknown["id"],))["status"], "needs_attention")
        self.assertEqual(self.db.one("SELECT status FROM jobs WHERE id=?", (persisted["id"],))["status"], "succeeded")
        self.assertEqual(self.comfy.submissions, [])
        event = self.db.one("SELECT detail FROM job_events WHERE job_id=? ORDER BY id DESC LIMIT 1", (persisted["id"],))
        self.assertEqual(json.loads(event["detail"])["code"], "completion_without_media")

    async def test_missing_upstream_prompt_is_attention_not_replay(self):
        row = self.add_job("running", "fixture-cleared")
        await self.worker.observe(row, resumed=True)
        self.assertEqual(self.db.one("SELECT status FROM jobs WHERE id=?", (row["id"],))["status"], "needs_attention")
        self.assertEqual(self.comfy.submissions, [])

    async def test_upstream_execution_error_preserves_history(self):
        row = self.add_job("running", "fixture-gpu-error")
        self.comfy.histories["fixture-gpu-error"] = {"status": {"completed": False, "status_str": "error", "messages": [["execution_error", {"exception_type": "OutOfMemoryError", "exception_message": "fixture GPU capacity exceeded"}]]}, "outputs": {}}
        await self.worker.observe(row, resumed=True)
        result = self.db.one("SELECT status,error FROM jobs WHERE id=?", (row["id"],))
        self.assertEqual(result["status"], "failed")
        self.assertIn("OutOfMemoryError", result["error"])
        self.assertTrue((self.root / "jobs" / row["id"] / "history.json").is_file())
        self.assertEqual(self.comfy.submissions, [])

    async def test_live_progress_is_durable_published_and_closed_on_completion(self):
        row = self.add_job("running", "fixture-live")
        ready, closed = asyncio.Event(), asyncio.Event()
        async def events(prompt_id):
            self.assertEqual(prompt_id, row["prompt_id"])
            try:
                yield {"phase": "running", "value": 0.4, "current_node": "12", "step": 4, "steps": 10}
                ready.set()
                await asyncio.Event().wait()
            finally:
                closed.set()
        async def history(prompt_id):
            await ready.wait()
            return {prompt_id: {"status": {"completed": True}, "outputs": {}}}
        self.comfy.progress_events, self.comfy.history = events, history
        messages = self.worker.hub.subscribe()
        await asyncio.wait_for(self.worker.observe(row), 1)
        first = messages.get_nowait()["job"]
        self.assertEqual(first["progress"]["value"], 0.4)
        self.assertEqual(first["progress"]["step"], 4)
        self.assertTrue(closed.is_set())
        result = self.db.one("SELECT status,progress FROM jobs WHERE id=?", (row["id"],))
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(json.loads(result["progress"])["phase"], "saving_outputs")
        self.assertEqual(self.comfy.submissions, [])

    async def test_missing_live_stream_does_not_stall_authoritative_completion(self):
        row = self.add_job("running", "fixture-no-stream")
        async def events(prompt_id):
            raise ComfyError("Fixture stream unavailable")
            yield  # This contract is an async iterator even when unavailable.
        async def history(prompt_id):
            await asyncio.sleep(0)
            return {prompt_id: {"status": {"completed": True}, "outputs": {}}}
        self.comfy.progress_events, self.comfy.history = events, history
        await asyncio.wait_for(self.worker.observe(row), 1)
        self.assertEqual(self.db.one("SELECT status FROM jobs WHERE id=?", (row["id"],))["status"], "succeeded")
        self.assertEqual(self.comfy.submissions, [])

    async def test_queue_and_connection_observations_publish_without_fake_percentages(self):
        row = self.add_job("running", "fixture-reconnect")
        calls = 0
        async def history(prompt_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ComfyError("Fixture connection dropped")
            if calls == 2:
                return {}
            return {prompt_id: {"status": {"completed": True}, "outputs": {}}}
        async def queue():
            return {"queue_running": [], "queue_pending": [[0, "fixture-other"], [1, row["prompt_id"]]]}
        self.comfy.history, self.comfy.queue = history, queue
        messages = self.worker.hub.subscribe()
        await asyncio.wait_for(self.worker.observe(row, resumed=True), 1)
        reconnecting, queued = messages.get_nowait()["job"], messages.get_nowait()["job"]
        self.assertEqual(reconnecting["progress"]["phase"], "reconnecting")
        self.assertEqual(queued["progress"]["phase"], "queued")
        self.assertEqual(queued["progress"]["queue_position"], 2)
        self.assertNotIn("value", queued["progress"])
        self.assertEqual(self.comfy.submissions, [])

    async def test_unchanged_progress_does_not_repeat_websocket_updates(self):
        row = self.add_job("running", "fixture-unchanged")
        messages = self.worker.hub.subscribe()
        self.worker.update_progress(row["id"], {"phase": "running", "step": 1, "steps": 10})
        self.worker.update_progress(row["id"], {"phase": "running", "step": 1, "steps": 10})
        self.assertEqual(messages.qsize(), 1)

    async def test_restarted_preparation_can_replace_unsubmitted_snapshot(self):
        row = self.add_job()
        snapshot_dir = self.root / "jobs" / row["id"]
        snapshot_dir.mkdir(parents=True)
        (snapshot_dir / "prompt.json").write_text('{}', encoding="utf-8")
        (snapshot_dir / "request.json").write_text('{}', encoding="utf-8")
        await self.worker.execute(row)
        self.assertEqual(self.db.one("SELECT status FROM jobs WHERE id=?", (row["id"],))["status"], "succeeded")
        self.assertEqual(len(self.comfy.submissions), 1)


class MigrationTests(unittest.TestCase):
    def test_v1_migration_preserves_profiles_assets_presets_and_jobs(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "existing.sqlite3"
            old_schema = DATABASE_SCHEMA.replace(", attributes TEXT NOT NULL DEFAULT '{}'", "")
            connection = sqlite3.connect(path)
            try:
                connection.executescript(old_schema + "\nPRAGMA user_version=1;")
                connection.execute("INSERT INTO characters VALUES(?,?,?,?,?,?,?)", ("legacy", "Original name", "Original description", "Original hand-written prompt", 1, "old-created", "old-updated"))
                connection.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)", ("legacy-asset", "legacy", "identity", "face.png", "image/png", 100, "characters/legacy/identity/face.png", "digest", "{}", "old-created"))
                connection.execute("INSERT INTO presets VALUES(?,?,?,?,?)", ("legacy-preset", "legacy", "Original preset", '{"seed":12}', "old-created"))
                connection.execute("INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?,?,?)", ("legacy-workflow", "Original workflow", "character_lab", "{}", "{}", "{}", None, "workflows/original.json", "digest", "old-created"))
                connection.execute("INSERT INTO jobs(id,module,character_id,workflow_id,status,parameters,asset_inputs,client_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", ("legacy-job", "character_lab", "legacy", "legacy-workflow", "cancelled", "{}", "{}", "client", "old-created", "old-updated"))
                connection.commit()
            finally:
                connection.close()
            db = Database(path)
            row = db.one("SELECT * FROM characters WHERE id='legacy'")
            self.assertEqual(row["name"], "Original name")
            self.assertEqual(row["prompt"], "Original hand-written prompt")
            self.assertEqual(row["description"], "Original description")
            self.assertEqual(row["created_at"], "old-created")
            self.assertEqual(row["updated_at"], "old-updated")
            self.assertEqual(row["attributes"], "{}")
            for table in ("assets", "presets", "workflows", "jobs"):
                self.assertEqual(db.one(f"SELECT COUNT(*) AS count FROM {table}")["count"], 1)
            self.assertEqual(db.one("PRAGMA user_version")["user_version"], 3)
            Database(path)  # Idempotent repeated startup.
            self.assertEqual(db.one("SELECT COUNT(*) AS count FROM characters")["count"], 1)


if __name__ == "__main__":
    unittest.main()
