import json
import unittest
from unittest.mock import Mock, patch

from mcp.server.fastmcp import FastMCP

from app.tools.json_query import service, tool


class JsonQueryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("json-query-tests")
        tool.register(self.mcp)

    async def call(self, value, expression):
        result = await self.mcp.call_tool("query_json_advanced", {"value": value, "expression": expression})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_filter_sort_and_reshape(self):
        value = json.dumps({"users": [{"name": "Bob", "score": 3, "active": True},
                                      {"name": "Ada", "score": 5, "active": True},
                                      {"name": "Eve", "score": 1, "active": False}]})
        result = await self.call(value, "sort_by(users[?active], &score)[].{person: name, points: score}")
        self.assertEqual(json.loads(result), [{"person": "Bob", "points": 3}, {"person": "Ada", "points": 5}])

    async def test_missing_null_and_scalar_results(self):
        for value, expression, expected in (("{}", "missing", None), ('{"ok":false}', "ok", False),
                                             ("[1,2,3]", "sum(@)", 6), ('"hello"', "@", "hello")):
            with self.subTest(expression=expression):
                self.assertEqual(json.loads(await self.call(value, expression)), expected)

    async def test_invalid_json_expressions_and_types(self):
        for value, expression in (("{", "@"), ("NaN", "@"), ("1e999", "@"), ("{}", "foo["),
                                  ("{}", "unknown_function(@)"), ("{}", "sort(@)"),
                                  ("{}", "&foo"), ("{}", "to_number('1e999')")):
            with self.subTest(value=value, expression=expression):
                self.assertTrue((await self.call(value, expression)).startswith("Error:"))

    async def test_input_and_expression_size_rejected_before_spawn(self):
        for value, expression in (("x" * 200001, "@"), ("{}", " "), ("{}", "a" * 1001)):
            with self.subTest(expression=expression[:10]), patch.object(service.multiprocessing, "get_context") as context:
                self.assertTrue((await self.call(value, expression)).startswith("Error:"))
                context.assert_not_called()

    async def test_node_depth_and_output_limits(self):
        cases = [(json.dumps([0] * 10000), "@", "node"),
                 ("[" * 52 + "0" + "]" * 52, "@", "nesting"),
                 (json.dumps(["x" * 500] * 250), "join('', @)", "output exceeds")]
        for value, expression, message in cases:
            with self.subTest(message=message):
                self.assertIn(message, await self.call(value, expression))

    async def test_busy_worker_returns_error(self):
        self.assertTrue(service._QUERY_SLOT.acquire(blocking=False))
        try:
            self.assertIn("busy", await self.call("{}", "@"))
        finally:
            service._QUERY_SLOT.release()


class JsonQueryWorkerTests(unittest.TestCase):
    def setUp(self):
        self.receiver, self.sender, self.process = Mock(), Mock(), Mock(pid=123)
        self.context = Mock()
        self.context.Pipe.return_value = (self.receiver, self.sender)
        self.context.Process.return_value = self.process
        self.process.is_alive.return_value = False

    def assert_slot_released(self):
        self.assertTrue(service._QUERY_SLOT.acquire(blocking=False))
        service._QUERY_SLOT.release()

    def test_timeout_terminates_worker_and_releases_slot(self):
        self.receiver.poll.return_value = False
        self.process.is_alive.side_effect = [True, False]
        with patch.object(service.multiprocessing, "get_context", return_value=self.context):
            with self.assertRaisesRegex(ValueError, "3-second"):
                service.query_json("{}", "@")
        self.process.terminate.assert_called_once()
        self.receiver.close.assert_called_once()
        self.process.close.assert_called_once()
        self.assert_slot_released()

    def test_crashed_worker_and_start_failure_release_slot(self):
        self.receiver.poll.return_value = True
        self.receiver.recv.side_effect = EOFError()
        with patch.object(service.multiprocessing, "get_context", return_value=self.context):
            with self.assertRaisesRegex(ValueError, "without a result"):
                service.query_json("{}", "@")
        self.assert_slot_released()
        self.process.pid = None
        self.process.start.side_effect = OSError("Cannot start worker")
        with patch.object(service.multiprocessing, "get_context", return_value=self.context):
            with self.assertRaises(OSError):
                service.query_json("{}", "@")
        self.assert_slot_released()

    def test_tree_limits_and_nonfinite_results(self):
        for value in ([float("inf")], {"x": float("nan")}, [1, 2, 3]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                service._check_tree(value, max_nodes=3)


if __name__ == "__main__":
    unittest.main()
