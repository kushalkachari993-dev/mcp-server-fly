import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.lockfile_utils import tool


def npm(packages):
    return json.dumps({"lockfileVersion": 3, "packages": packages})


class LockfileComparisonTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("lockfile-comparison-tests")
        tool.register(self.mcp)

    async def call(self, before, after, format="package-lock.json", limit=100):
        result = await self.mcp.call_tool("compare_lockfiles", {
            "before": before, "after": after, "format": format, "limit": limit,
        })
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_nested_npm_identity_and_change_counts(self):
        before = npm({"node_modules/a": {"version": "1.0.0"},
                      "node_modules/x/node_modules/a": {"version": "1.0.0"},
                      "node_modules/gone": {"version": "2.0.0"}})
        after = npm({"node_modules/a": {"version": "2.0.0"},
                     "node_modules/x/node_modules/a": {"version": "1.0.0"},
                     "node_modules/new": {"version": "1.0.0"}})
        result = json.loads(await self.call(before, after))
        self.assertEqual(result["counts"], {"added": 1, "removed": 1, "changed": 1})
        self.assertEqual(result["changes"][0]["path"], "node_modules/a")
        self.assertEqual(result["changes"][0]["after_versions"], ["2.0.0"])
        self.assertTrue(result["complete"])

    async def test_comparison_reads_records_beyond_inspection_limit(self):
        records = {f"node_modules/dep-{index}": {"version": "1.0.0"} for index in range(600)}
        before = npm(records)
        records["node_modules/dep-599"] = {"version": "2.0.0"}
        result = json.loads(await self.call(before, npm(records)))
        self.assertEqual(result["before_package_count"], 600)
        self.assertEqual(result["change_count"], 1)
        self.assertEqual(result["changes"][0]["name"], "dep-599")

    async def test_python_name_normalization_and_multiple_versions(self):
        before = '[[packages]]\nname="Demo_Pkg"\nversion="2.0"\n[[packages]]\nname="demo-pkg"\nversion="1.0"\n'
        after = '[[packages]]\nname="demo.pkg"\nversion="1.0"\n[[packages]]\nname="demo-pkg"\nversion="2.0"\n'
        self.assertTrue(json.loads(await self.call(before, after, "pylock.toml"))["equal"])
        result = json.loads(await self.call(before, after.replace('version="2.0"', 'version="3.0"'), "pylock.toml"))
        self.assertEqual(result["changes"][0]["before_versions"], ["1.0", "2.0"])
        self.assertEqual(result["changes"][0]["after_versions"], ["1.0", "3.0"])

    async def test_unresolved_and_limited_changes_are_explicit(self):
        before = npm({"node_modules/link": {"link": True}})
        after = npm({"node_modules/a": {"version": "1"}, "node_modules/b": {"version": "2"}})
        result = json.loads(await self.call(before, after, limit=1))
        self.assertFalse(result["complete"])
        self.assertEqual(result["unresolved"]["before"], 1)
        self.assertEqual(result["change_count"], 2)
        self.assertEqual(len(result["changes"]), 1)
        self.assertTrue(result["truncated"])

    async def test_invalid_input_and_no_network_access(self):
        for invalid in ('{}', '{"lockfileVersion":[],"packages":{}}',
                        '{"lockfileVersion":3,"packages":{},"packages":{}}'):
            with self.subTest(invalid=invalid):
                self.assertTrue((await self.call(invalid, npm({}))).startswith("Error:"))
        self.assertIn("format must", await self.call("", "", "uv.lock"))
        self.assertIn("limit", await self.call(npm({}), npm({}), limit=0))
        with patch("socket.getaddrinfo", side_effect=AssertionError("No network allowed")):
            self.assertTrue(json.loads(await self.call(npm({}), npm({})))["equal"])


if __name__ == "__main__":
    unittest.main()
