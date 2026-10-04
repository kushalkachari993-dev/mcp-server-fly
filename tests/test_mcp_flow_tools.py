import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.mcp_contract_utils import tool


def request(method, params=None, request_id="PRIVATE_REQUEST_ID"):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def result(payload, request_id="PRIVATE_REQUEST_ID"):
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


class McpFlowToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("mcp-flow-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        response = await self.mcp.call_tool(name, arguments)
        blocks = response[0] if isinstance(response, tuple) else response
        return "\n".join(block.text for block in blocks if block.type == "text")

    async def inspect(self, name, **arguments):
        return json.loads(await self.call(name, **arguments))

    async def test_content_blocks_all_kinds_and_redaction(self):
        blocks = [{"type": "text", "text": "PRIVATE_TEXT"},
                  {"type": "image", "data": "YQ==", "mimeType": "image/png"},
                  {"type": "audio", "data": "YQ==", "mimeType": "audio/wav"},
                  {"type": "resource_link", "uri": "file:///PRIVATE_PATH", "name": "PRIVATE_NAME"},
                  {"type": "resource", "resource": {"uri": "file:///PRIVATE_PATH", "text": "PRIVATE_TEXT"}}]
        text = await self.call("validate_mcp_tool_content_blocks",
                               result=json.dumps(result({"resultType": "complete", "content": blocks})),
                               protocol_version="2026-07-28")
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["content_count"], 5)
        self.assertEqual(value["content_kinds"], {kind: 1 for kind in
                         ("text", "image", "audio", "resource_link", "resource")})

    async def test_content_blocks_invalid_and_pending(self):
        blocks = [{"type": "text", "text": 9},
                  {"type": "image", "data": "PRIVATE_BAD_BASE64", "mimeType": "image/png"},
                  {"type": "resource", "resource": {"uri": "relative", "text": "x", "blob": "YQ=="}},
                  {"type": "resource_link", "uri": "relative", "name": "PRIVATE_NAME",
                   "annotations": []}]
        text = await self.call("validate_mcp_tool_content_blocks", result=json.dumps({"content": blocks}))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertFalse(value["valid"])
        self.assertTrue({"text_must_be_string", "data_must_be_base64", "uri_required",
                         "exactly_one_text_or_blob_required", "resource_link_identity_invalid", "object_required"}
                        <= {item["code"] for item in value["errors"]})
        pending = await self.inspect("validate_mcp_tool_content_blocks",
                                     result=json.dumps({"resultType": "input_required", "inputRequests": {}}),
                                     protocol_version="2026-07-28")
        self.assertFalse(pending["checked"])
        self.assertIsNone(pending["valid"])
        oversized = await self.inspect("validate_mcp_tool_content_blocks",
                                       result=json.dumps({"content": [{}] * 501}))
        self.assertFalse(oversized["valid"])
        self.assertIn("array_of_at_most_500_required", {item["code"] for item in oversized["errors"]})

    async def test_call_roundtrip_outcomes_and_redaction(self):
        call = request("tools/call", {"name": "PRIVATE_TOOL", "arguments": {"secret": "PRIVATE_VALUE"}})
        for payload, expected in [({"content": [{"type": "text", "text": "PRIVATE_VALUE"}]}, "success"),
                                  ({"content": [], "isError": True}, "tool_error")]:
            text = await self.call("validate_mcp_call_roundtrip", request=json.dumps(call),
                                   response=json.dumps(result(payload)))
            self.assertNotIn("PRIVATE_", text)
            value = json.loads(text)
            self.assertTrue(value["valid"])
            self.assertEqual(value["outcome"], expected)
        error = {"jsonrpc": "2.0", "id": "PRIVATE_REQUEST_ID",
                 "error": {"code": -32602, "message": "PRIVATE_ERROR"}}
        text = await self.call("validate_mcp_call_roundtrip", request=json.dumps(call),
                               response=json.dumps(error))
        self.assertNotIn("PRIVATE_", text)
        self.assertEqual(json.loads(text)["outcome"], "jsonrpc_error")

    async def test_call_roundtrip_mismatches_and_task_capability(self):
        call = request("tools/call", {"name": "x", "arguments": []})
        value = await self.inspect("validate_mcp_call_roundtrip", request=json.dumps(call),
                                   response=json.dumps(result({"isError": "yes"}, "OTHER_ID")))
        self.assertFalse(value["valid"])
        self.assertTrue({"arguments_object_required", "response_id_mismatch", "is_error_boolean_required"}
                        <= {item["code"] for item in value["issues"]})
        task_result = result({"resultType": "task", "taskId": "PRIVATE_TASK_ID"})
        value = await self.inspect("validate_mcp_call_roundtrip", request=json.dumps(call),
                                   response=json.dumps(task_result), protocol_version="2026-07-28")
        self.assertIn("task_extension_not_declared", {item["code"] for item in value["issues"]})
        call["params"]["arguments"] = {}
        call["params"]["_meta"] = {"io.modelcontextprotocol/clientCapabilities": {
            "extensions": {"io.modelcontextprotocol/tasks": {}}}}
        value = await self.inspect("validate_mcp_call_roundtrip", request=json.dumps(call),
                                   response=json.dumps(task_result), protocol_version="2026-07-28")
        self.assertTrue(value["valid"])
        self.assertEqual(value["outcome"], "task")

    async def test_task_update_partial_and_unknown_keys(self):
        snapshot = {"resultType": "complete", "taskId": "PRIVATE_TASK_ID", "status": "input_required",
                    "createdAt": "2026-07-28T10:00:00Z", "lastUpdatedAt": "2026-07-28T10:01:00Z",
                    "ttlMs": 60000, "inputRequests": {
                        "PRIVATE_FIRST": {"method": "elicitation/create", "params": {}},
                        "PRIVATE_SECOND": {"method": "roots/list", "params": {}}}}
        update = request("tasks/update", {"taskId": "PRIVATE_TASK_ID", "inputResponses": {
            "PRIVATE_FIRST": {"action": "accept", "content": {"secret": "PRIVATE_VALUE"}},
            "PRIVATE_OLD": {"action": "decline"}}})
        ack = result({"resultType": "complete"})
        text = await self.call("inspect_mcp_task_update_roundtrip", snapshot=json.dumps(snapshot),
                               update_request=json.dumps(update), update_result=json.dumps(ack))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["matched_response_count"], 1)
        self.assertEqual(value["unexpected_response_count"], 1)
        self.assertEqual(value["remaining_count"], 1)
        self.assertTrue(value["acknowledged"])

    async def test_task_update_detects_wrong_task_and_ack(self):
        snapshot = {"resultType": "complete", "taskId": "PRIVATE_TASK_ID", "status": "input_required",
                    "createdAt": "2026-07-28T10:00:00Z", "lastUpdatedAt": "2026-07-28T10:01:00Z",
                    "ttlMs": 60000, "inputRequests": {"PRIVATE_FIRST": {
                        "method": "elicitation/create", "params": {}}}}
        update = request("tasks/update", {"taskId": "WRONG_ID", "inputResponses": {"PRIVATE_FIRST": []}})
        value = await self.inspect("inspect_mcp_task_update_roundtrip", snapshot=json.dumps(snapshot),
                                   update_request=json.dumps(update),
                                   update_result=json.dumps(result({}, "WRONG_ID")))
        self.assertFalse(value["valid"])
        self.assertTrue({"task_id_mismatch", "input_response_shape_invalid", "ack_id_mismatch",
                         "complete_ack_required"} <= {item["code"] for item in value["issues"]})
        self.assertFalse(value["acknowledged"])

    async def test_cache_invalidation_list_and_exact_resource_uri(self):
        cached = result({"resultType": "complete", "ttlMs": 5000, "cacheScope": "private"})
        changed = {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
        text = await self.call("inspect_mcp_cache_invalidation",
                               request=json.dumps(request("tools/list", {"cursor": "PRIVATE_CURSOR"})),
                               response=json.dumps(cached), notification=json.dumps(changed))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertTrue(value["invalidates"])
        read = request("resources/read", {"uri": "file:///PRIVATE_PATH"})
        updated = {"jsonrpc": "2.0", "method": "notifications/resources/updated",
                   "params": {"uri": "file:///PRIVATE_PATH/child"}}
        value = await self.inspect("inspect_mcp_cache_invalidation", request=json.dumps(read),
                                   response=json.dumps(cached), notification=json.dumps(updated))
        self.assertTrue(value["valid"])
        self.assertFalse(value["invalidates"])
        updated["params"]["uri"] = "file:///PRIVATE_PATH"
        value = await self.inspect("inspect_mcp_cache_invalidation", request=json.dumps(read),
                                   response=json.dumps(cached), notification=json.dumps(updated))
        self.assertTrue(value["invalidates"])

    async def test_cache_invalidation_retry_and_bad_hints(self):
        changed = {"jsonrpc": "2.0", "method": "notifications/resources/list_changed"}
        cached = result({"resultType": "complete", "ttlMs": 1000, "cacheScope": "public"})
        retry = request("resources/templates/list", {"inputResponses": {"PRIVATE_KEY": {}}})
        value = await self.inspect("inspect_mcp_cache_invalidation", request=json.dumps(retry),
                                   response=json.dumps(cached), notification=json.dumps(changed))
        self.assertTrue(value["valid"])
        self.assertFalse(value["cache_eligible"])
        self.assertFalse(value["invalidates"])
        bad = result({"resultType": "complete", "ttlMs": -1, "cacheScope": "unknown"})
        value = await self.inspect("inspect_mcp_cache_invalidation",
                                   request=json.dumps(request("resources/templates/list")),
                                   response=json.dumps(bad), notification=json.dumps(changed))
        self.assertFalse(value["valid"])
        self.assertFalse(value["cache_eligible"])
        self.assertTrue({"ttl_ms_invalid", "cache_scope_invalid"}
                        <= {item["code"] for item in value["issues"]})


if __name__ == "__main__":
    unittest.main()
