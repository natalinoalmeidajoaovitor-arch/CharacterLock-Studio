"""Reviewed MATRIX section exports plus an explicitly adapted local Sheet.

The source JSON remains untouched. Sheet adaptation reuses real Qwen nodes and
adds an installed image-grid node, then saves the board and its real anchors.
No weights, extensions or models are downloaded or modified by this utility.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = Path.home() / "ComfyUI_windows_portable/MATRIX-Qwen21-Dataset-Workflow/workflows/normal/MATRIX-Qwen21-Dataset-V4.json"
SOURCE_SHA_PREFIX = "05f2804cb6e5"
OUTPUT = PROJECT / "workflows/local/matrix-lab"
FIELDS = {
    "UNETLoader": ["unet_name", "weight_dtype"], "CLIPLoader": ["clip_name", "type", "device"],
    "VAELoader": ["vae_name"], "Power Lora Loader (rgthree)": [],
    "MiniMaxH3MediaLoader": ["media_state", None, None, None], "MiniMaxH3ReferenceSplitter": [],
    "EmptyLatentImage": ["width", "height", "batch_size"], "PrimitiveInt": ["value", None],
    "TextEncodeQwenImage21": ["prompt", "negative_prompt", "resolution"],
    "KSampler": ["seed", None, "steps", "cfg", "sampler_name", "scheduler", "denoise"],
    "VAEDecode": [], "SaveImage": ["filename_prefix"], "ComfyMathExpression": ["expression"],
    "MATRIX_QwenImage21Resolution": ["aspect_ratio"],
}


def request(path, body=None, base="http://127.0.0.1:8000"):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def source():
    raw = SOURCE.read_bytes()
    if not hashlib.sha256(raw).hexdigest().startswith(SOURCE_SHA_PREFIX):
        raise ValueError("The supplied source changed; inspect it before adapting again.")
    graph = json.loads(raw)
    return graph, {n["id"]: n for n in graph["nodes"]}, {link[0]: link for link in graph["links"]}


def export(ids, nodes, links):
    keep = set(ids)
    result = {}
    for node_id in ids:
        node = nodes[node_id]
        fields = FIELDS[node["type"]]
        widgets = node.get("widgets_values") or []
        if fields and len(widgets) != len(fields):
            raise ValueError(f"Reviewed widget layout changed at source node {node_id}.")
        values = {key: deepcopy(value) for key, value in zip(fields, widgets) if key is not None}
        for item in node.get("inputs", []):
            link = links.get(item.get("link"))
            if link and link[1] in keep:
                values[item["name"]] = [str(link[1]), link[2]]
        result[str(node_id)] = {"class_type": node["type"], "inputs": values}
    return result


def model_config(graph, info):
    # This is the encoder already running successfully in CharacterLock, not a
    # replacement/download of the encoder named by the original package.
    encoder = "qwen3vl_8b_w4a8.safetensors"
    if encoder not in info["CLIPLoader"]["input"]["required"]["clip_name"][0]:
        raise ValueError("The previously validated local encoder is unavailable.")
    graph["11"]["inputs"]["clip_name"] = encoder


def parameter(node, field, kind="other", type="integer", **extra):
    return {"node_id": str(node), "input": field, "kind": kind, "type": type, **extra}


def media_parameter(node):
    return parameter(node, "media_state", "image", "string", required=True, serializer="h3_media_state")


def sheet(nodes, links, info, with_reference):
    encoders = [100, 190, 200, 260, 340, 350, 360, 380]
    ids = [10, 11, 12, 13, 51, 52, 62]
    for encoder in encoders:
        ids.extend([encoder, encoder + 1, encoder + 2, encoder + 3, encoder + 4])
    if with_reference:
        ids.extend([40, 41])
    graph = export(ids, nodes, links)
    model_config(graph, info)
    graph["51"]["inputs"] = {"width": 512, "height": 768, "batch_size": 1}
    graph["52"]["inputs"]["value"] = 20261016
    graph["62"]["inputs"]["value"] = 10
    for encoder in encoders:
        entry = graph[str(encoder)]["inputs"]
        for name in list(entry):
            if name.startswith("images."):
                del entry[name]
        entry["resolution"] = 0
        graph[str(encoder + 1)]["inputs"]["steps"] = ["62", 0]
        graph[str(encoder + 4)]["inputs"]["values.a"] = ["52", 0]
        if encoder != 100:
            # Official node's latent matches the first image's exact size;
            # avoid shifting image edits by sampling an unrelated latent size.
            graph[str(encoder + 1)]["inputs"]["latent_image"] = [str(encoder), 2]
        graph[str(encoder + 3)]["inputs"]["filename_prefix"] = f"CharacterLock/sheet/{encoder}"
    for encoder in (190, 200, 260):
        graph[str(encoder)]["inputs"]["images.image_1"] = ["102", 0]
    graph["260"]["inputs"]["prompt"] = "Same adult person as <image1>, same face, hair, eyes, skin and shirt. Change the framing completely: zoom out to a true waist-up studio photograph. Show the entire head, both shoulders, complete torso down to the waist and both arms with hands visible near the hips. The waist must be visible at the bottom of the frame. Neutral front view, arms relaxed, plain pale grey studio background, even soft light. Fully clothed; preserve the exact identity and upper-body clothing."
    graph["340"]["inputs"].update({"images.image_1": ["102", 0], "images.image_2": ["262", 0], "prompt": "Photorealistic full-body front reference of the same adult person. <image1> defines the face and <image2> defines the upper body and clothing. Show the complete person from head to closed shoes, standing neutrally with arms slightly away from the torso. Preserve the same face, hair, skin, body build and upper-body outfit. Complete a coherent modest casual outfit with trousers and closed shoes. Plain pale grey studio background and even soft light. Entire body inside the frame, no cropped feet, fully clothed."})
    for encoder in (350, 360, 380):
        graph[str(encoder)]["inputs"].update({"images.image_1": ["102", 0], "images.image_2": ["262", 0], "images.image_3": ["342", 0]})
    # Two additional pose chains are explicit new instances copied from the
    # real installed Qwen encoder/sampler/decode/save/math node schemas.
    pose_prompts = {
        430: "Change the pose completely: neutral front-facing A-pose, standing upright, both arms extended diagonally down about 35 degrees away from the body, palms facing forwards, both hands and all fingers visible, feet hip-width apart.",
        440: "Change the pose completely: confident front-facing stance with both hands resting on the hips, elbows pointing out, weight balanced on both feet, head facing the camera.",
    }
    for first, pose in pose_prompts.items():
        assert all(first + offset not in nodes for offset in range(5))
        for offset in range(5):
            node = deepcopy(graph[str(350 + offset)])
            for field, value in node["inputs"].items():
                if isinstance(value, list) and len(value) == 2 and str(value[0]).isdigit() and 350 <= int(value[0]) <= 354:
                    node["inputs"][field] = [str(first + int(value[0]) - 350), value[1]]
            graph[str(first + offset)] = node
        graph[str(first)]["inputs"]["prompt"] = "Same adult person: <image1> defines the face, <image2> the upper body, <image3> the complete body, clothing and shoes. " + pose + " Full body from head to shoes entirely inside the frame. Preserve the exact face, hair, body proportions, clothing, colours and shoes of the references. Plain pale grey studio background, even soft light, realistic photograph, fully clothed, no props, no extra people."
        graph[str(first + 3)]["inputs"]["filename_prefix"] = f"CharacterLock/sheet/{first}"
    # New IDs deliberately identify NEW adapted nodes, not nodes falsely
    # claimed to exist in MATRIX. Both classes are checked on the live server.
    assert 421 not in nodes and 422 not in nodes and 423 not in nodes
    panels = [102, 192, 202, 342, 362, 382, 352, 432, 442]
    graph["421"] = {"class_type": "ImageGridComposite3x3", "inputs": {f"image{index + 1}": [str(node_id), 0] for index, node_id in enumerate(panels)}}
    graph["422"] = {"class_type": "SaveImage", "inputs": {"images": ["421", 0], "filename_prefix": "CharacterLock/sheet/character_sheet"}}
    intro = "Create a realistic standard close-up reference portrait of an original fictional adult character. Identity profile: {identity}. Front-facing head and shoulders, camera at eye level, face centred and prominent, complete head and hair visible, plain pale grey studio background, even soft light, natural skin. Fully clothed in modest casual clothing. This close-up defines the face for the connected profile, three-quarter, body and pose views."
    parameters = {"identity_prompt": parameter(100, "prompt", "prompt", "string", required=True), "steps": parameter(62, "value", default=10, min=1, max=10000), "seed": parameter(52, "value", "seed", default=20261016, min=0, max=4294967000)}
    refs = {}
    if with_reference:
        graph["423"] = {"class_type": "ImageScale", "inputs": {"image": ["41", 0], "upscale_method": "lanczos", "width": 512, "height": 768, "crop": "center"}}
        graph["100"]["inputs"]["images.image_1"] = ["423", 0]
        graph["101"]["inputs"]["latent_image"] = ["100", 2]
        parameters["reference_image"] = media_parameter(40)
        refs = {"reference_image": "optional_reference"}
        intro += " Retain the face, hair and recognizable identity of <image1>; do not replace the person with a new face."
    graph["100"]["inputs"]["prompt"] = intro.replace("{identity}", "Adult fictional character, natural casual styling")
    outputs = {"103": "face", "193": "face_three_quarter", "203": "face_profile", "263": "upper_body", "343": "full_body", "353": "body_three_quarter", "363": "side", "383": "back", "433": "pose_a", "443": "pose_hands_on_hips", "422": "character_sheet"}
    return graph, {"parameters": parameters, "output_nodes": list(outputs)}, {"stage": "character_sheet", "prompt_parameter": "identity_prompt", "steps_parameter": "steps", "reference_parameters": refs, "output_categories": outputs, "prompt_template": intro}


def dataset(nodes, links, info, section):
    config = {
        "head": (100, 40, 41, 62, 52, "sheet_face"),
        "head360": (180, 46, 47, 63, 55, "sheet_face"),
        "upper360": (260, 42, 43, 64, 58, "sheet_upper_bundle"),
        "full360": (340, 44, 45, 65, 61, "sheet_full_bundle"),
    }
    first, loader, splitter, steps, seed, role = config[section]
    encoders = list(range(first, first + 80, 10))
    ids = [10, 11, 12, 13, loader, splitter, steps, seed]
    for encoder in encoders:
        ids.extend([encoder, encoder + 1, encoder + 2, encoder + 3, encoder + 4])
    graph = export(ids, nodes, links)
    model_config(graph, info)
    required_refs = 1 if section in {"head", "head360"} else 2 if section == "upper360" else 3
    outputs = {}
    for index, encoder in enumerate(encoders):
        entry = graph[str(encoder)]["inputs"]
        for name in list(entry):
            if name.startswith("images.") and int(name.rsplit("_", 1)[1]) > required_refs:
                del entry[name]
        entry["resolution"] = 0
        graph[str(encoder + 1)]["inputs"]["latent_image"] = [str(encoder), 2]
        graph[str(encoder + 3)]["inputs"]["filename_prefix"] = f"CharacterLock/dataset/{section}/{index + 1:02}"
        outputs[str(encoder + 3)] = "face" if section == "head" and index == 0 else "expressions" if section == "head" and index < 6 else "angles" if section in {"head", "head360"} else "body"
    first_prompt = graph[str(first)]["inputs"]["prompt"]
    template = first_prompt.replace("{", "{{").replace("}", "}}") + "\n\nCharacter identity profile: {identity}"
    parameters = {"identity_prompt": parameter(first, "prompt", "prompt", "string", required=True), "steps": parameter(steps, "value", default=10, min=1, max=10000), "seed": parameter(seed, "value", "seed", default=nodes[seed]["widgets_values"][0], min=0, max=4294967000), "sheet_references": media_parameter(loader)}
    return graph, {"parameters": parameters, "output_nodes": list(outputs)}, {"stage": "dataset", "prompt_parameter": "identity_prompt", "steps_parameter": "steps", "reference_parameters": {"sheet_references": role}, "output_categories": outputs, "prompt_template": template}


def dataset_smoke5(nodes, links, info):
    """Exactly five original MATRIX edits in one job, covering all anchors."""
    combined = {}
    for section in ("head", "head360", "upper360", "full360"):
        graph, _, _ = dataset(nodes, links, info, section)
        for node_id, node in graph.items():
            if node_id in combined and combined[node_id] != node:
                raise ValueError(f"Shared MATRIX node differs between sections: {node_id}")
            combined[node_id] = node
    outputs = {"103": "face", "113": "expressions", "203": "angles", "283": "body", "353": "body"}
    for output in outputs:
        sampler = str(int(output) - 2)
        combined[sampler]["inputs"]["steps"] = ["62", 0]
        combined[output]["inputs"]["filename_prefix"] = f"CharacterLock/dataset/smoke5/{output}"
    combined["62"]["inputs"]["value"] = 10
    keep = set()
    def visit(node_id):
        if node_id in keep:
            return
        keep.add(node_id)
        for value in combined[node_id]["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and str(value[0]) in combined and isinstance(value[1], int):
                visit(str(value[0]))
    for output in outputs:
        visit(output)
    graph = {key: value for key, value in combined.items() if key in keep}
    template = graph["100"]["inputs"]["prompt"].replace("{", "{{").replace("}", "}}") + "\n\nCharacter identity profile: {identity}"
    refs = {"face_head": "sheet_face", "face_angle": "sheet_face", "upper_references": "sheet_upper_bundle", "full_references": "sheet_full_bundle"}
    parameters = {"identity_prompt": parameter(100, "prompt", "prompt", "string", required=True), "steps": parameter(62, "value", default=10, min=1, max=10000), **{name: media_parameter(loader) for name, loader in zip(refs, (40, 46, 42, 44))}}
    return graph, {"parameters": parameters, "output_nodes": list(outputs)}, {"stage": "dataset", "prompt_parameter": "identity_prompt", "steps_parameter": "steps", "reference_parameters": refs, "output_categories": outputs, "prompt_template": template}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--with-smoke5", action="store_true", help="Also prepare/register the single five-photo Dataset test variant; never queues it.")
    args = parser.parse_args()
    sys.path.insert(0, str(PROJECT / "backend"))
    from app.workflows import WorkflowAdapter
    _, nodes, links = source()
    info = request("/object_info", base="http://127.0.0.1:8188")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    definitions = [("sheet-description", "Qwen 2.1 · Sheet padrão 9 vistas por descrição", sheet(nodes, links, info, False)), ("sheet-reference", "Qwen 2.1 · Sheet padrão 9 vistas com referência", sheet(nodes, links, info, True))]
    for key, title in (("head", "Expressões e rosto"), ("head360", "Rosto em 360°"), ("upper360", "Tronco em 360°"), ("full360", "Corpo inteiro em 360°")):
        definitions.append(("dataset-" + key, "MATRIX Qwen 2.1 · " + title + " (8 imagens)", dataset(nodes, links, info, key)))
    if args.with_smoke5:
        definitions.append(("dataset-smoke5", "MATRIX Qwen 2.1 · Teste de 5 fotos", dataset_smoke5(nodes, links, info)))
    manifest = {"source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(), "source_unchanged": True, "workflows": [], "adaptation_notes": ["Sheet is an authorized NEW adaptation, not a Sheet present in MATRIX.", "Original node IDs reused; 421 grid, 422 board SaveImage, 423 optional reference scaler and 430..444 pose chains are newly added installed node instances.", "Existing validated w4a8 text encoder reused; original int8 encoder is absent. No model replaced/downloaded.", "Edit samplers use encoder latent and resolution=0 to match references, following official ComfyUI guidance; original workflow remains untouched.", "Standard Sheet saves ten companion images and a fixed 3x3 board: three face closeups then six body views/poses. Upper body is a separate Dataset anchor. Approval remains explicit.", "Dataset preserves original per-view prompts and group steps/seeds; required reference ladder resolved from approved Sheet anchors.", "Optional smoke5 is exactly five original MATRIX edits in one job: face, expression, profile, upper body and full body, at ten shared steps. It does not execute the 32-image Dataset."]}
    existing = request("/api/workflows") if args.register else []
    for key, title, (graph, mapping, binding) in definitions:
        allow_missing = set(binding["reference_parameters"])
        validation = WorkflowAdapter(graph, mapping).validate(info, allow_missing=allow_missing | {"identity_prompt"})
        if not validation["valid"]:
            raise ValueError(json.dumps({"workflow": key, "errors": validation["errors"]}))
        for suffix, value in (("api", graph), ("mapping", mapping), ("binding", binding), ("validation", validation)):
            (OUTPUT / (key + "." + suffix + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        entry = {"key": key, "name": title, "node_count": len(graph), "binding": binding, "valid": True}
        if args.register:
            checksum = hashlib.sha256(json.dumps(graph, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            item = next((w for w in existing if w["sha256"] == checksum and w["mapping"] == mapping and w["module"] == "character_lab"), None)
            item = item or request("/api/workflows", {"name": title, "module": "character_lab", "workflow": graph, "mapping": mapping})
            binding = binding | {"workflow_id": item["id"]}
            request("/api/lab/workflows", binding)
            entry["workflow_id"] = item["id"]
            entry["binding"] = binding
        manifest["workflows"].append(entry)
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"prepared": len(definitions), "registered": args.register, "workflows": [{"key": e["key"], "id": e.get("workflow_id"), "nodes": e["node_count"]} for e in manifest["workflows"]]}))


if __name__ == "__main__":
    main()
