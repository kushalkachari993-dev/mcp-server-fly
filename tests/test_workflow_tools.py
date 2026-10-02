import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.github_utils import service, tool


class WorkflowToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("workflow-tests")
        tool.register(self.mcp)

    async def call(self, **arguments):
        result = await self.mcp.call_tool("list_github_workflow_runs", {"owner": "a", "repo": "b", **arguments})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_workflow_status_and_null_conclusion(self):
        payload = {"total_count": 2, "workflow_runs": [
            {"id": 1, "name": "Test", "head_branch": "main", "head_sha": "abc",
             "status": "completed", "conclusion": "failure", "html_url": "https://github.com/a/b/actions/runs/1"},
            {"id": 2, "status": "in_progress", "conclusion": None}]}
        with patch.object(service, "_request", return_value=payload) as request:
            result = json.loads(await self.call())
        self.assertEqual(result["runs"][0]["conclusion"], "failure")
        self.assertEqual(result["runs"][0]["sha"], "abc")
        self.assertIsNone(result["runs"][1]["conclusion"])
        self.assertFalse(result["truncated"])
        request.assert_called_once_with("repos/a/b/actions/runs", {"per_page": 11})

    async def test_branch_limit_truncation_and_empty_repository(self):
        payload = {"total_count": 100, "workflow_runs": [{"id": 1, "name": "x" * 201}, {"id": 2}]}
        with patch.object(service, "_request", return_value=payload) as request:
            result = json.loads(await self.call(branch="feature/tools", limit=1))
        self.assertEqual(len(result["runs"]), 1)
        self.assertEqual(len(result["runs"][0]["name"]), 200)
        self.assertTrue(result["truncated"])
        request.assert_called_once_with("repos/a/b/actions/runs", {"per_page": 2, "branch": "feature/tools"})
        with patch.object(service, "_request", return_value={"total_count": 0, "workflow_runs": []}):
            result = json.loads(await self.call())
        self.assertEqual(result["runs"], [])
        self.assertFalse(result["truncated"])

    async def test_invalid_inputs_do_not_request(self):
        for arguments in ({"owner": "../a"}, {"repo": ".."}, {"branch": "x" * 201},
                          {"branch": "main\n"}, {"limit": 0}, {"limit": 21}):
            with self.subTest(arguments=arguments), patch.object(service, "_request") as request:
                self.assertTrue((await self.call(**arguments)).startswith("Error:"))
                request.assert_not_called()

    async def test_malformed_response_and_rate_limit(self):
        for payload in ([], {}, {"total_count": 0, "workflow_runs": [None]},
                        {"total_count": 1, "workflow_runs": [{}]},
                        {"total_count": True, "workflow_runs": []}):
            with self.subTest(payload=payload), patch.object(service, "_request", return_value=payload):
                self.assertTrue((await self.call()).startswith("Error:"))
        for status in (403, 404, 429):
            with self.subTest(status=status), patch.object(service, "fetch_page", side_effect=ValueError(f"Webpage returned HTTP {status}")):
                self.assertIn(f"HTTP {status}", await self.call())

    async def test_request_uses_shared_github_host_pinning(self):
        body = b'{"total_count": 0, "workflow_runs": []}'
        with patch.object(service, "fetch_page", return_value=(body, "application/json", "url")) as fetch:
            await self.call(branch="feature/tools&other", limit=1)
        self.assertEqual(fetch.call_args.args[0], "https://api.github.com/repos/a/b/actions/runs?per_page=2&branch=feature%2Ftools%26other")
        self.assertEqual(fetch.call_args.kwargs["allowed_host"], "api.github.com")


if __name__ == "__main__":
    unittest.main()
