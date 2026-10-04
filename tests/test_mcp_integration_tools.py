import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.mcp_contract_utils import tool


def tool_page(name, cursor=None):
    page = {"tools": [{"name": name, "inputSchema": {"type": "object"}}]}
    if cursor is not None:
        page["nextCursor"] = cursor
    return page


def prompt_catalog(cursor=None):
    page = {"prompts": [{"name": "review", "arguments": [{"name": "code", "required": True},
                                                       {"name": "language"}]}]}
    if cursor is not None:
        page["nextCursor"] = cursor
    return page


class McpIntegrationToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("mcp-integration-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(block.text for block in blocks if block.type == "text")

    async def result(self, name, **arguments):
        return json.loads(await self.call(name, **arguments))

    async def test_empty_cursor_is_partial_in_existing_catalog_tools(self):
        tools = tool_page("first", "")
        inspected = await self.result("inspect_mcp_tool_manifest", manifest=json.dumps(tools))
        self.assertTrue(inspected["partial_list"])
        compared = await self.call("compare_mcp_tool_manifests", before=json.dumps(tools),
                                   after=json.dumps(tool_page("first")))
        self.assertIn("complete tools/list", compared)
        resources = {"resources": [{"uri": "docs://guide", "name": "guide"}], "nextCursor": ""}
        inspected = await self.result("inspect_mcp_resource_manifest", resources=json.dumps(resources))
        self.assertTrue(inspected["resource_list_partial"])
        prompts = prompt_catalog("")
        inspected = await self.result("inspect_mcp_prompt_manifest", manifest=json.dumps(prompts))
        self.assertTrue(inspected["partial_list"])

    async def test_paginated_catalog_empty_cursor_and_chain(self):
        pages = [tool_page("first", ""), tool_page("second")]
        value = await self.result("inspect_mcp_paginated_catalog", pages=json.dumps(pages), kind="tools",
                                  request_cursors='[null, ""]')
        self.assertEqual(value["page_count"], 2)
        self.assertEqual(value["entry_count"], 2)
        self.assertTrue(value["pages"][0]["has_next_cursor"])
        self.assertTrue(value["complete_chain"])
        self.assertEqual(value["issue_count"], 0)
        self.assertNotIn('"nextCursor": ""', json.dumps(value))

    async def test_paginated_catalog_modern_wrappers_and_cache(self):
        pages = [{"jsonrpc": "2.0", "id": 1, "result": {"resultType": "complete",
                  "ttlMs": 0, "cacheScope": "private", "prompts": [{"name": "review"}],
                  "nextCursor": "PRIVATE_CURSOR"}},
                 {"resultType": "complete", "ttlMs": 10, "cacheScope": "public",
                  "prompts": [{"name": "summarize"}]}]
        text = await self.call("inspect_mcp_paginated_catalog", pages=json.dumps(pages), kind="prompts",
                               request_cursors=json.dumps([None, "PRIVATE_CURSOR"]),
                               protocol_version="2026-07-28")
        self.assertNotIn("PRIVATE_CURSOR", text)
        self.assertTrue(json.loads(text)["complete_chain"])
        del pages[1]["cacheScope"]
        self.assertTrue((await self.call("inspect_mcp_paginated_catalog", pages=json.dumps(pages),
                                         kind="prompts", protocol_version="2026-07-28")).startswith("Error:"))
        pages[1]["cacheScope"] = "public"
        pages[1]["ttlMs"] = 1.5
        self.assertTrue((await self.call("inspect_mcp_paginated_catalog", pages=json.dumps(pages),
                                         kind="prompts", protocol_version="2026-07-28")).startswith("Error:"))

    async def test_paginated_catalog_detects_duplicates_and_cursor_reuse(self):
        pages = [tool_page("secret", "repeat"), tool_page("secret", "repeat"), tool_page("last")]
        pages[1]["tools"].append({"name": "secret", "inputSchema": {"type": "object"}})
        value = await self.result("inspect_mcp_paginated_catalog", pages=json.dumps(pages), kind="tools",
                                  request_cursors=json.dumps([None, "repeat", "repeat"]))
        self.assertEqual(value["duplicate_identity_count"], 2)
        self.assertEqual(value["cursor_reuse_count"], 1)
        self.assertFalse(value["complete_chain"])
        self.assertNotIn("secret", json.dumps(value))
        self.assertNotIn("repeat", json.dumps(value))

    async def test_paginated_catalog_indeterminate_or_broken_chain(self):
        pages = [tool_page("first", "cursor"), tool_page("second")]
        value = await self.result("inspect_mcp_paginated_catalog", pages=json.dumps(pages), kind="tools")
        self.assertIsNone(value["complete_chain"])
        self.assertFalse(value["request_cursor_chain_checked"])
        wrong = await self.result("inspect_mcp_paginated_catalog", pages=json.dumps(pages), kind="tools",
                                  request_cursors='[null, "wrong"]')
        self.assertFalse(wrong["request_cursor_chain_valid"])
        self.assertIn("request_cursor_mismatch", {item["code"] for item in wrong["issues"]})
        after_end = await self.result("inspect_mcp_paginated_catalog",
                                      pages=json.dumps([tool_page("first"), tool_page("second")]), kind="tools")
        self.assertIn("page_after_terminal", {item["code"] for item in after_end["issues"]})

    async def test_paginated_catalog_resource_and_template_identities(self):
        for kind, field, key in (("resources", "resources", "uri"),
                                 ("resource_templates", "resourceTemplates", "uriTemplate")):
            pages = [{field: [{key: "docs://private", "name": "PRIVATE_NAME"}], "nextCursor": "x"},
                     {field: [{key: "docs://private", "name": "PRIVATE_NAME"}]}]
            value = await self.result("inspect_mcp_paginated_catalog", pages=json.dumps(pages), kind=kind,
                                      request_cursors='[null,"x"]')
            self.assertEqual(value["duplicate_identity_count"], 1)
            self.assertNotIn("PRIVATE_NAME", json.dumps(value))

    async def test_completion_request_prompt_catalog_and_context(self):
        request = {"jsonrpc": "2.0", "id": 1, "method": "completion/complete", "params": {
            "ref": {"type": "ref/prompt", "name": "review"},
            "argument": {"name": "language", "value": "PRIVATE_PREFIX"},
            "context": {"arguments": {"code": "PRIVATE_CODE"}}}}
        text = await self.call("validate_mcp_completion_request", request=json.dumps(request),
                               catalog=json.dumps(prompt_catalog()))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertTrue(value["argument_declared"])
        self.assertEqual(value["context_argument_count"], 1)
        request["params"]["argument"]["name"] = "undeclared"
        value = await self.result("validate_mcp_completion_request", request=json.dumps(request),
                                  catalog=json.dumps(prompt_catalog()))
        self.assertFalse(value["valid"])
        self.assertFalse(value["argument_declared"])

    async def test_completion_request_partial_catalog_indeterminate(self):
        request = {"ref": {"type": "ref/prompt", "name": "missing"},
                   "argument": {"name": "topic", "value": ""}}
        value = await self.result("validate_mcp_completion_request", request=json.dumps(request),
                                  catalog=json.dumps(prompt_catalog("")))
        self.assertFalse(value["checked"])
        self.assertIsNone(value["valid"])
        self.assertTrue(value["catalog_partial"])
        value = await self.result("validate_mcp_completion_request", request=json.dumps(request),
                                  catalog=json.dumps(prompt_catalog()))
        self.assertTrue(value["checked"])
        self.assertFalse(value["valid"])

    async def test_completion_request_resource_exact_reference(self):
        catalog = {"resourceTemplates": [{"uriTemplate": "docs://items/{id}", "name": "item"}]}
        request = {"ref": {"type": "ref/resource", "uri": "docs://items/{id}"},
                   "argument": {"name": "id", "value": "PRIVATE_VALUE"}}
        value = await self.result("validate_mcp_completion_request", request=json.dumps(request),
                                  catalog=json.dumps(catalog))
        self.assertTrue(value["valid"])
        self.assertEqual(value["catalog_kind"], "resource_templates")
        self.assertIsNone(value["argument_declared"])
        request["ref"]["uri"] = "docs://items/1"
        value = await self.result("validate_mcp_completion_request", request=json.dumps(request),
                                  catalog=json.dumps(catalog))
        self.assertFalse(value["valid"])

    async def test_completion_request_rejects_malformed_values(self):
        request = {"ref": {"type": "ref/prompt", "name": "review"},
                   "argument": {"name": "code", "value": 3}}
        self.assertTrue((await self.call("validate_mcp_completion_request", request=json.dumps(request),
                                         catalog=json.dumps(prompt_catalog()))).startswith("Error:"))
        request["argument"]["value"] = "ok"
        request["context"] = {"arguments": {"code": 3}}
        self.assertTrue((await self.call("validate_mcp_completion_request", request=json.dumps(request),
                                         catalog=json.dumps(prompt_catalog()))).startswith("Error:"))

    async def test_completion_result_legacy_and_modern_redact_values(self):
        result = {"completion": {"values": ["PRIVATE_ONE", "PRIVATE_TWO"], "total": 4, "hasMore": True}}
        text = await self.call("validate_mcp_completion_result", response=json.dumps(result))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["value_count"], 2)
        result["resultType"] = "complete"
        value = await self.result("validate_mcp_completion_result", response=json.dumps(result),
                                  protocol_version="2026-07-28")
        self.assertTrue(value["valid"])
        del result["resultType"]
        self.assertTrue((await self.call("validate_mcp_completion_result", response=json.dumps(result),
                                         protocol_version="2026-07-28")).startswith("Error:"))

    async def test_completion_result_limits_and_inconsistency(self):
        result = {"completion": {"values": ["x"] * 101}}
        value = await self.result("validate_mcp_completion_result", response=json.dumps(result))
        self.assertFalse(value["valid"])
        self.assertIn("array_of_at_most_100_required", {item["code"] for item in value["issues"]})
        result = {"completion": {"values": ["x", 2], "total": 1, "hasMore": True}}
        value = await self.result("validate_mcp_completion_result", response=json.dumps(result))
        self.assertFalse(value["valid"])
        self.assertEqual({item["code"] for item in value["issues"]},
                         {"all_values_must_be_strings", "total_less_than_returned", "conflicts_with_total"})

    async def test_jsonrpc_error_classification_and_redaction(self):
        response = {"jsonrpc": "2.0", "id": "PRIVATE_ID", "error": {
            "code": -32602, "message": "PRIVATE_MESSAGE", "data": {"secret": "PRIVATE_DATA"}}}
        text = await self.call("inspect_mcp_jsonrpc_error", response=json.dumps(response))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertEqual(value["classification"], "invalid_params")
        self.assertTrue(value["data_present"])
        response["error"]["code"] = -32002
        value = await self.result("inspect_mcp_jsonrpc_error", response=json.dumps(response))
        self.assertEqual(value["classification"], "legacy_resource_not_found")
        response["error"]["code"] = -32020
        value = await self.result("inspect_mcp_jsonrpc_error", response=json.dumps(response),
                                  protocol_version="2026-07-28")
        self.assertEqual(value["classification"], "header_mismatch")

    async def test_jsonrpc_error_version_hint_and_unknown_code(self):
        response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32022,
                    "message": "PRIVATE_MESSAGE", "data": {"requested": "2026-07-28",
                                                        "supported": ["2025-11-25"]}}}
        value = await self.result("inspect_mcp_jsonrpc_error", response=json.dumps(response),
                                  protocol_version="2026-07-28")
        self.assertEqual(value["classification"], "unsupported_protocol_version")
        self.assertTrue(value["version_hint_shape_valid"])
        self.assertEqual(value["supported_version_count"], 1)
        response["error"]["code"] = -32123
        value = await self.result("inspect_mcp_jsonrpc_error", response=json.dumps(response))
        self.assertEqual(value["classification"], "other")
        self.assertFalse(value["known_for_version"])

    async def test_input_limits_and_malformed_json(self):
        self.assertTrue((await self.call("inspect_mcp_paginated_catalog", pages="x" * 200001,
                                         kind="tools")).startswith("Error:"))
        self.assertTrue((await self.call("inspect_mcp_paginated_catalog", pages="[]",
                                         kind="tools")).startswith("Error:"))
        self.assertTrue((await self.call("validate_mcp_completion_result",
                                         response='{"completion":{},"completion":{}}')).startswith("Error:"))
        self.assertTrue((await self.call("inspect_mcp_jsonrpc_error", response=json.dumps({
            "jsonrpc": "2.0", "error": {"code": True, "message": "bad"}}))).startswith("Error:"))
        self.assertTrue((await self.call("inspect_mcp_jsonrpc_error", response=json.dumps({
            "jsonrpc": "2.0", "error": {"code": -32600, "message": "bad"}}), limit=0)).startswith("Error:"))
