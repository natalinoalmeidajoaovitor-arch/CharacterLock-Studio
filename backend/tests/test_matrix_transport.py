"""Owned H3 reference bundles and approved Sheet anchors; isolated model fixtures."""
import asyncio
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from app.settings import Settings
from app.workflows import WorkflowAdapter


def png():
    stream = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(stream, format="PNG")
    return stream.getvalue()


class FixtureComfy:
    def __init__(self):
        self.uploads, self.submissions, self.histories = [], [], {}

    async def object_info(self):
        return {
            "FixtureImage": {"input": {"required": {"text": ["STRING"], "steps": ["INT", {"min": 1, "max": 50}]}, "optional": {"image": ["IMAGE"]}}, "output": ["IMAGE"]},
            "MiniMaxH3MediaLoader": {"input": {"required": {"media_state": ["STRING", {"default": "[]"}]}}, "output": ["H3_REFS"]},
            "FixtureSplit": {"input": {"required": {"references": ["H3_REFS"]}}, "output": ["IMAGE"]},
            "FixtureLoad": {"input": {"required": {"image": [["fixture.png"], {"image_upload": True}]}}, "output": ["IMAGE"]},
            "FixtureSave": {"input": {"required": {"images": ["IMAGE"]}}, "output": [], "output_node": True},
        }

    async def upload_file(self, path):
        self.uploads.append(path.name)
        return {"name": path.name, "subfolder": "", "type": "input"}

    async def submit(self, prompt, client_id=None):
        self.submissions.append(prompt)
        prompt_id = f"fixture-{len(self.submissions)}"
        outputs = {node: {"images": [{"filename": f"{node}.png", "type": "output"}]} for node, data in prompt.items() if data["class_type"] == "FixtureSave"}
        self.histories[prompt_id] = {"status": {"completed": True, "status_str": "success"}, "outputs": outputs}
        return {"prompt_id": prompt_id}

    async def history(self, prompt_id):
        return {prompt_id: self.histories[prompt_id]}

    async def queue(self):
        return {"queue_running": [], "queue_pending": []}

    async def download_output(self, descriptor):
        return png()

    async def close(self):
        pass


class MatrixTransportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.comfy = FixtureComfy()
        self.app = create_app(Settings(data_dir=self.root, comfy_autostart=False, start_worker=False), comfy=self.comfy)
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8000")
        self.client.__enter__()
        self.character_id = self.client.post("/api/characters", json={"name": "Fixture", "description": "Adult fictional character with brown eyes", "consent_confirmed": True}).json()["id"]
        self.base = f"/api/characters/{self.character_id}/lab"

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temporary.cleanup()

    def workflow(self, stage, role=None, bundle=False):
        graph = {"1": {"class_type": "FixtureImage", "inputs": {"text": "Fixture identity", "steps": 10}}, "2": {"class_type": "FixtureSave", "inputs": {"images": ["1", 0]}}}
        parameters = {"prompt": {"node_id": "1", "input": "text", "type": "string", "kind": "prompt", "required": True}, "steps": {"node_id": "1", "input": "steps", "type": "integer", "min": 1, "max": 50}}
        categories = {"2": "character_sheet" if stage == "character_sheet" else "face"}
        if bundle:
            for index, category in enumerate(("face", "upper_body", "full_body", "side", "back"), start=3):
                graph[str(index)] = deepcopy(graph["2"])
                categories[str(index)] = category
        if role:
            graph["8"] = {"class_type": "MiniMaxH3MediaLoader", "inputs": {"media_state": "[]"}}
            graph["9"] = {"class_type": "FixtureSplit", "inputs": {"references": ["8", 0]}}
            graph["1"]["inputs"]["image"] = ["9", 0]
            parameters["references"] = {"node_id": "8", "input": "media_state", "type": "string", "kind": "image", "required": True, "serializer": "h3_media_state"}
        mapping = {"parameters": parameters, "output_nodes": list(categories)}
        response = self.client.post("/api/workflows", json={"name": "Isolated MATRIX fixture", "module": "character_lab", "workflow": graph, "mapping": mapping})
        self.assertEqual(response.status_code, 201, response.text)
        workflow_id = response.json()["id"]
        binding = {"workflow_id": workflow_id, "stage": stage, "prompt_parameter": "prompt", "steps_parameter": "steps", "reference_parameters": {"references": role} if role else {}, "output_categories": categories}
        response = self.client.post("/api/lab/workflows", json=binding)
        self.assertEqual(response.status_code, 201, response.text)
        return workflow_id, graph, mapping, binding

    def generate(self, stage, workflow_id):
        response = self.client.post(self.base + "/generate", json={"stage": stage, "workflow_id": workflow_id, "steps": 10, "consent_confirmed": True})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def execute(self, job):
        asyncio.run(self.app.state.worker.execute(self.app.state.db.one("SELECT * FROM jobs WHERE id=?", (job["id"],))))
        result = self.client.get(f"/api/jobs/{job['id']}").json()
        self.assertEqual(result["status"], "succeeded", result)
        return result

    def sheet(self):
        workflow_id, _, _, _ = self.workflow("character_sheet", bundle=True)
        job = self.generate("character_sheet", workflow_id)
        self.execute(job)
        state = self.client.get(self.base).json()
        main = next(a["asset_id"] for a in state["assets"] if a.get("job_id") == job["id"] and a["category"] == "character_sheet")
        response = self.client.post(self.base + "/approve-sheet", json={"asset_id": main})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), main

    def test_main_approval_binds_only_its_real_companions_and_preserves_categories(self):
        state, main = self.sheet()
        self.assertEqual(set(state["sheet_anchors"]), {"face", "upper_body", "full_body"})
        self.assertTrue(all(state["sheet_anchors"].values()))
        self.assertEqual({a["category"] for a in state["assets"]}, {"character_sheet", "face", "upper_body", "full_body", "side", "back"})
        self.assertTrue(all(a["approval"] == "approved" and a["revision_id"] == state["active_revision_id"] for a in state["assets"]))
        face = state["sheet_anchors"]["face"]
        self.assertEqual(self.client.post(self.base + "/approve-sheet", json={"asset_id": face}).status_code, 422)
        self.assertEqual(self.client.patch(self.base + "/assets/" + face, json={"category": "character_sheet"}).status_code, 409)
        updated, _ = self.sheet()
        self.assertNotEqual(state["active_revision_id"], updated["active_revision_id"])
        self.assertTrue(set(state["sheet_anchors"].values()).isdisjoint(updated["sheet_anchors"].values()))
        self.assertTrue(any(a["asset_id"] == main and a["revision_id"] == state["active_revision_id"] for a in updated["assets"]))

    def test_expanded_sheet_closeups_and_poses_preserve_bundle_approval(self):
        workflow_id, graph, mapping, binding = self.workflow("character_sheet", bundle=True)
        additions = ("face_three_quarter", "face_profile", "body_three_quarter", "pose_a", "pose_hands_on_hips")
        for index, category in enumerate(additions, start=20):
            graph[str(index)] = deepcopy(graph["2"])
            mapping["output_nodes"].append(str(index))
            binding["output_categories"][str(index)] = category
        from app.db import encode
        self.app.state.db.execute("UPDATE workflows SET workflow=?,mapping=? WHERE id=?", (encode(graph), encode(mapping), workflow_id))
        response = self.client.post("/api/lab/workflows", json=binding)
        self.assertEqual(response.status_code, 201, response.text)
        job = self.generate("character_sheet", workflow_id)
        self.execute(job)
        pending = self.client.get(self.base).json()
        self.assertIsNone(pending["principal_asset_id"])
        self.assertTrue(all(a["approval"] == "pending" for a in pending["assets"]))
        main = next(a["asset_id"] for a in pending["assets"] if a["category"] == "character_sheet")
        response = self.client.post(self.base + "/approve-sheet", json={"asset_id": main})
        self.assertEqual(response.status_code, 200, response.text)
        approved = response.json()
        self.assertTrue(set(additions).issubset({a["category"] for a in approved["assets"]}))
        self.assertTrue(all(a["approval"] == "approved" and a["revision_id"] == approved["active_revision_id"] for a in approved["assets"]))
        self.assertTrue(all(approved["sheet_anchors"].values()))
        new_state, _ = self.sheet()
        old_assets = [a for a in new_state["assets"] if a.get("job_id") == job["id"]]
        self.assertTrue(all(a["revision_id"] == approved["active_revision_id"] for a in old_assets))
        self.assertNotEqual(approved["active_revision_id"], new_state["active_revision_id"])

    def test_h3_bundles_auto_resolve_deduplicate_uploads_and_retry_original_snapshot(self):
        state, _ = self.sheet()
        workflow_id, graph, mapping, binding = self.workflow("dataset", "sheet_full_bundle")
        # Two independent H3 slots share the same approved images. They must
        # retain their order while staging each physical asset only once.
        graph["10"] = {"class_type": "MiniMaxH3MediaLoader", "inputs": {"media_state": "[]"}}
        mapping["parameters"]["upper_references"] = mapping["parameters"]["references"] | {"node_id": "10"}
        row = self.app.state.db.one("SELECT * FROM workflows WHERE id=?", (workflow_id,))
        from app.db import encode
        self.app.state.db.execute("UPDATE workflows SET workflow=?,mapping=? WHERE id=?", (encode(graph), encode(mapping), workflow_id))
        response = self.client.post("/api/lab/workflows", json=binding | {"reference_parameters": {"references": "sheet_full_bundle", "upper_references": "sheet_upper_bundle"}})
        self.assertEqual(response.status_code, 201, response.text)
        job = self.generate("dataset", workflow_id)
        ids = [state["sheet_anchors"][key] for key in ("face", "upper_body", "full_body")]
        self.assertEqual(job["asset_inputs"], {"references": ids, "upper_references": ids[:2]})
        self.sheet()  # A queued job retains the identity it captured.
        self.execute(job)
        self.assertEqual(self.comfy.uploads, [asset_id + ".png" for asset_id in ids])
        prepared = self.comfy.submissions[-1]
        items = json.loads(prepared["8"]["inputs"]["media_state"])
        self.assertEqual(items, [{"kind": "picture", "file": asset_id + ".png", "enabled": True} for asset_id in ids])
        request = json.loads((self.root / "jobs" / job["id"] / "request.json").read_text())
        self.assertEqual(request["asset_inputs"], job["asset_inputs"])
        response = self.client.post(f"/api/jobs/{job['id']}/retry")
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["asset_inputs"], job["asset_inputs"])
        self.assertEqual(response.json()["lab_context"], job["lab_context"])
        self.assertEqual(row["module"], "character_lab")

    def test_legacy_sheet_without_anchors_has_actionable_dataset_blocker(self):
        asset = self.client.post(f"/api/characters/{self.character_id}/assets", data={"category": "character_sheets", "consent_confirmed": "true"}, files={"file": ("fixture.png", png(), "image/png")}).json()["id"]
        self.assertEqual(self.client.post(self.base + "/approve-sheet", json={"asset_id": asset}).status_code, 200)
        workflow_id, _, _, _ = self.workflow("dataset", "sheet_full_bundle")
        response = self.client.post(self.base + "/generate", json={"stage": "dataset", "workflow_id": workflow_id, "consent_confirmed": True})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("face, upper_body, full_body", response.text)

    def test_asset_lists_ownership_bounds_and_scalar_json_cannot_bypass_staging(self):
        state, _ = self.sheet()
        _, graph, mapping, _ = self.workflow("dataset", "sheet_full_bundle")
        # An unbound generic job checks the same staging boundary.
        workflow = self.client.post("/api/workflows", json={"name": "Unbound fixture", "module": "character_lab", "workflow": graph, "mapping": mapping}).json()
        body = {"module": "character_lab", "character_id": self.character_id, "workflow_id": workflow["id"], "parameters": {"prompt": "Fixture", "steps": 10}, "asset_inputs": {"references": [state["sheet_anchors"]["face"]]}, "consent_confirmed": True}
        self.assertEqual(self.client.post("/api/jobs", json=body).status_code, 202)
        for value in ([], [state["sheet_anchors"]["face"]] * 10, [{"file": "secret.png"}], "C:/secret.png"):
            response = self.client.post("/api/jobs", json=body | {"asset_inputs": {"references": value}})
            self.assertIn(response.status_code, {404, 422}, response.text)
        response = self.client.post("/api/jobs", json=body | {"asset_inputs": {}, "parameters": body["parameters"] | {"references": '[{"kind":"picture","file":"secret.png","enabled":true}]'}})
        self.assertEqual(response.status_code, 422)
        other = self.client.post("/api/characters", json={"name": "Other fixture", "consent_confirmed": True}).json()["id"]
        self.assertEqual(self.client.post("/api/jobs", json=body | {"character_id": other}).status_code, 422)
        graph["8"] = {"class_type": "FixtureLoad", "inputs": {"image": "fixture.png"}}
        graph.pop("9")
        graph["1"]["inputs"]["image"] = ["8", 0]
        mapping["parameters"]["references"] = {"node_id": "8", "input": "image", "type": "string", "kind": "image", "required": True}
        native = self.client.post("/api/workflows", json={"name": "Native fixture", "module": "character_lab", "workflow": graph, "mapping": mapping}).json()
        self.assertEqual(self.client.post("/api/jobs", json=body | {"workflow_id": native["id"]}).status_code, 422)

    def test_serializer_mapping_and_serialized_filenames_are_strict(self):
        _, graph, mapping, _ = self.workflow("dataset", "sheet_full_bundle")
        info = asyncio.run(self.comfy.object_info())
        adapter = WorkflowAdapter(graph, mapping)
        parameters = {"prompt": "Fixture", "steps": 10, "references": '[{"kind":"picture","file":"owned.png","enabled":true}]'}
        self.assertTrue(adapter.validate(info, parameters)["valid"])
        for filename in ("C:/secret.png", "../secret.png", "/secret.png", "owned.png [output]", ""):
            value = json.dumps([{"kind": "picture", "file": filename, "enabled": True}])
            self.assertFalse(adapter.validate(info, parameters | {"references": value})["valid"])
        for changes in ({"serializer": "unknown"}, {"input": "other"}, {"type": "integer"}, {"kind": "audio"}, {"required": False}, {"default": "[]"}):
            modified = deepcopy(mapping)
            modified["parameters"]["references"].update(changes)
            self.assertIn("mapping_serializer_invalid", {e["code"] for e in WorkflowAdapter(graph, modified).inspect()["mapping_errors"]})


if __name__ == "__main__":
    unittest.main()
