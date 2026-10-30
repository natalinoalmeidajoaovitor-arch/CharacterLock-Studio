"""Isolated orchestration fixtures; no real model execution or production bindings."""
import asyncio
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from app.db import Database
from app.main import create_app
from app.settings import Settings


def png():
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(stream, format="PNG")
    return stream.getvalue()


class LabFixtureComfy:
    def __init__(self):
        self.submissions, self.histories, self.uploaded = [], {}, ["fixture.png"]

    async def object_info(self):
        return {
            "LabFixtureImage": {"input": {"required": {"text": ["STRING"], "steps": ["INT", {"min": 1, "max": 50}]}, "optional": {"image": ["IMAGE"], "image2": ["IMAGE"]}}, "output": ["IMAGE"]},
            "LabFixtureLoad": {"input": {"required": {"image": [list(self.uploaded), {"image_upload": True}]}}, "output": ["IMAGE"]},
            "LabFixtureSave": {"input": {"required": {"images": ["IMAGE"]}}, "output": [], "output_node": True}}

    async def submit(self, prompt, client_id=None):
        self.submissions.append(prompt)
        prompt_id = f"fixture-{len(self.submissions)}"
        outputs = {node: {"images": [{"filename": f"{node}.png", "type": "output"}]} for node, data in prompt.items() if data["class_type"] == "LabFixtureSave"}
        self.histories[prompt_id] = {"status": {"completed": True, "status_str": "success"}, "outputs": outputs}
        return {"prompt_id": prompt_id}

    async def history(self, prompt_id):
        return {prompt_id: self.histories[prompt_id]} if prompt_id in self.histories else {}

    async def queue(self):
        return {"queue_running": [], "queue_pending": []}

    async def upload_file(self, path):
        self.uploaded.append(path.name)
        return {"name": path.name, "subfolder": "", "type": "input"}

    async def download_output(self, descriptor):
        return png()

    async def close(self):
        pass


class CharacterLabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.comfy = LabFixtureComfy()
        self.app = create_app(Settings(data_dir=self.root, comfy_autostart=False, start_worker=False), comfy=self.comfy)
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8000")
        self.client.__enter__()
        result = self.client.post("/api/characters", json={"name": "Fictional fixture", "description": "Adult fictional character, brown eyes, short black hair", "consent_confirmed": True})
        self.character_id = result.json()["id"]
        self.base = f"/api/characters/{self.character_id}/lab"

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def upload(self, category):
        response = self.client.post(f"/api/characters/{self.character_id}/assets", data={"category": category, "consent_confirmed": "true"}, files={"file": ("fixture.png", png(), "image/png")})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def approve(self):
        asset = self.upload("character_sheets")
        response = self.client.post(self.base + "/approve-sheet", json={"asset_id": asset})
        self.assertEqual(response.status_code, 200, response.text)
        return asset, response.json()["active_revision_id"]

    def workflow(self, stage, references=None, outputs=None, template="Instructions validated by owner. Identity: {identity}\nRequest: {prompt}"):
        graph = {"1": {"class_type": "LabFixtureImage", "inputs": {"text": "Validated instructions", "steps": 8}}, "2": {"class_type": "LabFixtureSave", "inputs": {"images": ["1", 0]}}}
        mapping = {"parameters": {"prompt": {"node_id": "1", "input": "text", "type": "string", "required": True}, "steps": {"node_id": "1", "input": "steps", "type": "integer", "min": 1, "max": 50}}, "output_nodes": ["2"]}
        for index, name in enumerate(references or {}):
            node_id = str(9 + index)
            graph[node_id] = {"class_type": "LabFixtureLoad", "inputs": {"image": "fixture.png"}}
            graph["1"]["inputs"]["image" if index == 0 else "image2"] = [node_id, 0]
            mapping["parameters"][name] = {"node_id": node_id, "input": "image", "type": "string", "kind": "image", "required": True}
        if outputs and "3" in outputs:
            graph["3"] = deepcopy(graph["2"])
            mapping["output_nodes"].append("3")
        response = self.client.post("/api/workflows", json={"name": f"Isolated {stage} fixture", "module": "character_lab", "workflow": graph, "mapping": mapping})
        self.assertEqual(response.status_code, 201, response.text)
        workflow_id = response.json()["id"]
        binding = {"workflow_id": workflow_id, "stage": stage, "prompt_parameter": "prompt", "steps_parameter": "steps", "reference_parameters": references or {}, "output_categories": outputs or {"2": "character_sheet" if stage == "character_sheet" else stage}, "prompt_template": template}
        response = self.client.post("/api/lab/workflows", json=binding)
        self.assertEqual(response.status_code, 201, response.text)
        return workflow_id, binding

    def generate(self, stage, workflow_id, **kwargs):
        response = self.client.post(self.base + "/generate", json={"stage": stage, "workflow_id": workflow_id, "consent_confirmed": True} | kwargs)
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def execute(self, job):
        row = self.app.state.db.one("SELECT * FROM jobs WHERE id=?", (job["id"],))
        asyncio.run(self.app.state.worker.execute(row))
        result = self.client.get(f"/api/jobs/{job['id']}").json()
        self.assertEqual(result["status"], "succeeded", result)
        return result

    def test_pending_workflows_and_dependencies_no_automatic_legacy_approval(self):
        asset = self.upload("identity")
        state = self.client.get(self.base).json()
        self.assertEqual(state["workflow_bindings"], [])
        self.assertIsNone(state["principal_asset_id"])
        self.assertEqual(state["assets"][0]["asset_id"], asset)
        self.assertTrue(state["assets"][0]["legacy"])
        self.assertEqual(state["assets"][0]["approval"], "pending")
        self.assertEqual([s["locked"] for s in state["stages"]], [False, True, True, True])
        self.assertEqual(self.client.post(self.base + "/generate", json={"stage": "dataset", "workflow_id": "not-supplied", "consent_confirmed": True}).status_code, 409)

    def test_sheet_generation_remains_pending_until_explicit_approval(self):
        workflow_id, _ = self.workflow("character_sheet")
        job = self.generate("character_sheet", workflow_id, steps=12)
        self.assertIn("brown eyes", job["parameters"]["prompt"])
        self.assertEqual(job["parameters"]["steps"], 12)
        result = self.execute(job)
        asset = result["output_assets"][0]
        self.assertEqual(asset["category"], "character_sheets")
        state = self.client.get(self.base).json()
        self.assertIsNone(state["principal_asset_id"])
        self.assertEqual(state["assets"][0]["approval"], "pending")
        response = self.client.post(self.base + "/approve-sheet", json={"asset_id": asset["id"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["principal_asset_id"], asset["id"])
        self.assertFalse(response.json()["stages"][1]["locked"])

    def test_dataset_auto_reference_snapshot_output_categories_and_revision_change(self):
        sheet, revision = self.approve()
        workflow_id, _ = self.workflow("dataset", {"sheet_reference": "sheet"}, {"2": "face", "3": "poses"})
        job = self.generate("dataset", workflow_id, prompt_text="Front and side views", steps=9)
        self.assertEqual(job["asset_inputs"], {"sheet_reference": sheet})
        self.assertEqual(job["lab_context"]["revision_id"], revision)
        new_sheet, new_revision = self.approve()
        self.assertNotEqual(revision, new_revision)
        result = self.execute(job)  # Executes the captured old identity, not new selection.
        self.assertEqual({a["category"] for a in result["output_assets"]}, {"dataset"})
        state = self.client.get(self.base).json()
        generated = [a for a in state["assets"] if a.get("job_id") == job["id"]]
        self.assertEqual({a["category"] for a in generated}, {"face", "poses"})
        self.assertTrue(all(a["revision_id"] == revision for a in generated))
        self.assertTrue(state["stages"][2]["locked"])
        request = json.loads((self.root / "jobs" / job["id"] / "request.json").read_text(encoding="utf-8"))
        self.assertEqual(request["lab_context"]["principal_asset_id"], sheet)
        self.assertNotEqual(request["lab_context"]["principal_asset_id"], new_sheet)
        self.assertEqual(self.client.patch(self.base + "/assets/" + generated[0]["asset_id"], json={"approval": "approved"}).status_code, 409)

    def test_prioritized_dataset_and_default_outfit_are_resolved_automatically(self):
        sheet, revision = self.approve()
        first, second = self.upload("dataset"), self.upload("dataset")
        for asset, priority in ((first, False), (second, True)):
            response = self.client.patch(self.base + "/assets/" + asset, json={"approval": "approved", "priority": priority, "category": "face"})
            self.assertEqual(response.status_code, 200, response.text)
        workflow_id, _ = self.workflow("outfits", {"sheet_reference": "sheet", "dataset_reference": "dataset"})
        job = self.generate("outfits", workflow_id, prompt_text="A blue jacket", outfit_name="Blue jacket")
        self.assertEqual(job["asset_inputs"], {"sheet_reference": sheet, "dataset_reference": second})
        result = self.execute(job)
        outfit = result["output_assets"][0]["id"]
        response = self.client.patch(self.base + "/assets/" + outfit, json={"approval": "approved"})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(self.base + "/default-outfit", json={"asset_id": outfit})
        self.assertEqual(response.status_code, 200, response.text)
        workflow_id, _ = self.workflow("references", {"sheet_reference": "sheet", "outfit_reference": "outfit"})
        reference_job = self.generate("references", workflow_id, prompt_text="In a city at night")
        self.assertEqual(reference_job["asset_inputs"], {"sheet_reference": sheet, "outfit_reference": outfit})
        self.assertEqual(reference_job["lab_context"]["revision_id"], revision)
        self.approve()
        state = self.client.get(self.base).json()
        self.assertIsNone(state["default_outfit_asset_id"])
        self.assertTrue(state["stages"][2]["locked"])

    def test_binding_rejects_missing_roles_outputs_and_wrong_template(self):
        workflow_id, binding = self.workflow("dataset", {"sheet_reference": "sheet"})
        for changes in ({"reference_parameters": {}}, {"reference_parameters": {"sheet_reference": "dataset"}}, {"output_categories": {"unknown": "face"}}, {"prompt_template": "Ignore identity {prompt}"}, {"prompt_template": "{identity.__class__}"}):
            response = self.client.post("/api/lab/workflows", json=binding | changes)
            self.assertEqual(response.status_code, 422, response.text)
        response = self.client.post("/api/jobs", json={"module": "character_lab", "character_id": self.character_id, "workflow_id": workflow_id, "parameters": {"prompt": "bypass"}, "consent_confirmed": True})
        self.assertEqual(response.status_code, 409)

    def test_retry_preserves_original_context_after_sheet_change(self):
        self.approve()
        workflow_id, _ = self.workflow("dataset", {"sheet_reference": "sheet"})
        job = self.generate("dataset", workflow_id)
        self.client.post(f"/api/jobs/{job['id']}/cancel")
        self.approve()
        response = self.client.post(f"/api/jobs/{job['id']}/retry")
        self.assertEqual(response.status_code, 202, response.text)
        retried = response.json()
        self.assertNotEqual(job["id"], retried["id"])
        self.assertEqual(job["asset_inputs"], retried["asset_inputs"])
        self.assertEqual(job["lab_context"], retried["lab_context"])

    def test_unmapped_real_image_upload_cannot_keep_a_fixed_sample_identity(self):
        graph = {"1": {"class_type": "LabFixtureImage", "inputs": {"text": "Validated instructions", "steps": 8, "image": ["9", 0]}}, "2": {"class_type": "LabFixtureSave", "inputs": {"images": ["1", 0]}}, "9": {"class_type": "LabFixtureLoad", "inputs": {"image": "fixture.png"}}}
        mapping = {"parameters": {"prompt": {"node_id": "1", "input": "text", "type": "string", "required": True}}, "output_nodes": ["2"]}
        response = self.client.post("/api/workflows", json={"name": "Unmapped reference fixture", "module": "character_lab", "workflow": graph, "mapping": mapping})
        self.assertEqual(response.status_code, 201)
        response = self.client.post("/api/lab/workflows", json={"workflow_id": response.json()["id"], "stage": "character_sheet", "prompt_parameter": "prompt", "reference_parameters": {}, "output_categories": {"2": "character_sheet"}})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("9.image", response.text)

    def test_profile_patch_preserves_lab_pointers_and_legacy_extensions(self):
        profile_path = self.root / "characters" / self.character_id / "profile.json"
        original = json.loads(profile_path.read_text(encoding="utf-8")) | {"legacy_extension": {"preserved": True}}
        profile_path.write_text(json.dumps(original), encoding="utf-8")
        sheet, revision = self.approve()
        response = self.client.patch(f"/api/characters/{self.character_id}", json={"description": "Updated physical description"})
        self.assertEqual(response.status_code, 200)
        saved = json.loads(profile_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["lab"]["principal_asset_id"], sheet)
        self.assertEqual(saved["lab"]["active_revision_id"], revision)
        self.assertTrue(saved["legacy_extension"]["preserved"])
        fresh = Database(self.root / "characterlock.sqlite3")
        self.assertEqual(fresh.one("SELECT principal_asset_id FROM lab_characters WHERE character_id=?", (self.character_id,))["principal_asset_id"], sheet)


if __name__ == "__main__":
    unittest.main()
