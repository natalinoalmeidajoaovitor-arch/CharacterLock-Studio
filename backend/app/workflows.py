"""Explicit, immutable adapters for ComfyUI API-format prompts.

UI workflow graphs may be inspected, but only an API export can be executed.
Discovery is advisory: it never creates a mapping or guesses widget positions.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any


class WorkflowError(ValueError):
    def __init__(self, message: str, details: list[dict] | None = None, code: str = "workflow_invalid"):
        super().__init__(message)
        self.message = message
        self.details = details or []
        self.code = code


def workflow_format(workflow: Any) -> str:
    if not isinstance(workflow, dict) or not workflow:
        return "invalid"
    if isinstance(workflow.get("nodes"), list):
        return "ui"
    if all(isinstance(node_id, str) and isinstance(node, dict)
           and isinstance(node.get("class_type"), str) and node["class_type"]
           and isinstance(node.get("inputs"), dict)
           for node_id, node in workflow.items()):
        return "api"
    return "invalid"


def _issue(code: str, message: str, **context: Any) -> dict:
    return {"code": code, "message": message, **context}


def _link(value: Any) -> bool:
    return (isinstance(value, list) and len(value) == 2
            and isinstance(value[0], (str, int)) and not isinstance(value[0], bool)
            and isinstance(value[1], int) and not isinstance(value[1], bool))


def _finite_number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) or isinstance(value, float) and math.isfinite(value)


def supported_video_input(workflow: dict, spec: dict) -> bool:
    """Only the inspected input-root VHS MP4 loader has a staging contract."""
    if (not isinstance(workflow, dict) or not isinstance(spec, dict)
            or not isinstance(spec.get("node_id"), str)):
        return False
    node = workflow.get(spec.get("node_id"))
    return (isinstance(node, dict) and node.get("class_type") == "VHS_LoadVideo"
            and isinstance(node.get("inputs"), dict) and "video" in node["inputs"]
            and spec.get("input") == "video" and spec.get("type") == "string"
            and spec.get("kind") == "video" and spec.get("required") is True
            and "serializer" not in spec and "default" not in spec)


def _unsafe_file_value(name: str, value: Any) -> bool:
    field = name.lower()
    file_fields = {"image", "images", "audio", "video", "mask", "ref_image", "ref_audio", "ref_video", "reference_image", "reference_audio",
                   "start_image", "end_image", "source_video", "ckpt_name", "unet_name", "vae_name", "clip_name", "lora_name", "model_name", "filename_prefix"}
    if not isinstance(value, str) or not (field in file_fields or "path" in field or "directory" in field or "filename" in field):
        return False
    normalized = value.replace("\\", "/")
    return ("\x00" in value or ":" in value or PureWindowsPath(value).is_absolute()
            or PurePosixPath(normalized).is_absolute() or ".." in PurePosixPath(normalized).parts)


def _kinds(name: str, class_type: str = "", declared_type: str = "") -> list[str]:
    text = name.lower()
    types = declared_type.upper()
    kinds: list[str] = []
    if "lora" in text:
        kinds.append("lora")
    if text in {"model", "model_name", "ckpt_name", "unet_name", "vae_name", "clip_name", "checkpoint"}:
        kinds.append("model")
    if "negative" in text and ("prompt" in text or "text" in text):
        kinds.append("negative_prompt")
    elif "prompt" in text or text in {"text", "ref_text", "caption"}:
        kinds.append("prompt")
    for kind, names in {
        "image": {"image", "images", "image_path", "ref_image", "reference_image", "start_image", "end_image"},
        "video": {"video", "video_path", "source_video", "ref_video"},
        "audio": {"audio", "audio_path", "ref_audio", "reference_audio"},
        "width": {"width"}, "height": {"height"},
        "seed": {"seed", "noise_seed"}, "duration": {"duration", "duration_seconds", "seconds", "num_frames", "length"},
    }.items():
        if text in names or (kind.upper() in {"IMAGE", "VIDEO", "AUDIO"} and types == kind.upper()):
            kinds.append(kind)
    return kinds


class WorkflowAdapter:
    PARAMETER_TYPES = {"string", "integer", "number", "boolean", "enum"}
    KINDS = {"prompt", "negative_prompt", "model", "lora", "image", "audio", "video", "width", "height", "seed", "duration", "other"}
    SPEC_KEYS = {"node_id", "input", "type", "required", "default", "label", "description", "kind", "choices", "min", "max", "serializer"}

    def __init__(self, workflow: dict, mapping: dict | None = None):
        self._workflow = deepcopy(workflow)
        self._mapping = deepcopy(mapping) if mapping is not None else {"parameters": {}, "output_nodes": []}
        self.format = workflow_format(self._workflow)
        self._mapping_errors = self._check_mapping()

    @property
    def workflow(self) -> dict:
        return deepcopy(self._workflow)

    @property
    def mapping(self) -> dict:
        return deepcopy(self._mapping)

    def _check_mapping(self) -> list[dict]:
        mapping = self._mapping
        if not isinstance(mapping, dict):
            return [_issue("mapping_invalid", "Mapping must be an object.")]
        errors = []
        unknown = set(mapping) - {"parameters", "output_nodes"}
        if unknown:
            errors.append(_issue("mapping_unknown_fields", "Unknown mapping fields.", fields=sorted(unknown)))
        parameters = mapping.get("parameters", {})
        if not isinstance(parameters, dict):
            errors.append(_issue("mapping_parameters_invalid", "parameters must be an object."))
            parameters = {}
        targets: set[tuple[str, str]] = set()
        for name, spec in parameters.items():
            if not isinstance(name, str) or not name or not isinstance(spec, dict):
                errors.append(_issue("mapping_parameter_invalid", "Every parameter needs a nonempty name and object specification.", parameter=str(name)))
                continue
            if set(spec) - self.SPEC_KEYS:
                errors.append(_issue("mapping_unknown_fields", "Unknown parameter fields.", parameter=name, fields=sorted(set(spec) - self.SPEC_KEYS)))
            if not isinstance(spec.get("node_id"), str) or not isinstance(spec.get("input"), str) or not spec.get("input"):
                errors.append(_issue("mapping_target_invalid", "node_id and input must be explicit strings.", parameter=name))
                continue
            target = (spec["node_id"], spec["input"])
            if target in targets:
                errors.append(_issue("mapping_duplicate_target", "Two parameters cannot write the same node input.", parameter=name))
            targets.add(target)
            if not isinstance(spec.get("type"), str) or spec["type"] not in self.PARAMETER_TYPES:
                errors.append(_issue("mapping_type_invalid", "Unsupported parameter type.", parameter=name))
            if "required" in spec and not isinstance(spec["required"], bool):
                errors.append(_issue("mapping_required_invalid", "required must be boolean.", parameter=name))
            if "kind" in spec and (not isinstance(spec["kind"], str) or spec["kind"] not in self.KINDS):
                errors.append(_issue("mapping_kind_invalid", "Unsupported parameter kind.", parameter=name))
            if "serializer" in spec:
                node = self._workflow.get(spec["node_id"], {}) if self.format == "api" else {}
                if (spec["serializer"] != "h3_media_state" or node.get("class_type") != "MiniMaxH3MediaLoader"
                        or spec["input"] != "media_state" or spec.get("type") != "string" or spec.get("kind") != "image"
                        or not spec.get("required") or "default" in spec):
                    errors.append(_issue("mapping_serializer_invalid", "h3_media_state requires an explicitly required image:string MiniMaxH3MediaLoader.media_state without a default.", parameter=name))
            for field in ("label", "description"):
                if field in spec and not isinstance(spec[field], str):
                    errors.append(_issue("mapping_metadata_invalid", f"{field} must be a string.", parameter=name))
            if "choices" in spec and (not isinstance(spec["choices"], list) or not spec["choices"]):
                errors.append(_issue("mapping_choices_invalid", "choices must be a nonempty array.", parameter=name))
            if spec.get("type") == "enum" and not spec.get("choices"):
                errors.append(_issue("mapping_choices_required", "enum parameters require explicit choices.", parameter=name))
            for bound in ("min", "max"):
                value = spec.get(bound)
                if bound in spec and not _finite_number(value):
                    errors.append(_issue("mapping_bounds_invalid", f"{bound} must be finite numeric.", parameter=name))
            if isinstance(spec.get("min"), (int, float)) and isinstance(spec.get("max"), (int, float)) and spec["min"] > spec["max"]:
                errors.append(_issue("mapping_bounds_invalid", "min cannot exceed max.", parameter=name))
            if self.format == "api":
                node = self._workflow.get(spec["node_id"])
                if node is None or spec["input"] not in node["inputs"]:
                    errors.append(_issue("mapping_target_missing", "Mapped input does not exist in the API export.", parameter=name, node_id=spec["node_id"], input=spec["input"]))
                elif isinstance(node["inputs"][spec["input"]], list):
                    errors.append(_issue("mapping_link_rewrite", "Linked inputs cannot be replaced by user parameters.", parameter=name))
            if "default" in spec:
                errors.extend(self._value_errors(name, spec, spec["default"]))
        outputs = mapping.get("output_nodes", [])
        if not isinstance(outputs, list) or any(not isinstance(v, str) for v in outputs):
            errors.append(_issue("mapping_outputs_invalid", "output_nodes must contain actual node ID strings."))
        elif len(outputs) != len(set(outputs)):
            errors.append(_issue("mapping_outputs_duplicate", "output_nodes cannot contain duplicate IDs."))
        elif self.format == "api":
            for node_id in outputs:
                if node_id not in self._workflow:
                    errors.append(_issue("mapping_output_missing", "Output node does not exist in the API export.", node_id=node_id))
        return errors

    @staticmethod
    def _value_errors(name: str, spec: dict, value: Any) -> list[dict]:
        expected = spec.get("type")
        numeric = _finite_number(value)
        matches = {"string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool),
                   "number": numeric, "boolean": isinstance(value, bool),
                   "enum": isinstance(value, (str, bool)) or numeric}
        if not isinstance(expected, str) or not matches.get(expected, False):
            return [_issue("parameter_type", f"Parameter must have type {expected}.", parameter=name)]
        errors = []
        if "choices" in spec and isinstance(spec["choices"], list) and value not in spec["choices"]:
            errors.append(_issue("parameter_choice", "Parameter is outside its allowed choices.", parameter=name))
        if numeric:
            for bound, operator in (("min", lambda a, b: a < b), ("max", lambda a, b: a > b)):
                if isinstance(spec.get(bound), (int, float)) and operator(value, spec[bound]):
                    errors.append(_issue("parameter_range", f"Parameter violates {bound}.", parameter=name, limit=spec[bound]))
        if spec.get("required") and isinstance(value, str) and not value.strip():
            errors.append(_issue("parameter_required", "Required parameter cannot be empty.", parameter=name))
        return errors

    def validate_parameters(self, parameters: dict, allow_missing: set[str] | None = None) -> dict:
        errors = deepcopy(self._mapping_errors)
        if not isinstance(parameters, dict):
            return {"valid": False, "errors": errors + [_issue("parameters_invalid", "Parameters must be an object.")], "warnings": []}
        specs = self._mapping.get("parameters", {}) if isinstance(self._mapping, dict) else {}
        if not isinstance(specs, dict):
            specs = {}
        for name in parameters:
            if name not in specs:
                errors.append(_issue("parameter_unknown", "Parameter is not in the explicit mapping allowlist.", parameter=name))
        for name, spec in specs.items():
            if not isinstance(spec, dict):
                continue
            if name in parameters:
                errors.extend(self._value_errors(name, spec, parameters[name]))
                if spec.get("serializer") == "h3_media_state":
                    try:
                        items = json.loads(parameters[name])
                        if (not isinstance(items, list) or not 1 <= len(items) <= 9
                                or any(not isinstance(item, dict) or set(item) != {"kind", "file", "enabled"}
                                       or item["kind"] != "picture" or item["enabled"] is not True
                                       or not isinstance(item["file"], str) or not item["file"]
                                       or _unsafe_file_value("image", item["file"])
                                       or "[" in item["file"] or "]" in item["file"] for item in items)):
                            raise ValueError()
                    except (TypeError, ValueError, KeyError):
                        errors.append(_issue("parameter_media_state_invalid", "H3 picture state must contain 1..9 uploaded relative image filenames.", parameter=name))
            elif "default" not in spec and spec.get("required") and name not in (allow_missing or set()):
                errors.append(_issue("parameter_required", "Required parameter is missing.", parameter=name))
        return {"valid": not errors, "errors": errors, "warnings": []}

    def inspect(self) -> dict:
        nodes, candidates = [], []
        raw_nodes = self._workflow.items() if self.format == "api" else ((str(n.get("id", "")), n) for n in self._workflow.get("nodes", []) if isinstance(n, dict)) if self.format == "ui" else []
        for node_id, node in raw_nodes:
            class_type = node.get("class_type", node.get("type", ""))
            if not isinstance(class_type, str):
                class_type = ""
            fields = []
            raw_inputs = node.get("inputs", {})
            if self.format == "api":
                inputs = ((name, value, "", _link(value)) for name, value in raw_inputs.items())
            else:
                inputs = ((field.get("name", ""), None, field.get("type", ""), field.get("link") is not None) for field in raw_inputs if isinstance(field, dict)) if isinstance(raw_inputs, list) else []
            for name, value, declared, linked in inputs:
                if not isinstance(name, str) or not isinstance(declared, str):
                    continue
                kinds = _kinds(name, class_type, declared)
                fields.append({"name": name, "value_type": declared or type(value).__name__, "linked": linked, "categories": kinds})
                for kind in kinds:
                    candidates.append({"node_id": node_id, "input": name, "kind": kind, "linked": linked})
            nodes.append({"node_id": node_id, "class_type": class_type, "inputs": fields,
                          "widget_values_present": bool(node.get("widgets_values")) if self.format == "ui" else False})
        output_ids = self._mapping.get("output_nodes", []) if isinstance(self._mapping, dict) else []
        return {"format": self.format, "executable": self.format == "api" and not self._mapping_errors and bool(output_ids),
                "node_count": len(nodes), "nodes": nodes, "candidates": candidates, "output_nodes": deepcopy(output_ids),
                "mapping_errors": deepcopy(self._mapping_errors),
                "notes": ["UI widget positions are not mapped. Export API format from ComfyUI."] if self.format == "ui" else []}

    def _parameterized(self, parameters: dict | None) -> dict:
        prompt = deepcopy(self._workflow)
        specs = self._mapping.get("parameters", {}) if isinstance(self._mapping, dict) else {}
        if self.format != "api" or self._mapping_errors or not isinstance(specs, dict):
            return prompt
        for name, spec in specs.items():
            if parameters is not None and name in parameters:
                prompt[spec["node_id"]]["inputs"][spec["input"]] = deepcopy(parameters[name])
            elif "default" in spec:
                prompt[spec["node_id"]]["inputs"][spec["input"]] = deepcopy(spec["default"])
        return prompt

    def validate(self, object_info: dict, parameters: dict | None = None, allow_missing: set[str] | None = None) -> dict:
        errors = deepcopy(self._mapping_errors)
        warnings, outputs = [], []
        if self.format != "api":
            errors.append(_issue("api_export_required", "Execution requires an API-format prompt export. UI graphs can only be inspected."))
            return {"valid": False, "errors": errors, "warnings": warnings, "outputs": outputs}
        if parameters is not None:
            parameter_report = self.validate_parameters(parameters, allow_missing=allow_missing)
            errors = parameter_report["errors"]
            if not isinstance(parameters, dict):
                return {"valid": False, "errors": errors, "warnings": warnings, "outputs": outputs}
        if not isinstance(object_info, dict) or not object_info:
            errors.append(_issue("object_info_unavailable", "Live ComfyUI /object_info is required before execution."))
            return {"valid": False, "errors": errors, "warnings": warnings, "outputs": outputs}
        prompt = self._parameterized(parameters)
        pending_media = {
            (spec.get("node_id"), spec.get("input"))
            for name, spec in self._mapping.get("parameters", {}).items()
            if isinstance(spec, dict) and isinstance(spec.get("kind"), str) and spec["kind"] in {"image", "audio", "video"}
            and ((parameters is None and spec.get("required") and "default" not in spec)
                 or (isinstance(parameters, dict) and name in (allow_missing or set()) and name not in parameters))
        } if not self._mapping_errors and isinstance(self._mapping, dict) and isinstance(self._mapping.get("parameters", {}), dict) else set()
        edges: dict[str, list[str]] = {node_id: [] for node_id in prompt}
        for node_id, node in prompt.items():
            schema = object_info.get(node["class_type"])
            if not isinstance(schema, dict):
                errors.append(_issue("node_not_installed", "Node class is not exposed by this ComfyUI instance.", node_id=node_id, class_type=node["class_type"]))
                continue
            input_schema = schema.get("input", {})
            if not isinstance(input_schema, dict):
                errors.append(_issue("node_schema_invalid", "Unsupported node input schema.", node_id=node_id))
                continue
            required = input_schema.get("required", {})
            optional = input_schema.get("optional", {})
            if not isinstance(required, dict) or not isinstance(optional, dict):
                errors.append(_issue("node_schema_invalid", "Unsupported node input schema.", node_id=node_id))
                continue
            required = dict(required)
            known = {**required, **optional}
            # V3 autogrow inputs serialize as explicit dotted names, not as a
            # literal container. Only expand names/types advertised by the
            # installed schema; malformed or complex templates fail closed.
            for root_name, definition in list(known.items()):
                if not isinstance(definition, (list, tuple)) or len(definition) < 2 or definition[0] != "COMFY_AUTOGROW_V3":
                    continue
                options = definition[1] if isinstance(definition[1], dict) else {}
                template = options.get("template", {})
                children = template.get("input", {}).get("required", {}) if isinstance(template, dict) and isinstance(template.get("input"), dict) else {}
                names = template.get("names", []) if isinstance(template, dict) else []
                minimum = template.get("min", 1) if isinstance(template, dict) else 1
                prefix = template.get("prefix") if isinstance(template, dict) else None
                maximum = template.get("max") if isinstance(template, dict) else None
                if (not names and isinstance(prefix, str) and prefix and isinstance(maximum, int)
                        and not isinstance(maximum, bool) and 0 < maximum <= 512):
                    names = [f"{prefix}{index}" for index in range(maximum)]
                if (not isinstance(children, dict) or len(children) != 1 or not isinstance(names, list)
                        or not names or any(not isinstance(name, str) or not name for name in names)
                        or not isinstance(minimum, int) or isinstance(minimum, bool) or not 0 <= minimum <= len(names)):
                    continue
                child_definition = next(iter(children.values()))
                expanded = {f"{root_name}.{name}": child_definition for name in names}
                known.update(expanded)
                required.pop(root_name, None)
                present = sum(name in node["inputs"] for name in expanded)
                if present < minimum:
                    errors.append(_issue("input_required", "Autogrow input requires more connected values.", node_id=node_id, input=root_name, minimum=minimum))
            for name in required:
                if name not in node["inputs"]:
                    errors.append(_issue("input_required", "Required node input is absent.", node_id=node_id, input=name))
            for name, value in node["inputs"].items():
                if name not in known:
                    errors.append(_issue("input_unknown", "Input is absent from the installed node schema.", node_id=node_id, input=name))
                    continue
                definition = known[name]
                if not isinstance(definition, (list, tuple)) or not definition:
                    errors.append(_issue("input_schema_invalid", "Unsupported input schema.", node_id=node_id, input=name))
                    continue
                expected = definition[0]
                constraints = definition[1] if len(definition) > 1 and isinstance(definition[1], dict) else {}
                if isinstance(value, list):
                    if not _link(value):
                        errors.append(_issue("link_invalid", "Connections require [actual_node_id, output_index].", node_id=node_id, input=name))
                        continue
                    upstream, slot = str(value[0]), value[1]
                    if upstream not in prompt:
                        errors.append(_issue("link_node_missing", "Connected node does not exist.", node_id=node_id, input=name, source_node=upstream))
                        continue
                    edges[node_id].append(upstream)
                    source_schema = object_info.get(prompt[upstream]["class_type"], {})
                    if not isinstance(source_schema, dict):
                        source_schema = {}
                    source_outputs = source_schema.get("output", [])
                    if not isinstance(source_outputs, (list, tuple)) or slot < 0 or slot >= len(source_outputs):
                        errors.append(_issue("link_slot_invalid", "Connected output index does not exist in installed schema.", node_id=node_id, input=name, source_node=upstream, output_index=slot))
                        continue
                    actual = source_outputs[slot]
                    expected_type = "STRING" if isinstance(expected, list) else expected
                    if isinstance(actual, str) and isinstance(expected_type, str) and actual != "*" and expected_type != "*" and not set(actual.split(",")).intersection(expected_type.split(",")):
                        errors.append(_issue("link_type", "Connected output type differs from the installed input type.", node_id=node_id, input=name, expected_type=expected_type, actual_type=actual))
                    continue
                context = {"node_id": node_id, "input": name}
                if (node_id, name) in pending_media and isinstance(value, str):
                    warnings.append(_issue("media_binding_pending", "Required asset will be staged and checked against fresh node choices before submission.", **context))
                    continue
                if _unsafe_file_value(name, value):
                    errors.append(_issue("input_path_unsafe", "File inputs and output prefixes must use relative ComfyUI storage paths without traversal.", **context))
                if expected == "COMBO" and isinstance(constraints.get("options"), list):
                    if value not in constraints["options"]:
                        errors.append(_issue("input_choice_not_installed", "Value is absent from the installed V3 combo options.", **context))
                elif isinstance(expected, list):
                    if value not in expected:
                        errors.append(_issue("input_choice_not_installed", "Value is not available in the live node choices. Check model paths and installed files.", **context))
                elif isinstance(expected, str) and expected in {"INT", "FLOAT", "STRING", "BOOLEAN"}:
                    mapped_type = {"INT": "integer", "FLOAT": "number", "STRING": "string", "BOOLEAN": "boolean"}[expected]
                    for issue in self._value_errors(name, {"type": mapped_type, **{key: constraints[key] for key in ("min", "max") if key in constraints}}, value):
                        errors.append({**issue, **context})
                else:
                    errors.append(_issue("input_connection_required", "Custom typed inputs require an explicit connection; no literal serializer is configured.", expected_type=expected, **context))
        colors: dict[str, int] = {}
        for root in edges:
            stack = [(root, False)]
            while stack:
                node_id, exiting = stack.pop()
                if exiting:
                    colors[node_id] = 2
                    continue
                if colors.get(node_id) == 1:
                    errors.append(_issue("graph_cycle", "Prompt contains a cyclic dependency.", node_id=node_id))
                    continue
                if colors.get(node_id) == 2:
                    continue
                colors[node_id] = 1
                stack.append((node_id, True))
                stack.extend((upstream, False) for upstream in edges[node_id])
        output_nodes = self._mapping.get("output_nodes", []) if isinstance(self._mapping, dict) else []
        if not output_nodes:
            errors.append(_issue("output_mapping_required", "Explicit output_nodes are required before execution."))
        for node_id in output_nodes if isinstance(output_nodes, list) else []:
            if not isinstance(node_id, str):
                continue
            node = prompt.get(node_id)
            if node is None:
                continue
            schema = object_info.get(node["class_type"], {})
            if not isinstance(schema, dict):
                schema = {}
            if not schema.get("output_node"):
                errors.append(_issue("output_not_executable", "Mapped output is not an output node in the live ComfyUI schema.", node_id=node_id))
            outputs.append({"node_id": node_id, "class_type": node["class_type"], "types": deepcopy(schema.get("output", [])), "output_node": bool(schema.get("output_node"))})
        warnings.append(_issue("server_validation_required", "ComfyUI validates custom node rules again at /prompt. Successful preflight does not establish model compatibility or available VRAM."))
        return {"valid": not errors, "errors": errors, "warnings": warnings, "outputs": outputs}

    def build(self, parameters: dict, object_info: dict) -> dict:
        report = self.validate(object_info, parameters)
        if not report["valid"]:
            raise WorkflowError("Workflow preflight failed.", report["errors"])
        return self._parameterized(parameters)

    def output_descriptors(self, history_entry: dict) -> list[dict]:
        """Return only server-reported file descriptors from mapped output nodes."""
        descriptors = []
        if self._mapping_errors:
            return descriptors
        node_outputs = history_entry.get("outputs", {})
        if not isinstance(node_outputs, dict):
            return descriptors
        for node_id in self._mapping.get("output_nodes", []):
            payload = node_outputs.get(node_id, {})
            if not isinstance(payload, dict):
                continue
            for kind, entries in payload.items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if isinstance(entry, dict) and isinstance(entry.get("filename"), str):
                        descriptors.append({**deepcopy(entry), "node_id": node_id, "kind": kind})
        return descriptors
