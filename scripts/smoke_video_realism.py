"""Short local GPU check of the registered Realism + Turbo8 preset.

One job, eight steps, 0.2 MP, 22 frames. Does not change production defaults,
download weights, approve assets, or retry an ambiguous attempt.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import urllib.request

from smoke_sheet import CHARACTER, ROOT, request

REPORT = ROOT / ".local/video-realism-live-test.json"
REFERENCE = "561f2c0a931c4602a7a73aba832205c9"


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
            raise SystemExit("Submission was already attempted; inspect the saved job before any retry.")
        queue = request("/api/system")["queue"]
        native = request("/queue", base="http://127.0.0.1:8188")
        if queue["active"] or queue["queued"] or native["queue_running"] or native["queue_pending"]:
            raise SystemExit("Both queues must be idle before this short check.")
        folder = ROOT / "workflows/local/video-realism"
        graph = json.loads((folder / "local-installed.api.json").read_text(encoding="utf-8"))
        mapping = json.loads((folder / "local-installed.mapping.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256(json.dumps(graph, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        options = [w for w in request("/api/workflows?module=video_studio") if w["sha256"] == digest and w["mapping"] == mapping]
        if len(options) != 1:
            raise SystemExit("Expected one registered reviewed local Realism + Turbo8 workflow.")
        payload = {"module": "video_studio", "character_id": CHARACTER, "workflow_id": options[0]["id"], "parameters": {"scene_prompt": "The fictional adult woman in <Picture 1>, age 26, wearing the same white shirt. Natural subtle smile and a small head turn, stationary medium portrait shot, soft studio light, realistic natural skin. Preserve the same face, hair and clothing, fully clothed.", "duration_seconds": 0.4, "megapixels": 0.2, "resolution_multiple": 32, "steps": 8, "realism_strength": 1.0, "turbo_strength": 1.0, "seed": 20261016}, "asset_inputs": {"identity_image": REFERENCE}, "consent_confirmed": True}
        report = {"attempted_at": datetime.now(timezone.utc).isoformat(), "request": payload, "production_defaults_unchanged": True}
        save(report)
        job = request("/api/jobs", payload)
        report.update(job_id=job["id"], job=job)
    else:
        if not report.get("job_id"):
            raise SystemExit("No unambiguous job ID; inspect the history before any retry.")
        job = request("/api/jobs/" + report["job_id"])
        report.update(job=job, checked_at=datetime.now(timezone.utc).isoformat())
    save(report)
    if args.action == "verify":
        if job["status"] != "succeeded":
            raise SystemExit("The short video must finish before verification.")
        prompt = json.loads((ROOT / "data/jobs" / job["id"] / "prompt.json").read_text(encoding="utf-8"))
        assert prompt["334"]["class_type"] == prompt["335"]["class_type"] == "LoraLoaderModelOnly"
        assert prompt["334"]["inputs"]["lora_name"] == "h3-realism-people-t2v-i2v-r2v.safetensors"
        assert prompt["335"]["inputs"]["lora_name"] == "minimax_h3_fl2v_lightx2v_turbo_8step_v1.0_resized_avg_rank_24_bf16.safetensors"
        assert prompt["334"]["inputs"]["strength_model"] == prompt["335"]["inputs"]["strength_model"] == 1
        assert prompt["335"]["inputs"]["model"] == ["334", 0]
        assert prompt["332"]["inputs"]["model"] == ["335", 0] and prompt["332"]["inputs"]["steps"] == 8
        assert prompt["336"]["inputs"]["string_a"] == "r34l1sm" and prompt["265"]["inputs"]["prompt"] == ["336", 0]
        assert len(job["output_assets"]) == 1
        asset = job["output_assets"][0]
        assert asset["media_type"] == "video/mp4"
        with sqlite3.connect((ROOT / "data/characterlock.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT relative_path,sha256 FROM assets WHERE id=?", (asset["id"],)).fetchone()
        video_path = (ROOT / "data" / row["relative_path"]).resolve()
        assert video_path.is_relative_to((ROOT / "data").resolve())
        digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
        assert digest == row["sha256"]
        with urllib.request.urlopen("http://127.0.0.1:8000/api/assets/" + asset["id"] + "/file", timeout=30) as response:
            assert hashlib.sha256(response.read()).hexdigest() == digest
        ffmpeg = Path.home() / "ComfyUI_windows_portable/python_embeded/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"
        if not ffmpeg.is_file():
            raise SystemExit("Existing local FFmpeg decoder is unavailable; preserve the completed video.")
        decoded = subprocess.run([str(ffmpeg), "-hide_banner", "-i", str(video_path), "-f", "null", "-"], capture_output=True, text=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        (ROOT / ".local/video-realism-decode.log").write_text(decoded.stderr, encoding="utf-8")
        assert decoded.returncode == 0
        frame_counts = re.findall(r"frame=\s*(\d+)", decoded.stderr)
        assert frame_counts and int(frame_counts[-1]) == 22
        assert "Video: h264" in decoded.stderr and "Audio: aac" in decoded.stderr
        preview = ROOT / ".local/video-realism-frame.png"
        extracted = subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_path), "-frames:v", "1", str(preview)], capture_output=True, text=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        assert extracted.returncode == 0 and preview.is_file()
        report["verification"] = {"steps": 8, "realism_strength": 1, "turbo_strength": 1, "trigger_fixed": True, "frames": 22, "full_audio_video_decode": True, "path": str(video_path), "preview": str(preview), "bytes": video_path.stat().st_size, "sha256": digest}
        save(report)
        print(json.dumps(report["verification"], ensure_ascii=False))
    print(json.dumps({"job_id": job["id"], "status": job["status"], "error": job.get("error"), "outputs": [{"id": a["id"], "filename": a["filename"], "bytes": a["size_bytes"]} for a in job.get("output_assets", [])]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
