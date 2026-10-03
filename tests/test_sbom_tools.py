import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.sbom_utils import service, tool


def bom(**fields):
    return {"bomFormat": "CycloneDX", "specVersion": "1.7", **fields}


def component(name="demo", ref="demo", **fields):
    return {"type": "library", "name": name, "bom-ref": ref, **fields}


class SbomInspectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("sbom-tests")
        tool.register(self.mcp)

    async def call(self, content, **arguments):
        result = await self.mcp.call_tool("inspect_sbom", {"content": content, **arguments})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_component_inventory_versions_licenses_and_omission(self):
        content = bom(version=2, components=[component(version="1.0.0", purl="pkg:npm/demo@1.0.0", scope="optional",
            licenses=[{"license": {"id": "MIT", "text": {"content": "hidden-license-text"}}},
                      {"license": {"name": "Custom"}}, {"expression": "MIT OR Apache-2.0"}],
            description="hidden-description", properties=[{"name": "token", "value": "hidden-property"}],
            externalReferences=[{"url": "https://example.com/hidden-reference"}])])
        output = await self.call(json.dumps(content))
        data = json.loads(output)
        self.assertEqual(data["component_count"], 1)
        self.assertEqual(data["bom_version"], 2)
        row = data["components"][0]
        self.assertEqual(row["version"], "1.0.0")
        self.assertEqual(row["purl"], "pkg:npm/demo@1.0.0")
        self.assertEqual(row["scope"], "optional")
        self.assertEqual(row["licenses"][0], {"id": "MIT", "name": None})
        self.assertEqual(row["licenses"][2]["expression"], "MIT OR Apache-2.0")
        for hidden in ("hidden-license-text", "hidden-description", "hidden-property", "hidden-reference"):
            self.assertNotIn(hidden, output)

    async def test_metadata_nested_inventory_and_dependencies_are_separate(self):
        content = bom(metadata={"component": component("app", "app", type="application")},
                      components=[component("parent", "parent", components=[component("child", "child")])],
                      dependencies=[{"ref": "app", "dependsOn": ["parent"]}, {"ref": "child", "dependsOn": []}])
        data = json.loads(await self.call(json.dumps(content)))
        self.assertEqual(data["component_count"], 3)
        self.assertEqual(data["components"][0]["role"], "metadata")
        self.assertEqual(data["components"][2]["parent_bom_ref"], "parent")
        self.assertEqual(data["dependency_graph"]["edge_count"], 1)
        self.assertFalse(data["dependency_graph"]["has_cycle"])
        self.assertEqual(data["dependency_graph"]["unresolved_reference_count"], 0)

    async def test_cycles_unresolved_service_external_refs_and_deduplication(self):
        content = bom(components=[component("a", "a"), component("b", "b")], services=[{"bom-ref": "svc"}],
                      dependencies=[{"ref": "a", "dependsOn": ["b", "b", "svc", "urn:cdx:external"]},
                                    {"ref": "b", "dependsOn": ["a"]}])
        data = json.loads(await self.call(json.dumps(content)))
        graph = data["dependency_graph"]
        self.assertTrue(graph["has_cycle"])
        self.assertEqual(graph["edge_count"], 4)
        self.assertEqual(graph["unresolved_references"], ["svc", "urn:cdx:external"])
        self.assertIn("not necessarily invalid", " ".join(data["notes"]))

    async def test_supported_versions_empty_inventory_and_unspecified_fields(self):
        for version in ("1.5", "1.6", "1.7"):
            data = json.loads(await self.call(json.dumps(bom(specVersion=version))))
            self.assertEqual(data["component_count"], 0)
            self.assertEqual(data["dependency_graph"]["edge_count"], 0)
            self.assertIsNone(data["bom_version"])
        data = json.loads(await self.call(json.dumps(bom(components=[{"type": "library", "name": "demo"}]))))
        self.assertIsNone(data["components"][0]["version"])
        self.assertIsNone(data["components"][0]["scope"])
        self.assertIsNone(data["components"][0]["bom_ref"])

    async def test_truncation_of_components_edges_and_unresolved_refs(self):
        content = bom(components=[component("a", "a"), component("b", "b")],
                      dependencies=[{"ref": "a", "dependsOn": ["b", "x", "y"]}, {"ref": "b"}])
        data = json.loads(await self.call(json.dumps(content), limit=1))
        self.assertEqual(data["component_count"], 2)
        self.assertEqual(len(data["components"]), 1)
        self.assertEqual(data["dependency_graph"]["edge_count"], 3)
        self.assertEqual(data["dependency_graph"]["unresolved_reference_count"], 2)
        self.assertEqual(len(data["dependency_graph"]["unresolved_references"]), 1)
        self.assertEqual(data["dependency_graph"]["dependencies"][0]["depends_on"], ["b"])
        self.assertTrue(data["dependency_graph"]["dependencies"][0]["truncated"])
        self.assertTrue(data["truncated"])

    async def test_unsupported_formats_and_malformed_roots(self):
        for content in ("", "{", "[]", "null", "<bom></bom>", '{"spdxVersion":"SPDX-2.3"}',
                        json.dumps(bom(specVersion="1.4")), json.dumps(bom(bomFormat="Other")),
                        json.dumps(bom(specVersion=True)), json.dumps(bom(components={})), json.dumps(bom(metadata=[]))):
            self.assertTrue((await self.call(content)).startswith("Error:"))

    async def test_duplicate_keys_nonfinite_numbers_and_source_errors(self):
        for content in ('{"bomFormat":"CycloneDX","bomFormat":"hidden-marker"}',
                        '{"bomFormat":"CycloneDX","specVersion":"1.7","token":"hidden-marker',
                        '{"bomFormat":"CycloneDX","specVersion":"1.7","ignored":NaN}',
                        '{"bomFormat":"CycloneDX","specVersion":"1.7","ignored":1e999}'):
            output = await self.call(content)
            self.assertTrue(output.startswith("Error:"))
            self.assertNotIn("hidden-marker", output)

    async def test_duplicate_component_and_dependency_references(self):
        for content in (bom(components=[component(), component("other")]),
                        bom(metadata={"component": component()}, components=[component()]),
                        bom(dependencies=[{"ref": "a"}, {"ref": "a"}])):
            self.assertTrue((await self.call(json.dumps(content))).startswith("Error:"))

    async def test_component_license_and_dependency_shapes(self):
        cases = (bom(components=[{}]), bom(components=[component(name=True)]), bom(version=True), bom(version=0),
                 bom(components=[component(version=1)]), bom(components=[component(licenses=[{}])]),
                 bom(components=[component(licenses=[{"license": {"id": "MIT", "name": "MIT"}}])]),
                 bom(components=[component(licenses=[{"license": []}])]),
                 bom(components=[component(licenses=[{"expression": None}])]),
                 bom(components=[component(components={})]), bom(dependencies=[{"ref": "a", "dependsOn": [True]}]),
                 bom(dependencies=[{"ref": "a", "dependsOn": {}}]), bom(dependencies=[{}]))
        for content in cases:
            self.assertTrue((await self.call(json.dumps(content))).startswith("Error:"))

    async def test_all_components_validated_even_when_not_returned(self):
        content = bom(components=[component(), {"name": "invalid"}])
        self.assertTrue((await self.call(json.dumps(content), limit=1)).startswith("Error:"))

    async def test_input_structure_component_and_text_bounds(self):
        cases = (" " * 200001, json.dumps(bom(components=[component(name="x" * 2001)])),
                 json.dumps(bom(components=[component(str(i), str(i)) for i in range(1001)])),
                 json.dumps(bom(ignored=[0] * 10001)),
                 '{"bomFormat":"CycloneDX","specVersion":"1.7","ignored":' + '[' * 51 + '0' + ']' * 51 + '}')
        for content in cases:
            self.assertTrue((await self.call(content)).startswith("Error:"))
        with self.assertRaises(ValueError):
            service.inspect_sbom(json.dumps(bom()), True)
        for limit in (0, 201):
            self.assertTrue((await self.call(json.dumps(bom()), limit=limit)).startswith("Error:"))

    async def test_output_cap(self):
        with patch.object(service, "inspect_sbom", return_value={"data": "x" * 100001}):
            self.assertIn("100000", await self.call(json.dumps(bom())))

    async def test_dependency_entry_edge_license_and_nested_inventory_bounds(self):
        cases = (bom(dependencies=[{"ref": str(i)} for i in range(1001)]),
                 bom(dependencies=[{"ref": str(i), "dependsOn": [str(j) for j in range(1000)]} for i in range(6)]),
                 bom(components=[component(licenses=[{"license": {"id": "MIT"}}] * 51)]),
                 bom(metadata={"component": component("root", "root")},
                     components=[component(str(i), str(i)) for i in range(1000)]))
        for content in cases:
            with self.subTest(fields=list(content)):
                self.assertTrue((await self.call(json.dumps(content))).startswith("Error:"))

    async def test_inventory_does_not_fetch_schemas_licenses_or_references(self):
        content = bom(**{"$schema": "https://example.com/never-fetch"}, components=[component(
            licenses=[{"license": {"id": "MIT", "url": "https://example.com/never-fetch-license"}}])])
        with patch("builtins.open", side_effect=AssertionError("Unexpected file access")), \
                patch("socket.create_connection", side_effect=AssertionError("Unexpected network access")), \
                patch("subprocess.run", side_effect=AssertionError("Unexpected execution")):
            data = service.inspect_sbom(json.dumps(content), 50)
        self.assertEqual(data["component_count"], 1)


if __name__ == "__main__":
    unittest.main()
