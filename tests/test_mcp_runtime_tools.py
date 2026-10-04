import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.mcp_contract_utils import tool


def legacy_profile():
    return {"protocolVersion": "2025-11-25", "serverInfo": {"name": "example", "version": "1.0"},
            "capabilities": {"tools": {"listChanged": True}, "resources": {"subscribe": True},
                             "experimental": {"PRIVATE_KEY": {"secret": "PRIVATE_SETTING"}}},
            "instructions": "PRIVATE_INSTRUCTIONS"}


def modern_profile():
    return {"resultType": "complete", "supportedVersions": ["2026-07-28", "2025-11-25"],
            "capabilities": {"tools": {}, "prompts": {"listChanged": True},
                             "extensions": {"com.example/private": {"token": "PRIVATE_SETTING"}}},
            "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "modern", "version": "2.0"}},
            "ttlMs": 3000, "cacheScope": "private", "instructions": "PRIVATE_INSTRUCTIONS"}


def prompts():
    return {"prompts": [{"name": "review", "arguments": [
        {"name": "code", "required": True}, {"name": "language"}]}]}


class McpRuntimeToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("mcp-runtime-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(block.text for block in blocks if block.type == "text")

    async def result(self, name, **arguments):
        return json.loads(await self.call(name, **arguments))

    async def test_legacy_capabilities_inspection_omits_settings(self):
        response = {"jsonrpc": "2.0", "id": 1, "result": legacy_profile()}
        text = await self.call("inspect_mcp_server_capabilities", response=json.dumps(response))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertEqual(value["declared_protocol_version"], "2025-11-25")
        self.assertEqual(value["server_name"], "example")
        self.assertTrue(value["capabilities"]["tools"]["listChanged"])
        self.assertFalse(value["capabilities"]["prompts"]["present"])
        self.assertEqual(value["experimental_count"], 1)
        self.assertIsNone(value["supported_versions"])

    async def test_modern_capabilities_inspection_and_version_boundaries(self):
        value = await self.result("inspect_mcp_server_capabilities", response=json.dumps(modern_profile()),
                                  protocol_version="2026-07-28")
        self.assertEqual(value["supported_versions"], ["2026-07-28", "2025-11-25"])
        self.assertEqual(value["cache_scope"], "private")
        self.assertEqual(value["extension_count"], 1)
        self.assertTrue((await self.call("inspect_mcp_server_capabilities",
                                         response=json.dumps(modern_profile()))).startswith("Error:"))
        self.assertTrue((await self.call("inspect_mcp_server_capabilities",
                                         response=json.dumps(legacy_profile()),
                                         protocol_version="2026-07-28")).startswith("Error:"))

    async def test_capabilities_comparison_selected_flags_and_private_changes(self):
        old, new = modern_profile(), modern_profile()
        new["supportedVersions"].reverse()
        unchanged = await self.result("compare_mcp_server_capabilities", before=json.dumps(old),
                                      after=json.dumps(new), protocol_version="2026-07-28")
        self.assertEqual(unchanged["selected_change_count"], 0)
        new["capabilities"]["prompts"]["listChanged"] = False
        new["capabilities"]["resources"] = {"subscribe": True}
        new["capabilities"]["extensions"] = {"com.example/new": {"token": "NEW_PRIVATE_SETTING"}}
        new["instructions"] = "NEW_PRIVATE_INSTRUCTIONS"
        new["supportedVersions"] = ["2026-07-28"]
        text = await self.call("compare_mcp_server_capabilities", before=json.dumps(old),
                               after=json.dumps(new), protocol_version="2026-07-28")
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertEqual({row["field"] for row in value["changes"]},
                         {"supportedVersions", "prompts.listChanged", "resources.present",
                          "resources.subscribe", "extensions", "instructions"})

    async def test_capability_profile_malformed_and_error_rejected(self):
        bad = legacy_profile()
        bad["capabilities"]["tools"]["listChanged"] = "yes"
        self.assertTrue((await self.call("inspect_mcp_server_capabilities", response=json.dumps(bad))).startswith("Error:"))
        error = {"jsonrpc": "2.0", "id": 1, "error": {"message": "PRIVATE_ERROR"}}
        text = await self.call("inspect_mcp_server_capabilities", response=json.dumps(error))
        self.assertTrue(text.startswith("Error:"))
        self.assertNotIn("PRIVATE_ERROR", text)
        modern = modern_profile()
        modern["supportedVersions"] = ["2026-07-28", "2026-07-28"]
        self.assertTrue((await self.call("inspect_mcp_server_capabilities", response=json.dumps(modern),
                                         protocol_version="2026-07-28")).startswith("Error:"))
        modern = modern_profile()
        modern["ttlMs"] = True
        self.assertTrue((await self.call("inspect_mcp_server_capabilities", response=json.dumps(modern),
                                         protocol_version="2026-07-28")).startswith("Error:"))
        modern = modern_profile()
        modern["supportedVersions"] = ["2025-11-25"]
        self.assertTrue((await self.call("inspect_mcp_server_capabilities", response=json.dumps(modern),
                                         protocol_version="2026-07-28")).startswith("Error:"))

    async def test_prompt_arguments_required_types_and_unknown_names(self):
        value = await self.result("validate_mcp_prompt_arguments", manifest=json.dumps(prompts()),
                                  prompt_name="review", arguments=json.dumps({"language": "Python", "extra": "yes"}))
        self.assertFalse(value["valid"])
        self.assertEqual(value["missing_required"], ["code"])
        self.assertEqual(value["undeclared_arguments"], ["extra"])
        text = await self.call("validate_mcp_prompt_arguments", manifest=json.dumps(prompts()),
                               prompt_name="review", arguments=json.dumps({"code": "PRIVATE_CODE", "extra": "PRIVATE_VALUE"}))
        self.assertNotIn("PRIVATE_", text)
        self.assertTrue(json.loads(text)["valid"])
        value = await self.result("validate_mcp_prompt_arguments", manifest=json.dumps(prompts()),
                                  prompt_name="review", arguments=json.dumps({"code": 42}))
        self.assertFalse(value["valid"])
        self.assertEqual(value["non_string_arguments"], ["code"])

    async def test_prompt_arguments_partial_and_absent(self):
        page = prompts()
        page["nextCursor"] = "PRIVATE_CURSOR"
        value = await self.result("validate_mcp_prompt_arguments", manifest=json.dumps(page),
                                  prompt_name="review", arguments='{"code":"ok"}')
        self.assertTrue(value["catalog_partial"])
        self.assertTrue(value["valid"])
        text = await self.call("validate_mcp_prompt_arguments", manifest=json.dumps(page),
                               prompt_name="missing", arguments="{}")
        self.assertIn("follow nextCursor", text)

    async def test_resource_read_text_blob_and_empty(self):
        result = {"contents": [{"uri": "docs://private", "text": "PRIVATE_TEXT"},
                               {"uri": "docs://private/image", "mimeType": "image/png", "blob": "aGVsbG8="}]}
        text = await self.call("validate_mcp_resource_read_result", response=json.dumps(result))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["content_kinds"], {"text": 1, "blob": 1})
        self.assertTrue((await self.result("validate_mcp_resource_read_result",
                                           response='{"contents":[]}'))["valid"])

    async def test_modern_completed_read_and_prompt_results(self):
        read = {"jsonrpc": "2.0", "id": 2, "result": {"resultType": "complete",
                "contents": [{"uri": "docs://private", "text": "PRIVATE_TEXT"}],
                "ttlMs": 1000, "cacheScope": "private"}}
        self.assertTrue((await self.result("validate_mcp_resource_read_result", response=json.dumps(read),
                                           protocol_version="2026-07-28"))["valid"])
        prompt = {"resultType": "complete", "messages": [
            {"role": "user", "content": {"type": "text", "text": "PRIVATE_TEXT"}}]}
        self.assertTrue((await self.result("validate_mcp_prompt_get_result", response=json.dumps(prompt),
                                           protocol_version="2026-07-28"))["valid"])

    async def test_resource_read_invalid_fields_and_cache_hints(self):
        result = {"resultType": "complete", "contents": [
            {"uri": "docs://x", "text": "secret", "blob": "aGVsbG8="},
            {"uri": "docs://y", "blob": "NOT_BASE64"}, {"text": "secret"}],
                  "ttlMs": 0, "cacheScope": "private"}
        value = await self.result("validate_mcp_resource_read_result", response=json.dumps(result),
                                  protocol_version="2026-07-28")
        self.assertFalse(value["valid"])
        self.assertEqual({row["code"] for row in value["errors"]},
                         {"exactly_one_text_or_blob_required", "blob_must_be_base64", "uri_required"})
        result["contents"].append({"uri": "relative/path", "text": "secret"})
        value = await self.result("validate_mcp_resource_read_result", response=json.dumps(result),
                                  protocol_version="2026-07-28")
        self.assertIn("uri_required", {row["code"] for row in value["errors"]})
        result["cacheScope"] = "wrong"
        value = await self.result("validate_mcp_resource_read_result", response=json.dumps(result),
                                  protocol_version="2026-07-28")
        self.assertIn("cache_hints_invalid", {row["code"] for row in value["errors"]})

    async def test_input_required_not_mistaken_for_complete(self):
        pending = {"resultType": "input_required", "requestState": "PRIVATE_STATE"}
        for name in ("validate_mcp_resource_read_result", "validate_mcp_prompt_get_result"):
            text = await self.call(name, response=json.dumps(pending), protocol_version="2026-07-28")
            self.assertNotIn("PRIVATE_STATE", text)
            value = json.loads(text)
            self.assertFalse(value["checked"])
            self.assertIsNone(value["valid"])
            self.assertEqual(value["reason"], "input_required")
        self.assertTrue((await self.call("validate_mcp_resource_read_result",
                                         response=json.dumps({"resultType": "input_required"}),
                                         protocol_version="2026-07-28")).startswith("Error:"))
        self.assertTrue((await self.call("validate_mcp_prompt_get_result", response=json.dumps(pending))).startswith("Error:"))

    async def test_prompt_get_all_supported_content_kinds_and_redaction(self):
        value = {"messages": [
            {"role": "user", "content": {"type": "text", "text": "PRIVATE_TEXT"}},
            {"role": "assistant", "content": {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"}},
            {"role": "user", "content": {"type": "audio", "data": "aGVsbG8=", "mimeType": "audio/wav"}},
            {"role": "assistant", "content": {"type": "resource", "resource": {
                "uri": "docs://PRIVATE_URI", "text": "PRIVATE_RESOURCE"}}},
            {"role": "user", "content": {"type": "resource_link", "uri": "docs://PRIVATE_LINK", "name": "link"}}],
                 "description": "PRIVATE_DESCRIPTION"}
        text = await self.call("validate_mcp_prompt_get_result", response=json.dumps(value))
        self.assertNotIn("PRIVATE_", text)
        result = json.loads(text)
        self.assertTrue(result["valid"])
        self.assertEqual(result["message_count"], 5)
        self.assertEqual(set(result["content_kinds"]),
                         {"text", "image", "audio", "resource", "resource_link"})

    async def test_prompt_get_rejects_bad_role_and_blocks(self):
        value = {"resultType": "complete", "messages": [
            {"role": "system", "content": {"type": "text", "text": "PRIVATE_TEXT"}},
            {"role": "user", "content": {"type": "image", "data": "bad", "mimeType": "image/png"}},
            {"role": "assistant", "content": {"type": "unknown", "text": "PRIVATE_TEXT"}},
            {"role": "user", "content": {"type": "resource", "resource": {"uri": "docs://x", "blob": "bad"}}}]}
        text = await self.call("validate_mcp_prompt_get_result", response=json.dumps(value),
                               protocol_version="2026-07-28")
        self.assertNotIn("PRIVATE_TEXT", text)
        result = json.loads(text)
        self.assertFalse(result["valid"])
        self.assertEqual({row["code"] for row in result["errors"]},
                         {"unsupported_role", "data_must_be_base64", "unsupported_content_type",
                          "blob_must_be_base64"})

    async def test_shared_limits_and_duplicate_keys(self):
        self.assertTrue((await self.call("validate_mcp_prompt_get_result",
                                         response='{"messages":[],"messages":[]}')).startswith("Error:"))
        self.assertTrue((await self.call("validate_mcp_resource_read_result",
                                         response="x" * 200001)).startswith("Error:"))
        self.assertTrue((await self.call("validate_mcp_prompt_arguments", manifest=json.dumps(prompts()),
                                         prompt_name="review", arguments="{}", limit=0)).startswith("Error:"))
        self.assertTrue((await self.call("inspect_mcp_server_capabilities", response=json.dumps(legacy_profile()),
                                         protocol_version="unsupported")).startswith("Error:"))
