"""Explicit local 10-step smoke tests; one job at a time, no model downloads.

prepare registers reviewed mapping copies, never overwrites workflows or approves
identity. submit/check/verify keep durable evidence so an uncertain submission is
not blindly repeated. Character Sheet is not inferred from the portrait test.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT / ".local" / "smoke-10steps"
REPORT = EVIDENCE / "report.json"
SOURCES = {"image": "6257db03a2f145e797cabc302a19f23c", "video": "d01d407a9ab54a2e9827fd73ec5cb1aa", "voice": "6440066ef1c64e279ef9e6722f58ee7e"}
TERMINAL = {"succeeded", "failed", "cancelled", "needs_attention"}


def request(path, payload=None, base="http://127.0.0.1:8000"):
    req = urllib.request.Request(base + path, data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def save(report):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    temporary = REPORT.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(REPORT)


def load():
    return json.loads(REPORT.read_text(encoding="utf-8"))


def prepare():
    sys.path.insert(0, str(PROJECT / "backend"))
    from app.workflows import WorkflowAdapter
    characters = request("/api/characters")
    if len(characters) != 1:
        raise SystemExit("Choose a character explicitly before testing a different library.")
    character = characters[0]
    report = load() if REPORT.exists() else {"created_at": datetime.now(timezone.utc).isoformat(), "steps": 10, "character_id": character["id"], "areas": {}, "limitations": []}
    assert report["character_id"] == character["id"] and report["steps"] == 10
    with urllib.request.urlopen("http://127.0.0.1:8188/object_info", timeout=30) as response:
        info = json.load(response)
    for area, source_id in SOURCES.items():
        if area in report["areas"]:
            continue
        source = request("/api/workflows/" + source_id)
        graph, mapping = deepcopy(source["workflow"]), deepcopy(source["mapping"])
        if area == "image":
            assert graph["101"]["class_type"] == "KSampler"
            steps = mapping["parameters"]["steps"]
            assert steps["node_id"] == "101" and steps["input"] == "steps"
            steps["choices"] = sorted(set(steps["choices"] + [10]))
            steps["default"] = 10
            values = {"prompt": character["prompt"] + " Fully clothed, simple casual shirt. Natural head-and-shoulders portrait, neutral background, soft daylight.", "width": 512, "height": 640, "steps": 10, "seed": 2026101610}
        elif area == "video":
            assert graph["332"]["class_type"] == "MiniMaxH3DualClockSamplerT8"
            constraints = info[graph["332"]["class_type"]]["input"]["required"]["steps"][1]
            assert constraints["min"] <= 10 <= constraints["max"]
            mapping["parameters"]["steps"] = {"node_id": "332", "input": "steps", "type": "integer", "default": 10, "min": constraints["min"], "max": constraints["max"], "label": "Passos de geração"}
            values = {"steps": 10, "duration_seconds": 0.4, "megapixels": 0.2, "aspect_ratio": "16:9 (Widescreen)", "seed": 2026101610, "scene_prompt": character["prompt"] + " Fully clothed in a casual shirt, a small friendly smile and gentle head movement. Stable medium portrait camera, soft studio light, no cuts. Preserve the face and identity of the supplied image."}
        else:
            values = {"text": "Olá, eu sou " + character["name"] + ". Este é o teste de voz com dez etapas no CharacterLock Studio.", "language": "Portuguese", "speed": 1.0, "num_step": 10, "seed": 2026101610}
        validation = WorkflowAdapter(graph, mapping).validate(info, values, allow_missing={"identity_image"} if area == "video" else set())
        if not validation["valid"]:
            raise SystemExit(json.dumps({"area": area, "preflight": validation}))
        if area != "voice":
            variant = request("/api/workflows", {"name": source["name"] + " — teste 10 steps", "module": source["module"], "workflow": graph, "mapping": mapping})
            workflow_id = variant["id"]
        else:
            workflow_id = source_id
        report["areas"][area] = {"source_workflow_id": source_id, "workflow_id": workflow_id, "module": source["module"], "parameters": values, "preflight": validation, "graph_unchanged": graph == source["workflow"]}
        save(report)
    if "lab_state_before" not in report:
        report["lab_state_before"] = request("/api/characters/" + character["id"] + "/lab")
    save(report)
    print(json.dumps({"prepared": list(report["areas"]), "report": str(REPORT)}))


def submit(area):
    report = load()
    target = report["areas"][area]
    if target.get("job_id") or target.get("submission_attempted_at"):
        raise SystemExit("Submission already attempted; inspect jobs and resume instead of repeating.")
    system = request("/api/system")
    native_queue = request("/queue", base="http://127.0.0.1:8188")
    if system["queue"]["active"] or system["queue"]["queued"] or native_queue.get("queue_running") or native_queue.get("queue_pending"):
        raise SystemExit("Wait until both Studio and ComfyUI queues are idle.")
    asset_inputs = {}
    if area == "video":
        image = report["areas"]["image"]
        if not image.get("job_id"):
            raise SystemExit("Finish the image test first.")
        image_job = request("/api/jobs/" + image["job_id"])
        if image_job["status"] != "succeeded" or not image_job["output_assets"]:
            raise SystemExit("The video test requires the successful image output.")
        asset_inputs["identity_image"] = image_job["output_assets"][0]["id"]
    target["submission_attempted_at"] = datetime.now(timezone.utc).isoformat()
    target["asset_inputs"] = asset_inputs
    save(report)
    job = request("/api/jobs", {"module": target["module"], "character_id": report["character_id"], "workflow_id": target["workflow_id"], "parameters": target["parameters"], "asset_inputs": asset_inputs, "consent_confirmed": True})
    target["job_id"], target["job"] = job["id"], job
    save(report)
    print(json.dumps({"area": area, "job_id": job["id"], "status": job["status"]}))


def check(area):
    report = load()
    target = report["areas"][area]
    job = request("/api/jobs/" + target["job_id"])
    target["job"] = job
    save(report)
    print(json.dumps({"area": area, "job_id": job["id"], "status": job["status"], "progress": job["progress"], "error": job["error"], "output_count": len(job["output_assets"])}))


def retry(area):
    report = load()
    target = report["areas"][area]
    old = request("/api/jobs/" + target["job_id"])
    if old["status"] != "failed" or old.get("prompt_id") or target.get("retry_submission_attempted_at"):
        raise SystemExit("Only one explicit retry of a confirmed pre-submission failure is supported.")
    system = request("/api/system")
    native = request("/queue", base="http://127.0.0.1:8188")
    if system["queue"]["active"] or system["queue"]["queued"] or native.get("queue_running") or native.get("queue_pending"):
        raise SystemExit("Queues must be idle before retry.")
    target.setdefault("previous_attempts", []).append(old)
    target["retry_submission_attempted_at"] = datetime.now(timezone.utc).isoformat()
    save(report)
    job = request("/api/jobs/" + old["id"] + "/retry", {})
    target["job_id"], target["job"] = job["id"], job
    save(report)
    print(json.dumps({"area": area, "previous_job_id": old["id"], "job_id": job["id"], "status": job["status"]}))


def verify():
    report = load()
    for area, target in report["areas"].items():
        if not target.get("job_id"):
            continue
        job = request("/api/jobs/" + target["job_id"])
        target["job"] = job
        target["verification"] = []
        prompt_path = PROJECT / "data" / "jobs" / job["id"] / "prompt.json"
        if prompt_path.exists():
            prompt = json.loads(prompt_path.read_text(encoding="utf-8"))
            node, field = ("101", "steps") if area == "image" else ("332", "steps") if area == "video" else ("14", "num_step")
            target["actual_submitted_steps"] = prompt[node]["inputs"][field]
            assert target["actual_submitted_steps"] == 10
        for asset in job["output_assets"]:
            with urllib.request.urlopen("http://127.0.0.1:8000" + asset["url"], timeout=30) as response:
                data = response.read()
                media_type = response.headers.get_content_type()
            digest = hashlib.sha256(data).hexdigest()
            target["verification"].append({"asset_id": asset["id"], "bytes": len(data), "sha256_matches": digest == asset["sha256"], "http_media_type": media_type})
            assert len(data) == asset["size_bytes"] and digest == asset["sha256"]
        print(json.dumps({"area": area, "status": job["status"], "actual_submitted_steps": target.get("actual_submitted_steps"), "outputs_verified": len(target["verification"]), "error": job["error"]}))
    report["lab_state_after"] = request("/api/characters/" + report["character_id"] + "/lab")
    report["verified_at"] = datetime.now(timezone.utc).isoformat()
    save(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "submit", "check", "retry", "verify"])
    parser.add_argument("area", nargs="?", choices=list(SOURCES))
    args = parser.parse_args()
    if args.action in {"submit", "check", "retry"} and not args.area:
        parser.error("Select an area.")
    if args.action == "prepare":
        prepare()
    elif args.action == "submit":
        submit(args.area)
    elif args.action == "check":
        check(args.area)
    elif args.action == "retry":
        retry(args.area)
    else:
        verify()
