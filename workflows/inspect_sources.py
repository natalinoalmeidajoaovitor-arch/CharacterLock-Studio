"""Offline, read-only source inspection plus byte-identical local preservation.

This never imports ComfyUI, downloads models, converts a graph or submits a job.
Private originals belong in the gitignored originals directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil


def inspect_graph(graph: dict, scope: str = "root") -> list[dict]:
    nodes = graph.get("nodes", [])
    if isinstance(nodes, list):
        records = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            records.append({"node_id": str(node.get("id", "")), "class_type": node.get("type", ""),
                            "input_names": [value["name"] for value in node.get("inputs", []) if isinstance(value, dict) and isinstance(value.get("name"), str)],
                            "output_types": [value.get("type") for value in node.get("outputs", []) if isinstance(value, dict)],
                            "widget_count": len(node.get("widgets_values", [])) if isinstance(node.get("widgets_values"), (list, dict)) else 0})
        result = [{"scope": scope, "node_count": len(records), "node_types": dict(sorted(Counter(record["class_type"] for record in records).items())), "nodes": records}]
        definitions = graph.get("definitions", {})
        for subgraph in definitions.get("subgraphs", []) if isinstance(definitions, dict) else []:
            if isinstance(subgraph, dict):
                result.extend(inspect_graph(subgraph, "subgraph:" + str(subgraph.get("id", "unknown"))))
        return result
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--originals", type=Path, required=True)
    args = parser.parse_args()
    args.originals.mkdir(parents=True, exist_ok=True)
    records = []
    for source in args.source:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.suffix.lower() != ".json":
                continue
            payload = path.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            preserved_name = digest[:12] + "-" + path.name
            destination = args.originals / preserved_name
            if destination.exists() and destination.read_bytes() != payload:
                raise RuntimeError("Preserved workflow collision; originals were not modified.")
            if not destination.exists():
                shutil.copyfile(path, destination)
            graph = json.loads(payload)
            format_name = "ui" if isinstance(graph, dict) and isinstance(graph.get("nodes"), list) else "api" if isinstance(graph, dict) and graph and all(isinstance(node, dict) and isinstance(node.get("class_type"), str) and isinstance(node.get("inputs"), dict) for node in graph.values()) else "invalid"
            records.append({"file": path.name, "source_hint": source.name + "/" + path.relative_to(source).as_posix(),
                            "preserved_original": "workflows/originals/" + preserved_name, "sha256": digest,
                            "bytes": len(payload), "format": format_name, "execution_status": "requires_api_export" if format_name == "ui" else "requires_explicit_mapping_and_live_validation",
                            "graphs": inspect_graph(graph) if isinstance(graph, dict) else []})
    inventory = {"inspection": "offline_source_only", "comfyui_live_validation": False,
                 "notes": ["Originals are byte-identical local copies and gitignored because they may contain private prompts and filenames.",
                           "No prompt text, widget values or node titles are included in this inventory.",
                           "UI graphs are not executable API prompts. Widget indices are not mapped or guessed.",
                           "Installed source or model files do not establish runtime compatibility; /object_info and a real authorized generation are still required."],
                 "workflows": records}
    args.inventory.parent.mkdir(parents=True, exist_ok=True)
    args.inventory.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.originals / "LOCAL-ONLY.txt").write_text("PRIVATE ORIGINAL WORKFLOWS — local preserved copies. Do not commit or execute these UI graphs. Export API format in ComfyUI and create explicit mappings before validation.\n", encoding="utf-8")
    print(json.dumps({"workflows": len(records), "formats": dict(Counter(record["format"] for record in records)), "inventory": str(args.inventory)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
