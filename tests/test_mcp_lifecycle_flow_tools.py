import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.mcp_contract_utils import tool


_SUB_ID = "io.modelcontextprotocol/subscriptionId"


def request(method, params=None, request_id="PRIVATE_REQUEST_ID"):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def response(result, request_id="PRIVATE_REQUEST_ID"):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def initialize_request():
    return request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                                  "clientInfo": {"name": "PRIVATE_CLIENT", "version": "1.0"}})


def initialize_response(version="2025-11-25"):
    return response({"protocolVersion": version, "capabilities": {"tools": {}},
                     "serverInfo": {"name": "PRIVATE_SERVER", "version": "2.0"},
                     "instructions": "PRIVATE_INSTRUCTIONS"})


def initialized():
    return {"jsonrpc": "2.0", "method": "notifications/initialized"}


def task_event(status, updated, task_id="PRIVATE_TASK_ID", **extra):
    return {"jsonrpc": "2.0", "method": "notifications/tasks", "params": {
        "_meta": {"io.modelcontextprotocol/subscriptionId": "PRIVATE_LISTEN_ID"},
        "taskId": task_id, "status": status, "createdAt": "2026-07-28T10:00:00Z",
        "lastUpdatedAt": updated, "ttlMs": 60000, **extra}}


def listen_request():
    return request("subscriptions/listen", {
        "notifications": {"taskIds": ["PRIVATE_TASK_ID", "PRIVATE_OTHER_TASK"]},
        "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                  "io.modelcontextprotocol/clientCapabilities": {
                      "extensions": {"io.modelcontextprotocol/tasks": {}}}}}, "PRIVATE_LISTEN_ID")


class McpLifecycleFlowToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("mcp-lifecycle-flow-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(block.text for block in blocks if block.type == "text")

    async def inspect(self, name, **arguments):
        return json.loads(await self.call(name, **arguments))

    async def test_initialize_success_and_redaction(self):
        text = await self.call("validate_mcp_initialize_roundtrip",
                               request=json.dumps(initialize_request()),
                               response=json.dumps(initialize_response()),
                               initialized=json.dumps(initialized()),
                               supported_versions=json.dumps(["2025-11-25"]))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["outcome"], "success")
        self.assertTrue(value["compatible"])
        self.assertFalse(value["version_changed"])

    async def test_initialize_counteroffer_and_missing_notification(self):
        arguments = {"request": json.dumps(initialize_request()),
                     "response": json.dumps(initialize_response("2025-06-18")),
                     "initialized": json.dumps(initialized())}
        value = await self.inspect("validate_mcp_initialize_roundtrip", **arguments,
                                   supported_versions=json.dumps(["2025-11-25", "2025-06-18"]))
        self.assertTrue(value["valid"])
        self.assertTrue(value["version_changed"])
        value = await self.inspect("validate_mcp_initialize_roundtrip", **arguments,
                                   supported_versions=json.dumps(["2025-11-25"]))
        self.assertIn("negotiated_version_not_supported_by_client",
                      {item["code"] for item in value["issues"]})
        arguments["response"] = json.dumps(initialize_response())
        arguments["initialized"] = ""
        value = await self.inspect("validate_mcp_initialize_roundtrip", **arguments)
        self.assertIn("initialized_notification_missing", {item["code"] for item in value["issues"]})

    async def test_initialize_jsonrpc_error_and_bad_shapes(self):
        failure = {"jsonrpc": "2.0", "id": "PRIVATE_REQUEST_ID",
                   "error": {"code": -32602, "message": "PRIVATE_ERROR"}}
        text = await self.call("validate_mcp_initialize_roundtrip",
                               request=json.dumps(initialize_request()), response=json.dumps(failure))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["outcome"], "jsonrpc_error")
        value = await self.inspect("validate_mcp_initialize_roundtrip",
                                   request=json.dumps(initialize_request()),
                                   response=json.dumps(response({"protocolVersion": "2026-07-28"}, "WRONG_ID")),
                                   initialized=json.dumps(initialized()))
        self.assertFalse(value["valid"])
        self.assertTrue({"initialize_response_id_mismatch", "negotiated_legacy_version_invalid",
                         "server_capabilities_invalid", "server_info_invalid"}
                        <= {item["code"] for item in value["issues"]})

    async def test_resource_subscription_and_unsubscribe(self):
        subscribe = request("resources/subscribe", {"uri": "file:///PRIVATE_RESOURCE"})
        unsubscribe = request("resources/unsubscribe", {"uri": "file:///PRIVATE_RESOURCE"}, "PRIVATE_UNSUB_ID")
        event = {"jsonrpc": "2.0", "method": "notifications/resources/updated",
                 "params": {"uri": "file:///PRIVATE_RESOURCE"}}
        text = await self.call("inspect_mcp_resource_subscription_flow",
                               subscribe_request=json.dumps(subscribe), subscribe_result=json.dumps(response({})),
                               notifications=json.dumps([event]), unsubscribe_request=json.dumps(unsubscribe),
                               unsubscribe_result=json.dumps(response({}, "PRIVATE_UNSUB_ID")))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["matching_update_count"], 1)
        self.assertTrue(value["subscribe_acknowledged"])
        self.assertTrue(value["unsubscribe_acknowledged"])

    async def test_resource_subscription_mismatch_and_bounds(self):
        subscribe = request("resources/subscribe", {"uri": "file:///PRIVATE_RESOURCE"})
        event = {"jsonrpc": "2.0", "method": "notifications/resources/updated",
                 "params": {"uri": "file:///OTHER_RESOURCE"}}
        value = await self.inspect("inspect_mcp_resource_subscription_flow",
                                   subscribe_request=json.dumps(subscribe),
                                   subscribe_result=json.dumps(response({}, "WRONG_ID")),
                                   notifications=json.dumps([event]))
        self.assertFalse(value["valid"])
        self.assertTrue({"subscribe_response_id_mismatch", "updated_uri_mismatch"}
                        <= {item["code"] for item in value["issues"]})
        text = await self.call("inspect_mcp_resource_subscription_flow",
                               subscribe_request=json.dumps(subscribe), subscribe_result=json.dumps(response({})),
                               notifications=json.dumps([event] * 101))
        self.assertTrue(text.startswith("Error:"))

    async def test_cancellation_late_response_is_a_race(self):
        call = request("tools/call", {"name": "PRIVATE_TOOL"})
        cancellation = {"jsonrpc": "2.0", "method": "notifications/cancelled",
                        "params": {"requestId": "PRIVATE_REQUEST_ID", "reason": "PRIVATE_REASON"}}
        text = await self.call("inspect_mcp_cancellation_flow", request=json.dumps(call),
                               cancellation=json.dumps(cancellation),
                               late_response=json.dumps(response({"content": [{"type": "text",
                                                                                "text": "PRIVATE_RESULT"}]})))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertTrue(value["late_response_seen"])
        self.assertTrue(value["race_possible"])

    async def test_cancellation_rejects_wrong_id_initialize_and_task(self):
        cancellation = {"jsonrpc": "2.0", "method": "notifications/cancelled",
                        "params": {"requestId": "WRONG_ID", "reason": []}}
        value = await self.inspect("inspect_mcp_cancellation_flow",
                                   request=json.dumps(initialize_request()),
                                   cancellation=json.dumps(cancellation), task_augmented=True)
        self.assertFalse(value["valid"])
        self.assertTrue({"initialize_cannot_be_cancelled", "task_cancel_required",
                         "cancelled_request_id_mismatch", "cancellation_reason_invalid"}
                        <= {item["code"] for item in value["issues"]})

    async def test_task_notification_statuses_and_redaction(self):
        events = [task_event("working", "2026-07-28T10:00:00Z"),
                  task_event("working", "2026-07-28T10:00:00Z", "PRIVATE_OTHER_TASK"),
                  task_event("input_required", "2026-07-28T10:01:00Z", inputRequests={
                      "PRIVATE_INPUT": {"method": "elicitation/create", "params": {"message": "PRIVATE_TEXT"}}}),
                  task_event("completed", "2026-07-28T10:02:00Z", result={"content": [
                      {"type": "text", "text": "PRIVATE_RESULT"}]})]
        text = await self.call("inspect_mcp_task_notification_sequence",
                               listen_request=json.dumps(listen_request()), notifications=json.dumps(events))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["observed_task_count"], 2)
        self.assertEqual(value["last_status_counts"], {"completed": 1, "working": 1})

    async def test_task_notification_detects_regression_and_mismatches(self):
        listen = listen_request()
        events = [task_event("completed", "2026-07-28T10:02:00Z", result={"content": []}),
                  task_event("working", "2026-07-28T10:01:00Z"),
                  task_event("working", "2026-07-28T10:02:00Z", "PRIVATE_UNSUBSCRIBED")]
        events[1]["params"]["_meta"][_SUB_ID] = "WRONG_ID"
        value = await self.inspect("inspect_mcp_task_notification_sequence",
                                   listen_request=json.dumps(listen), notifications=json.dumps(events))
        self.assertFalse(value["valid"])
        self.assertTrue({"task_last_updated_regressed", "task_left_terminal_state",
                         "subscription_id_mismatch", "task_not_subscribed"}
                        <= {item["code"] for item in value["issues"]})

    async def test_task_notification_invalid_id_and_empty_capture(self):
        listen = listen_request()
        empty = await self.inspect("inspect_mcp_task_notification_sequence",
                                   listen_request=json.dumps(listen), notifications="[]")
        self.assertTrue(empty["valid"])
        invalid = task_event("working", "2026-07-28T10:00:00Z")
        invalid["params"]["taskId"] = []
        value = await self.inspect("inspect_mcp_task_notification_sequence",
                                   listen_request=json.dumps(listen), notifications=json.dumps([invalid]))
        self.assertFalse(value["valid"])
        self.assertTrue({"task_id_invalid", "task_not_subscribed"}
                        <= {item["code"] for item in value["issues"]})
        malformed_status = task_event([], "2026-07-28T10:00:00Z")
        value = await self.inspect("inspect_mcp_task_notification_sequence",
                                   listen_request=json.dumps(listen),
                                   notifications=json.dumps([malformed_status,
                                                             task_event("working", "2026-07-28T10:01:00Z")]))
        self.assertIn("task_status_invalid", {item["code"] for item in value["issues"]})


if __name__ == "__main__":
    unittest.main()
