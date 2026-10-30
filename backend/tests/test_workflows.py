"""Contract unit fixtures only; these nodes are not production workflows."""
from copy import deepcopy
import unittest

from app.workflows import WorkflowAdapter, WorkflowError, workflow_format


def fixture():
    prompt = {
        "2": {"class_type": "FixtureText", "inputs": {"text": "original"}},
        "7": {"class_type": "FixtureModel", "inputs": {"ckpt_name": "local/model.safetensors"}},
        "12": {"class_type": "FixtureOutput", "inputs": {"conditioning": ["2", 0], "model": ["7", 0], "seed": 9, "filename_prefix": "studio/result"}},
    }
    mapping = {"parameters": {"prompt": {"node_id": "2", "input": "text", "type": "string", "required": True},
                              "seed": {"node_id": "12", "input": "seed", "type": "integer", "min": 0, "max": 100}}, "output_nodes": ["12"]}
    info = {
        "FixtureText": {"input": {"required": {"text": ["STRING", {}]}}, "output": ["CONDITIONING"], "output_node": False},
        "FixtureModel": {"input": {"required": {"ckpt_name": [["local/model.safetensors"], {}]}}, "output": ["MODEL"], "output_node": False},
        "FixtureOutput": {"input": {"required": {"conditioning": ["CONDITIONING"], "model": ["MODEL"], "seed": ["INT", {"min": 0, "max": 100}], "filename_prefix": ["STRING"]}}, "output": [], "output_node": True},
    }
    return prompt, mapping, info


class WorkflowTests(unittest.TestCase):
    def test_v3_optional_autogrow_uses_only_advertised_names_and_types(self):
        graph = {"1": {"class_type": "FixtureSource", "inputs": {}},
                 "2": {"class_type": "FixtureGrow", "inputs": {"text": "fixture", "device": "auto"}},
                 "3": {"class_type": "FixtureSave", "inputs": {"images": ["2", 0]}}}
        mapping = {"parameters": {}, "output_nodes": ["3"]}
        info = {"FixtureSource": {"input": {}, "output": ["IMAGE"]},
                "FixtureGrow": {"input": {"required": {"text": ["STRING"], "device": ["COMBO", {"options": ["auto", "cpu"]}],
                                "images": ["COMFY_AUTOGROW_V3", {"template": {"input": {"required": {"image": ["IMAGE"]}}, "names": ["image_1", "image_2"], "min": 0}}]}}, "output": ["IMAGE"]},
                "FixtureSave": {"input": {"required": {"images": ["IMAGE"]}}, "output": [], "output_node": True}}
        self.assertTrue(WorkflowAdapter(graph, mapping).validate(info)["valid"])
        graph["2"]["inputs"]["images.image_1"] = ["1", 0]
        self.assertTrue(WorkflowAdapter(graph, mapping).validate(info)["valid"])
        graph["2"]["inputs"]["images.image_3"] = ["1", 0]
        self.assertIn("input_unknown", {e["code"] for e in WorkflowAdapter(graph, mapping).validate(info)["errors"]})
        del graph["2"]["inputs"]["images.image_3"]
        info["FixtureSource"]["output"] = ["STRING"]
        self.assertIn("link_type", {e["code"] for e in WorkflowAdapter(graph, mapping).validate(info)["errors"]})

    def test_v3_combo_choices_and_autogrow_minimum_remain_enforced(self):
        graph = {"1": {"class_type": "FixtureGrow", "inputs": {"device": "invented"}}}
        mapping = {"parameters": {}, "output_nodes": ["1"]}
        info = {"FixtureGrow": {"input": {"required": {"device": ["COMBO", {"options": ["auto", "cpu"]}],
               "images": ["COMFY_AUTOGROW_V3", {"template": {"input": {"required": {"image": ["IMAGE"]}}, "names": ["image_1"], "min": 1}}]}}, "output": [], "output_node": True}}
        codes = {e["code"] for e in WorkflowAdapter(graph, mapping).validate(info)["errors"]}
        self.assertTrue({"input_choice_not_installed", "input_required"}.issubset(codes))

    def test_v3_autogrow_prefix_is_bounded_by_live_maximum(self):
        graph = {"1": {"class_type": "FixtureImage", "inputs": {}},
                 "2": {"class_type": "FixtureVideo", "inputs": {"ref_images.ref_image_0": ["1", 0]}}}
        mapping = {"parameters": {}, "output_nodes": ["2"]}
        info = {"FixtureImage": {"input": {}, "output": ["IMAGE"]},
                "FixtureVideo": {"input": {"required": {"ref_images": ["COMFY_AUTOGROW_V3", {"template": {
                    "input": {"required": {"ref_image": ["IMAGE"]}}, "prefix": "ref_image_", "min": 0, "max": 2}}]}}, "output": [], "output_node": True}}
        self.assertTrue(WorkflowAdapter(graph, mapping).validate(info)["valid"])
        graph["2"]["inputs"]["ref_images.ref_image_2"] = ["1", 0]
        self.assertIn("input_unknown", {e["code"] for e in WorkflowAdapter(graph, mapping).validate(info)["errors"]})

    def test_build_is_immutable_across_calls(self):
        prompt, mapping, info = fixture()
        original = deepcopy(prompt)
        adapter = WorkflowAdapter(prompt, mapping)
        prompt["2"]["inputs"]["text"] = "external mutation"
        built = adapter.build({"prompt": "first", "seed": 10}, info)
        built["2"]["inputs"]["text"] = "result mutation"
        self.assertEqual(adapter.build({"prompt": "second"}, info)["12"]["inputs"]["seed"], 9)
        self.assertEqual(adapter.workflow, original)

    def test_ui_graph_can_be_inspected_but_never_executed(self):
        adapter = WorkflowAdapter({"nodes": [{"id": 4, "type": "RealNamedNode", "inputs": [{"name": "ref_audio", "type": "AUDIO", "link": 1}], "widgets_values": ["private prompt"]}]})
        report = adapter.inspect()
        self.assertEqual(report["format"], "ui")
        self.assertEqual(report["candidates"][0]["input"], "ref_audio")
        self.assertNotIn("private prompt", str(report))
        with self.assertRaises(WorkflowError):
            adapter.build({}, {"RealNamedNode": {}})

    def test_exact_api_format_rejects_wrappers_and_malformed_nodes(self):
        prompt, _, _ = fixture()
        self.assertEqual(workflow_format(prompt), "api")
        self.assertEqual(workflow_format({"prompt": prompt}), "invalid")
        self.assertEqual(workflow_format({"2": {"class_type": "X", "inputs": []}}), "invalid")

    def test_missing_model_and_node_rejected(self):
        prompt, mapping, info = fixture()
        info["FixtureModel"]["input"]["required"]["ckpt_name"][0] = ["different.safetensors"]
        report = WorkflowAdapter(prompt, mapping).validate(info, {"prompt": "text"})
        self.assertIn("input_choice_not_installed", {e["code"] for e in report["errors"]})
        del info["FixtureText"]
        self.assertIn("node_not_installed", {e["code"] for e in WorkflowAdapter(prompt, mapping).validate(info)["errors"]})

    def test_allowlist_required_types_and_ranges(self):
        prompt, mapping, _ = fixture()
        adapter = WorkflowAdapter(prompt, mapping)
        self.assertFalse(adapter.validate_parameters({})["valid"])
        self.assertTrue(adapter.validate_parameters({}, allow_missing={"prompt"})["valid"])
        self.assertFalse(adapter.validate_parameters({"prompt": "text", "unmapped": 2})["valid"])
        self.assertFalse(adapter.validate_parameters({"prompt": "text", "seed": True})["valid"])
        self.assertFalse(adapter.validate_parameters({"prompt": "text", "seed": 101})["valid"])
        self.assertFalse(adapter.validate_parameters({"prompt": "  "})["valid"])

    def test_mapping_never_guesses_missing_ids_inputs_or_rewires_links(self):
        prompt, mapping, info = fixture()
        for spec in ({"node_id": "999", "input": "text", "type": "string"},
                     {"node_id": "2", "input": "invented", "type": "string"},
                     {"node_id": "12", "input": "model", "type": "string"}):
            mapping["parameters"] = {"test": spec}
            self.assertFalse(WorkflowAdapter(prompt, mapping).validate(info)["valid"])

    def test_required_node_inputs_connections_and_output_flags(self):
        prompt, mapping, info = fixture()
        del prompt["12"]["inputs"]["seed"]
        prompt["12"]["inputs"]["model"] = ["7", 2]
        info["FixtureOutput"]["output_node"] = False
        codes = {e["code"] for e in WorkflowAdapter(prompt, mapping).validate(info)["errors"]}
        self.assertTrue({"input_required", "link_slot_invalid", "output_not_executable"}.issubset(codes))

    def test_preflight_omits_request_required_checks_and_defaults_apply(self):
        prompt, mapping, info = fixture()
        adapter = WorkflowAdapter(prompt, mapping)
        self.assertTrue(adapter.validate(info)["valid"])
        self.assertFalse(adapter.validate(info, {})["valid"])
        mapping["parameters"]["prompt"]["default"] = "default"
        self.assertEqual(WorkflowAdapter(prompt, mapping).build({}, info)["2"]["inputs"]["text"], "default")

    def test_pending_image_binding_is_validated_after_staging(self):
        prompt = {"1": {"class_type": "FixtureImage", "inputs": {"image": ""}},
                  "3": {"class_type": "FixtureSave", "inputs": {"images": ["1", 0]}}}
        mapping = {"parameters": {"reference": {"node_id": "1", "input": "image", "type": "string", "kind": "image", "required": True}}, "output_nodes": ["3"]}
        info = {"FixtureImage": {"input": {"required": {"image": [["staged.png"]]}}, "output": ["IMAGE"]},
                "FixtureSave": {"input": {"required": {"images": ["IMAGE"]}}, "output": [], "output_node": True}}
        adapter = WorkflowAdapter(prompt, mapping)
        self.assertTrue(adapter.validate(info)["valid"])
        self.assertTrue(adapter.validate(info, {}, allow_missing={"reference"})["valid"])
        self.assertFalse(adapter.validate(info, {"reference": "missing.png"})["valid"])
        self.assertEqual(adapter.build({"reference": "staged.png"}, info)["1"]["inputs"]["image"], "staged.png")

    def test_traversal_absolute_paths_and_output_prefix_rejected(self):
        prompt, mapping, info = fixture()
        for bad in ("../result", "..\\result", "C:\\escape", "\\\\server\\share", "/tmp/result", "https://remote/file"):
            prompt["12"]["inputs"]["filename_prefix"] = bad
            self.assertIn("input_path_unsafe", {e["code"] for e in WorkflowAdapter(prompt, mapping).validate(info)["errors"]})

    def test_cycles_and_type_mismatch_rejected(self):
        prompt, mapping, info = fixture()
        prompt["12"]["inputs"]["model"] = ["2", 0]
        self.assertIn("link_type", {e["code"] for e in WorkflowAdapter(prompt, mapping).validate(info)["errors"]})
        prompt["2"]["inputs"]["text"] = ["2", 0]
        self.assertIn("graph_cycle", {e["code"] for e in WorkflowAdapter(prompt, mapping).validate(info)["errors"]})

    def test_outputs_only_from_explicit_nodes_and_server_descriptors(self):
        prompt, mapping, _ = fixture()
        adapter = WorkflowAdapter(prompt, mapping)
        history = {"outputs": {"12": {"images": [{"filename": "result.png", "subfolder": "", "type": "output"}], "text": ["not a file"]},
                               "999": {"images": [{"filename": "other.png"}]}}}
        outputs = adapter.output_descriptors(history)
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["node_id"], "12")

    def test_malformed_schema_and_params_fail_closed(self):
        prompt, mapping, info = fixture()
        info["FixtureText"]["input"] = []
        self.assertFalse(WorkflowAdapter(prompt, mapping).validate(info)["valid"])
        self.assertFalse(WorkflowAdapter(prompt, mapping).validate(info, ["not an object"])["valid"])
        mapping["parameters"]["prompt"]["type"] = []
        mapping["parameters"]["prompt"]["kind"] = {}
        self.assertFalse(WorkflowAdapter(prompt, mapping).validate(info)["valid"])
        mapping["output_nodes"] = [[]]
        self.assertFalse(WorkflowAdapter(prompt, mapping).validate(info)["valid"])
        self.assertEqual(WorkflowAdapter({"nodes": [{"id": 1, "type": [], "inputs": None}]}).inspect()["node_count"], 1)


if __name__ == "__main__":
    unittest.main()
