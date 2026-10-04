import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.mcp_contract_utils import tool


def modern_request(method, params=None, request_id="PRIVATE_REQUEST_ID"):
    supplied = dict(params or {})
    supplied["_meta"] = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                         "io.modelcontextprotocol/clientCapabilities": {
                             "extensions": {"io.modelcontextprotocol/tasks": {}}}}
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": supplied}


def notification(method, params):
    return {"jsonrpc": "2.0", "method": method, "params": params}


def task(status, updated="2026-07-28T10:00:00Z", **extra):
    return {"resultType": "complete", "taskId": "PRIVATE_TASK_ID", "status": status,
            "createdAt": "2026-07-28T10:00:00Z", "lastUpdatedAt": updated,
            "ttlMs": 60000, "pollIntervalMs": 1000, **extra}


class McpObservabilityToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("mcp-observability-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(block.text for block in blocks if block.type == "text")

    async def result(self, name, **arguments):
        return json.loads(await self.call(name, **arguments))

    async def test_progress_valid_and_redacted(self):
        request = modern_request("tools/call", {"name": "PRIVATE_TOOL", "_meta": {
            "progressToken": "PRIVATE_TOKEN"}})
        request["params"]["_meta"]["progressToken"] = "PRIVATE_TOKEN"
        events = [notification("notifications/progress", {"progressToken": "PRIVATE_TOKEN",
                  "progress": 0.5, "total": 2, "message": "PRIVATE_MESSAGE"}),
                  notification("notifications/progress", {"progressToken": "PRIVATE_TOKEN",
                  "progress": 1.5})]
        text = await self.call("inspect_mcp_progress_sequence", request=json.dumps(request),
                               notifications=json.dumps(events), protocol_version="2026-07-28")
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["notification_count"], 2)
        self.assertEqual(value["notifications_with_total"], 1)

    async def test_progress_rejects_mismatch_regression_and_bad_shape(self):
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"_meta": {"progressToken": 0}}}
        events = [notification("notifications/progress", {"progressToken": 0, "progress": 2}),
                  notification("notifications/progress", {"progressToken": 0, "progress": 2}),
                  notification("notifications/progress", {"progressToken": 1, "progress": -1}),
                  notification("notifications/progress", {"progressToken": 0, "progress": 3,
                                                           "total": "unknown", "message": []})]
        value = await self.result("inspect_mcp_progress_sequence", request=json.dumps(request),
                                  notifications=json.dumps(events))
        self.assertFalse(value["valid"])
        self.assertTrue({"progress_not_increasing", "progress_token_mismatch", "progress_value_invalid",
                         "total_value_invalid", "message_must_be_text"}
                        <= {item["code"] for item in value["issues"]})
        request["params"]["_meta"] = {}
        value = await self.result("inspect_mcp_progress_sequence", request=json.dumps(request),
                                  notifications=json.dumps(events[:1]))
        self.assertIn("progress_unrequested", {item["code"] for item in value["issues"]})
        self.assertTrue((await self.call("inspect_mcp_progress_sequence", request=json.dumps(request),
                                          notifications=json.dumps([{}] * 101))).startswith("Error:"))

    async def test_subscription_valid_with_child_resource_task_and_close(self):
        request = modern_request("subscriptions/listen", {"notifications": {
            "toolsListChanged": True, "resourceSubscriptions": ["board://PRIVATE_RESOURCE"],
            "taskIds": ["PRIVATE_TASK_ID"]}})
        meta = {"_meta": {"io.modelcontextprotocol/subscriptionId": "PRIVATE_REQUEST_ID"}}
        frames = [notification("notifications/subscriptions/acknowledged", {
            "notifications": request["params"]["notifications"], **meta}),
            notification("notifications/tools/list_changed", meta),
            notification("notifications/resources/updated", {"uri": "board://PRIVATE_RESOURCE/child", **meta}),
            notification("notifications/tasks", {"taskId": "PRIVATE_TASK_ID", **meta}),
            {"jsonrpc": "2.0", "id": "PRIVATE_REQUEST_ID", "result": {"resultType": "complete"}}]
        text = await self.call("validate_mcp_subscription_stream", request=json.dumps(request),
                               events=json.dumps(frames))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["notification_count"], 3)
        self.assertTrue(value["graceful_close_seen"])

    async def test_subscription_flags_wrong_ack_id_and_unrequested_event(self):
        request = modern_request("subscriptions/listen", {"notifications": {"toolsListChanged": True}})
        frames = [notification("notifications/subscriptions/acknowledged", {
            "notifications": {"promptsListChanged": True},
            "_meta": {"io.modelcontextprotocol/subscriptionId": "WRONG_ID"}}),
            notification("notifications/prompts/list_changed", {
                "_meta": {"io.modelcontextprotocol/subscriptionId": "PRIVATE_REQUEST_ID"}})]
        value = await self.result("validate_mcp_subscription_stream", request=json.dumps(request),
                                  events=json.dumps(frames))
        self.assertFalse(value["valid"])
        self.assertTrue({"ack_exceeds_requested_filter", "subscription_id_mismatch"}
                        <= {item["code"] for item in value["issues"]})
        self.assertTrue((await self.call("validate_mcp_subscription_stream", request=json.dumps(request),
                                          events="[]")).startswith("Error:"))

    async def test_subscription_requires_ack_first_and_task_capability(self):
        request = modern_request("subscriptions/listen", {"notifications": {"taskIds": ["PRIVATE_TASK_ID"]}})
        del request["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]["extensions"]
        frames = [notification("notifications/tasks", {"taskId": "PRIVATE_TASK_ID", "_meta": {
            "io.modelcontextprotocol/subscriptionId": "PRIVATE_REQUEST_ID"}})]
        value = await self.result("validate_mcp_subscription_stream", request=json.dumps(request),
                                  events=json.dumps(frames))
        self.assertTrue({"ack_missing_or_not_first", "task_extension_not_declared"}
                        <= {item["code"] for item in value["issues"]})
        frames[0]["method"] = []
        value = await self.result("validate_mcp_subscription_stream", request=json.dumps(request),
                                  events=json.dumps(frames))
        self.assertIn("unsupported_stream_notification", {item["code"] for item in value["issues"]})

    async def test_cache_hints_valid_private_pages_and_redacted(self):
        pages = [{"resultType": "complete", "ttlMs": 1000, "cacheScope": "private",
                  "tools": [{"name": "PRIVATE_TOOL"}], "nextCursor": "PRIVATE_CURSOR"},
                 {"resultType": "complete", "ttlMs": 500, "cacheScope": "private", "tools": []}]
        text = await self.call("validate_mcp_cache_hints", method="tools/list",
                               responses=json.dumps(pages), user_scoped=True)
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["private_count"], 2)

    async def test_cache_hints_detect_invalid_ttl_scope_and_interim_hints(self):
        pages = [{"resultType": "complete", "ttlMs": 1.5, "cacheScope": "public"},
                 {"resultType": "complete", "ttlMs": -1, "cacheScope": "private"},
                 {"resultType": "input_required", "ttlMs": 0}]
        value = await self.result("validate_mcp_cache_hints", method="resources/list",
                                  responses=json.dumps(pages), user_scoped=True)
        self.assertFalse(value["valid"])
        self.assertTrue({"ttl_ms_invalid", "page_cache_scope_changed", "user_scoped_result_declared_public",
                         "input_required_has_cache_hints"}
                        <= {item["code"] for item in value["issues"]})
        self.assertTrue((await self.call("validate_mcp_cache_hints", method="resources/read",
                                          responses=json.dumps(pages))).startswith("Error:"))

    async def test_task_lifecycle_valid_and_cancel_not_assumed_terminal(self):
        creation = task("working")
        creation["resultType"] = "task"
        polls = [task("input_required", "2026-07-28T10:01:00Z", inputRequests={
            "PRIVATE_INPUT_ID": {"method": "elicitation/create", "params": {"message": "PRIVATE_MESSAGE"}}}),
            task("completed", "2026-07-28T10:02:00Z", result={"content": [{
                "type": "text", "text": "PRIVATE_RESULT"}], "isError": True})]
        cancel = modern_request("tasks/cancel", {"taskId": "PRIVATE_TASK_ID"})
        ack = {"jsonrpc": "2.0", "id": "PRIVATE_REQUEST_ID", "result": {"resultType": "complete"}}
        text = await self.call("inspect_mcp_task_lifecycle", create_result=json.dumps(creation),
                               snapshots=json.dumps(polls), cancel_request=json.dumps(cancel),
                               cancel_result=json.dumps(ack))
        self.assertNotIn("PRIVATE_", text)
        value = json.loads(text)
        self.assertTrue(value["valid"])
        self.assertEqual(value["last_observed_status"], "completed")
        self.assertTrue(value["cancel_ack_supplied"])

    async def test_task_lifecycle_detects_inconsistent_snapshots(self):
        creation = task("completed", result={"content": []})
        creation["resultType"] = "task"
        polls = [task("working", "2026-07-28T09:59:00Z"),
                 task("failed", "2026-07-28T10:02:00Z", taskId="WRONG_ID", error={"message": "PRIVATE_ERROR"})]
        value = await self.result("inspect_mcp_task_lifecycle", create_result=json.dumps(creation),
                                  snapshots=json.dumps(polls))
        self.assertFalse(value["valid"])
        self.assertTrue({"task_left_terminal_state", "task_last_updated_regressed",
                         "task_id_changed", "failed_error_invalid"}
                        <= {item["code"] for item in value["issues"]})
        self.assertTrue((await self.call("inspect_mcp_task_lifecycle", create_result=json.dumps(creation),
                                          snapshots="[]", cancel_request="{}")).startswith("Error:"))
        creation["status"] = []
        value = await self.result("inspect_mcp_task_lifecycle", create_result=json.dumps(creation),
                                  snapshots="[]")
        self.assertIn("task_status_invalid", {item["code"] for item in value["issues"]})


if __name__ == "__main__":
    unittest.main()
