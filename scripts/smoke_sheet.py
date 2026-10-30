"""Run/check the explicitly authorized 10-step Sheet smoke test once.

Never approves the result or resubmits an ambiguous attempt automatically.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / ".local/sheet-live-test.json"
CHARACTER = "666c7d77234c4f14b8284f769a749c15"
REFERENCE = "c03ccfee97454a359342bbbab97e4807"


def request(path, body=None, base="http://127.0.0.1:8000"):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def save(report):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    global REPORT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["submit", "check", "verify"])
    parser.add_argument("--report", default=REPORT.name, help="A JSON filename in the private .local folder; distinct tests never overwrite old evidence.")
    args = parser.parse_args()
    if Path(args.report).name != args.report or not args.report.endswith(".json"):
        raise SystemExit("Use a simple JSON filename for the private report.")
    REPORT = ROOT / ".local" / args.report
    report = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    if args.action == "submit":
        if report.get("attempted_at"):
            raise SystemExit("Submission already attempted; inspect/check the saved report.")
        queue = request("/api/system")["queue"]
        native = request("/queue", base="http://127.0.0.1:8188")
        if queue["active"] or queue["queued"] or native["queue_running"] or native["queue_pending"]:
            raise SystemExit("The local queues must be idle before this test.")
        manifest = json.loads((ROOT / "workflows/local/matrix-lab/manifest.json").read_text(encoding="utf-8"))
        workflow = next(w for w in manifest["workflows"] if w["key"] == "sheet-reference")
        payload = {"stage": "character_sheet", "workflow_id": workflow["workflow_id"], "steps": 10, "reference_asset_id": REFERENCE, "consent_confirmed": True}
        report = {"attempted_at": datetime.now(timezone.utc).isoformat(), "character_id": CHARACTER, "request": payload, "approval": "pending_human_review"}
        save(report)
        job = request(f"/api/characters/{CHARACTER}/lab/generate", payload)
        report.update(job_id=job["id"], job=job)
        save(report)
    else:
        if not report.get("job_id"):
            raise SystemExit("No unambiguous job ID; inspect the history before any retry.")
        job = request("/api/jobs/" + report["job_id"])
        report["job"] = job
        report["checked_at"] = datetime.now(timezone.utc).isoformat()
        save(report)
    if args.action == "verify":
        from PIL import Image
        if job["status"] != "succeeded":
            raise SystemExit("The Sheet must finish before verification.")
        prompt = json.loads((ROOT / "data/jobs" / job["id"] / "prompt.json").read_text(encoding="utf-8"))
        snapshot = json.loads((ROOT / "data/jobs" / job["id"] / "request.json").read_text(encoding="utf-8"))
        expected = set(snapshot["lab_context"]["output_categories"].values())
        samplers = [node for node in prompt.values() if node["class_type"] == "KSampler"]
        def steps(node):
            value = node["inputs"]["steps"]
            return prompt[value[0]]["inputs"]["value"] if isinstance(value, list) else value
        assert len(samplers) == len(expected) - 1 and all(steps(node) == 10 for node in samplers)
        lab = request(f"/api/characters/{CHARACTER}/lab")
        entries = [entry for entry in lab["assets"] if entry.get("job_id") == job["id"]]
        assert len(entries) == len(expected) and {e["category"] for e in entries} == expected
        board = next(e for e in entries if e["category"] == "character_sheet")
        assert all(e["approval"] == board["approval"] and e["revision_id"] == board["revision_id"] for e in entries)
        assert board["approval"] in {"pending", "approved"}
        assert bool(board["revision_id"]) == (board["approval"] == "approved")
        pending = board["approval"] != "approved"
        report["approval"] = "pending_human_review" if pending else "approved"
        verification = {"steps_per_sampler": [steps(node) for node in samplers], "human_approval_pending": pending, "current_principal": lab["principal_asset_id"] == board["asset_id"], "revision_id": board["revision_id"], "files": []}
        with sqlite3.connect((ROOT / "data/characterlock.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            for entry in entries:
                row = db.execute("SELECT relative_path,sha256 FROM assets WHERE id=?", (entry["asset_id"],)).fetchone()
                path = (ROOT / "data" / row["relative_path"]).resolve()
                assert path.is_relative_to((ROOT / "data").resolve())
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                assert digest == row["sha256"]
                with Image.open(path) as picture:
                    size = list(picture.size)
                    picture.verify()
                with urllib.request.urlopen("http://127.0.0.1:8000/api/assets/" + entry["asset_id"] + "/file", timeout=30) as response:
                    assert hashlib.sha256(response.read()).hexdigest() == digest
                verification["files"].append({"id": entry["asset_id"], "category": entry["category"], "path": str(path), "size": size, "sha256": digest})
        baseline = json.loads((ROOT / ".local/lab-before.json").read_text(encoding="utf-8"))
        assert all(hashlib.sha256((ROOT / "data" / a["relative_path"]).read_bytes()).hexdigest() == a["verified_sha256"] for a in baseline["assets"])
        verification["previous_assets_preserved"] = len(baseline["assets"])
        report["verification"] = verification
        save(report)
        print(json.dumps(verification, ensure_ascii=False))
    print(json.dumps({"job_id": report["job_id"], "status": job["status"], "progress": job.get("progress"), "error": job.get("error"), "outputs": [{"id": a["id"], "filename": a["filename"], "size": a["size_bytes"], "category": a["metadata"].get("lab", {}).get("category")} for a in job.get("output_assets", [])]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
