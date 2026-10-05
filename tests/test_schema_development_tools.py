import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP
from app.tools.schema_development import service, tool


class SchemaDevelopmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("schema-development")
        tool.register(self.mcp)

    async def call(self, name, **args):
        result = await self.mcp.call_tool(name, args)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_inspection_local_refs_boolean_and_annotation_boundaries(self):
        schema = {"$defs": {"n": {"type": "integer"}}, "properties": {
            "a/b": {"$ref": "#/$defs/n"}, "missing": {"$ref": "#/$defs/absent"}, "no": False},
            "examples": [{"$ref": "https://example.com"}], "required": ["a/b"]}
        report = json.loads(await self.call("inspect_json_schema", schema=json.dumps(schema)))
        self.assertEqual(report["schema_nodes"], 5)
        self.assertEqual([ref["resolved"] for ref in report["references"]], [True, False])
        self.assertIn("/properties/a~1b", [node["path"] for node in report["declarations"]])
        self.assertEqual(json.loads(await self.call("inspect_json_schema", schema="false"))["declarations"],
                         [{"path": "", "boolean_schema": False}])

    async def test_dialects_and_restricted_refs(self):
        for dialect in service._DIALECTS:
            report = json.loads(await self.call("inspect_json_schema", schema=json.dumps({"$schema": dialect})))
            self.assertEqual(report["dialect"], dialect)
        for schema in ('{"$schema":"unknown"}', '{"type":"invalid"}', '[]',
                       '{"$ref":"https://example.com/schema"}', '{"$id":"urn:test"}',
                       '{"$dynamicRef":"#x"}', '{"$recursiveRef":"#"}',
                       '{"properties":{"x":{"$schema":"http://json-schema.org/draft-07/schema#"}}}'):
            with self.subTest(schema=schema):
                self.assertTrue((await self.call("inspect_json_schema", schema=schema)).startswith("Error:"))

    async def test_compare_counts_and_limits_and_no_compatibility_claim(self):
        result = json.loads(await self.call("compare_json_schemas", before='{"enum":[true],"title":"old"}',
                                            after='{"enum":[1],"title":"new","type":"integer"}', limit=1))
        self.assertEqual(result["change_count"], 3)
        self.assertTrue(result["truncated"])
        self.assertFalse(result["compatibility_assessed"])
        self.assertNotIn("old", json.dumps(result))

    async def test_inference_observed_types_and_samples_validate(self):
        examples = [{"id": 1, "tags": []}, {"id": 2.5, "tags": [True, "x"], "optional": None}]
        result = json.loads(await self.call("infer_json_schema", examples=json.dumps(examples)))
        schema = result["schema"]
        self.assertEqual(schema["required"], ["id", "tags"])
        self.assertEqual(schema["properties"]["id"]["type"], "number")
        self.assertNotIn("additionalProperties", schema)
        self.assertTrue(result["uncertainty"])
        report = json.loads(await self.call("validate_json_schema_batch", value=json.dumps(examples), schema=json.dumps(schema)))
        self.assertTrue(report["valid"])
        self.assertEqual(json.loads(await self.call("infer_json_schema", examples="[[]]"))["schema"]["items"], {})
        for value in ("[]", "{}"):
            self.assertTrue((await self.call("infer_json_schema", examples=value)).startswith("Error:"))

    async def test_batch_evaluates_all_items_and_sanitizes_diagnostics(self):
        report = json.loads(await self.call("validate_json_schema_batch", value='[1,"secret",false,null]',
                                           schema='{"type":"integer"}', limit=1))
        self.assertEqual(report["evaluated_records"], 4)
        self.assertEqual(report["invalid_records"], 3)
        self.assertEqual(report["errors"][0]["record"], 1)
        self.assertTrue(report["truncated"])
        self.assertNotIn("secret", json.dumps(report))
        self.assertTrue(json.loads(await self.call("validate_json_schema_batch", value="[]", schema="false"))["valid"])
        self.assertTrue((await self.call("validate_json_schema_batch", value="{}", schema="{}")).startswith("Error:"))

    async def test_jsonl_line_numbers_malformed_and_blank_lines(self):
        report = json.loads(await self.call("validate_jsonl_schema", content='1\n\n"secret"\nbad\n2\r\n',
                                           schema='{"type":"integer"}'))
        self.assertEqual(report["evaluated_records"], 3)
        self.assertEqual(report["malformed_lines"], [4])
        self.assertEqual(report["errors"][0]["record"], 3)
        self.assertFalse(report["valid"])

    async def test_local_ref_validation_and_unresolved_ref_errors(self):
        schema = '{"$defs":{"n":{"type":"integer"}},"$ref":"#/$defs/n"}'
        report = json.loads(await self.call("validate_json_schema_batch", value='[1,"x"]', schema=schema))
        self.assertEqual(report["invalid_records"], 1)
        self.assertTrue((await self.call("validate_json_schema_batch", value="[1]", schema='{"$ref":"#missing"}')).startswith("Error:"))
        self.assertTrue(json.loads(await self.call("validate_json_schema_batch", value='["not-email"]',
                                                  schema='{"format":"email"}'))["valid"])

    async def test_pointer_extracts_nodes_not_annotations_and_preserves_refs(self):
        schema = '{"properties":{"a/b":{"type":"string"},"~":false},"$defs":{"n":{}},"$ref":"#/$defs/n"}'
        self.assertEqual(json.loads(await self.call("resolve_json_schema_pointer", schema=schema, pointer="/properties/a~1b")), {"type": "string"})
        self.assertFalse(json.loads(await self.call("resolve_json_schema_pointer", schema=schema, pointer="/properties/~0")))
        self.assertEqual(json.loads(await self.call("resolve_json_schema_pointer", schema=schema, pointer=""))["$ref"], "#/$defs/n")
        for pointer in ("/properties/a~1b/type", "/missing", "/bad~2", "bad"):
            self.assertTrue((await self.call("resolve_json_schema_pointer", schema=schema, pointer=pointer)).startswith("Error:"))

    async def test_bounds_and_duplicates(self):
        for schema in ('{"type":"integer","type":"string"}', ' ' * 200001, '[' * 51 + '0' + ']' * 51):
            self.assertTrue((await self.call("inspect_json_schema", schema=schema)).startswith("Error:"))
        self.assertTrue((await self.call("inspect_json_schema", schema="{}", limit=0)).startswith("Error:"))
        self.assertTrue((await self.call("validate_json_schema_batch", value=json.dumps([0] * 10000), schema="{}")).startswith("Error:"))

    async def test_worker_timeout_and_busy_slots(self):
        with patch.object(service, "_TIMEOUT", 0):
            self.assertIn("3-second", await self.call("inspect_json_schema", schema="{}"))
        with patch.object(service, "_SLOTS") as slots:
            slots.acquire.return_value = False
            self.assertIn("busy", await self.call("inspect_json_schema", schema="{}"))

    async def test_six_tools_registered(self):
        self.assertEqual({t.name for t in await self.mcp.list_tools()}, {
            "inspect_json_schema", "compare_json_schemas", "infer_json_schema",
            "validate_jsonl_schema", "validate_json_schema_batch", "resolve_json_schema_pointer"})


if __name__ == "__main__":
    unittest.main()
