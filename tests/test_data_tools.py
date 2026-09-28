import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.csv_utils import tool as csv_tools
from app.tools.datetime_utils import tool as datetime_tools
from app.tools.json_utils import tool as json_tools
from app.tools.registry import register_all_tools


class DataToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("utility-tests")
        for module in (csv_tools, datetime_tools, json_tools):
            module.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_registry_exposes_all_39_tools(self):
        server = FastMCP("registry-test")
        register_all_tools(server)
        names = {tool.name for tool in await server.list_tools()}
        self.assertEqual(len(names), 39)
        self.assertTrue({
            "csv_to_json", "json_to_csv", "query_json", "compare_json",
            "timestamp_to_datetime", "datetime_to_timestamp",
            "get_webpage_text", "validate_json_schema", "yaml_to_json",
            "json_to_yaml", "cron_next_runs",
            "read_rss_feed", "extract_webpage_links", "extract_html_tables",
            "summarize_numbers", "diff_text", "convert_units",
        }.issubset(names))

    async def test_csv_quoted_cells_and_leading_zeros(self):
        result = await self.call(
            "csv_to_json", csv_text='code,note\r\n001,"Hello, world"\r\n002,"two\nlines"\r\n'
        )
        self.assertEqual(json.loads(result), [
            {"code": "001", "note": "Hello, world"},
            {"code": "002", "note": "two\nlines"},
        ])

    async def test_csv_bom_and_tab_delimiter(self):
        result = await self.call("csv_to_json", csv_text="\ufeffname\tcity\nAda\tLondon\n", delimiter="\t")
        self.assertEqual(json.loads(result), [{"name": "Ada", "city": "London"}])

    async def test_csv_rejects_malformed_input(self):
        for value in ("", "name,name\nx,y", "name,\nx,y", "a,b\nx", 'a,b\nx,"unfinished'):
            with self.subTest(value=value):
                self.assertTrue((await self.call("csv_to_json", csv_text=value)).startswith("Error:"))

    async def test_csv_limits_and_invalid_delimiter(self):
        for arguments in (
            {"csv_text": "a\n" + "x\n" * 1001},
            {"csv_text": "a" * 200001},
            {"csv_text": "a\nx", "delimiter": "::"},
            {"csv_text": "a\nx", "delimiter": "\n"},
        ):
            with self.subTest(arguments=list(arguments)):
                self.assertTrue((await self.call("csv_to_json", **arguments)).startswith("Error:"))

    async def test_json_csv_union_of_columns(self):
        rows = [{"name": "Ada, A", "active": True}, {"name": "Bob", "count": 2, "active": None}]
        result = await self.call("json_to_csv", value=json.dumps(rows))
        self.assertEqual(result, 'name,active,count\n"Ada, A",true,\nBob,,2\n')

    async def test_json_csv_round_trip(self):
        rows = [{"name": "Ada", "note": 'one,"two"\nthree'}]
        csv_text = await self.call("json_to_csv", value=json.dumps(rows), delimiter=";")
        result = await self.call("csv_to_json", csv_text=csv_text, delimiter=";")
        self.assertEqual(json.loads(result), rows)

    async def test_json_csv_rejects_invalid_shapes_and_numbers(self):
        for value in ('{"a":1}', '[1]', '[{"a":{}}]', '[{}]', '[{"a":NaN}]', '[{"a":1e999}]', '{'):
            with self.subTest(value=value):
                self.assertTrue((await self.call("json_to_csv", value=value)).startswith("Error:"))
        self.assertEqual(await self.call("json_to_csv", value="[]"), "")

    async def test_json_pointer_nested_array(self):
        result = await self.call("query_json", value='{"users":[{"name":"Ada"}]}', pointer="/users/0/name")
        self.assertEqual(json.loads(result), "Ada")

    async def test_json_pointer_escaped_and_empty_keys(self):
        value = '{"a/b":{"~key":null},"":false,"~1":"literal"}'
        self.assertEqual(await self.call("query_json", value=value, pointer="/a~1b/~0key"), "null")
        self.assertEqual(await self.call("query_json", value=value, pointer="/"), "false")
        self.assertEqual(json.loads(await self.call("query_json", value=value, pointer="/~01")), "literal")
        self.assertEqual(json.loads(await self.call("query_json", value=value)), json.loads(value))

    async def test_json_pointer_rejects_invalid_paths(self):
        for value, pointer in (
            ('{}', 'a'), ('{}', '/missing'), ('{}', '/~2'), ('{}', '/~'),
            ('[1]', '/01'), ('[1]', '/-1'), ('[1]', '/2'), ('1', '/a'),
            ('NaN', ''), ('1e999', ''), ('{', ''),
        ):
            with self.subTest(value=value, pointer=pointer):
                self.assertTrue((await self.call("query_json", value=value, pointer=pointer)).startswith("Error:"))

    async def test_json_diff_added_removed_and_changed(self):
        result = json.loads(await self.call(
            "compare_json", before='{"a/b":1,"old":true}', after='{"a/b":2,"new":null}'
        ))
        self.assertFalse(result["equal"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["differences"], [
            {"path": "/a~1b", "type": "changed", "before": 1, "after": 2},
            {"path": "/old", "type": "removed", "before": True},
            {"path": "/new", "type": "added", "after": None},
        ])

    async def test_json_diff_types_and_array_order(self):
        result = json.loads(await self.call("compare_json", before="[true,1]", after="[1,true]"))
        self.assertEqual(len(result["differences"]), 2)
        result = json.loads(await self.call("compare_json", before='{"a":1,"b":2}', after='{"b":2,"a":1.0}'))
        self.assertTrue(result["equal"])

    async def test_json_diff_limits(self):
        for count, truncated in ((100, False), (101, True)):
            result = json.loads(await self.call("compare_json", before="[]", after=json.dumps(list(range(count)))))
            self.assertEqual(len(result["differences"]), 100)
            self.assertEqual(result["truncated"], truncated)
        nested = "[" * 102 + "0" + "]" * 102
        self.assertTrue((await self.call("compare_json", before=nested, after=nested)).startswith("Error:"))

    async def test_json_input_limit(self):
        self.assertTrue((await self.call("query_json", value=" " * 200001)).startswith("Error:"))
        self.assertTrue((await self.call("compare_json", before="{}", after="{" )).startswith("Error:"))

    async def test_timestamp_epoch_and_offsets(self):
        self.assertEqual(await self.call("timestamp_to_datetime", timestamp=0), "1970-01-01T00:00:00+00:00")
        self.assertEqual(await self.call("timestamp_to_datetime", timestamp=0, timezone_name="Asia/Kolkata"), "1970-01-01T05:30:00+05:30")
        self.assertEqual(await self.call("datetime_to_timestamp", datetime_text="1970-01-01T05:30:00+05:30"), "0")
        self.assertEqual(await self.call("datetime_to_timestamp", datetime_text="1970-01-01 00:00"), "0")

    async def test_fractional_and_negative_timestamps(self):
        result = await self.call("datetime_to_timestamp", datetime_text="1970-01-01T00:00:00.123456Z", unit="milliseconds")
        self.assertEqual(result, "123.456")
        self.assertEqual(await self.call("timestamp_to_datetime", timestamp=123.456, unit="milliseconds"), "1970-01-01T00:00:00.123456+00:00")
        self.assertEqual(await self.call("timestamp_to_datetime", timestamp=-1), "1969-12-31T23:59:59+00:00")
        self.assertEqual(await self.call("datetime_to_timestamp", datetime_text="1969-12-31T23:59:59.500Z"), "-0.5")

    async def test_timestamps_reject_invalid_inputs(self):
        for arguments in (
            {"timestamp": float("inf")}, {"timestamp": 1e100},
            {"timestamp": 0, "timezone_name": "Not/AZone"}, {"timestamp": 0, "unit": "minutes"},
        ):
            with self.subTest(arguments=arguments):
                self.assertTrue((await self.call("timestamp_to_datetime", **arguments)).startswith("Error:"))
        for arguments in ({"datetime_text": "not-a-date"}, {"datetime_text": "1970-01-01", "unit": "minutes"}):
            with self.subTest(arguments=arguments):
                self.assertTrue((await self.call("datetime_to_timestamp", **arguments)).startswith("Error:"))


if __name__ == "__main__":
    unittest.main()
