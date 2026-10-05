import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.mcp_contract_utils import tool


def call_request(request_id, name="demo", arguments=None):
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments if arguments is not None else {}}}


class McpReliabilityToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("mcp-reliability-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(block.text for block in blocks if block.type == "text")

    async def inspect(self, name, **arguments):
        return json.loads(await self.call(name, **arguments))

    async def test_sse_streamable_messages_comments_and_redaction(self):
        content = (': PRIVATE_KEEPALIVE\r\n\r\n'
                   'id: PRIVATE_ID\r\nretry: 1000\r\ndata: \r\n\r\n'
                   'event: message\r\ndata: {"jsonrpc":"2.0","method":"notifications/progress",\r\n'
                   'data: "params":{"message":"PRIVATE_BODY"}}\r\n\r\n'
                   'data: {"jsonrpc":"2.0","id":1,"result":{"private":"PRIVATE_RESULT"}}\r\n\r\n')
        text = await self.call("inspect_mcp_sse_trace", content=content)
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["frame_count"], 3)
        self.assertEqual(value["counts"]["comment"], 1)
        self.assertEqual(value["counts"]["empty"], 1)
        self.assertEqual(value["counts"]["notification"], 1)
        self.assertEqual(value["counts"]["response"], 1)

    async def test_sse_legacy_endpoint_and_2026_restrictions(self):
        legacy = 'event: endpoint\ndata: /messages?token=PRIVATE_TOKEN\n\n'
        value = await self.inspect("inspect_mcp_sse_trace", content=legacy, mode="legacy-sse")
        self.assertTrue(value["valid"])
        self.assertEqual(value["counts"]["endpoint"], 1)
        value = await self.inspect("inspect_mcp_sse_trace", content=legacy)
        self.assertIn("endpoint_event_in_streamable_http", {item["code"] for item in value["issues"]})
        request = 'id: cursor\ndata: {"jsonrpc":"2.0","id":1,"method":"roots/list"}\n\n'
        value = await self.inspect("inspect_mcp_sse_trace", content=request, protocol_version="2026-07-28")
        self.assertEqual({item["code"] for item in value["issues"]},
                         {"event_id_not_supported_2026", "server_request_not_supported_2026"})
        self.assertIn("Error:", await self.call("inspect_mcp_sse_trace", content=legacy,
                                                mode="legacy-sse", protocol_version="2026-07-28"))

    async def test_sse_invalid_message_duplicate_id_and_partial_frame(self):
        content = ('id: repeated\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
                   'id: repeated\ndata: PRIVATE_BAD_JSON\n\n'
                   'data: {"jsonrpc":"2.0"}')
        value = await self.inspect("inspect_mcp_sse_trace", content=content)
        self.assertFalse(value["valid"])
        self.assertTrue(value["partial_frame"])
        self.assertEqual(value["frame_count"], 2)
        self.assertEqual({item["code"] for item in value["issues"]},
                         {"event_id_reused", "jsonrpc_message_invalid"})

    async def test_session_recovery_and_redaction(self):
        exchanges = [
            {"method": "POST", "initialize": True, "response_status": 200,
             "response_headers": {"Mcp-Session-Id": "PRIVATE_SESSION"}},
            {"method": "POST", "response_status": 200, "stream": "PRIVATE_STREAM",
             "request_headers": {"Mcp-Session-Id": "PRIVATE_SESSION", "Mcp-Protocol-Version": "2025-11-25"},
             "event_ids": ["PRIVATE_EVENT"]},
            {"method": "GET", "response_status": 404, "stream": "PRIVATE_STREAM",
             "request_headers": {"Mcp-Session-Id": "PRIVATE_SESSION", "Mcp-Protocol-Version": "2025-11-25",
                                 "Last-Event-ID": "PRIVATE_EVENT"}},
            {"method": "POST", "initialize": True, "response_status": 200,
             "response_headers": {"Mcp-Session-Id": "PRIVATE_NEW_SESSION"}},
        ]
        text = await self.call("inspect_mcp_session_recovery", exchanges=json.dumps(exchanges))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["counts"]["resumption"], 1)
        self.assertEqual(value["counts"]["session_expired"], 1)

    async def test_session_mismatch_and_cross_stream_resume(self):
        exchanges = [
            {"method": "POST", "initialize": True, "response_status": 200,
             "response_headers": {"Mcp-Session-Id": "session"}},
            {"method": "POST", "response_status": 200, "stream": "a",
             "request_headers": {"Mcp-Session-Id": "wrong", "Mcp-Protocol-Version": "2025-11-25"},
             "event_ids": ["event"]},
            {"method": "GET", "response_status": 200, "stream": "b",
             "request_headers": {"Mcp-Session-Id": "session", "Mcp-Protocol-Version": "2025-11-25",
                                 "Last-Event-ID": "event"}},
        ]
        value = await self.inspect("inspect_mcp_session_recovery", exchanges=json.dumps(exchanges))
        self.assertEqual({item["code"] for item in value["issues"]},
                         {"session_id_missing_or_mismatch", "resume_stream_mismatch"})

    async def test_session_expiry_at_end_is_pending_not_invalid(self):
        exchanges = [
            {"method": "POST", "initialize": True, "response_status": 200,
             "response_headers": {"Mcp-Session-Id": "session"}, "event_ids": ["first"]},
            {"method": "GET", "response_status": 404,
             "request_headers": {"Mcp-Session-Id": "session", "Mcp-Protocol-Version": "2025-11-25",
                                 "Last-Event-ID": "first"}},
        ]
        value = await self.inspect("inspect_mcp_session_recovery", exchanges=json.dumps(exchanges))
        self.assertTrue(value["valid"])
        self.assertTrue(value["reinitialize_required"])
        self.assertEqual(value["counts"]["event_ids"], 1)

    async def test_session_delete_at_end_and_followup_without_init(self):
        exchanges = [
            {"method": "POST", "initialize": True, "response_status": 200,
             "response_headers": {"Mcp-Session-Id": "session"}},
            {"method": "DELETE", "response_status": 204,
             "request_headers": {"Mcp-Session-Id": "session", "Mcp-Protocol-Version": "2025-11-25"}},
        ]
        value = await self.inspect("inspect_mcp_session_recovery", exchanges=json.dumps(exchanges))
        self.assertTrue(value["valid"])
        self.assertTrue(value["reinitialize_required"])
        exchanges.append({"method": "POST", "response_status": 200,
                          "request_headers": {"Mcp-Session-Id": "session",
                                              "Mcp-Protocol-Version": "2025-11-25"}})
        value = await self.inspect("inspect_mcp_session_recovery", exchanges=json.dumps(exchanges))
        self.assertIn("reinitialize_required", {item["code"] for item in value["issues"]})

    async def test_session_unsupported_header_values_and_bounds(self):
        rows = [{"method": "POST", "initialize": True, "response_status": 200,
                 "response_headers": {"Mcp-Session-Id": "bad value"}}]
        value = await self.inspect("inspect_mcp_session_recovery", exchanges=json.dumps(rows))
        self.assertIn("session_id_invalid", {item["code"] for item in value["issues"]})
        self.assertIn("Error:", await self.call("inspect_mcp_session_recovery",
                                                exchanges=json.dumps(rows * 101)))

    async def test_retry_risk_hints_are_not_safety_claims(self):
        manifest = {"tools": [
            {"name": "writer", "inputSchema": {"type": "object"}},
            {"name": "reader", "inputSchema": {"type": "object"},
             "annotations": {"readOnlyHint": True, "idempotentHint": True}},
        ]}
        calls = [call_request(1, "writer", {"secret": "PRIVATE_VALUE"}),
                 call_request(2, "writer", {"secret": "PRIVATE_VALUE"}),
                 call_request(3, "reader"), call_request(4, "reader")]
        text = await self.call("inspect_mcp_tool_retry_risk", manifest=json.dumps(manifest),
                               attempts=json.dumps(calls))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["repeat_count"], 2)
        self.assertEqual(value["repeats"][0]["risk"], "possible_duplicate_effect")
        self.assertEqual(value["repeats"][1]["risk"], "hinted_lower_risk")
        self.assertTrue(value["repeats"][1]["read_only_hint"])

    async def test_retry_reused_id_unknown_tool_partial_catalog_and_limit(self):
        manifest = {"tools": [{"name": "demo", "inputSchema": {"type": "object"}}]}
        calls = [call_request(1), call_request(1), call_request(2, "unknown")]
        value = await self.inspect("inspect_mcp_tool_retry_risk", manifest=json.dumps(manifest),
                                   attempts=json.dumps(calls), limit=1)
        self.assertEqual(value["issue_count"], 2)
        self.assertEqual(len(value["issues"]), 1)
        self.assertTrue(value["truncated"])
        manifest["nextCursor"] = "cursor"
        self.assertIn("Error:", await self.call("inspect_mcp_tool_retry_risk",
                                                manifest=json.dumps(manifest), attempts=json.dumps(calls)))


class DeployedCatalogComparisonTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_catalog_contains_new_tools(self):
        from scripts.test_deployed_mcp import _local_tool_names

        names = await _local_tool_names()
        self.assertEqual(len(names), 183)
        self.assertTrue({"inspect_mcp_sse_trace", "inspect_mcp_session_recovery",
                         "inspect_mcp_tool_retry_risk"}.issubset(names))

    def test_catalog_comparison_rejects_drift_and_duplicates(self):
        from scripts.test_deployed_mcp import _check_catalog

        _check_catalog({"a", "b"}, ["b", "a"])
        with self.assertRaisesRegex(RuntimeError, "1 missing, 1 unexpected"):
            _check_catalog({"a", "b"}, ["a", "c"])
        with self.assertRaisesRegex(RuntimeError, "1 duplicate"):
            _check_catalog({"a"}, ["a", "a"])
