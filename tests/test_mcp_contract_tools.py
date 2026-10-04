import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.mcp_contract_utils import tool


def manifest():
    return {"tools": [{"name": "orders.lookup", "description": "PRIVATE_DESCRIPTION",
                       "inputSchema": {"type": "object", "properties": {
                           "id": {"type": "integer"},
                           "note": {"type": "string", "default": "PRIVATE_DEFAULT"}},
                           "required": ["id"], "additionalProperties": False},
                       "outputSchema": {"type": "object", "properties": {
                           "total": {"type": "number"}}, "required": ["total"]},
                       "annotations": {"readOnlyHint": True, "destructiveHint": False}}]}


class McpContractToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("mcp-contract-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(block.text for block in blocks if block.type == "text")

    async def result(self, name, **arguments):
        return json.loads(await self.call(name, **arguments))

    async def test_inspect_wrapped_list_omits_description_and_defaults(self):
        content = json.dumps({"jsonrpc": "2.0", "id": 1, "result": manifest()})
        text = await self.call("inspect_mcp_tool_manifest", manifest=content)
        self.assertNotIn("PRIVATE_DESCRIPTION", text)
        self.assertNotIn("PRIVATE_DEFAULT", text)
        value = json.loads(text)
        self.assertEqual(value["tool_count"], 1)
        self.assertFalse(value["partial_list"])
        self.assertEqual(value["tools"][0]["required_arguments"], ["id"])
        self.assertTrue(value["tools"][0]["annotation_hints"]["readOnlyHint"])
        self.assertEqual(value["tools"][0]["output_root_type"], "object")

    async def test_inspect_partial_page_and_nonconforming_name(self):
        doc = manifest()
        doc["tools"][0]["name"] = "not recommended"
        doc["nextCursor"] = "PRIVATE_CURSOR"
        value = await self.result("inspect_mcp_tool_manifest", manifest=json.dumps(doc))
        self.assertTrue(value["partial_list"])
        self.assertEqual(value["nonconforming_name_count"], 1)
        self.assertNotIn("PRIVATE_CURSOR", json.dumps(value))
        text = await self.call("compare_mcp_tool_manifests", before=json.dumps(doc), after=json.dumps(manifest()))
        self.assertIn("complete tools/list snapshots", text)

    async def test_compare_exact_names_and_selected_shape(self):
        before = manifest()
        after = manifest()
        changed = after["tools"][0]
        changed["description"] = "NEW_PRIVATE_DESCRIPTION"
        changed["inputSchema"]["properties"]["id"]["type"] = "string"
        changed["inputSchema"]["properties"]["status"] = {"type": "string"}
        changed["inputSchema"]["required"] = ["status"]
        changed["outputSchema"]["required"] = []
        after["tools"].append({"name": "new.tool", "inputSchema": {"type": "object"}})
        text = await self.call("compare_mcp_tool_manifests", before=json.dumps(before), after=json.dumps(after))
        for secret in ("PRIVATE_DESCRIPTION", "NEW_PRIVATE_DESCRIPTION", "PRIVATE_DEFAULT"):
            self.assertNotIn(secret, text)
        value = json.loads(text)
        self.assertEqual(value["selected_change_count"], 4)
        self.assertEqual({row["field"] for row in value["changes"]},
                         {"tool_presence", "input_schema", "output_schema", "description"})
        delta = next(row["selected_shape"] for row in value["changes"] if row["field"] == "input_schema")
        self.assertEqual(delta["required_added"], ["status"])
        self.assertEqual(delta["required_removed"], ["id"])
        self.assertEqual(delta["properties_added"], ["status"])
        self.assertEqual(delta["property_type_changes"][0]["name"], "id")

    async def test_compare_uses_full_identity_before_shortening(self):
        prefix = "x" * 250
        before = {"tools": [{"name": prefix + "a", "inputSchema": {"type": "object"}}]}
        after = {"tools": [{"name": prefix + "b", "inputSchema": {"type": "object"}}]}
        value = await self.result("compare_mcp_tool_manifests", before=json.dumps(before), after=json.dumps(after))
        self.assertEqual(value["selected_change_count"], 2)
        self.assertTrue(value["truncated"])

    async def test_argument_validation_and_value_redaction(self):
        content = json.dumps(manifest())
        args = {"manifest": content, "tool_name": "orders.lookup"}
        self.assertTrue((await self.result("validate_mcp_tool_arguments", arguments='{"id": 1}', **args))["valid"])
        text = await self.call("validate_mcp_tool_arguments", arguments='{"id": "ARGUMENT_SECRET"}', **args)
        self.assertNotIn("ARGUMENT_SECRET", text)
        value = json.loads(text)
        self.assertFalse(value["valid"])
        self.assertEqual(value["errors"][0]["path"], "/id")
        self.assertTrue((await self.call("validate_mcp_tool_arguments", arguments="[]", **args)).startswith("Error:"))

    async def test_argument_local_ref_draft7_and_external_ref_rejection(self):
        doc = manifest()
        doc["tools"][0]["inputSchema"] = {"$schema": "http://json-schema.org/draft-07/schema#",
                                              "type": "object", "properties": {"id": {"$ref": "#/$defs/id"}},
                                              "$defs": {"id": {"type": "integer"}}}
        args = {"manifest": json.dumps(doc), "tool_name": "orders.lookup"}
        self.assertTrue((await self.result("validate_mcp_tool_arguments", arguments='{"id": 1}', **args))["valid"])
        doc["tools"][0]["inputSchema"]["properties"]["id"]["$ref"] = "https://private.example/schema"
        text = await self.call("validate_mcp_tool_arguments", manifest=json.dumps(doc),
                               tool_name="orders.lookup", arguments='{"id": 1}')
        self.assertIn("Only local JSON Schema references", text)
        self.assertNotIn("private.example", text)

    async def test_result_validation_2025_and_unchecked_states(self):
        content = json.dumps(manifest())
        args = {"manifest": content, "tool_name": "orders.lookup"}
        good = {"content": [], "structuredContent": {"total": 2.5}}
        self.assertTrue((await self.result("validate_mcp_tool_result", result=json.dumps(good), **args))["schema_valid"])
        bad = {"content": [], "structuredContent": {"total": "RESULT_SECRET"}}
        text = await self.call("validate_mcp_tool_result", result=json.dumps(bad), **args)
        self.assertNotIn("RESULT_SECRET", text)
        value = json.loads(text)
        self.assertFalse(value["schema_valid"])
        self.assertEqual(value["errors"][0]["path"], "/total")
        missing = await self.result("validate_mcp_tool_result", result='{"content":[]}', **args)
        self.assertEqual(missing["reason"], "structured_content_missing")
        errored = await self.result("validate_mcp_tool_result", result='{"isError":true,"content":[]}', **args)
        self.assertFalse(errored["checked"])
        self.assertEqual(errored["reason"], "tool_error")
        doc = manifest()
        del doc["tools"][0]["outputSchema"]
        no_schema = await self.result("validate_mcp_tool_result", manifest=json.dumps(doc),
                                      tool_name="orders.lookup", result=json.dumps(good))
        self.assertEqual(no_schema["reason"], "output_schema_absent")

    async def test_result_validation_2026_allows_json_array(self):
        doc = manifest()
        doc["tools"][0]["outputSchema"] = {"type": "array", "items": {"type": "integer"}}
        args = {"manifest": json.dumps(doc), "tool_name": "orders.lookup"}
        result = {"resultType": "complete", "content": [], "structuredContent": [1, 2]}
        value = await self.result("validate_mcp_tool_result", result=json.dumps(result),
                                  protocol_version="2026-07-28", **args)
        self.assertTrue(value["schema_valid"])
        old = await self.result("validate_mcp_tool_result", result=json.dumps(result), **args)
        self.assertEqual(old["reason"], "structured_content_must_be_object")
        waiting = await self.result("validate_mcp_tool_result", result='{"resultType":"input_required"}',
                                    protocol_version="2026-07-28", **args)
        self.assertFalse(waiting["checked"])
        self.assertEqual(waiting["reason"], "input_required")

    async def test_invalid_schema_errors_do_not_echo_schema_values(self):
        doc = manifest()
        doc["tools"][0]["inputSchema"]["properties"]["id"] = {"type": "PRIVATE_BAD_TYPE"}
        text = await self.call("validate_mcp_tool_arguments", manifest=json.dumps(doc),
                               tool_name="orders.lookup", arguments='{"id": 1}')
        self.assertTrue(text.startswith("Error:"))
        self.assertNotIn("PRIVATE_BAD_TYPE", text)

    async def test_malformed_result_type_is_a_user_error(self):
        text = await self.call("validate_mcp_tool_result", manifest=json.dumps(manifest()),
                               tool_name="orders.lookup", result='{"resultType":{},"structuredContent":{}}',
                               protocol_version="2026-07-28")
        self.assertIn("resultType must be text", text)

    async def test_limits_duplicates_and_protocol_versions(self):
        content = json.dumps(manifest())
        self.assertTrue((await self.call("inspect_mcp_tool_manifest", manifest="x" * 200001)).startswith("Error:"))
        self.assertTrue((await self.call("inspect_mcp_tool_manifest", manifest=content, limit=0)).startswith("Error:"))
        self.assertTrue((await self.call("inspect_mcp_tool_manifest", manifest=content,
                                         protocol_version="unsupported")).startswith("Error:"))
        duplicate = '{"tools":[],"tools":[]}'
        self.assertTrue((await self.call("inspect_mcp_tool_manifest", manifest=duplicate)).startswith("Error:"))
        doc = manifest()
        doc["tools"].append(doc["tools"][0])
        self.assertTrue((await self.call("inspect_mcp_tool_manifest", manifest=json.dumps(doc))).startswith("Error:"))
