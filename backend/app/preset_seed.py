"""Automatic first-boot seeding of redistributable studio API workflows."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .db import encode, now
from .storage import safe_path
from .workflows import WorkflowAdapter

if TYPE_CHECKING:
    from .db import Database
    from .settings import Settings

log = logging.getLogger("characterlock.presets")


def _adapt_installed_model_aliases(workflow: dict, comfyui_dir: Path) -> dict:
    """Adapt known GGUF filename aliases to match whichever encoder file is installed."""
    text_encoders_dir = comfyui_dir / "ComfyUI" / "models" / "text_encoders"
    q2_k = text_encoders_dir / "qwen3vl-32B-MiniMax-H3-Q2_K.gguf"
    q2_k_m = text_encoders_dir / "qwen3vl_32b_minimax_h3-Q2_K_M.gguf"
    if not q2_k.is_file() and q2_k_m.is_file():
        updated = json.loads(json.dumps(workflow))
        for node in updated.values():
            if isinstance(node, dict) and node.get("class_type") == "CLIPLoaderGGUF":
                inputs = node.get("inputs", {})
                if inputs.get("clip_name") == "qwen3vl-32B-MiniMax-H3-Q2_K.gguf":
                    inputs["clip_name"] = "qwen3vl_32b_minimax_h3-Q2_K_M.gguf"
        return updated
    return workflow


def seed_preset_workflows(db: "Database", settings: "Settings") -> dict:
    """Seed redistributable studio workflows when the workflows table is empty."""
    existing = db.one("SELECT COUNT(*) AS count FROM workflows")
    if existing and existing["count"] > 0:
        return {"seeded": 0, "skipped": True, "reason": "workflows_already_present"}

    presets_dir = settings.app_root / "workflows" / "presets"
    manifest_path = presets_dir / "manifest.json"
    if not manifest_path.is_file():
        return {"seeded": 0, "skipped": True, "reason": "manifest_not_found"}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("workflows", [])
    seeded = 0
    stamp = now()

    for entry in entries:
        workflow_id = entry["id"]
        api_path = presets_dir / entry["api_file"]
        map_path = presets_dir / entry["mapping_file"]
        if not api_path.is_file() or not map_path.is_file():
            continue

        raw_workflow = json.loads(api_path.read_text(encoding="utf-8"))
        workflow = _adapt_installed_model_aliases(raw_workflow, settings.comfyui_dir)
        mapping = json.loads(map_path.read_text(encoding="utf-8"))

        adapter = WorkflowAdapter(workflow, mapping)
        inspection = adapter.inspect()
        original = encode(workflow)
        mapping_json = encode(adapter.mapping)
        original_rel = f"workflows/{workflow_id}/original.json"

        folder = safe_path(settings.data_dir, f"workflows/{workflow_id}")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "original.json").write_text(original, encoding="utf-8")
        (folder / "mapping.json").write_text(mapping_json, encoding="utf-8")

        sha = hashlib.sha256(original.encode("utf-8")).hexdigest()
        with db.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO workflows VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    workflow_id,
                    entry["name"],
                    entry["module"],
                    original,
                    mapping_json,
                    encode(inspection),
                    None,
                    original_rel,
                    sha,
                    stamp,
                ),
            )
            lab_binding = entry.get("lab_binding")
            if lab_binding:
                conn.execute(
                    "INSERT OR IGNORE INTO lab_workflows VALUES(?,?,?,?,?)",
                    (
                        workflow_id,
                        lab_binding["stage"],
                        encode(lab_binding["config"]),
                        stamp,
                        stamp,
                    ),
                )
        seeded += 1

    log.info("Seeded %d redistributable preset workflows into %s", seeded, settings.data_dir)
    return {"seeded": seeded, "skipped": False}
