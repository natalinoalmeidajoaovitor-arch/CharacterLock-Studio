"""Register and bind Character Lab Outfits & References workflows, approve pending dataset items, and validate all executable workflows."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import urllib.request

BASE = "http://127.0.0.1:8000/api"
PROJECT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT / "data/characterlock.sqlite3"


def req(path: str, payload=None, method: str | None = None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method or ("POST" if payload is not None else "GET"),
    )
    with urllib.request.urlopen(r, timeout=45) as resp:
        return json.load(resp)


def make_qwen_stage_graph(prefix: str, default_prompt: str):
    return {
        "10": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"},
        },
        "11": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": "qwen3vl_8b_w4a8.safetensors", "type": "qwen_image", "device": "default"},
        },
        "12": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"},
        },
        "13": {
            "class_type": "Power Lora Loader (rgthree)",
            "inputs": {"model": ["10", 0], "clip": ["11", 0]},
        },
        "40": {
            "class_type": "MiniMaxH3MediaLoader",
            "inputs": {"media_state": "[]"},
        },
        "41": {
            "class_type": "MiniMaxH3ReferenceSplitter",
            "inputs": {"references": ["40", 0]},
        },
        "52": {
            "class_type": "PrimitiveInt",
            "inputs": {"value": 20261017},
        },
        "62": {
            "class_type": "PrimitiveInt",
            "inputs": {"value": 10},
        },
        "100": {
            "class_type": "TextEncodeQwenImage21",
            "inputs": {
                "prompt": default_prompt,
                "negative_prompt": "",
                "resolution": 0,
                "clip": ["13", 1],
                "vae": ["12", 0],
                "images.image_1": ["41", 0],
                "images.image_2": ["41", 1],
                "images.image_3": ["41", 2],
            },
        },
        "101": {
            "class_type": "KSampler",
            "inputs": {
                "seed": ["52", 0],
                "steps": ["62", 0],
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "beta",
                "denoise": 1.0,
                "model": ["13", 0],
                "positive": ["100", 0],
                "negative": ["100", 1],
                "latent_image": ["100", 2],
            },
        },
        "102": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["101", 0], "vae": ["12", 0]},
        },
        "103": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": prefix, "images": ["102", 0]},
        },
    }


def main():
    mapping = {
        "parameters": {
            "prompt": {
                "node_id": "100",
                "input": "prompt",
                "kind": "prompt",
                "type": "string",
                "required": True,
                "label": "Descrição",
            },
            "steps": {
                "node_id": "62",
                "input": "value",
                "kind": "other",
                "type": "integer",
                "default": 10,
                "min": 1,
                "max": 100,
                "label": "Passos de geração",
            },
            "seed": {
                "node_id": "52",
                "input": "value",
                "kind": "seed",
                "type": "integer",
                "default": 20261017,
                "min": 0,
                "max": 4294967000,
                "label": "Seed",
            },
            "identity_references": {
                "node_id": "40",
                "input": "media_state",
                "kind": "image",
                "type": "string",
                "required": True,
                "serializer": "h3_media_state",
            },
        },
        "output_nodes": ["103"],
    }

    existing_wfs = req("/workflows?module=character_lab")

    # 1. Register and bind Outfits workflow
    outfit_name = "Qwen 2.1 · Figurino da Personagem (local)"
    outfit_wf = next((w for w in existing_wfs if w["name"] == outfit_name), None)
    if not outfit_wf:
        outfit_wf = req(
            "/workflows",
            {
                "name": outfit_name,
                "module": "character_lab",
                "workflow": make_qwen_stage_graph(
                    "CharacterLock/outfits/outfit",
                    "Full-body studio fashion photograph of the character in <image1>, <image2>, <image3>.",
                ),
                "mapping": mapping,
            },
        )
    req("/workflows/" + outfit_wf["id"] + "/validate", {})
    req(
        "/lab/workflows",
        {
            "workflow_id": outfit_wf["id"],
            "stage": "outfits",
            "prompt_parameter": "prompt",
            "steps_parameter": "steps",
            "reference_parameters": {"identity_references": "sheet_full_bundle"},
            "output_categories": {"103": "outfits"},
            "prompt_template": (
                "Same person as <image1>, <image2>, and <image3>. Full-body studio fashion photograph showing "
                "the character wearing the requested outfit: {prompt}. Plain soft grey studio background, even "
                "studio lighting, sharp focus, realistic skin and fabric texture. Keep the exact face, hair, "
                "skin tone, eye colour, and body proportions of <image1>, <image2>, and <image3>.\n\n"
                "Character identity profile: {identity}"
            ),
        },
    )
    print("Bound Outfits workflow:", outfit_wf["id"])

    # 2. Register and bind References workflow
    ref_name = "Qwen 2.1 · Referência em Cena (local)"
    ref_wf = next((w for w in existing_wfs if w["name"] == ref_name), None)
    if not ref_wf:
        ref_wf = req(
            "/workflows",
            {
                "name": ref_name,
                "module": "character_lab",
                "workflow": make_qwen_stage_graph(
                    "CharacterLock/references/scene",
                    "Realistic cinematic photograph of the character in <image1>, <image2>, <image3>.",
                ),
                "mapping": mapping,
            },
        )
    req("/workflows/" + ref_wf["id"] + "/validate", {})
    req(
        "/lab/workflows",
        {
            "workflow_id": ref_wf["id"],
            "stage": "references",
            "prompt_parameter": "prompt",
            "steps_parameter": "steps",
            "reference_parameters": {"identity_references": "sheet_full_bundle"},
            "output_categories": {"103": "references"},
            "prompt_template": (
                "Same person as <image1>, <image2>, and <image3>. Realistic cinematic photograph of the "
                "character in scene: {prompt}. Natural lighting, sharp focus on the face, realistic skin "
                "texture and proportions. Keep the exact face, hair, skin tone, eye colour, and recognizable "
                "identity of <image1>, <image2>, and <image3>.\n\n"
                "Character identity profile: {identity}"
            ),
        },
    )
    print("Bound References workflow:", ref_wf["id"])

    # 3. Approve pending dataset assets for all characters so stages 03 and 04 are unlocked
    for char in req("/characters"):
        cid = char["id"]
        lab = req("/characters/" + cid + "/lab")
        rev = lab.get("active_revision_id")
        for asset in lab.get("assets", []):
            if asset["stage"] == "dataset" and asset["approval"] == "pending" and asset.get("revision_id") == rev:
                req("/characters/" + cid + "/lab/assets/" + asset["asset_id"], {"approval": "approved"}, method="PATCH")
                print(f"Approved dataset asset {asset['asset_id']} for {char['name']}")

    # 4. Ensure OmniVoice mapping has a default text so Voice Studio button is never blocked on empty draft
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT id, mapping FROM workflows WHERE id=?", ("6440066ef1c64e279ef9e6722f58ee7e",)).fetchone()
        if row:
            m = json.loads(row[1])
            if "text" in m.get("parameters", {}) and not m["parameters"]["text"].get("default"):
                m["parameters"]["text"]["default"] = "Olá! Eu sou uma influenciadora virtual criada no CharacterLock Studio."
                conn.execute("UPDATE workflows SET mapping=? WHERE id=?", (json.dumps(m, ensure_ascii=False), row[0]))
                conn.commit()
                print("Updated OmniVoice default text in DB")

    # 5. Validate all executable workflows
    for wf in req("/workflows"):
        if wf.get("executable"):
            res = req("/workflows/" + wf["id"] + "/validate", {})
            print(f"Validated {wf['module']} | {wf['name']} -> valid={res['valid']}")


if __name__ == "__main__":
    main()
