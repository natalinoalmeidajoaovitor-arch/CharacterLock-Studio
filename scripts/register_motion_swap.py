"""Export MiniMax H3 Character Swap (Motion Swap) to executable API format.

Preserves workflows/originals/f5c24c580c3d-MinimaxH3_Char_Swap-20261015.json
untouched. Resolves SetNode/GetNode virtual links and provides an explicitly
documented local-installed variant using installed UNET, GGUF CLIP, and LoRAs
plus native LoadImage and VHS_LoadVideo staging inputs.
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
SOURCE = PROJECT / "workflows/originals/f5c24c580c3d-MinimaxH3_Char_Swap-20261015.json"
SOURCE_SHA256 = "f5c24c580c3d4aa6095bc58a5ca45787ee956051212b039321480bf59d5fd521"
OUTPUT = PROJECT / "workflows/local/motion-swap"
NAME = "MiniMax H3 · Character & Motion Swap (local)"

LOCAL_VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
LOCAL_AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
LOCAL_UNET = "Minimax-h3_Singularity_ref2va_Pruned_v1.3_int8.safetensors"
LOCAL_CLIP = "qwen3vl-32B-MiniMax-H3-Q2_K.gguf"
LOCAL_TURBO_LORA = "minimax_h3_fl2v_lightx2v_turbo_8step_v1.0_resized_avg_rank_24_bf16.safetensors"
LOCAL_SWAP_LORA = "h3_character_swap_pro4500_1000.safetensors"
LOCAL_REALISM_LORA = "h3-realism-people-t2v-i2v-r2v.safetensors"

DEFAULT_TARGET_PERSON = "man on the right in the black t-shirt"

DEFAULT_SWAP_PROMPT = (
    "Replace the [TARGET_PERSON] in <Video 1> with the character shown in <Picture 1>.\n\n"
    "subject_definitions:\n"
    "<Subject 1> is the replacement character whose appearance comes from <Picture 1> and whose performance comes from the [TARGET_PERSON] being replaced in <Video 1>. Preserve the reference character's facial features, hairstyle, skin tone, body proportions, clothing, colors, and distinctive visual style. The reference image supplies appearance only, not the character's pose, expression, background, or framing.\n"
    "<Subject 2> is the surrounding scene from <Video 1>, including its exact orange background wall, lighting, hanging microphone, objects, and any people other than the [TARGET_PERSON] being replaced.\n"
    "<Video 1> is the source video being edited and supplies the shot composition, camera movement, timing, and sequence of actions.\n\n"
    "summary:\n"
    "[video editing + reference generation] The target video is an edited version of <Video 1>. Replace only the [TARGET_PERSON] with <Subject 1>, transferring their complete visible performance to the reference character while preserving <Subject 2> and the source video's framing and timing.\n\n"
    "retention_analysis:\n"
    "<Subject 1> (throughout [Shot 1]): fully_preserved - maintain the character's referenced identity, clothing, proportions, and visual style consistently as the character performs the source person's movements.\n"
    "<Subject 2> (throughout [Shot 1]): fully_preserved - retain the surrounding scene, exact background color, and other people unchanged over time.\n"
    "<Video 1>: partially_preserved - retain composition, camera motion, action timing, and duration; replace only the [TARGET_PERSON]'s appearance.\n\n"
    "detailed_description:\n"
    "Preserve the source scene's visual treatment while retaining the replacement character's distinctive design. Adapt illumination, shading, and perspective to the source scene.\n\n"
    "[Shot 1] Begin with the same composition and camera viewpoint as <Video 1>. <Subject 1> occupies the [TARGET_PERSON]'s position and follows their movement through the frame. Match the original performance moment by moment: body posture, gestures, head turns, gaze, blinking, facial expressions, and visible mouth movements.\n\n"
    "Maintain the reference character's identity through every expression and viewing angle. Hair and clothing move naturally with the transferred performance. Preserve interactions with source-scene objects and the ordering of foreground and background occlusions.\n\n"
    "Keep the source video's crop and shot scale. Show only the portions of the replacement character that belong within that framing; do not widen the shot to reproduce the full-body reference. Do not import the reference image's gray background, static pose, or handheld props. Preserve the source camera movement and action timing through the final frame.\n\n"
    "overall_soundscape:\n"
    "Retain the source clip's existing sound without adding new dialogue or sound effects.\n\n"
    "non_diegetic_music:\n"
    "Retain existing source music, if present; add no new music."
)

H264_DEFAULTS = {"pix_fmt": "yuv420p", "crf": 19, "save_metadata": True, "trim_to_audio": False}


def request(base: str, path: str, payload=None):
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def parameter(node_id, field, kind="other", type="number", **extra):
    return {"node_id": str(node_id), "input": field, "kind": kind, "type": type, **extra}


def prepare(source_path: Path = SOURCE):
    raw = source_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if not digest.startswith("f5c24c580c3d"):
        raise ValueError(f"Unexpected source SHA-256: {digest}")
    ui = json.loads(raw)
    nodes = {n["id"]: n for n in ui["nodes"]}
    if 6541 not in nodes or 6617 not in nodes:
        raise ValueError("Expected Motion Swap nodes 6541 and 6617 are missing.")

    # Resolved active API graph preserving original node IDs and topology.
    graph = {
        "207": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": LOCAL_VIDEO_VAE},
        },
        "208": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": LOCAL_AUDIO_VAE},
        },
        "209": {
            "class_type": "VAEDecodeAudio",
            "inputs": {"samples": ["213", 1], "vae": ["208", 0]},
        },
        "211": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "euler"},
        },
        "212": {
            "class_type": "BasicScheduler",
            "inputs": {"model": ["6007", 0], "scheduler": "beta", "steps": 8, "denoise": 1},
        },
        "213": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["217", 0],
                "guider": ["214", 0],
                "sampler": ["211", 0],
                "sigmas": ["212", 0],
                "latent_image": ["6617", 1],
            },
        },
        "214": {
            "class_type": "BasicGuider",
            "inputs": {"model": ["6007", 0], "conditioning": ["6617", 0]},
        },
        "215": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": LOCAL_UNET, "weight_dtype": "default"},
        },
        "216": {
            "class_type": "CLIPLoaderGGUF",
            "inputs": {"clip_name": LOCAL_CLIP, "type": "minimax"},
        },
        "217": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": ["6327", 0]},
        },
        "6007": {
            "class_type": "MiniMaxH3SigmaShift",
            "inputs": {"model": ["6126", 0], "shift_video": 12, "shift_audio": 3},
        },
        "6122": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["215", 0], "lora_name": LOCAL_TURBO_LORA, "strength_model": 1},
        },
        "6123": {
            "class_type": "PathchSageAttentionKJ",
            "inputs": {"model": ["6373", 0], "sage_attention": "auto", "allow_compile": False},
        },
        "6126": {
            "class_type": "ModelPatchTorchSettings",
            "inputs": {"model": ["6127", 0], "enable_fp16_accumulation": True},
        },
        "6127": {
            "class_type": "MiniMaxChunkFeedForward",
            "inputs": {"model": ["6123", 0], "chunks": 2, "seq_threshold": 4096},
        },
        "6327": {
            "class_type": "SeedNode",
            "inputs": {"seed": 43},
        },
        "6341": {
            "class_type": "PrimitiveFloat",
            "inputs": {"value": 0.5},
        },
        "6342": {
            "class_type": "PrimitiveFloat",
            "inputs": {"value": 5},
        },
        "6343": {
            "class_type": "PrimitiveFloat",
            "inputs": {"value": 24},
        },
        "6344": {
            "class_type": "ComfyMathExpression",
            "inputs": {
                "expression": "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17",
                "values.a": ["6342", 0],
            },
        },
        "6345": {
            "class_type": "ResolutionSelector",
            "inputs": {
                "aspect_ratio": "16:9 (Widescreen)",
                "megapixels": ["6341", 0],
                "multiple": 32,
            },
        },
        "6346": {
            "class_type": "StringReplace",
            "inputs": {
                "string": ["6350", 0],
                "find": "[TARGET_PERSON]",
                "replace": DEFAULT_TARGET_PERSON,
            },
        },
        "6348": {
            "class_type": "ComfyMathExpression",
            "inputs": {
                "expression": "max(5, a - ((a - 5) % 17))",
                "values.a": ["6613", 1],
            },
        },
        "6349": {
            "class_type": "ImageResizeKJv2",
            "inputs": {
                "image": ["6614", 0],
                "width": 1024,
                "height": 1024,
                "upscale_method": "lanczos",
                "keep_proportion": "resize",
                "pad_color": "0, 0, 0",
                "crop_position": "center",
                "divisible_by": 32,
                "device": "cpu",
            },
        },
        "6350": {
            "class_type": "PrimitiveStringMultiline",
            "inputs": {"value": DEFAULT_SWAP_PROMPT},
        },
        "6373": {
            "class_type": "MiniMaxH3MemoryEfficientSageAttentionPatch",
            "inputs": {"model": ["6374", 0]},
        },
        "6374": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["6615", 0], "lora_name": LOCAL_REALISM_LORA, "strength_model": 0},
        },
        "6432": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["213", 1], "vae": ["207", 0]},
        },
        "6516": {
            "class_type": "ImageResizeKJv2",
            "inputs": {
                "image": ["6613", 0],
                "width": ["6345", 0],
                "height": ["6345", 1],
                "upscale_method": "lanczos",
                "keep_proportion": "pad",
                "pad_color": "0, 0, 0",
                "crop_position": "center",
                "divisible_by": 2,
                "device": "cpu",
            },
        },
        "6541": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["6432", 0],
                "audio": ["209", 0],
                "frame_rate": 24,
                "loop_count": 0,
                "filename_prefix": "CharacterLock/motion_swap",
                "format": "video/h264-mp4",
                "pingpong": False,
                "save_output": True,
            },
        },
        "6613": {
            "class_type": "VHS_LoadVideo",
            "inputs": {
                "video": "characterlock_motion_reference.mp4",
                "force_rate": ["6343", 0],
                "custom_width": 0,
                "custom_height": 0,
                "frame_load_cap": ["6344", 1],
                "skip_first_frames": 0,
                "select_every_nth": 1,
                "format": "AnimateDiff",
            },
        },
        "6614": {
            "class_type": "LoadImage",
            "inputs": {"image": "characterlock_identity_reference.png"},
        },
        "6615": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["6122", 0], "lora_name": LOCAL_SWAP_LORA, "strength_model": 1},
        },
        "6617": {
            "class_type": "MiniMaxH3ReferenceToVideo",
            "inputs": {
                "clip": ["216", 0],
                "vae": ["207", 0],
                "audio_vae": ["208", 0],
                "ref_images.ref_image_0": ["6349", 0],
                "ref_videos.ref_video_0": ["6516", 0],
                "prompt": ["6346", 0],
                "width": ["6345", 0],
                "height": ["6345", 1],
                "length": ["6348", 1],
                "ref_image_size": "match",
            },
        },
    }

    mapping = {
        "parameters": {
            "identity_image": parameter(
                6614, "image", "image", "string", required=True,
                label="Referência da personagem (<Picture 1>)",
                description="Imagem aprovada da personagem enviada ao ComfyUI como <Picture 1>.",
            ),
            "source_video": parameter(
                6613, "video", "video", "string", required=True,
                label="Vídeo de movimento (<Video 1>)",
                description="Vídeo MP4 de referência de movimento enviado ao ComfyUI como <Video 1>.",
            ),
            "target_person": parameter(
                6346, "replace", "other", "string", required=True,
                default=DEFAULT_TARGET_PERSON,
                label="Pessoa a substituir em <Video 1>",
                description="Identifique qual pessoa do vídeo original será substituída (ex.: homem da direita ou homem da esquerda).",
            ),
            "swap_prompt": parameter(
                6350, "value", "prompt", "string", required=True,
                default=DEFAULT_SWAP_PROMPT,
                label="Instrução de Character Swap",
                description="Use [TARGET_PERSON] para inserir automaticamente a pessoa escolhida na instrução de substituição entre <Video 1> e <Picture 1>.",
            ),
            "duration_seconds": parameter(
                6342, "value", "duration", default=5, min=0.5, max=10.0,
                label="Duração (segundos)",
                description="Limitado a 5 s no teste (sincronizado automaticamente com os quadros reais do vídeo na quantização 5 + 17n do MiniMax H3).",
            ),
            "megapixels": parameter(
                6341, "value", "other", default=0.5, min=0.2, max=2.0,
                label="Resolução (megapixels)",
            ),
            "aspect_ratio": parameter(
                6345, "aspect_ratio", "other", "enum",
                default="16:9 (Widescreen)",
                choices=[
                    "1:1 (Square)",
                    "2:3 (Portrait Photo)",
                    "3:2 (Photo)",
                    "3:4 (Portrait Standard)",
                    "4:3 (Standard)",
                    "9:16 (Portrait Widescreen)",
                    "16:9 (Widescreen)",
                    "21:9 (Ultrawide)",
                ],
                label="Proporção",
            ),
            "swap_strength": parameter(
                6615, "strength_model", "lora", default=1, min=0, max=2,
                label="Força da LoRA Character Swap",
            ),
            "realism_strength": parameter(
                6374, "strength_model", "lora", default=0, min=0, max=2,
                label="Força da LoRA Realismo",
            ),
            "turbo_strength": parameter(
                6122, "strength_model", "lora", default=1, min=0, max=2,
                label="Força da LoRA Turbo",
            ),
            "steps": parameter(
                212, "steps", "other", "integer", default=8, min=1, max=50,
                label="Steps",
            ),
            "seed": parameter(
                6327, "seed", "seed", "integer", default=43, min=0, max=9007199254740991,
                label="Seed",
            ),
        },
        "output_nodes": ["6541"],
    }

    provenance = {
        "source_file": str(source_path),
        "source_sha256": digest,
        "source_unchanged": source_path.read_bytes() == raw,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "source_node_count": len(ui["nodes"]),
        "prepared_node_count": len(graph),
        "active_output_node": "6541",
        "resolved_virtual_node_ids": [6317, 6318, 6320, 6324, 6325, 6347, 6360, 6361, 6362, 6365, 6366, 6367, 6428, 6433, 6487, 6488, 6611],
        "omitted_note_node_ids": [6340, 6532],
        "bypassed_unavailable_attention_node": {
            "node_id": 6616,
            "class_type": "VedaSparseAttention",
            "reason": "VedaSparseAttention custom node and predictor weights are not installed; MiniMaxH3MemoryEfficientSageAttentionPatch (6373) and PathchSageAttentionKJ (6123) remain active in the model chain.",
        },
        "local_replacements": [
            {"node_id": "207", "source": "minimax-h3\\minimax_h3_video_vae_fp16.safetensors", "local": LOCAL_VIDEO_VAE},
            {"node_id": "208", "source": "minimax-h3\\minimax_h3_audio_vae_fp32.safetensors", "local": LOCAL_AUDIO_VAE},
            {"node_id": "215", "source": "minimax-h3\\Minimax-h3_Singularity_ref2va_v1.3_int8.safetensors", "local": LOCAL_UNET},
            {"node_id": "216", "source_class": "CLIPLoader", "local_class": "CLIPLoaderGGUF", "local": LOCAL_CLIP, "type": "minimax"},
            {"node_id": "6122", "source": "minimax-h3\\minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors", "local": LOCAL_TURBO_LORA},
            {"node_id": "6615", "source": "minimax-h3\\h3_character_swap_pro4500_1000.safetensors", "local": LOCAL_SWAP_LORA},
            {"node_id": "6374", "source": "minimax-h3\\h3-realism-people-t2v-i2v-r2v(r34l1sm).safetensors", "local": LOCAL_REALISM_LORA, "default_strength": 0},
            {"node_id": "6346", "source_class": "StringConcatenate", "local_class": "StringReplace", "reason": "Remove r34l1sm portrait trigger prefix and inject explicit [TARGET_PERSON] selector."},
            {"node_id": "6348", "class_type": "ComfyMathExpression", "reason": "Synchronize MiniMaxH3ReferenceToVideo.length with actual loaded VHS_LoadVideo frame_count rounded down to 17k+5."},
            {"node_id": "6349", "input": "keep_proportion", "source": "crop", "local": "resize", "reason": "Prevent center-cropping portrait <Picture 1> into 16:9 widescreen, which cut off the character's head."},
            {"node_id": "6613", "source_class": "VHS_LoadVideoPath", "local_class": "VHS_LoadVideo"},
            {"node_id": "6614", "source_class": "VHS_LoadImagePath", "local_class": "LoadImage"},
            {"node_id": "6349,6516", "input": "upscale_method", "source": "nvidia_rtx_vsr", "local": "lanczos", "reason": "Avoid VSR failure when downscaling 1080p inputs on CPU tensor path."},
        ],
    }
    return graph, mapping, provenance


def validate(graph, mapping, info):
    sys.path.insert(0, str(PROJECT / "backend"))
    from app.workflows import WorkflowAdapter, supported_video_input
    adapter = WorkflowAdapter(graph, mapping)
    report = adapter.validate(info, allow_missing={"identity_image", "source_video"})
    if not supported_video_input(graph, mapping["parameters"]["source_video"]):
        report["errors"].append({"code": "video_input_unsupported", "message": "source_video is not a valid VHS_LoadVideo.video upload input."})
    report["valid"] = not report["errors"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--studio-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args()
    graph, mapping, provenance = prepare()
    info = request(args.comfy_url, "/object_info")
    report = validate(graph, mapping, info)
    provenance["preflight_valid"] = report["valid"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for prefix in ("local-installed", "minimax-h3-motion-swap.local-installed"):
        for suffix, value in (("api", graph), ("mapping", mapping), ("provenance", provenance), ("validation", report)):
            (OUTPUT / f"{prefix}.{suffix}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    summary = {"prepared_nodes": len(graph), "preflight_valid": report["valid"], "errors": report["errors"], "registered": False}
    if args.register and report["valid"]:
        checksum = hashlib.sha256(json.dumps(graph, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        existing = next((row for row in request(args.studio_url, "/workflows?module=motion_swap") if row["sha256"] == checksum and row["mapping"] == mapping), None)
        registered = existing or request(args.studio_url, "/workflows", {"name": NAME, "module": "motion_swap", "workflow": graph, "mapping": mapping})
        remote = request(args.studio_url, f"/workflows/{registered['id']}/validate", {})
        summary.update(registered=True, workflow_id=registered["id"], studio_preflight_valid=remote["valid"], studio_errors=remote["errors"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
