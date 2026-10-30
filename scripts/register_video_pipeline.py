"""Prepare a sanitized MiniMax H3 API from metadata of an already completed MP4.

This utility never submits a prompt or job, loads a model, or changes ComfyUI.
The optional --register flag stores a workflow only after a live preflight passes.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "backend"))
from app.workflows import WorkflowAdapter  # noqa: E402

LOCAL = PROJECT / "workflows" / "local"
STEM = "video_studio_minimax_h3_base"
NAME = "MiniMax H3 · vídeo base local"
DEFAULT_OUTPUT = Path.home() / "ComfyUI_windows_portable" / "ComfyUI" / "output"
SOURCE_ORIGINAL = PROJECT / "workflows" / "originals" / "c53ae78c351d-Best Minimax H3 skin realism workflow.json"
SAFE_SCENE = (
    "An original fictional adult character, age 26, fully dressed in a modest "
    "casual outfit, standing in a softly lit studio. Natural expression, a small "
    "friendly smile, subtle head movement, static medium portrait shot. "
    "Preserve the face and visual identity of the supplied reference image. "
    "Safe for work, everyday lifestyle scene."
)


def request(base: str, path: str, payload=None):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + path, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def mp4_metadata(data: bytes, start=0, end=None, parent=b""):
    """Read JSON metadata atoms; do not decode or execute video content."""
    end = len(data) if end is None else end
    while start + 8 <= end:
        size, box_type = struct.unpack_from(">I4s", data, start)
        header = 8
        if size == 1:
            if start + 16 > end:
                return
            size = struct.unpack_from(">Q", data, start + 8)[0]
            header = 16
        if size == 0:
            size = end - start
        if size < header or start + size > end:
            return
        payload = start + header
        if box_type in {b"moov", b"udta", b"meta", b"ilst"} or parent == b"ilst":
            yield from mp4_metadata(data, payload + (4 if box_type == b"meta" else 0), start + size, box_type)
        elif box_type == b"data" and payload + 8 <= start + size:
            raw = data[payload + 8:start + size]
            try:
                value = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError):
                pass
            else:
                yield value, raw
        start += size


def extract_source(output: Path):
    for source in sorted(output.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
        content = source.read_bytes()
        for graph, raw in mp4_metadata(content):
            if not isinstance(graph, dict) or not graph:
                continue
            if not all(isinstance(node, dict) and isinstance(node.get("inputs"), dict) and isinstance(node.get("class_type"), str) for node in graph.values()):
                continue
            if graph.get("265", {}).get("class_type") != "MiniMaxH3ReferenceToVideo" or graph.get("264", {}).get("class_type") != "VHS_VideoCombine":
                continue
            return deepcopy(graph), {
                "source_kind": "completed_local_mp4_embedded_api_prompt",
                "source_media_sha256": hashlib.sha256(content).hexdigest(),
                "source_api_sha256": hashlib.sha256(raw).hexdigest(),
                "source_modified_at": datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(),
                "source_node_count": len(graph),
            }
    raise ValueError("No matching completed MiniMax H3 API prompt was found in the five newest MP4 metadata containers.")


def linked(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], (str, int)) and isinstance(value[1], int)


def reachable(graph, output):
    pending, keep = [output], set()
    while pending:
        node_id = pending.pop()
        if node_id in keep:
            continue
        if node_id not in graph:
            raise ValueError("An actual source connection points to a missing node.")
        keep.add(node_id)
        pending.extend(str(value[0]) for value in graph[node_id]["inputs"].values() if linked(value))
    return {node_id: node for node_id, node in graph.items() if node_id in keep}


def prepare(output: Path):
    graph, provenance = extract_source(output)
    expected = {
        "51": "LoadImage", "58": "MiniMaxH3MemoryEfficientSageAttentionPatch",
        "192": "UNETLoader", "250": "ComfyMathExpression", "252": "ResolutionSelector",
        "256": "RandomNoise", "259": "PrimitiveFloat", "263": "Text",
        "264": "VHS_VideoCombine", "265": "MiniMaxH3ReferenceToVideo",
        "332": "MiniMaxH3DualClockSamplerT8", "334": "Power Lora Loader (rgthree)",
    }
    if any(graph.get(nid, {}).get("class_type") != cls for nid, cls in expected.items()):
        raise ValueError("The completed API does not have the reviewed source node identities.")
    if graph["265"]["inputs"].get("ref_images.ref_image_0") != ["51", 0]:
        raise ValueError("The source's first reference image connection differs from the reviewed API.")
    for node in graph.values():
        node.pop("_meta", None)
    graph["51"]["inputs"]["image"] = "characterlock/identity_reference.png"
    graph["263"]["inputs"]["text"] = SAFE_SCENE
    graph["259"]["inputs"]["value"] = 0.4
    graph["252"]["inputs"].update(megapixels=0.2, multiple=32)
    graph["256"]["inputs"]["noise_seed"] = 42
    graph["265"]["inputs"]["ref_image_size"] = "match"
    for field in list(graph["265"]["inputs"]):
        if field.startswith("ref_images.") and field != "ref_images.ref_image_0":
            del graph["265"]["inputs"][field]
        elif field.startswith(("ref_videos.", "ref_video_audios.", "ref_audios.")):
            del graph["265"]["inputs"][field]
    # Installed rgthree load_loras(model=None, clip=None, **kwargs) is passthrough
    # when no lora_N dictionaries are supplied. All optional LoRAs are disabled.
    graph["334"]["inputs"] = {key: value for key, value in graph["334"]["inputs"].items() if key in {"model", "clip"}}
    graph["264"]["inputs"]["filename_prefix"] = "characterlock/video"
    if graph["264"]["inputs"].get("format") != "video/h264-mp4":
        raise ValueError("Reviewed completed output is not H.264 MP4.")
    # Installed VHS apply_format_widgets supplies reviewed H.264 defaults.
    for field in ("pix_fmt", "crf", "save_metadata", "trim_to_audio"):
        graph["264"]["inputs"].pop(field, None)
    original_ids = set(graph)
    graph = reachable(graph, "264")
    expression = "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17"
    if graph["250"]["inputs"].get("expression") != expression:
        raise ValueError("The frame quantization expression differs from the completed source.")
    # No uploaded source filenames, private prompt text, UI titles or LoRA names
    # remain. Only reviewed runtime enum/model literals and formula are retained.
    media_nodes = [nid for nid, n in graph.items() if n["class_type"] in {"LoadImage", "LoadAudio", "VHS_LoadVideo"}]
    if media_nodes != ["51"]:
        raise ValueError("Unexpected unbound media input remains after pruning.")
    if any(isinstance(v, dict) for node in graph.values() for v in node["inputs"].values()):
        raise ValueError("Unexpected custom literal serializer remains.")
    mapping = {"parameters": {
        "identity_image": {"node_id": "51", "input": "image", "type": "string", "kind": "image", "required": True, "label": "Referência visual do personagem", "description": "Escolha uma imagem da biblioteca; o arquivo será enviado automaticamente ao ComfyUI."},
        "scene_prompt": {"node_id": "263", "input": "text", "type": "string", "kind": "prompt", "required": True, "default": SAFE_SCENE, "label": "Identidade e direção da cena"},
        "duration_seconds": {"node_id": "259", "input": "value", "type": "number", "kind": "duration", "default": 0.4, "min": 0.1, "max": 15.0, "label": "Duração solicitada (segundos)", "description": "O H3 quantiza o resultado para 5 + 17n quadros a 24 fps. 0,4 s resulta em 22 quadros, aproximadamente 0,92 s."},
        "megapixels": {"node_id": "252", "input": "megapixels", "type": "number", "kind": "other", "default": 0.2, "min": 0.1, "max": 1.0, "label": "Resolução (megapixels)", "description": "Teste inicial em 0,2 MP. O seletor real ajusta largura e altura a múltiplos de 32."},
        "aspect_ratio": {"node_id": "252", "input": "aspect_ratio", "type": "enum", "kind": "other", "default": graph["252"]["inputs"]["aspect_ratio"], "choices": ["1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", "3:4 (Portrait Standard)", "4:3 (Standard)", "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)"], "label": "Proporção do vídeo"},
        "seed": {"node_id": "256", "input": "noise_seed", "type": "integer", "kind": "seed", "default": 42, "min": 0, "max": 2147483647, "label": "Seed"},
    }, "output_nodes": ["264"]}
    provenance.update({
        "preserved_original": str(SOURCE_ORIGINAL.relative_to(PROJECT)).replace("\\", "/"),
        "preserved_original_sha256": hashlib.sha256(SOURCE_ORIGINAL.read_bytes()).hexdigest(),
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "prepared_node_count": len(graph),
        "removed_unreachable_node_ids": sorted(original_ids - set(graph)),
        "changes": ["Replace private prompt with neutral fully dressed fictional adult scene", "Replace image filenames with one required character-owned asset binding", "Keep first reference only, remove optional extra media references", "Remove unreachable nodes including disconnected SplitSigmas", "Disable all optional LoRAs via installed PowerLora passthrough", "Remove all UI metadata and dynamic LoRA UI widgets", "Set duration 0.4 s (22 frames at 24 fps), resolution 0.2 MP, multiples of 32, seed 42", "Retain original node IDs, installed model choices, graph connections and quantization formula", "Use installed H.264 defaults: yuv420p, CRF 19, metadata true, trim false", "Use relative generic output prefix characterlock/video"],
        "execution_requested": False,
        "quality_note": "Very short base smoke preset without optional LoRAs. A successful structural preflight does not prove GPU memory fit or perceptual quality.",
    })
    return graph, mapping, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--studio-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--register", action="store_true", help="Register only when live preflight passes; never run a job.")
    args = parser.parse_args()
    workflow, mapping, provenance = prepare(args.output_dir)
    info = request(args.comfy_url, "/object_info")
    adapter = WorkflowAdapter(workflow, mapping)
    report = adapter.validate(info)
    provenance["preflight_valid"] = report["valid"]
    LOCAL.mkdir(parents=True, exist_ok=True)
    for suffix, value in ((".api.json", workflow), (".mapping.json", mapping), (".provenance.json", provenance), (".validation.json", report)):
        (LOCAL / (STEM + suffix)).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"prepared_nodes": len(workflow), "preflight_valid": report["valid"], "errors": report["errors"], "execution_requested": False}
    if args.register:
        if not report["valid"]:
            summary["registered"] = False
        else:
            canonical = json.dumps(workflow, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            digest = hashlib.sha256(canonical).hexdigest()
            existing = next((row for row in request(args.studio_url, "/workflows?module=video_studio") if row["sha256"] == digest), None)
            registered = existing or request(args.studio_url, "/workflows", {"name": NAME, "module": "video_studio", "workflow": workflow, "mapping": mapping})
            remote_report = request(args.studio_url, f"/workflows/{registered['id']}/validate", {})
            summary.update(workflow_id=registered["id"], registered=True, studio_preflight_valid=remote_report["valid"], studio_errors=remote_report["errors"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
