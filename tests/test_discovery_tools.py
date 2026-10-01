import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.github_utils import service as github_service
from app.tools.github_utils import tool as github_tools
from app.tools.toml_utils import tool as toml_tools
from app.tools.webpage import tool as webpage_tools


class DiscoveryToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("discovery-tests")
        for module in (github_tools, toml_tools, webpage_tools):
            module.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_github_directory_root_and_truncation(self):
        rows = [{"name": "src", "path": "src", "type": "dir", "size": 0, "sha": "abc",
                 "html_url": "https://github.com/a/b/tree/main/src"},
                {"name": "README.md", "path": "README.md", "type": "file", "size": 10}]
        with patch.object(github_service, "_request", return_value=rows) as request:
            result = json.loads(await self.call("list_github_directory", owner="a", repo="b", limit=1))
        self.assertEqual(result["entries"][0]["type"], "dir")
        self.assertTrue(result["truncated"])
        request.assert_called_once_with("repos/a/b/contents", None)

    async def test_github_directory_path_ref_and_invalid_inputs(self):
        with patch.object(github_service, "_request", return_value=[]) as request:
            result = json.loads(await self.call("list_github_directory", owner="a", repo="b",
                                                path="docs/API reference", ref="main"))
        self.assertEqual(result["entries"], [])
        request.assert_called_once_with("repos/a/b/contents/docs/API%20reference", {"ref": "main"})
        for arguments in ({"path": "../private"}, {"path": "a//b"}, {"path": "a\\b"},
                          {"ref": "x" * 201}, {"limit": 101}):
            with self.subTest(arguments=arguments), patch.object(github_service, "_request") as request:
                result = await self.call("list_github_directory", owner="a", repo="b", **arguments)
                self.assertTrue(result.startswith("Error:"))
                request.assert_not_called()
        with patch.object(github_service, "_request", return_value={"type": "file"}):
            self.assertIn("directory", await self.call("list_github_directory", owner="a", repo="b", path="file"))

    async def test_toml_dates_arrays_and_nested_tables(self):
        value = 'name = "demo"\nreleased = 2026-09-30\nthresholds = [1, 2]\n[server]\nenabled = true\n'
        result = json.loads(await self.call("toml_to_json", value=value))
        self.assertEqual(result["released"], "2026-09-30")
        self.assertEqual(result["thresholds"], [1, 2])
        self.assertEqual(result["server"], {"enabled": True})

    async def test_toml_rejects_invalid_and_oversized_values(self):
        for value in ('name = "unfinished', 'value = nan', 'value = inf', "x" * 200001):
            with self.subTest(value=value[:20]):
                self.assertTrue((await self.call("toml_to_json", value=value)).startswith("Error:"))
        with patch.object(toml_tools, "_MAX_OUTPUT", 20):
            self.assertIn("output exceeds", await self.call("toml_to_json", value='name = "a long value"'))

    async def test_json_ld_extracts_documents_and_counts_invalid_scripts(self):
        body = b'''<html><head><script type="application/ld+json">{"@type":"Article","name":"First"}</script>
        <script type="application/ld+json; charset=utf-8">not json</script>
        <script type="APPLICATION/LD+JSON">[{"@type":"Person","name":"Ada"}]</script></head></html>'''
        with patch.object(webpage_tools, "fetch_page", return_value=(body, "text/html", "https://example.com/page")):
            result = json.loads(await self.call("extract_json_ld", url="https://example.com/page"))
        self.assertEqual(result["invalid_scripts"], 1)
        self.assertEqual(len(result["documents"]), 2)
        self.assertEqual(result["documents"][0]["name"], "First")
        self.assertFalse(result["truncated"])
        with patch.object(webpage_tools, "fetch_page", return_value=(body, "text/html", "https://example.com/page")):
            result = json.loads(await self.call("extract_json_ld", url="https://example.com/page", max_items=1))
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["documents"]), 1)

    async def test_json_ld_output_budget_and_fetch_errors(self):
        body = ('<script type="application/ld+json">' +
                json.dumps({"@type": "Article", "description": "x" * 6000}) + '</script>').encode()
        with patch.object(webpage_tools, "fetch_page", return_value=(body, "text/html", "https://example.com/")):
            result = json.loads(await self.call("extract_json_ld", url="https://example.com/", max_chars=5000))
        self.assertEqual(result["documents"], [])
        self.assertTrue(result["truncated"])
        with patch.object(webpage_tools, "fetch_page", return_value=(body, "text/plain", "https://example.com/")):
            self.assertIn("HTML webpage", await self.call("extract_json_ld", url="https://example.com/"))
        with patch.object(webpage_tools, "fetch_page", side_effect=ValueError("non-public address blocked")):
            self.assertIn("blocked", await self.call("extract_json_ld", url="http://localhost/"))


if __name__ == "__main__":
    unittest.main()
