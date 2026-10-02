import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.manifest_utils import service, tool


class ManifestToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("manifest-tests")
        tool.register(self.mcp)

    async def call(self, content, format="package.json", limit=100):
        result = await self.mcp.call_tool("inspect_dependency_manifest", {"content": content, "format": format, "limit": limit})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_npm_groups_constraints_and_optional_override(self):
        manifest = {"name": "demo", "dependencies": {"one": "^1.0.0", "@scope/two": "file:../local"},
                    "devDependencies": {"test": "~2.0.0"}, "optionalDependencies": {"one": "^2.0.0"},
                    "peerDependencies": {"peer": ""}, "scripts": {"install": "ignored"}}
        result = json.loads(await self.call(json.dumps(manifest)))
        self.assertEqual(result["declaration_count"], 5)
        self.assertEqual(result["dependencies"][0]["requirement"], "^1.0.0")
        self.assertTrue(result["dependencies"][0]["overridden_by_optional"])
        self.assertEqual(result["dependencies"][1]["requirement"], "file:../local")
        self.assertEqual(result["dependencies"][2]["group"], "devDependencies")
        self.assertFalse(result["truncated"])
        self.assertNotIn("scripts", result)

    async def test_python_requirements_markers_urls_and_groups(self):
        content = '''[project]
name = "demo"
dependencies = ['requests[socks]>=2; python_version >= "3.10"', "sample @ https://example.com/sample.whl"]
[project.optional-dependencies]
test = ["pytest>=8"]
[build-system]
requires = ["setuptools>=70"]
[dependency-groups]
dev = ["ruff", {include-group = "test"}]
test = ["coverage>=7"]
'''
        result = json.loads(await self.call(content, "pyproject.toml"))
        self.assertEqual(result["declaration_count"], 6)
        requirement = result["dependencies"][0]
        self.assertEqual(requirement["name"], "requests")
        self.assertEqual(requirement["extras"], ["socks"])
        self.assertEqual(requirement["specifier"], ">=2")
        self.assertIn("python_version", requirement["marker"])
        self.assertEqual(result["dependencies"][1]["url"], "https://example.com/sample.whl")
        self.assertEqual(result["dependencies"][2]["group"], "project.optional-dependencies.test")
        self.assertEqual(result["dependencies"][3]["group"], "build-system.requires")
        self.assertEqual(result["group_includes"], [{"group": "dev", "include": "test"}])
        self.assertIn("not installed versions", result["notice"])

    async def test_dynamic_tool_overrides_and_workspaces_are_reported(self):
        content = '[project]\ndynamic = ["dependencies"]\n[tool.poetry.dependencies]\nrequests = "*"\n'
        result = json.loads(await self.call(content, "pyproject.toml"))
        self.assertEqual(result["dynamic"], ["dependencies"])
        self.assertEqual(len(result["warnings"]), 2)
        content = json.dumps({"workspaces": ["packages/*"], "overrides": {"x": "1"}, "bundleDependencies": ["x"]})
        result = json.loads(await self.call(content))
        self.assertEqual(len(result["warnings"]), 3)

    async def test_includes_are_not_expanded_even_when_cyclic(self):
        content = '[dependency-groups]\na = [{include-group = "b"}]\nb = [{include-group = "a"}]\n'
        result = json.loads(await self.call(content, "pyproject.toml", limit=1))
        self.assertEqual(result["dependencies"], [])
        self.assertEqual(len(result["group_includes"]), 1)
        self.assertTrue(result["truncated"])
        self.assertIn("without expansion", result["warnings"][0])

    async def test_limit_preserves_total_declared_count(self):
        content = json.dumps({"dependencies": {"one": "1", "two": "2"}})
        result = json.loads(await self.call(content, limit=1))
        self.assertEqual(result["declaration_count"], 2)
        self.assertEqual(len(result["dependencies"]), 1)
        self.assertTrue(result["truncated"])

    async def test_invalid_shapes_duplicates_and_numbers(self):
        for content in ('[]', '{', '{"dependencies": []}', '{"dependencies": {"x": 1}}',
                        '{"dependencies": {"x":"1","x":"2"}}', '{"x":NaN}', '{"x":1e999}',
                        '{"dependencies":{"x":"bad\\nvalue"}}', '{"optionalDependencies":null}'):
            with self.subTest(content=content):
                self.assertTrue((await self.call(content)).startswith("Error:"))

    async def test_invalid_python_declarations_and_toml(self):
        for content in ('[project]\ndependencies = "requests"', '[project]\ndependencies = ["requests>="]',
                        '[project]\ndynamic = "dependencies"', '[project]\noptional-dependencies = []',
                        '[dependency-groups]\ndev = [{unknown = "x"}]', '[dependency-groups]\ndev = "x"',
                        '[project', '[project]\nname = "a"\nname = "b"'):
            with self.subTest(content=content):
                self.assertTrue((await self.call(content, "pyproject.toml")).startswith("Error:"))

    async def test_resource_limits_and_unsupported_format(self):
        for content, format, limit in (("x" * 200001, "package.json", 100), ("{}", "requirements.txt", 100),
                                       ("{}", "package.json", 0), ("{}", "package.json", 201),
                                       ('{"nested":' + '[' * 51 + '0' + ']' * 51 + '}', "package.json", 100),
                                       (json.dumps({"x": [0] * 10000}), "package.json", 100),
                                       (json.dumps({"dependencies": {"x": "x" * 1001}}), "package.json", 100)):
            with self.subTest(format=format, size=len(content)):
                self.assertTrue((await self.call(content, format, limit)).startswith("Error:"))

    async def test_dependency_count_and_output_budget(self):
        content = json.dumps({"dependencies": {f"dep-{i}": "1" for i in range(1001)}})
        self.assertIn("1000 dependency", await self.call(content))
        content = json.dumps({"dependencies": {f"dep-{i}": "x" * 900 for i in range(150)}})
        self.assertIn("output exceeds", await self.call(content, limit=200))
        self.assertTrue(json.loads(await self.call(content, limit=5))["truncated"])

    async def test_empty_standard_manifest_and_no_network_access(self):
        for content, format in (("{}", "package.json"), ("", "pyproject.toml")):
            with self.subTest(format=format):
                self.assertEqual(json.loads(await self.call(content, format))["dependencies"], [])
        with patch("socket.getaddrinfo", side_effect=AssertionError("Network must not be used")):
            result = json.loads(await self.call('[project]\ndependencies=["demo @ https://example.com/demo.whl"]', "pyproject.toml"))
        self.assertEqual(result["declaration_count"], 1)


if __name__ == "__main__":
    unittest.main()
