import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.log_utils import tool


def jsonl(rows):
    return "\n".join(json.dumps(row) for row in rows) + "\n"


class LogToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("log-tests")
        tool.register(self.mcp)

    async def call(self, content, **arguments):
        result = await self.mcp.call_tool("analyze_jsonl_logs", {"content": content, **arguments})
        blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in blocks if item.type == "text")

    async def test_counts_frequent_messages_and_chronological_time_range(self):
        content = jsonl([{"level": "INFO", "message": "ok", "timestamp": "2026-01-01T10:00:00+05:30"},
                         {"level": "ERROR", "message": "failed", "timestamp": "2026-01-01T04:00:00Z"},
                         {"level": "fatal", "message": "failed", "timestamp": "2026-01-01T04:15:00Z"}])
        result = json.loads(await self.call(content))
        self.assertEqual(result["parsed_entries"], 3)
        self.assertEqual(result["error_count"], 2)
        self.assertEqual(result["frequent_messages"][0]["count"], 2)
        self.assertEqual(result["timestamp_range"], {"first": "2026-01-01T04:00:00+00:00",
                                                   "last": "2026-01-01T04:30:00+00:00"})

    async def test_custom_fields_blank_and_malformed_lines(self):
        content = '{"severity":"warn","msg":"slow","time":"2026-01-01T01:00:00Z"}\n\ninvalid\n[]\n{"x":NaN}\n'
        result = json.loads(await self.call(content, level_field="severity", message_field="msg", timestamp_field="time"))
        self.assertEqual(result["line_count"], 5)
        self.assertEqual(result["parsed_entries"], 1)
        self.assertEqual(result["blank_lines"], 1)
        self.assertEqual(result["invalid_entries"], 3)
        self.assertEqual(result["level_counts"], [{"level": "warning", "count": 1}])
        self.assertEqual([row["line"] for row in result["invalid_samples"]], [3, 4, 5])

    async def test_limits_bound_samples_but_totals_cover_all_lines(self):
        content = jsonl([{"level": "error", "message": "a"}, {"level": "error", "message": "b"},
                         {"level": "error", "message": "a"}]) + "bad\nbad\n"
        result = json.loads(await self.call(content, limit=1))
        self.assertEqual(result["error_count"], 3)
        self.assertEqual(result["invalid_entries"], 2)
        self.assertEqual(len(result["error_samples"]), 1)
        self.assertEqual(result["frequent_messages"][0]["count"], 2)
        self.assertTrue(result["truncated"])

    async def test_ambiguous_times_and_numeric_levels_are_counted(self):
        content = jsonl([{"level": 50, "timestamp": 0}, {"level": "info", "timestamp": "2026-01-01T01:00:00"},
                         {"level": "info", "timestamp": "invalid"}, {"level": "info"}])
        result = json.loads(await self.call(content))
        self.assertEqual(result["invalid_timestamps"], 3)
        self.assertEqual(result["missing_timestamps"], 1)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["timestamp_range"], {"first": None, "last": None})

    async def test_unicode_content_is_not_split_into_extra_lines(self):
        content = json.dumps({"message": "hello" + chr(0x85) + "world"}, ensure_ascii=False) + "\n"
        result = json.loads(await self.call(content))
        self.assertEqual(result["line_count"], 1)
        self.assertEqual(result["parsed_entries"], 1)

    async def test_input_bounds_empty_input_and_no_network(self):
        for content, arguments in (("x" * 1000001, {}), ("\n" * 5001, {}), ("", {"limit": 51}),
                                    ("", {"level_field": ""})):
            with self.subTest(arguments=arguments):
                self.assertTrue((await self.call(content, **arguments)).startswith("Error:"))
        with patch("socket.getaddrinfo", side_effect=AssertionError("No network allowed")):
            result = json.loads(await self.call(""))
        self.assertEqual(result["parsed_entries"], 0)
        result = json.loads(await self.call(jsonl([{"level": "error", "message": "x" * 1001}])))
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["error_samples"][0]["message"]), 1000)


if __name__ == "__main__":
    unittest.main()
