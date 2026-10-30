"""One explicitly requested Dataset smoke test: five photos, ten steps.

Requires the expanded Sheet to be approved by the user. Never approves it,
queues multiple tests, retries an ambiguous submission, or runs all 32 views.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import urllib.request

from smoke_sheet import CHARACTER, ROOT, request

REPORT = ROOT / ".local/dataset-five-live-test.json"


def save(report):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["submit", "check", "verify"])
    args = parser.parse_args()
    report = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    if args.action == "submit":
        if report.get("attempted_at"):
            raise SystemExit("The single Dataset test was already attempted; check its saved job/history.")
        sheet = json.loads((ROOT / ".local/sheet-expanded-live-test.json").read_text(encoding="utf-8"))
        if sheet["job"]["status"] != "succeeded":
            raise SystemExit("The expanded Sheet must complete first.")
        board = next(a["id"] for a in sheet["job"]["output_assets"] if a["metadata"].get("lab", {}).get("category") == "character_sheet")
        state = request(f"/api/characters/{CHARACTER}/lab")
        if state["principal_asset_id"] != board or not all(state["sheet_anchors"].get(k) for k in ("face", "upper_body", "full_body")):
            raise SystemExit("Approve the new Sheet and its references before this Dataset test.")
        queue = request("/api/system")["queue"]
        native = request("/queue", base="http://127.0.0.1:8188")
        if queue["active"] or queue["queued"] or native["queue_running"] or native["queue_pending"]:
            raise SystemExit("Both local queues must be idle before the single test.")
        manifest = json.loads((ROOT / "workflows/local/matrix-lab/manifest.json").read_text(encoding="utf-8"))
        workflow = next(w for w in manifest["workflows"] if w["key"] == "dataset-smoke5")
        payload = {"stage": "dataset", "workflow_id": workflow["workflow_id"], "steps": 10, "consent_confirmed": True}
        report = {"attempted_at": datetime.now(timezone.utc).isoformat(), "character_id": CHARACTER, "sheet_asset_id": board, "revision_id": state["active_revision_id"], "request": payload, "expected_photos": 5}
        save(report)
        job = request(f"/api/characters/{CHARACTER}/lab/generate", payload)
        report.update(job_id=job["id"], job=job)
    else:
        if not report.get("job_id"):
            raise SystemExit("No unambiguous job ID; inspect the history before any retry.")
        job = request("/api/jobs/" + report["job_id"])
        report.update(job=job, checked_at=datetime.now(timezone.utc).isoformat())
    save(report)
    if args.action == "verify":
        from PIL import Image
        if job["status"] != "succeeded":
            raise SystemExit("The single test has not succeeded.")
        folder = ROOT / "data/jobs" / job["id"]
        prompt = json.loads((folder / "prompt.json").read_text(encoding="utf-8"))
        snapshot = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        samplers = [n for n in prompt.values() if n["class_type"] == "KSampler"]
        values = [n["inputs"]["steps"] for n in samplers]
        steps = [prompt[v[0]]["inputs"]["value"] if isinstance(v, list) else v for v in values]
        assert len(samplers) == 5 and steps == [10] * 5
        assert sum(n["class_type"] == "SaveImage" for n in prompt.values()) == 5
        assert snapshot["lab_context"]["revision_id"] == report["revision_id"]
        loaders = [json.loads(prompt[str(node_id)]["inputs"]["media_state"]) for node_id in (40, 46, 42, 44)]
        assert [len(items) for items in loaders] == [1, 1, 2, 3]
        assert all(item["kind"] == "picture" and item["enabled"] is True for items in loaders for item in items)
        unique_uploads = {item["file"] for items in loaders for item in items}
        assert len(unique_uploads) == 3 and loaders[0] == loaders[1]
        outputs = job["output_assets"]
        assert len(outputs) == 5
        verification = {"job_count": 1, "photo_count": len(outputs), "steps_per_sampler": steps, "reference_counts": [len(items) for items in loaders], "unique_uploaded_anchors": len(unique_uploads), "files": []}
        with sqlite3.connect((ROOT / "data/characterlock.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            for asset in outputs:
                assert asset["metadata"]["lab"]["stage"] == "dataset" and asset["metadata"]["lab"]["revision_id"] == report["revision_id"]
                row = db.execute("SELECT relative_path,sha256 FROM assets WHERE id=?", (asset["id"],)).fetchone()
                path = (ROOT / "data" / row["relative_path"]).resolve()
                assert path.is_relative_to((ROOT / "data").resolve())
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                assert digest == row["sha256"]
                with Image.open(path) as picture:
                    size = list(picture.size)
                    picture.verify()
                with urllib.request.urlopen("http://127.0.0.1:8000/api/assets/" + asset["id"] + "/file", timeout=30) as response:
                    assert hashlib.sha256(response.read()).hexdigest() == digest
                verification["files"].append({"id": asset["id"], "category": asset["metadata"]["lab"]["category"], "path": str(path), "size": size, "sha256": digest})
        baseline = json.loads((ROOT / ".local/lab-before.json").read_text(encoding="utf-8"))
        assert all(hashlib.sha256((ROOT / "data" / asset["relative_path"]).read_bytes()).hexdigest() == asset["verified_sha256"] for asset in baseline["assets"])
        verification["previous_assets_preserved"] = len(baseline["assets"])
        report["verification"] = verification
        save(report)
        print(json.dumps(verification, ensure_ascii=False))
    print(json.dumps({"job_id": job["id"], "status": job["status"], "photos": len(job.get("output_assets", [])), "error": job.get("error")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
