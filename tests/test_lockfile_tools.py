import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.lockfile_utils import tool


class LockfileToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("lockfile-tests")
        tool.register(self.mcp)

    async def call(self, content, format="package-lock.json", limit=100):
        result = await self.mcp.call_tool("inspect_lockfile", {"content": content, "format": format, "limit": limit})
        content_blocks = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content_blocks if item.type == "text")

    async def test_package_lock_v3_lists_resolved_versions(self):
        content = json.dumps({"name": "demo", "lockfileVersion": 3, "packages": {
            "": {"name": "demo", "version": "1.0.0"},
            "node_modules/alpha": {"version": "1.2.3", "dev": True},
            "node_modules/@scope/beta": {"version": "2.0.0", "optional": True},
        }})
        result = json.loads(await self.call(content))
        self.assertEqual(result["package_count"], 2)
        self.assertEqual(result["packages"][0]["name"], "alpha")
        self.assertEqual(result["packages"][1]["name"], "@scope/beta")
        self.assertTrue(result["packages"][0]["dev"])
        self.assertIn("not installed", result["notice"])

    async def test_pylock_lists_packages_and_truncates(self):
        content = 'lock-version = "1.0"\n\n[[packages]]\nname = "requests"\nversion = "2.32.0"\nrequires-python = ">=3.8"\n\n[[packages]]\nname = "urllib3"\nversion = "2.2.0"\n'
        result = json.loads(await self.call(content, "pylock.toml", 1))
        self.assertEqual(result["lock_version"], "1.0")
        self.assertEqual(result["packages"][0]["requires_python"], ">=3.8")
        self.assertEqual(result["package_count"], 2)
        self.assertTrue(result["truncated"])

    async def test_invalid_formats_and_unresolved_records_fail_closed(self):
        for content, format in (("{}", "package-lock.json"), ("packages = {}", "pylock.toml")):
            with self.subTest(format=format):
                self.assertTrue((await self.call(content, format)).startswith("Error:"))
        content = json.dumps({"lockfileVersion": 3, "packages": {"node_modules/link": {"link": True}}})
        result = json.loads(await self.call(content))
        self.assertEqual(result["unresolved_count"], 1)
        self.assertEqual(result["packages"], [])

    async def test_input_and_limit_bounds(self):
        self.assertIn("2 MB", await self.call("x" * 2_000_001))
        self.assertIn("between 1 and 500", await self.call("{}", limit=0))


if __name__ == "__main__":
    unittest.main()
