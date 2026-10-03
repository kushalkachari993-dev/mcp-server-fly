import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.json_patch import tool


class JsonPatchToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("json-patch-tests")
        tool.register(self.mcp)

    async def call(self, value, operations):
        result = await self.mcp.call_tool("apply_json_patch", {
            "value": json.dumps(value), "patch": json.dumps(operations),
        })
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_all_six_operations_escaped_keys_and_copy_isolation(self):
        result = json.loads(await self.call({"list": [1, 2], "a/b": {"~key": "old"}}, [
            {"op": "test", "path": "/list/0", "value": 1.0},
            {"op": "add", "path": "/list/-", "value": 3},
            {"op": "copy", "from": "/a~1b", "path": "/copy"},
            {"op": "replace", "path": "/a~1b/~0key", "value": "new"},
            {"op": "move", "from": "/list/0", "path": "/list/2"},
            {"op": "remove", "path": "/list/0"},
        ]))
        self.assertEqual(result, {"list": [3, 1], "a/b": {"~key": "new"}, "copy": {"~key": "old"}})

    async def test_root_replacement_copy_and_move(self):
        for value in (None, 7, "text", [1, 2], {}):
            with self.subTest(value=value):
                self.assertEqual(json.loads(await self.call(value, [{"op": "add", "path": "", "value": [3]}])), [3])
        self.assertEqual(json.loads(await self.call({"a": 1}, [{"op": "copy", "from": "", "path": "/backup"}])),
                         {"a": 1, "backup": {"a": 1}})
        self.assertEqual(json.loads(await self.call([{"n": 2}], [{"op": "move", "from": "/0", "path": ""}])), {"n": 2})
        self.assertEqual(json.loads(await self.call({"a": 1}, [{"op": "move", "from": "", "path": ""}])), {"a": 1})

    async def test_test_operation_distinguishes_boolean_and_numbers(self):
        self.assertIn("test failed", await self.call({"x": {"n": True}}, [{"op": "test", "path": "/x", "value": {"n": 1}}]))
        self.assertEqual(json.loads(await self.call({"x": {"n": 1, "a": 2}}, [
            {"op": "test", "path": "/x", "value": {"a": 2.0, "n": 1.0}}])), {"x": {"n": 1, "a": 2}})

    async def test_errors_return_no_partial_document(self):
        result = await self.call({}, [{"op": "add", "path": "/a", "value": 1},
                                      {"op": "test", "path": "/a", "value": 2}])
        self.assertTrue(result.startswith("Error: Patch operation 2"))
        for operations in ([{"op": "replace", "path": "/missing", "value": 1}],
                           [{"op": "remove", "path": ""}], [{"op": "unknown", "path": "/a"}],
                           [{"op": "add", "path": "/a"}], [{"op": "copy", "path": "/a"}],
                           [{"op": "add", "path": "/bad~2", "value": 1}]):
            with self.subTest(operations=operations):
                self.assertTrue((await self.call({}, operations)).startswith("Error:"))

    async def test_indices_scalars_and_moves_into_descendants_are_rejected(self):
        for value, operations in (([1], [{"op": "replace", "path": "/01", "value": 2}]),
                                  ({"s": "hello"}, [{"op": "test", "path": "/s/0", "value": "h"}]),
                                  ({"a": []}, [{"op": "move", "from": "/a", "path": "/a/0"}])):
            with self.subTest(value=value):
                self.assertTrue((await self.call(value, operations)).startswith("Error:"))

    async def test_dash_is_a_valid_object_key_but_not_an_array_replace_index(self):
        self.assertEqual(json.loads(await self.call({"-": "old"}, [
            {"op": "replace", "path": "/-", "value": "new"}])), {"-": "new"})
        self.assertTrue((await self.call({}, [{"op": "replace", "path": "/-", "value": "new"}])).startswith("Error:"))
        self.assertTrue((await self.call([1], [{"op": "replace", "path": "/-", "value": 2}])).startswith("Error:"))

    async def test_resource_limits_and_empty_patch(self):
        self.assertEqual(json.loads(await self.call([1, 2], [])), [1, 2])
        self.assertIn("50 operations", await self.call({}, [{"op": "test", "path": "", "value": {}}] * 51))
        self.assertIn("node", await self.call([0] * 10000, []))
        self.assertIn("exceeds", await self.call({"s": "x" * 100000}, [{"op": "copy", "from": "/s", "path": "/duplicate"}]))


if __name__ == "__main__":
    unittest.main()
