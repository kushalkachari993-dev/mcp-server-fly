import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.pypi_utils import service, tool


class PyPIToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("pypi-tests")
        tool.register(self.mcp)

    async def call(self, tool_name, **arguments):
        result = await self.mcp.call_tool(tool_name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_package_metadata_is_bounded_and_host_pinned(self):
        payload = {"info": {"name": "sampleproject", "version": "4.0.0", "summary": "A sample",
                            "requires_python": ">=3.9", "requires_dist": ["one"] * 31,
                            "project_urls": {f"link-{number}": "https://example.com" for number in range(11)},
                            "license_expression": "MIT", "package_url": "https://pypi.org/project/sampleproject/"},
                   "releases": {"0.1": ["ignored"]}}
        with patch.object(service, "fetch_page", return_value=(json.dumps(payload).encode(), "application/json", "https://pypi.org/pypi/sampleproject/json")) as fetch:
            result = json.loads(await self.call("get_pypi_package", name="sampleproject"))
        self.assertEqual(result["version"], "4.0.0")
        self.assertEqual(len(result["dependencies"]), 30)
        self.assertEqual(len(result["project_urls"]), 10)
        self.assertTrue(result["truncated"])
        self.assertNotIn("releases", result)
        self.assertEqual(fetch.call_args.kwargs["allowed_host"], "pypi.org")

    async def test_package_rejects_bad_names_responses_and_private_fetches(self):
        for name in ("../secret", "requests/name", "invalid-", "", "x" * 201):
            with self.subTest(name=name), patch.object(service, "fetch_page") as fetch:
                self.assertTrue((await self.call("get_pypi_package", name=name)).startswith("Error:"))
                fetch.assert_not_called()
        for body in (b"not json", b"[]", b'{"info": {}}'):
            with self.subTest(body=body), patch.object(service, "fetch_page", return_value=(body, "application/json", "url")):
                self.assertTrue((await self.call("get_pypi_package", name="sampleproject")).startswith("Error:"))
        with patch.object(service, "fetch_page", side_effect=ValueError("non-public address blocked")):
            self.assertIn("blocked", await self.call("get_pypi_package", name="sampleproject"))


if __name__ == "__main__":
    unittest.main()
