import json
import unittest

from mcp.server.fastmcp import FastMCP

from app.tools.version_utils import tool


class VersionToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("version-tests")
        tool.register(self.mcp)

    async def call(self, first, second, scheme="semver"):
        result = await self.mcp.call_tool("compare_versions", {"first": first, "second": second, "scheme": scheme})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_semver_numeric_and_prerelease_order(self):
        for first, second, expected in (("1.9.0", "1.10.0", -1), ("2.0.0", "1.9.0", 1),
                                        ("1.0.0", "1.0.0", 0), ("1.0.0-rc.1", "1.0.0", -1),
                                        ("1.0.0-beta.2", "1.0.0-beta.11", -1)):
            with self.subTest(first=first, second=second):
                result = json.loads(await self.call(first, second))
                self.assertEqual(result["comparison"], expected)
                self.assertEqual(result["relation"], {-1: "older", 0: "equal", 1: "newer"}[expected])

    async def test_semver_build_metadata_does_not_change_precedence(self):
        result = json.loads(await self.call("1.0.0+build.1", "1.0.0+build.2"))
        self.assertEqual(result["comparison"], 0)
        self.assertEqual(result["first"], "1.0.0+build.1")
        self.assertIn("not an assessment", result["notice"])

    async def test_pep440_epoch_dev_post_local_and_normalization(self):
        for first, second, expected in (("1.0", "1.0.0", 0), ("1!1.0", "9.0", 1),
                                        ("1.0.dev1", "1.0a1", -1), ("1.0.post1", "1.0", 1),
                                        ("1.0+abc.2", "1.0+abc.1", 1)):
            with self.subTest(first=first, second=second):
                self.assertEqual(json.loads(await self.call(first, second, "pep440"))["comparison"], expected)
        self.assertEqual(json.loads(await self.call("v1.0RC1", "1.0", "pep440"))["first"], "1.0rc1")

    async def test_invalid_versions_ranges_schemes_and_length(self):
        for first, second, scheme in (("1.0", "1.0.0", "semver"), ("01.0.0", "1.0.0", "semver"),
                                      ("v1.0.0", "1.0.0", "semver"), ("1.0.0-01", "1.0.0", "semver"),
                                      ("^1.0.0", "1.0.0", "semver"), ("1.0", ">=2", "pep440"),
                                      ("", "1.0.0", "semver"), ("x" * 201, "1.0", "pep440"),
                                      ("1.0.0\n", "1.0.0", "semver"), ("1.0.0", "2.0.0", "auto")):
            with self.subTest(first=first, scheme=scheme):
                self.assertTrue((await self.call(first, second, scheme)).startswith("Error:"))


if __name__ == "__main__":
    unittest.main()
