import json
import unittest
from unittest.mock import patch

import urllib3
from mcp.server.fastmcp import FastMCP

from app.tools.npm_utils import service, tool


class NpmToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("npm-tests")
        tool.register(self.mcp)

    async def call(self, name="example"):
        result = await self.mcp.call_tool("get_npm_package", {"name": name})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_scoped_package_and_latest_endpoint(self):
        payload = {"name": "@scope/example", "version": "1.2.3", "description": "Test",
                   "engines": {"node": ">=20"}, "license": "MIT",
                   "repository": {"url": "https://github.com/a/b"},
                   "dependencies": {"one": "^1.0.0"}, "peerDependencies": {"two": "^2"},
                   "scripts": {"install": "ignored"}, "deprecated": "Use another package"}
        with patch.object(service, "fetch_page", return_value=(json.dumps(payload).encode(), "application/json", "url")) as fetch:
            result = json.loads(await self.call("@scope/example"))
        self.assertEqual(result["version"], "1.2.3")
        self.assertEqual(result["requires_node"], ">=20")
        self.assertEqual(result["dependencies"], [{"name": "one", "requirement": "^1.0.0"}])
        self.assertEqual(result["peer_dependencies"][0]["name"], "two")
        self.assertEqual(result["repository"], "https://github.com/a/b")
        self.assertEqual(result["deprecated"], "Use another package")
        self.assertFalse(result["truncated"])
        self.assertNotIn("scripts", result)
        fetch.assert_called_once_with("https://registry.npmjs.org/%40scope%2Fexample/latest",
                                      media_types={"application/json"}, allowed_host="registry.npmjs.org")

    async def test_optional_fields_and_legacy_license(self):
        payload = {"name": "example", "version": "1", "license": {"type": "MIT"}, "repository": "git://example.com/a"}
        with patch.object(service, "fetch_page", return_value=(json.dumps(payload).encode(), "application/json", "url")):
            result = json.loads(await self.call())
        self.assertEqual(result["license"], "MIT")
        self.assertEqual(result["dependencies"], [])
        self.assertEqual(result["repository"], "git://example.com/a")

    async def test_lists_and_fields_are_bounded(self):
        payload = {"name": "example", "version": "1", "description": "x" * 1001,
                   "dependencies": {f"dep-{i}": "x" * 501 for i in range(31)},
                   "peerDependencies": {f"dep-{i}": "1" for i in range(31)}}
        with patch.object(service, "fetch_page", return_value=(json.dumps(payload).encode(), "application/json", "url")):
            result = json.loads(await self.call())
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["dependencies"]), 30)
        self.assertEqual(len(result["peer_dependencies"]), 30)
        self.assertEqual(len(result["dependencies"][0]["requirement"]), 500)
        self.assertEqual(len(result["description"]), 1000)

    async def test_invalid_names_do_not_fetch(self):
        for name in ("", "../name", "https://example.com", "Uppercase", "x" * 215,
                     "@scope", "@scope/a/b", "@scope/..", "name?other", "name\n"):
            with self.subTest(name=name), patch.object(service, "fetch_page") as fetch:
                self.assertTrue((await self.call(name)).startswith("Error:"))
                fetch.assert_not_called()

    async def test_invalid_metadata(self):
        for payload in ([], {}, {"name": "other", "version": "1"}, {"name": "example", "version": 1},
                        {"name": "example", "version": "1", "dependencies": []},
                        {"name": "example", "version": "1", "peerDependencies": {"dep": {}}}):
            with self.subTest(payload=payload), patch.object(service, "fetch_page", return_value=(json.dumps(payload).encode(), "application/json", "url")):
                self.assertTrue((await self.call()).startswith("Error:"))
        with patch.object(service, "fetch_page", return_value=(b"invalid", "application/json", "url")):
            self.assertIn("invalid JSON", await self.call())

    async def test_transport_errors_are_reported(self):
        for error in (ValueError("Webpage returned HTTP 404"), ValueError("1 MB download limit"),
                      ValueError("Destination host is not allowed"), urllib3.exceptions.HTTPError("timeout")):
            with self.subTest(error=error), patch.object(service, "fetch_page", side_effect=error):
                self.assertTrue((await self.call()).startswith("Error:"))


if __name__ == "__main__":
    unittest.main()
