"""Export MiniMax H3 realism, plus an explicit installed-files variant if requested.

Preparation reads the original and live node schemas, and writes private review
artifacts. It never submits a prompt, loads weights, downloads files or edits
ComfyUI. --register only stores the export after its live preflight succeeds.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT.parent / "WORK" / "Best Minimax H3 skin realism workflow.json"
SOURCE_SHA256 = "c53ae78c351d0dc82b3a056eeb5b0e4cb5af43dd09e0115b3d28b4a4ceb513a2"
OUTPUT = PROJECT / "workflows/local/video-realism"
STEM = "source-exact"
NAME = "MiniMax H3 · Realismo (workflow original)"
LOCAL_NAME = "MiniMax H3 · Realismo + Turbo 8 (local)"
LOCAL_UNET = "Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors"
LOCAL_CLIP = "qwen3vl-32B-MiniMax-H3-Q2_K.gguf"
LOCAL_TURBO = "minimax_h3_fl2v_lightx2v_turbo_8step_v1.0_resized_avg_rank_24_bf16.safetensors"
SAFE_SCENE = (
    "An original fictional adult character, age 26, from <Picture 1>, "
    "fully dressed in a modest casual outfit, standing in a softly lit studio. "
    "Natural expression, a small friendly smile, subtle head movement, static "
    "medium portrait shot. Preserve the face, hair and visual identity of the "
    "supplied reference image. Realistic natural skin texture and soft light."
)

# Explicit reviewed names from widgets_values_named, never positional guesses.
# Runtime links override corresponding widget values, exactly as the UI does.
FIELDS = {
    "UNETLoader": ("unet_name", "weight_dtype"),
    "CLIPLoader": ("clip_name", "type", "device"),
    "VAELoader": ("vae_name",),
    "LoadImage": ("image",),
    "MiniMaxH3MemoryEfficientSageAttentionPatch": (),
    "MiniMaxH3DualClockSamplerT8": ("steps", "shift_video", "shift_audio", "sampler_name", "scheduler"),
    "MiniMaxH3ReferenceToVideo": ("prompt", "width", "height", "length", "ref_image_size"),
    "RandomNoise": ("noise_seed",),
    "PrimitiveFloat": ("value",),
    "ComfyMathExpression": ("expression",),
    "ResolutionSelector": ("aspect_ratio", "megapixels", "multiple"),
    "Text": ("text",),
    "BasicGuider": (),
    "SamplerCustomAdvanced": (),
    "VAEDecode": (),
    "VAEDecodeAudio": (),
    "VHS_VideoCombine": ("frame_rate", "loop_count", "filename_prefix", "format", "pingpong", "save_output"),
}
EXPECTED_LORAS = [
    {"on": True, "lora": "h3-realism-people-t2v-i2v-r2v.safetensors", "strength": 1, "strengthTwo": None},
    {"on": False, "lora": "minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors", "strength": 1, "strengthTwo": None},
    {"on": True, "lora": "minimax_h3_turbo_v4_step600_ema.safetensors", "strength": 1, "strengthTwo": None},
    {"on": False, "lora": "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors", "strength": 1, "strengthTwo": None},
]
H264_DEFAULTS = {"pix_fmt": "yuv420p", "crf": 19, "save_metadata": True, "trim_to_audio": False}


def request(base: str, path: str, payload=None):
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


class ReviewedGraph:
    """Resolve only the reviewed source's virtual nodes and active dependencies."""

    def __init__(self, ui: dict):
        self.nodes = {n["id"]: n for n in ui["nodes"]}
        self.links = {link[0]: link for link in ui["links"]}
        if len(self.nodes) != len(ui["nodes"]) or len(self.links) != len(ui["links"]):
            raise ValueError("The UI graph contains duplicate node or link IDs.")
        self.setters = {}
        for node in self.nodes.values():
            if node["type"] != "SetNode":
                continue
            constant = node.get("widgets_values_named", {}).get("Constant")
            if not isinstance(constant, str) or not constant or constant in self.setters:
                raise ValueError("Missing or ambiguous reviewed SetNode constant.")
            self.setters[constant] = node["id"]
        self.api = {}
        self.visiting = set()
        self.virtual_nodes = set()
        self.bypassed_media = set()
        self.omitted_inputs = []
        self.lora_rows = []

    def input_link(self, node: dict, index: int):
        inputs = node.get("inputs", [])
        if index >= len(inputs):
            raise ValueError(f"Missing virtual input on source node {node['id']}.")
        link_id = inputs[index].get("link")
        if link_id is None:
            return None
        link = self.links.get(link_id)
        if link is None or link[3] != node["id"] or link[4] != index:
            raise ValueError(f"Inconsistent UI connection on source node {node['id']}.")
        return self.resolve(link[1], link[2])

    def resolve(self, node_id: int, slot: int, trail=()):
        if node_id not in self.nodes:
            raise ValueError(f"Source connection points to absent node {node_id}.")
        if node_id in trail:
            raise ValueError("Cyclic virtual-node connection in the source.")
        node = self.nodes[node_id]
        outputs = node.get("outputs", [])
        if not isinstance(slot, int) or slot < 0 or slot >= len(outputs):
            raise ValueError(f"Invalid source output slot {node_id}:{slot}.")
        mode = node.get("mode", 0)
        if mode == 4:
            # The only bypassed dependencies reachable from active output264
            # are media loaders, or virtual SetNodes fed by those loaders.
            # None has a same-type connected input to forward. Do not guess
            # bypass rules for dormant samplers/upscalers in the second pass.
            if node["type"] in {"LoadImage", "LoadAudio", "VHS_LoadVideo"}:
                if any(item.get("link") is not None for item in node.get("inputs", [])):
                    raise ValueError("A bypassed media loader gained an upstream connection.")
                self.bypassed_media.add(node_id)
                return None
            if node["type"] == "SetNode":
                self.virtual_nodes.add(node_id)
                return self.input_link(node, 0)
            raise ValueError(f"Unreviewed bypass on the active path: {node_id}.")
        if mode != 0:
            raise ValueError(f"Unsupported execution mode on active source node {node_id}.")
        if node["type"] == "GetNode":
            self.virtual_nodes.add(node_id)
            constant = node.get("widgets_values_named", {}).get("Constant")
            setter_id = self.setters.get(constant)
            if setter_id is None:
                raise ValueError(f"GetNode {node_id} has no unique source setter.")
            setter = self.nodes[setter_id]
            self.virtual_nodes.add(setter_id)
            link_id = setter.get("inputs", [{}])[0].get("link")
            if link_id is None:
                return None
            link = self.links[link_id]
            return self.resolve(link[1], link[2], trail + (node_id, setter_id))
        if node["type"] in {"SetNode", "Reroute"}:
            self.virtual_nodes.add(node_id)
            link_id = node.get("inputs", [{}])[0].get("link")
            if link_id is None:
                return None
            link = self.links[link_id]
            return self.resolve(link[1], link[2], trail + (node_id,))
        if node["type"] == "Power Lora Loader (rgthree)":
            if slot != 0:
                raise ValueError("The reviewed source does not consume the rgthree CLIP output.")
            self.emit_loras(node)
            return ["335", 0]
        self.emit(node_id)
        return [str(node_id), slot]

    def emit_loras(self, node: dict):
        if "335" in self.api:
            return
        if node["id"] != 334 or 335 in self.nodes:
            raise ValueError("Reviewed LoRA identities changed.")
        named = node.get("widgets_values_named", {})
        rows = [deepcopy(named.get(f"lora_{index}")) for index in range(1, 5)]
        if rows != EXPECTED_LORAS or any(key.startswith("lora_") for key in set(named) - {f"lora_{i}" for i in range(1, 5)}):
            raise ValueError("The supplied LoRA order, toggles or strengths changed.")
        if len(node.get("inputs", [])) != 2 or node["inputs"][1].get("link") is not None:
            raise ValueError("Native model-only LoRA conversion requires unconnected CLIP.")
        if node.get("outputs", [None, {}])[1].get("links"):
            raise ValueError("Native model-only LoRA conversion cannot drop a consumed CLIP output.")
        model = self.input_link(node, 0)
        if model is None:
            raise ValueError("Active LoRA model connection is missing.")
        active = [row for row in rows if row["on"]]
        for runtime_id, row in zip(("334", "335"), active):
            self.api[runtime_id] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": model, "lora_name": row["lora"], "strength_model": row["strength"],
            }}
            model = [runtime_id, 0]
        self.lora_rows = rows

    def emit(self, node_id: int):
        key = str(node_id)
        if key in self.api:
            return
        if node_id in self.visiting:
            raise ValueError("Cyclic active dependency in the source.")
        node = self.nodes[node_id]
        cls = node["type"]
        if cls not in FIELDS or node.get("mode", 0) != 0:
            raise ValueError(f"Unreviewed executable source node: {node_id} ({cls}).")
        self.visiting.add(node_id)
        named = node.get("widgets_values_named") or {}
        values = {}
        for field in FIELDS[cls]:
            if field not in named:
                raise ValueError(f"Reviewed named widget is absent: {node_id}.{field}.")
            values[field] = deepcopy(named[field])
        for index, item in enumerate(node.get("inputs", [])):
            if item.get("link") is None:
                continue
            connected = self.input_link(node, index)
            if connected is not None:
                values[item["name"]] = connected
            elif cls == "MiniMaxH3ReferenceToVideo" and item["name"].startswith(("ref_images.", "ref_videos.", "ref_video_audios.", "ref_audios.")):
                self.omitted_inputs.append({"node_id": key, "input": item["name"], "reason": "source_media_loader_bypassed"})
            else:
                raise ValueError(f"Required active path resolves to bypassed media: {node_id}.{item['name']}.")
        self.api[key] = {"class_type": cls, "inputs": values}
        self.visiting.remove(node_id)


def parameter(node_id, field, kind="other", type="number", **extra):
    return {"node_id": str(node_id), "input": field, "kind": kind, "type": type, **extra}


def prepare(source_path: Path = SOURCE, local_installed: bool = False):
    raw = source_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError("The supplied original changed; review its UI graph before exporting again.")
    ui = json.loads(raw)
    compiler = ReviewedGraph(ui)
    compiler.emit(264)
    graph = compiler.api
    expected_ids = {"36", "37", "38", "51", "58", "192", "223", "226", "250", "252", "253", "254", "256", "259", "263", "264", "265", "332", "334", "335"}
    if set(graph) != expected_ids or graph["265"]["inputs"].get("ref_images.ref_image_0") != ["51", 0]:
        raise ValueError("The reviewed active graph identities or primary reference path changed.")
    original_widgets = compiler.nodes[264]["widgets_values_named"]
    if any(original_widgets.get(key) != value for key, value in H264_DEFAULTS.items()):
        raise ValueError("Reviewed dynamic H.264 settings changed.")
    graph["51"]["inputs"]["image"] = "characterlock_identity_reference.png"
    graph["263"]["inputs"]["text"] = SAFE_SCENE
    # Studio's identity-aware GenerationPayload replaces scene_prompt at run
    # time. Keep the provider's trigger in a real graph node so that replacement
    # cannot accidentally drop it. This is an explicit NEW installed instance.
    if 336 in compiler.nodes or graph["265"]["inputs"]["prompt"] != ["263", 0]:
        raise ValueError("The reviewed prompt route or new trigger node identity changed.")
    graph["336"] = {"class_type": "StringConcatenate", "inputs": {
        "string_a": "r34l1sm", "string_b": ["263", 0], "delimiter": ", ",
    }}
    graph["265"]["inputs"]["prompt"] = ["336", 0]
    replacements = []
    if local_installed:
        # Explicitly authorized local adaptation. These exact installed choices
        # are still validated against fresh schemas; no alias/fallback search.
        replacements = [
            {"node_id": "192", "input": "unet_name", "source": graph["192"]["inputs"]["unet_name"], "local": LOCAL_UNET},
            {"node_id": "38", "source_class": "CLIPLoader", "local_class": "CLIPLoaderGGUF", "source_inputs": deepcopy(graph["38"]["inputs"]), "local_inputs": {"clip_name": LOCAL_CLIP, "type": "stable_diffusion"}},
            {"node_id": "335", "input": "lora_name", "source": graph["335"]["inputs"]["lora_name"], "local": LOCAL_TURBO},
            {"node_id": "252", "input": "multiple", "source": graph["252"]["inputs"]["multiple"], "local": 32, "reason": "Align generated image dimensions to H3 latent multiples, including low-resolution previews."},
        ]
        graph["192"]["inputs"]["unet_name"] = LOCAL_UNET
        graph["38"] = {"class_type": "CLIPLoaderGGUF", "inputs": {"clip_name": LOCAL_CLIP, "type": "stable_diffusion"}}
        graph["335"]["inputs"]["lora_name"] = LOCAL_TURBO
        graph["252"]["inputs"]["multiple"] = 32
    # Keep graph ordering deterministic and independent of recursive traversal.
    graph = dict(sorted(graph.items(), key=lambda item: int(item[0])))
    mapping = {"parameters": {
        "identity_image": parameter(51, "image", "image", "string", required=True, label="Referência da personagem", description="Imagem da biblioteca enviada automaticamente ao ComfyUI como <Picture 1>."),
        "scene_prompt": parameter(263, "text", "prompt", "string", required=True, default=SAFE_SCENE, label="Direção da cena", description="Use <Picture 1> para a referência selecionada. O gatilho r34l1sm é acrescentado automaticamente pelo workflow."),
        "realism_strength": parameter(334, "strength_model", "lora", default=1, min=0, max=2, label="Força do realismo", description="LoRA de realismo ativada por padrão com força 1, conforme o arquivo enviado."),
        "turbo_strength": parameter(335, "strength_model", "lora", default=1, min=0, max=2, label="Força da Turbo8" if local_installed else "Força da TurboV4", description="Apenas esta LoRA Turbo é carregada após a LoRA de realismo; força padrão 1."),
        "duration_seconds": parameter(259, "value", "duration", default=graph["259"]["inputs"]["value"], min=0.1, max=15.0, label="Duração (segundos)", description="O workflow quantiza para 5 + 17n quadros a 24 fps. O padrão 5 s gera 124 quadros (cerca de 5,17 s)."),
        "megapixels": parameter(252, "megapixels", default=graph["252"]["inputs"]["megapixels"], min=0.1, max=16.0, label="Resolução (megapixels)"),
        "resolution_multiple": parameter(252, "multiple", type="integer", default=graph["252"]["inputs"]["multiple"], min=8, max=128, label="Múltiplo da resolução", description="O preset local usa múltiplos de 32 para alinhar as dimensões aos latentes H3. O original usa 24."),
        "aspect_ratio": parameter(252, "aspect_ratio", type="enum", default=graph["252"]["inputs"]["aspect_ratio"], choices=["1:1 (Square)", "2:3 (Portrait Photo)", "3:2 (Photo)", "3:4 (Portrait Standard)", "4:3 (Standard)", "9:16 (Portrait Widescreen)", "16:9 (Widescreen)", "21:9 (Ultrawide)"], label="Proporção"),
        "steps": parameter(332, "steps", type="integer", default=graph["332"]["inputs"]["steps"], min=1, max=1000, label="Steps"),
        "seed": parameter(256, "noise_seed", "seed", "integer", default=graph["256"]["inputs"]["noise_seed"], min=0, max=9007199254740991, label="Seed"),
    }, "output_nodes": ["264"]}
    provenance = {
        "source_kind": "user_supplied_ui_workflow",
        "source_file": str(source_path),
        "source_sha256": digest,
        "source_unchanged": source_path.read_bytes() == raw,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "source_node_count": len(ui["nodes"]),
        "prepared_node_count": len(graph),
        "active_output_node": "264",
        "source_loras": compiler.lora_rows,
        "loras_loaded_in_order": [graph[node_id]["inputs"]["lora_name"] for node_id in ("334", "335")],
        "native_lora_conversion": {"source_node_id": "334", "runtime_nodes": ["334", "335"], "new_runtime_node_ids": ["335"], "clip_connected": False},
        "fixed_realism_trigger": {"node_id": "336", "class_type": "StringConcatenate", "text": "r34l1sm", "delimiter": ", ", "new_runtime_node_id": True},
        "resolved_virtual_node_ids": sorted(compiler.virtual_nodes),
        "bypassed_media_node_ids": sorted(compiler.bypassed_media),
        "omitted_optional_inputs": compiler.omitted_inputs,
        "preserved_dynamic_h264_defaults": H264_DEFAULTS,
        "variant": "local-installed" if local_installed else "source-exact",
        "models_substituted": local_installed,
        "authorized_local_replacements": replacements,
        "execution_requested": False,
        "changes": [
            "Resolve actual SetNode/GetNode/Reroute links; export only dependencies of active output264. The bypassed second pass remains inactive.",
            "Replace source rgthree334 with native model-only LoRA nodes334 and335, preserving enabled LoRA order and strengths. Source CLIP input is disconnected and CLIP output unused. Disabled LoRAs remain disabled and are recorded without being loaded.",
            "Native LoRA filename choices must validate; unlike rgthree, absent enabled LoRAs cannot silently become passthrough.",
            "Replace private source image filename at LoadImage51 with a required character-owned library asset binding, preserving the original primary reference connection.",
            "Replace private source prompt with a neutral fictional adult scene. Add new installed StringConcatenate336 to prepend r34l1sm after any scene or identity text supplied by Studio. The original text remains only in the untouched original file.",
            "Omit dynamic H.264 widget literals whose exact values match installed format defaults, because the Studio adapter validates only schema-declared inputs. Verify those defaults live before registration.",
            "Preserve actual source models, sampling settings, duration, resolution multiple24, reference sizing max, output prefix and audio path without local substitutions or downloads.",
        ],
        "quality_note": "Structural preflight does not prove GPU memory fit, weight compatibility or visual quality. This source preset deliberately fails closed while its exact models or enabled LoRAs are absent.",
    }
    if local_installed:
        provenance["changes"].append("Explicit user-authorized local variant replaces the unavailable source UNET, CLIP loader/encoder, and enabled TurboV4 LoRA with the three exact installed choices recorded in authorized_local_replacements. It additionally changes ResolutionSelector.multiple from24 to32 to align generation dimensions with H3 latents. Realism remains first at strength1, followed by only the selected Turbo8 at strength1; no Turbo4 is stacked.")
        provenance["changes"][-2] = "Preserve source sampling settings, duration, megapixels, reference sizing max, output prefix and audio path. Explicit local weights and resolution-alignment substitutions below are not claimed to be the original configuration."
        provenance["quality_note"] = "Local adaptation uses installed files and retains eight sampling steps. Structural preflight does not prove this pruned UNET/Turbo8 combination's weight compatibility, GPU memory fit or visual quality; no generation is performed by this utility."
    return graph, mapping, provenance


def validate(graph, mapping, info):
    sys.path.insert(0, str(PROJECT / "backend"))
    from app.workflows import WorkflowAdapter
    report = WorkflowAdapter(graph, mapping).validate(info, allow_missing={"identity_image"})
    formats = info.get("VHS_VideoCombine", {}).get("input", {}).get("required", {}).get("format", [])
    widgets = formats[1].get("formats", {}).get("video/h264-mp4", []) if len(formats) > 1 and isinstance(formats[1], dict) else []
    defaults = {}
    for widget in widgets:
        if not isinstance(widget, list) or len(widget) < 2:
            continue
        name, kind = widget[:2]
        options = widget[2] if len(widget) > 2 and isinstance(widget[2], dict) else {}
        defaults[name] = options.get("default", kind[0] if isinstance(kind, list) and kind else None)
    if any(defaults.get(key) != value for key, value in H264_DEFAULTS.items()):
        report["errors"].append({"code": "format_defaults_changed", "message": "Live H.264 defaults do not match preserved source settings.", "node_id": "264"})
    report["valid"] = not report["errors"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--studio-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--local-installed", action="store_true", help="Prepare the explicitly authorized local UNET, GGUF encoder and Turbo8 adaptation; record every substitution.")
    parser.add_argument("--register", action="store_true", help="Store only a valid workflow; never submit a job.")
    args = parser.parse_args()
    graph, mapping, provenance = prepare(args.source, local_installed=args.local_installed)
    stem = "local-installed" if args.local_installed else STEM
    name = LOCAL_NAME if args.local_installed else NAME
    info = request(args.comfy_url, "/object_info")
    report = validate(graph, mapping, info)
    provenance["preflight_valid"] = report["valid"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for suffix, value in (("api", graph), ("mapping", mapping), ("provenance", provenance), ("validation", report)):
        (args.output_dir / f"{stem}.{suffix}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"variant": stem, "prepared_nodes": len(graph), "preflight_valid": report["valid"], "errors": report["errors"], "execution_requested": False, "registered": False}
    if args.register and report["valid"]:
        checksum = hashlib.sha256(json.dumps(graph, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        existing = next((row for row in request(args.studio_url, "/workflows?module=video_studio") if row["sha256"] == checksum and row["mapping"] == mapping), None)
        registered = existing or request(args.studio_url, "/workflows", {"name": name, "module": "video_studio", "workflow": graph, "mapping": mapping})
        remote = request(args.studio_url, f"/workflows/{registered['id']}/validate", {})
        summary.update(registered=True, workflow_id=registered["id"], studio_preflight_valid=remote["valid"], studio_errors=remote["errors"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
