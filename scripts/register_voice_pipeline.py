"""Register and validate a reviewed, local-only OmniVoice API pipeline; never generate."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
import urllib.error
import urllib.request


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "workflows" / "originals" / "d1578ad80c66-Omini_voice.json"
SOURCE_SHA256 = "d1578ad80c66c84c34ab98e25a534c1e7a0bc74f6627ff77590bd7aab90032ce"
NAME = "OmniVoice - narração local (auto voice)"
CLASSES = {"1": "OmniVoiceModelLoader", "14": "OmniVoiceGenerate", "6": "PreviewAudio"}
MODEL_FILES = (
    "config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
    "audio_tokenizer/config.json", "audio_tokenizer/model.safetensors",
    "audio_tokenizer/preprocessor_config.json",
)


def loopback_origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise argparse.ArgumentTypeError("Only a plain loopback HTTP origin is allowed.")
    return value.rstrip("/")


def request(origin, path, payload=None):
    # Only loopback URLs are accepted by the CLI; no Hub/model downloads are used.
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    req = urllib.request.Request(origin + path, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Local API returned {exc.code}: {detail}") from exc


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def prepare(comfy_origin, portable):
    content = SOURCE.read_bytes()
    if hashlib.sha256(content).hexdigest() != SOURCE_SHA256:
        raise ValueError("The preserved original changed; review it before adapting.")
    original = json.loads(content)
    nodes = {str(node["id"]): node["type"] for node in original["nodes"]}
    if any(nodes.get(node_id) != name for node_id, name in CLASSES.items()):
        raise ValueError("Expected reviewed node IDs/classes are absent from the original.")
    links = {tuple(link[1:5]) for link in original["links"]}
    if not {(1, 0, 14, 0), (14, 0, 6, 0)}.issubset(links):
        raise ValueError("The preserved model and audio output connections changed.")

    model_root = portable / "ComfyUI" / "models" / "omnivoice"
    installed = {}
    for relative in MODEL_FILES:
        path = model_root / relative
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Required local model file missing: {path}. Downloads are forbidden.")
        if path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))
        installed[relative] = path.stat().st_size

    schemas = {}
    for class_name in CLASSES.values():
        response = request(comfy_origin, "/object_info/" + class_name)
        schemas[class_name] = response[class_name]
    loader = schemas["OmniVoiceModelLoader"]["input"]["required"]
    generate = schemas["OmniVoiceGenerate"]["input"]
    if "cuda:0" not in loader["device"][0] or "float16" not in loader["dtype"][0]:
        raise ValueError("The installed loader no longer supports the reviewed device/dtype.")
    if "auto_voice" not in generate["required"]["mode"][0]:
        raise ValueError("Installed generator does not expose auto_voice.")
    languages = generate["optional"]["language"][0]
    if not isinstance(languages, list) or "Portuguese" not in languages:
        raise ValueError("The installed generator does not expose the expected language choices.")
    if not schemas["PreviewAudio"].get("output_node"):
        raise ValueError("PreviewAudio is not an executable output node in this installation.")

    # This is an explicit, reviewed API adaptation using named live inputs.
    # The original UI widget positions are never converted or modified.
    workflow = {
        "1": {"class_type": "OmniVoiceModelLoader", "inputs": {"device": "cuda:0", "dtype": "float16", "compile": False}},
        "14": {"class_type": "OmniVoiceGenerate", "inputs": {
            "model": ["1", 0], "text": "Olá. Esta é uma demonstração de voz local.",
            "mode": "auto_voice", "language": "Portuguese", "guidance_scale": 2.0,
            "speed": 1.0, "num_step": 32, "seed": 42,
        }},
        "6": {"class_type": "PreviewAudio", "inputs": {"audio": ["14", 0]}},
    }
    parameters = {
        "text": {"node_id": "14", "input": "text", "type": "string", "kind": "prompt", "required": True,
                 "label": "Texto da narração", "description": "Texto falado; preenchido pelo editor de narração do Voice Studio."},
        "language": {"node_id": "14", "input": "language", "type": "enum", "kind": "other", "required": True,
                     "default": "Portuguese", "choices": languages, "label": "Idioma", "description": "Idioma real exposto pelo OmniVoice instalado."},
    }
    for name, value, kind, label in (("speed", 1.0, "other", "Velocidade"), ("num_step", 32, "other", "Etapas de síntese"), ("seed", 42, "seed", "Semente")):
        definition, constraints = generate["optional"][name]
        parameters[name] = {"node_id": "14", "input": name, "type": "integer" if definition == "INT" else "number",
                            "kind": kind, "required": True, "default": value, "label": label,
                            **{bound: constraints[bound] for bound in ("min", "max") if bound in constraints}}
    mapping = {"parameters": parameters, "output_nodes": ["6"]}
    return workflow, mapping, schemas, model_root, installed


def register(args):
    workflow, mapping, schemas, model_root, installed = prepare(args.comfy, args.portable.resolve())
    destination = PROJECT / "workflows" / "local"
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "omnivoice-auto-voice.api.json", workflow)
    write_json(destination / "omnivoice-auto-voice.mapping.json", mapping)
    write_json(destination / "omnivoice-auto-voice.schemas.json", schemas)
    canonical = json.dumps(workflow, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    graph_hash = hashlib.sha256(canonical).hexdigest()
    existing = request(args.studio, "/api/workflows?module=voice")
    matching = [item for item in existing if item.get("sha256") == graph_hash and item.get("module") == "voice"]
    registered = None
    for item in matching:
        candidate = request(args.studio, "/api/workflows/" + item["id"])
        if candidate["mapping"] == mapping:
            registered = candidate
            break
    created = registered is None
    if created:
        registered = request(args.studio, "/api/workflows", {"name": NAME, "module": "voice", "workflow": workflow, "mapping": mapping})
    report = request(args.studio, "/api/workflows/" + registered["id"] + "/validate", {})
    write_json(destination / "omnivoice-auto-voice.registration.json", {
        "id": registered["id"], "created": created, "validation": report,
        "preserved_original": str(SOURCE.relative_to(PROJECT)), "source_sha256": SOURCE_SHA256,
        "model_directory": str(model_root), "local_model_files": installed,
        "mode": "auto_voice", "download_policy": "forbidden; local files checked before registration",
        "execution_requested": False,
    })
    notes = f"""# OmniVoice local: auto_voice

Workflow registrado: `{registered['id']}`. Validação: `{report['valid']}`.
Origem preservada: `{SOURCE.relative_to(PROJECT)}`.
SHA-256 original: `{SOURCE_SHA256}`; conferido antes e depois do registro.

Cópia API revisada: IDs reais 1 (OmniVoiceModelLoader) → 14 (OmniVoiceGenerate) → 6 (PreviewAudio).
O nó LoadAudio 2 e a ligação de ref_audio foram omitidos nesta cópia. O original permaneceu intacto.
Modo fixo: auto_voice, sem clonagem, sem referência de pessoa e sem roster de speakers.
Loader fixo: cuda:0, float16, compile=false. Guidance fixo: 2.0.
Entradas públicas: text (kind prompt), language, speed, num_step, seed. Saída pública: nó 6.
Idioma padrão Portuguese; opções capturadas do schema instalado: {', '.join(mapping['parameters']['language']['choices'])}.

Modelos somente locais em `{model_root}`. O script exige todos os arquivos locais antes de registrar.
Nenhum download, instalação, POST /prompt ou POST /api/jobs foi executado pelo script.
Para bloquear também qualquer fallback de download durante geração futura, inicie o processo ComfyUI com
HF_HUB_OFFLINE=1 e TRANSFORMERS_OFFLINE=1. Essas variáveis precisam estar no processo que executa os nós;
configurá-las apenas no Studio ou neste script não modifica uma instância ComfyUI já aberta.

Preflight confirma schemas, conexões e entradas; ainda não confirma carga do modelo, VRAM nem qualidade.
PreviewAudio escreve uma prévia temporária que o worker do Studio poderá importar após execução real.
Reproduzir: .venv\\Scripts\\python.exe scripts\\register_voice_pipeline.py
O script reutiliza um registro idêntico e revalida; nunca solicita geração.
"""
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("The preserved original changed during registration.")
    (destination / "omnivoice-auto-voice.notes.md").write_text(notes, encoding="utf-8")
    print(json.dumps({"workflow_id": registered["id"], "created": created, "valid": report["valid"],
                      "errors": report["errors"], "output_nodes": mapping["output_nodes"],
                      "parameters": list(mapping["parameters"]), "execution_requested": False}, ensure_ascii=False, indent=2))
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--studio", type=loopback_origin, default="http://127.0.0.1:8000")
    parser.add_argument("--comfy", type=loopback_origin, default="http://127.0.0.1:8188")
    parser.add_argument("--portable", type=Path, default=Path.home() / "ComfyUI_windows_portable")
    register(parser.parse_args())
