"""Independent Character Lab acceptance checks; never uses the live library/GPU."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.db import Database, SCHEMA, encode, uid
from app.storage import Storage


class LabMigrationAcceptanceTests(unittest.TestCase):
    def test_v2_migration_preserves_every_legacy_record_and_file(self):
        """New stage/revision state must not reorganize old assets or profiles."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "characterlock.sqlite3"
            character_id, asset_id, workflow_id, job_id, preset_id = [uid() for _ in range(5)]
            relative = f"characters/{character_id}/expressions/{asset_id}.png"
            files = {
                relative: b"legacy image bytes preserved without re-encoding",
                f"characters/{character_id}/profile.json": b'{"name":"Legacy","custom":"keep me"}\r\n',
                f"workflows/{workflow_id}/original.json": b'{ "legacy": true, "widgets_values": [42] }\r\n',
                f"workflows/{workflow_id}/mapping.json": b'{ "parameters": {}, "output_nodes": [] }\r\n',
                f"jobs/{job_id}/prompt.json": b'{ "immutable": "old execution" }\r\n',
                f"jobs/{job_id}/history.json": b'{ "outputs": {} }\r\n',
            }
            for relative_path, content in files.items():
                destination = root / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            old_schema = SCHEMA.split("CREATE TABLE IF NOT EXISTS lab_characters", 1)[0]
            connection = sqlite3.connect(path)
            try:
                connection.executescript(old_schema + "\nPRAGMA user_version=2;")
                connection.execute("INSERT INTO characters VALUES(?,?,?,?,?,?,?,?)", (character_id, "Legacy", "Physical description", "Hand-written prompt", 1, "old-created", "old-updated", '{"age":"42"}'))
                connection.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?)", (asset_id, character_id, "expressions", "old-expression.png", "image/png", len(files[relative]), relative, hashlib.sha256(files[relative]).hexdigest(), '{"origin":"user","custom":"keep"}', "old-created"))
                connection.execute("INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?,?,?)", (workflow_id, "Legacy workflow", "character_lab", '{"nodes":[]}', '{"parameters":{}}', '{"format":"ui","executable":false}', None, f"workflows/{workflow_id}/original.json", "original-digest", "old-created"))
                connection.execute("INSERT INTO jobs(id,module,character_id,workflow_id,status,parameters,asset_inputs,prompt_id,client_id,output_assets,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, "character_lab", character_id, workflow_id, "succeeded", '{"steps":25}', "{}", "old-prompt-id", "old-client", encode([asset_id]), "old-created", "old-updated"))
                connection.execute("INSERT INTO job_events(job_id,status,detail,created_at) VALUES(?,?,?,?)", (job_id, "succeeded", '{"output_count":1}', "old-created"))
                connection.execute("INSERT INTO presets VALUES(?,?,?,?,?)", (preset_id, character_id, "Legacy preset", '{"seed":42}', "old-created"))
                connection.commit()
                connection.row_factory = sqlite3.Row
                legacy_tables = ("characters", "assets", "workflows", "jobs", "job_events", "presets")
                original_rows = {table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")] for table in legacy_tables}
            finally:
                connection.close()

            migrated = Database(path)
            Storage(root, migrated, 1024 * 1024)
            Database(path)  # A repeated restart must be idempotent too.

            self.assertEqual(migrated.one("PRAGMA user_version")["user_version"], 3)
            for table, rows in original_rows.items():
                self.assertEqual(migrated.all(f"SELECT * FROM {table} ORDER BY rowid"), rows, table)
            for relative_path, content in files.items():
                self.assertEqual((root / relative_path).read_bytes(), content, relative_path)
            for table in ("lab_characters", "lab_revisions", "lab_assets", "lab_workflows", "lab_jobs"):
                self.assertEqual(migrated.one(f"SELECT COUNT(*) AS n FROM {table}")["n"], 0, table)
            with migrated.connect() as connection:
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])


class LabApiAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        # Protect the global default app even when this file runs independently;
        # importing app.main must never migrate the user's production library.
        from fastapi.testclient import TestClient
        with patch.dict("os.environ", {"CHARACTERLOCK_DATA_DIR": str(self.root / "bootstrap")}):
            from app.main import create_app
        from app.settings import Settings
        from test_api import FixtureComfy

        self.settings = Settings(data_dir=self.root, start_worker=False, comfy_autostart=False, comfy_proxy_autostart=False)
        self.comfy = FixtureComfy()
        self.app = create_app(self.settings, comfy=self.comfy)
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8000")
        self.client.__enter__()
        self.character = self.new_character("Independent acceptance fixture")
        self.base = f"/api/characters/{self.character['id']}/lab"

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temporary.cleanup()

    def new_character(self, name):
        response = self.client.post("/api/characters", json={"name": name, "description": "Physical identity", "prompt": "Original prompt", "consent_confirmed": True})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def upload(self, category="character_sheets", character=None, audio=False):
        from test_api import png
        character = character or self.character
        data = b"RIFF\x14\x00\x00\x00WAVEfmt \x00\x00\x00\x00" if audio else png()
        filename, media = ("fixture.wav", "audio/wav") if audio else ("fixture.png", "image/png")
        response = self.client.post(f"/api/characters/{character['id']}/assets", files={"file": (filename, data, media)}, data={"category": category, "consent_confirmed": "true"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def state(self):
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def approve(self, asset):
        response = self.client.post(self.base + "/approve-sheet", json={"asset_id": asset["id"]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_read_only_legacy_view_neither_approves_nor_rewrites_old_data(self):
        self.upload("expressions")
        self.upload("poses")
        self.upload("dataset")
        profile_path = self.root / "characters" / self.character["id"] / "profile.json"
        profile_bytes = profile_path.read_bytes()
        original_assets = self.app.state.db.all("SELECT * FROM assets ORDER BY id")
        original_characters = self.app.state.db.all("SELECT * FROM characters ORDER BY id")
        for _ in range(2):
            state = self.state()
            self.assertIsNone(state["principal_asset_id"])
            self.assertIsNone(state["active_revision_id"])
            self.assertEqual([stage["key"] for stage in state["stages"]], ["character_sheet", "dataset", "outfits", "references"])
            stages = {stage["key"]: stage for stage in state["stages"]}
            for name in ("dataset", "outfits", "references"):
                self.assertTrue(stages[name]["locked"], name)
                self.assertTrue(stages[name]["reason"], name)
        self.assertEqual(self.app.state.db.all("SELECT * FROM assets ORDER BY id"), original_assets)
        self.assertEqual(self.app.state.db.all("SELECT * FROM characters ORDER BY id"), original_characters)
        self.assertEqual(profile_path.read_bytes(), profile_bytes)
        for table in ("lab_characters", "lab_revisions", "lab_assets"):
            self.assertEqual(self.app.state.db.one(f"SELECT COUNT(*) AS n FROM {table}")["n"], 0)
        self.assertEqual(self.comfy.submissions, [])

    def test_sheet_approval_is_explicit_idempotent_and_does_not_unlock_without_dataset(self):
        sheet = self.upload()
        first = self.approve(sheet)
        second = self.approve(sheet)
        self.assertEqual(first["principal_asset_id"], sheet["id"])
        self.assertEqual(first["active_revision_id"], second["active_revision_id"])
        self.assertEqual(len(second["revisions"]), 1)
        stages = {stage["key"]: stage for stage in second["stages"]}
        self.assertTrue(stages["character_sheet"]["complete"])
        self.assertFalse(stages["dataset"]["locked"])
        self.assertFalse(stages["dataset"]["complete"])
        self.assertTrue(stages["outfits"]["locked"])
        self.assertTrue(stages["references"]["locked"])
        self.assertEqual(self.comfy.submissions, [])

    def test_cross_character_approval_and_edit_are_rejected_without_side_effects(self):
        other = self.new_character("Other independent fixture")
        foreign = self.upload(character=other)
        for method, endpoint, body in (
            ("post", self.base + "/approve-sheet", {"asset_id": foreign["id"]}),
            ("patch", self.base + "/assets/" + foreign["id"], {"stage": "dataset", "approval": "approved"}),
            ("post", self.base + "/default-outfit", {"asset_id": foreign["id"]}),
        ):
            response = getattr(self.client, method)(endpoint, json=body)
            self.assertIn(response.status_code, {404, 422}, response.text)
        self.assertIsNone(self.state()["principal_asset_id"])
        self.assertEqual(self.app.state.db.one("SELECT COUNT(*) AS n FROM lab_revisions")["n"], 0)
        self.assertEqual(self.comfy.submissions, [])

    def test_nonimage_and_missing_file_cannot_become_principal(self):
        audio = self.upload("audio", audio=True)
        response = self.client.post(self.base + "/approve-sheet", json={"asset_id": audio["id"]})
        self.assertIn(response.status_code, {404, 422}, response.text)
        sheet = self.upload()
        _, path = self.app.state.storage.asset_path(sheet["id"])
        path.unlink()  # Test-owned temporary file only.
        response = self.client.post(self.base + "/approve-sheet", json={"asset_id": sheet["id"]})
        self.assertIn(response.status_code, {404, 422}, response.text)
        self.assertIsNone(self.state()["principal_asset_id"])
        self.assertEqual(self.app.state.db.one("SELECT COUNT(*) AS n FROM lab_revisions")["n"], 0)

    def test_base_workflow_is_not_silently_reclassified_as_character_sheet(self):
        from test_api import GRAPH, MAPPING
        response = self.client.post("/api/workflows", json={"name": "Legacy portrait, not a sheet", "module": "character_lab", "workflow": GRAPH, "mapping": MAPPING})
        self.assertEqual(response.status_code, 201, response.text)
        state = self.state()
        self.assertEqual(state["workflow_bindings"], [])
        self.assertTrue(all(not stage["workflow_ids"] for stage in state["stages"]))
        response = self.client.post(self.base + "/generate", json={"stage": "character_sheet", "workflow_id": response.json()["id"], "consent_confirmed": True})
        self.assertIn(response.status_code, {409, 422}, response.text)
        self.assertEqual(self.client.get("/api/jobs").json(), [])

    def test_replacing_sheet_preserves_old_dataset_and_outfit_revision(self):
        first = self.approve(self.upload())
        old_revision = first["active_revision_id"]
        dataset = self.upload("dataset")
        response = self.client.patch(self.base + "/assets/" + dataset["id"], json={"approval": "approved", "category": "face", "priority": True})
        self.assertEqual(response.status_code, 200, response.text)
        outfit = self.upload("outfits")
        response = self.client.patch(self.base + "/assets/" + outfit["id"], json={"approval": "approved", "outfit_name": "Old revision wardrobe"})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(self.base + "/default-outfit", json={"asset_id": outfit["id"]})
        self.assertEqual(response.status_code, 200, response.text)
        original_metadata = {asset_id: self.app.state.db.one("SELECT * FROM lab_assets WHERE asset_id=?", (asset_id,)) for asset_id in (dataset["id"], outfit["id"])}
        original_paths = {asset_id: self.app.state.storage.asset_path(asset_id)[1] for asset_id in original_metadata}
        original_bytes = {asset_id: path.read_bytes() for asset_id, path in original_paths.items()}
        second = self.approve(self.upload())
        self.assertNotEqual(second["active_revision_id"], old_revision)
        self.assertIsNone(second["default_outfit_asset_id"])
        stages = {stage["key"]: stage for stage in second["stages"]}
        self.assertFalse(stages["dataset"]["complete"])
        self.assertTrue(stages["outfits"]["locked"])
        self.assertTrue(stages["references"]["locked"])

        for asset_id, metadata in original_metadata.items():
            response = self.client.patch(self.base + "/assets/" + asset_id, json={"approval": "approved"})
            self.assertEqual(response.status_code, 409, response.text)
            response = self.client.patch(self.base + "/assets/" + asset_id, json={"stage": "references", "category": "references"})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(self.app.state.db.one("SELECT * FROM lab_assets WHERE asset_id=?", (asset_id,)), metadata)
            self.assertEqual(original_paths[asset_id].read_bytes(), original_bytes[asset_id])
        self.assertEqual(self.client.post(self.base + "/default-outfit", json={"asset_id": outfit["id"]}).status_code, 409)
        self.assertEqual(len(self.state()["revisions"]), 2)

    def test_profile_preserves_custom_keys_and_lab_pointers_through_ordinary_edit(self):
        profile_path = self.root / "characters" / self.character["id"] / "profile.json"
        original = json.loads(profile_path.read_text(encoding="utf-8"))
        original["custom_legacy_metadata"] = {"note": "Keep this existing information", "nested": [1, 2, 3]}
        profile_path.write_text(json.dumps(original), encoding="utf-8")
        sheet = self.upload()
        state = self.approve(sheet)
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        self.assertEqual(profile["custom_legacy_metadata"], original["custom_legacy_metadata"])
        self.assertEqual(profile["lab"]["principal_asset_id"], sheet["id"])
        self.assertEqual(profile["lab"]["active_revision_id"], state["active_revision_id"])
        response = self.client.patch(f"/api/characters/{self.character['id']}", json={"description": "Explicitly edited physical identity"})
        self.assertEqual(response.status_code, 200, response.text)
        edited = json.loads(profile_path.read_text(encoding="utf-8"))
        self.assertEqual(edited["custom_legacy_metadata"], original["custom_legacy_metadata"])
        self.assertEqual(edited["lab"], profile["lab"])
        self.assertEqual(edited["description"], "Explicitly edited physical identity")

    def test_output_registration_failure_rolls_back_library_and_checkpoint_together(self):
        from test_api import GRAPH, MAPPING
        response = self.client.post("/api/workflows", json={"name": "Transactional output fixture", "module": "character_lab", "workflow": GRAPH, "mapping": MAPPING})
        self.assertEqual(response.status_code, 201, response.text)
        workflow_id = response.json()["id"]
        response = self.client.post("/api/lab/workflows", json={"workflow_id": workflow_id, "stage": "character_sheet", "prompt_parameter": "prompt", "output_categories": {"2": "character_sheet"}})
        self.assertEqual(response.status_code, 201, response.text)
        response = self.client.post(self.base + "/generate", json={"stage": "character_sheet", "workflow_id": workflow_id, "consent_confirmed": True})
        self.assertEqual(response.status_code, 202, response.text)
        job_id = response.json()["id"]
        row = self.app.state.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        with patch("app.jobs.CharacterLab.write_asset", side_effect=RuntimeError("Isolated lab metadata persistence failure")):
            asyncio.run(self.app.state.worker.execute(row))
        job = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(job["status"], "needs_attention", job)
        self.assertEqual(job["output_assets"], [])
        self.assertEqual(self.app.state.db.one("SELECT COUNT(*) AS n FROM assets")["n"], 0)
        self.assertEqual(self.app.state.db.one("SELECT COUNT(*) AS n FROM lab_assets")["n"], 0)
        self.assertEqual(list((self.root / "characters" / self.character["id"] / "character_sheets").iterdir()), [])
        self.assertEqual(list((self.root / "tmp").iterdir()), [])

    def test_original_steps_default_is_captured_in_generation_provenance(self):
        from test_api import GRAPH, MAPPING
        original_info = self.comfy.object_info

        async def fixture_info_with_steps():
            schema = await original_info()
            schema["FixtureImageSource"]["input"]["required"]["steps"] = ["INT", {"min": 1, "max": 50}]
            return schema

        self.comfy.object_info = fixture_info_with_steps
        graph, mapping = deepcopy(GRAPH), deepcopy(MAPPING)
        graph["1"]["inputs"]["steps"] = 8
        mapping["parameters"]["steps"] = {"node_id": "1", "input": "steps", "type": "integer", "min": 1, "max": 50}
        response = self.client.post("/api/workflows", json={"name": "Workflow-owned steps fixture", "module": "character_lab", "workflow": graph, "mapping": mapping})
        self.assertEqual(response.status_code, 201, response.text)
        workflow_id = response.json()["id"]
        response = self.client.post("/api/lab/workflows", json={"workflow_id": workflow_id, "stage": "character_sheet", "prompt_parameter": "prompt", "steps_parameter": "steps", "output_categories": {"2": "character_sheet"}})
        self.assertEqual(response.status_code, 201, response.text)
        response = self.client.post(self.base + "/generate", json={"stage": "character_sheet", "workflow_id": workflow_id, "consent_confirmed": True})
        self.assertEqual(response.status_code, 202, response.text)
        job = response.json()
        self.assertEqual(job["parameters"]["steps"], 8)
        self.assertEqual(job["lab_context"]["parameters"]["steps"], 8)
        row = self.app.state.db.one("SELECT * FROM jobs WHERE id=?", (job["id"],))
        asyncio.run(self.app.state.worker.execute(row))
        completed = self.client.get(f"/api/jobs/{job['id']}").json()
        self.assertEqual(completed["status"], "succeeded", completed)
        self.assertEqual(completed["output_assets"][0]["metadata"]["parameters"]["steps"], 8)
        self.assertEqual(self.comfy.submissions[0]["1"]["inputs"]["steps"], 8)


if __name__ == "__main__":
    unittest.main()
