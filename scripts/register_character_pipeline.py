"""Reviewed first portrait branch of the user's MATRIX Qwen 2.1 workflow.

Explicit fields below were checked against the installed node source/schema.
This is not a general UI-widget converter. No downloads or jobs are performed.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "backend"))
from app.workflows import WorkflowAdapter

SOURCE = PROJECT / "workflows/originals/05f2804cb6e5-MATRIX-Qwen21-Dataset-V4.json"
SOURCE_HASH_PREFIX = "05f2804cb6e5"
FIELDS = {
    10: ("UNETLoader", ["unet_name", "weight_dtype"]),
    11: ("CLIPLoader", ["clip_name", "type", "device"]),
    12: ("VAELoader", ["vae_name"]),
    13: ("Power Lora Loader (rgthree)", []),
    51: ("EmptyLatentImage", ["width", "height", "batch_size"]),
    100: ("TextEncodeQwenImage21", ["prompt", "negative_prompt", "resolution"]),
    # control_after_generate is a frontend-only widget, not a server input.
    101: ("KSampler", ["seed", None, "steps", "cfg", "sampler_name", "scheduler", "denoise"]),
    102: ("VAEDecode", []),
    103: ("SaveImage", ["filename_prefix"]),
}


def request(url, body=None):
    payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as response:
        return json.load(response)


def prepare(info):
    raw = SOURCE.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if not digest.startswith(SOURCE_HASH_PREFIX):
        raise ValueError("Reviewed source changed; inspect the new graph before exporting.")
    source = json.loads(raw)
    nodes = {node["id"]: node for node in source["nodes"]}
    links = {link[0]: link for link in source["links"]}
    graph = {}
    for node_id, (class_type, fields) in FIELDS.items():
        node = nodes[node_id]
        if node["type"] != class_type:
            raise ValueError(f"Reviewed node {node_id} changed class.")
        values = node.get("widgets_values") or []
        if fields and len(values) != len(fields):
            raise ValueError(f"Reviewed widget layout changed at {node_id}.")
        inputs = {name: deepcopy(value) for name, value in zip(fields, values) if name is not None}
        for entry in node.get("inputs", []):
            link = links.get(entry.get("link"))
            if link and link[1] in FIELDS:
                inputs[entry["name"]] = [str(link[1]), link[2]]
        graph[str(node_id)] = {"class_type": class_type, "inputs": inputs}
    # Disabled LoRAs in the original are no-ops (verified load_loras source).
    if any(isinstance(value, dict) and value.get("on") for value in nodes[13]["widgets_values"]):
        raise ValueError("Enabled LoRA requires its own reviewed serializer.")
    clip = "qwen3vl_8b_w4a8.safetensors"
    if clip not in info["CLIPLoader"]["input"]["required"]["clip_name"][0]:
        raise ValueError("The existing local Qwen text encoder was not found.")
    graph["11"]["inputs"]["clip_name"] = clip
    graph["51"]["inputs"].update(width=512, height=640, batch_size=1)
    graph["100"]["inputs"]["prompt"] = "A natural portrait of an original fictional adult virtual character, fully clothed, soft daylight."
    graph["103"]["inputs"]["filename_prefix"] = "CharacterLock/identity"
    # Empty media slots in the original are omitted: the installed autogrow
    # schema has min=0, and execute(images=None) supports text-to-image.
    parameters = {
        "prompt": {"node_id": "100", "input": "prompt", "type": "string", "kind": "prompt", "required": True, "label": "Identidade do personagem"},
        "negative_prompt": {"node_id": "100", "input": "negative_prompt", "type": "string", "kind": "negative_prompt", "default": "", "label": "Elementos a evitar"},
        "width": {"node_id": "51", "input": "width", "type": "enum", "kind": "width", "choices": [512, 768, 1024], "default": 512, "label": "Largura"},
        "height": {"node_id": "51", "input": "height", "type": "enum", "kind": "height", "choices": [512, 640, 768, 1024], "default": 640, "label": "Altura"},
        "steps": {"node_id": "101", "input": "steps", "type": "enum", "choices": [8, 16, 25, 32], "default": 25, "label": "Passos de geração"},
        "seed": {"node_id": "101", "input": "seed", "type": "integer", "kind": "seed", "min": 0, "max": 4294967295, "default": 1001, "label": "Semente"},
    }
    mapping = {"parameters": parameters, "output_nodes": ["103"]}
    report = WorkflowAdapter(graph, mapping).validate(info)
    if not report["valid"]:
        raise ValueError(json.dumps(report["errors"], ensure_ascii=False))
    return graph, mapping, {"source_sha256": digest, "source_nodes": list(FIELDS),
                            "changes": ["First portrait branch only; dataset fan-out excluded.", "Empty optional reference slots omitted for text-to-image.", "Existing w4a8 text encoder selected from live choices.", "Width/height and sampler seed/steps made literal parameters.", "Disabled LoRAs remain no-ops; output prefix is CharacterLock/identity."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args()
    graph, mapping, provenance = prepare(request("http://127.0.0.1:8188/object_info"))
    directory = PROJECT / "workflows/local"
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in (("character_lab_qwen21_base.api.json", graph), ("character_lab_qwen21_base.mapping.json", mapping), ("character_lab_qwen21_base.provenance.json", provenance)):
        (directory / name).write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.register:
        payload = {"name": "Qwen 2.1 — Imagem-base", "module": "character_lab", "workflow": graph, "mapping": mapping}
        existing = request("http://127.0.0.1:8000/api/workflows")
        checksum = hashlib.sha256(json.dumps(graph, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        workflow = next((item for item in existing if item["sha256"] == checksum and item["module"] == "character_lab" and item["mapping"] == mapping), None)
        workflow = workflow or request("http://127.0.0.1:8000/api/workflows", payload)
        print(json.dumps({"workflow_id": workflow["id"], "format": workflow["format"], "generation_submitted": False}))
    else:
        print("Reviewed API pipeline prepared. No generation submitted.")


if __name__ == "__main__":
    main()
