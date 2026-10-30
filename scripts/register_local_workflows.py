"""Register preserved local source graphs for inspection, without executing them."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]
MODULES = {
    "Best Minimax H3 skin realism workflow.json": "video_studio",
    "Latent_Up_video_salvo.json": "video_studio",
    "MinimaxH3_Char_Swap-20261015.json": "motion_swap",
    "NVIDIA UP.JSON": "video_studio",
    "Omini_voice.json": "voice",
    "MATRIX-Qwen21-Dataset-V4.json": "character_lab",
    "MATRIX-Qwen21-Dataset-V4-Turbo.json": "character_lab",
}
BASE = "http://127.0.0.1:8000/api"


def request(path, payload=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def register(inventory: Path):
    entries = json.loads(inventory.read_text(encoding="utf-8"))["workflows"]
    existing = {(row["sha256"], row["module"]) for row in request("/workflows")}
    imported = 0
    for entry in entries:
        source = (PROJECT / entry["preserved_original"]).resolve(strict=True)
        if PROJECT not in source.parents:
            raise ValueError("Source must be a preserved file inside this project.")
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise ValueError(f"Original hash changed: {entry['file']}")
        module = MODULES.get(entry["file"])
        if module is None:
            raise ValueError(f"No reviewed module assignment for {entry['file']}")
        workflow = json.loads(content)
        canonical = json.dumps(workflow, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        key = (hashlib.sha256(canonical).hexdigest(), module)
        if key in existing:
            continue
        request("/workflows", {"name": Path(entry["file"]).stem, "module": module, "workflow": workflow})
        existing.add(key)
        imported += 1
    print(f"{imported} workflow(s) registrado(s) para inspeção. Nenhuma execução foi solicitada.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=PROJECT / "docs" / "workflow-inventory.json")
    args = parser.parse_args()
    register(args.inventory)
