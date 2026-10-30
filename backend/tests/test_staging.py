"""A real client/worker contract test for ComfyUI's input-root image choices."""
from email import policy
from email.parser import BytesParser
import io
import json
from pathlib import Path
import tempfile
import unittest

import httpx
from PIL import Image

from app.comfy import ComfyClient
from app.db import Database, encode, now, uid
from app.jobs import JobHub, JobWorker
from app.storage import Storage
from app.workflows import WorkflowAdapter


class ImageStagingTests(unittest.IsolatedAsyncioTestCase):
    async def test_uploaded_root_image_passes_worker_choice_revalidation(self):
        await self.stage_image(simulate_legacy=False)

    async def test_legacy_subfolder_is_rejected_before_submission(self):
        await self.stage_image(simulate_legacy=True)

    async def stage_image(self, *, simulate_legacy):
        # Installed LoadImage uses os.listdir(input_dir), not a recursive scan.
        # Keep the transport fixture equally strict so a subfolder upload fails
        # the worker's second validation rather than silently bypassing it.
        root_choices, uploads, submissions = [], [], []
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        async def handler(request):
            if request.url.path == "/object_info":
                return httpx.Response(200, json={
                    "LoadImage": {"input": {"required": {"image": [list(root_choices), {"image_upload": True}]}}, "output": ["IMAGE"]},
                    "SaveImage": {"input": {"required": {"images": ["IMAGE", {}]}}, "output": [], "output_node": True},
                })
            if request.url.path == "/upload/image":
                body = await request.aread()
                message = BytesParser(policy=policy.default).parsebytes(
                    b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + body)
                fields, filename = {}, None
                for part in message.iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    if name == "image":
                        filename = part.get_filename()
                        self.assertEqual(part.get_payload(decode=True), image_bytes)
                    else:
                        fields[name] = part.get_payload(decode=True).decode()
                self.assertIsNotNone(filename)
                uploads.append((filename, fields))
                if fields.get("subfolder", "") == "":
                    root_choices.append(filename)
                return httpx.Response(200, json={"name": filename, "subfolder": fields.get("subfolder", ""), "type": "input"})
            if request.url.path == "/prompt":
                payload = json.loads(request.content)
                submissions.append(payload)
                self.assertIn(payload["prompt"]["1"]["inputs"]["image"], root_choices)
                return httpx.Response(200, json={"prompt_id": "fixture-staged"})
            if request.url.path == "/history/fixture-staged":
                return httpx.Response(200, json={"fixture-staged": {"status": {"completed": True, "status_str": "success"}, "outputs": {"2": {"images": [{"filename": "fixture.png", "type": "output"}]}}}})
            if request.url.path == "/view":
                return httpx.Response(200, content=image_bytes)
            self.fail(f"Unexpected fixture request: {request.method} {request.url.path}")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = Database(root / "fixture.sqlite3")
            storage = Storage(root, db, 1024 * 1024)
            character_id, workflow_id, job_id = uid(), uid(), uid()
            db.execute("INSERT INTO characters(id,name,description,prompt,consent_confirmed,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (character_id, "fixture", "", "", 1, now(), now()))
            source = root / "source.png"
            source.write_bytes(image_bytes)
            asset = storage.register(source, character_id, "identity", "reference.png")
            graph = {"1": {"class_type": "LoadImage", "inputs": {"image": ""}}, "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}}}
            mapping = {"parameters": {"reference": {"node_id": "1", "input": "image", "type": "string", "kind": "image", "required": True}}, "output_nodes": ["2"]}
            db.execute("INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?,?,?)", (workflow_id, "fixture", "video_studio", encode(graph), encode(mapping), encode(WorkflowAdapter(graph, mapping).inspect()), None, "workflows/fixture/original.json", "fixture", now()))
            db.execute("INSERT INTO jobs(id,module,character_id,workflow_id,status,parameters,asset_inputs,client_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (job_id, "video_studio", character_id, workflow_id, "queued", "{}", encode({"reference": asset["id"]}), uid(), now(), now()))
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                client = ComfyClient("http://127.0.0.1:8188", http_client=http)
                if simulate_legacy:
                    # Reproduce the old adapter default through the same real
                    # multipart code, rather than faking the worker's response.
                    async def legacy_upload(path):
                        return await client.upload_image(path, subfolder="characterlock")
                    client.upload_file = legacy_upload
                worker = JobWorker(db, storage, client, JobHub(), poll_seconds=0.001)
                await worker.execute(db.one("SELECT * FROM jobs WHERE id=?", (job_id,)))
            result = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
            self.assertEqual(len(uploads), 1)
            self.assertEqual(uploads[0][0], asset["id"] + ".png")
            if simulate_legacy:
                self.assertEqual(uploads[0][1]["subfolder"], "characterlock")
                self.assertEqual(result["status"], "failed", result)
                error = json.loads(result["error"])
                self.assertEqual(error["code"], "workflow_invalid")
                self.assertIn("input_choice_not_installed", [detail["code"] for detail in error["details"]])
                self.assertEqual(submissions, [])
                self.assertEqual(json.loads(result["output_assets"]), [])
                return
            self.assertEqual(result["status"], "succeeded", result)
            self.assertEqual(uploads[0][1], {"type": "input", "subfolder": "", "overwrite": "false"})
            self.assertEqual(len(submissions), 1)
            snapshot = json.loads((root / "jobs" / job_id / "prompt.json").read_text())
            self.assertEqual(snapshot["1"]["inputs"]["image"], asset["id"] + ".png")
            self.assertEqual(len(json.loads(result["output_assets"])), 1)
