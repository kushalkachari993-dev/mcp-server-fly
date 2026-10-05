import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP
from app.tools.data_transform import service, tool


class DataTransformTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("data-transform-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_inspection_counts_types_missing_and_invalid_without_values(self):
        result = await self.call("inspect_jsonl", content='{"a":true,"secret":"hidden"}\n{"a":null}\n[]\n42\nbad\n\n')
        self.assertNotIn("hidden", result)
        report = json.loads(result)
        self.assertEqual(report["valid_records"], 4)
        self.assertEqual(report["invalid_lines"], [5])
        self.assertEqual(report["fields"]["secret"]["missing"], 1)
        self.assertEqual(report["fields"]["a"]["types"], {"boolean": 1, "null": 1})
        self.assertEqual(report["blank_lines"], 2)

    async def test_inspection_limits_do_not_truncate_analysis(self):
        report = json.loads(await self.call("inspect_jsonl", content='{"a":1,"b":2}\nbad\nbad', limit=1))
        self.assertEqual(report["invalid_line_count"], 2)
        self.assertEqual(report["invalid_lines"], [2])
        self.assertTrue(report["truncated"])
        self.assertTrue((await self.call("inspect_jsonl", content="", limit=0)).startswith("Error:"))

    async def test_jsonl_roundtrip_all_record_types_and_escaped_newlines(self):
        values = [{"text": "a\nb\u2028c"}, [1, False], None, "x", 4.5]
        text = await self.call("json_to_jsonl", value=json.dumps(values))
        self.assertEqual(len(text.split("\n")), len(values))
        self.assertFalse(text.endswith("\n"))
        self.assertEqual(json.loads(await self.call("jsonl_to_json", content=text)), values)
        self.assertEqual(await self.call("json_to_jsonl", value="[]"), "")
        self.assertEqual(json.loads(await self.call("jsonl_to_json", content=" \n\r\n")), [])
        self.assertEqual(json.loads(await self.call("jsonl_to_json", content="1\r\n2")), [1, 2])

    async def test_invalid_jsonl_is_atomic_and_reports_only_line_number(self):
        result = await self.call("jsonl_to_json", content='{"ok":1}\n{"secret":private}')
        self.assertIn("line 2", result)
        self.assertNotIn("private", result)
        self.assertNotIn("ok", result)
        self.assertTrue((await self.call("json_to_jsonl", value="{}")).startswith("Error:"))

    async def test_flatten_roundtrip_escaped_empty_and_numeric_keys_and_arrays(self):
        values = [{"a/b": {"~": 1, "": {}}, "0": [1, {"nested": 2}], "": {"x": True}},
                  [], {}, None, "root", 42]
        for value in values:
            with self.subTest(value=value):
                flat = await self.call("flatten_json", value=json.dumps(value))
                self.assertEqual(json.loads(await self.call("unflatten_json", value=flat)), value)
        flat = json.loads(await self.call("flatten_json", value='{"a/b":{"~":1},"0":[1]}'))
        self.assertEqual(flat, {"/a~1b/~0": 1, "/0": [1]})
        self.assertEqual(json.loads(await self.call("unflatten_json", value='{"/0/x":1}')), {"0": {"x": 1}})

    async def test_unflatten_rejects_conflicts_in_both_orders_and_invalid_pointers(self):
        for value in ('{"/a":{},"/a/b":1}', '{"/a/b":1,"/a":{}}',
                      '{"":1,"/a":2}', '{"a":1}', '{"/a~2":1}', '[]'):
            with self.subTest(value=value):
                self.assertTrue((await self.call("unflatten_json", value=value)).startswith("Error:"))
        self.assertEqual(json.loads(await self.call("unflatten_json", value="{}")), {})

    async def test_redaction_array_escaping_root_and_unselected_values(self):
        result = await self.call("redact_json_fields", value='{"a/b":[{"~":123}],"keep":true}',
                                 pointers_json='["/a~1b/0/~0"]', mask="X")
        self.assertEqual(json.loads(result), {"a/b": [{"~": "X"}], "keep": True})
        self.assertEqual(json.loads(await self.call("redact_json_fields", value="1", pointers_json='[""]')), "[REDACTED]")
        self.assertEqual(json.loads(await self.call("redact_json_fields", value="[1]", pointers_json="[]")), [1])

    async def test_redaction_rejects_missing_noncanonical_duplicate_and_overlapping_paths(self):
        for paths in ('["/a/01"]', '["/a/-"]', '["/a/2"]', '["/missing"]',
                      '["/a","/a/0"]', '["/a/0","/a"]', '["/a","/a"]', '["","/a"]', '[1]', '{}'):
            with self.subTest(paths=paths):
                result = await self.call("redact_json_fields", value='{"a":["secret"]}', pointers_json=paths)
                self.assertTrue(result.startswith("Error:"))
                self.assertNotIn("secret", result)

    async def test_strict_json_and_resource_bounds(self):
        for value in ('{"a":1,"a":2}', 'NaN', 'Infinity', '1e999', '"unterminated', ' ' * 200001,
                      '[' * 51 + '0' + ']' * 51, json.dumps([0] * 10000)):
            with self.subTest(value=value[:30]):
                self.assertTrue((await self.call("flatten_json", value=value)).startswith("Error:"))
        self.assertTrue((await self.call("unflatten_json", value=json.dumps({"/x" * 51: 1}))).startswith("Error:"))
        self.assertTrue((await self.call("redact_json_fields", value='{"x":1}', pointers_json='["/x"]',
                                         mask="x" * 200001)).startswith("Error:"))
        self.assertTrue((await self.call("json_to_jsonl", value=json.dumps(["é" * 40000]))).startswith("Error:"))
        # Shared tree limits also apply to the reconstructed result.
        self.assertTrue((await self.call("unflatten_json", value=json.dumps({"/x" * 50: [0]}))).startswith("Error:"))

    async def test_worker_dispatch_and_six_registered_tools(self):
        self.assertEqual({item.name for item in await self.mcp.list_tools()}, {
            "inspect_jsonl", "jsonl_to_json", "json_to_jsonl", "flatten_json",
            "unflatten_json", "redact_json_fields"})
        with patch.object(service, "flatten_json", return_value="{}") as function:
            self.assertEqual(await self.call("flatten_json", value="{}"), "{}")
            function.assert_called_once_with("{}")


if __name__ == "__main__":
    unittest.main()
