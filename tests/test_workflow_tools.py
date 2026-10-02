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

    async def call_jobs(self, **arguments):
        result = await self.mcp.call_tool("list_github_workflow_jobs", {"owner": "a", "repo": "b", "run_id": 123, **arguments})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_jobs_include_failures_and_pending_steps(self):
        payload = {"total_count": 1, "jobs": [{"id": 12, "name": "Tests", "status": "completed", "conclusion": "failure",
                     "steps": [{"number": 1, "name": "Test", "status": "completed", "conclusion": "failure"},
                               {"number": 2, "name": "Cleanup", "status": "queued", "conclusion": None}]}]}
        with patch.object(service, "_request", return_value=payload) as request:
            result = json.loads(await self.call_jobs())
        self.assertEqual(result["jobs"][0]["steps"][0]["conclusion"], "failure")
        self.assertIsNone(result["jobs"][0]["steps"][1]["conclusion"])
        self.assertEqual(result["jobs"][0]["step_count"], 2)
        self.assertFalse(result["truncated"])
        request.assert_called_once_with("repos/a/b/actions/runs/123/jobs", {"filter": "latest", "per_page": 11})

    async def test_jobs_and_steps_are_bounded(self):
        payload = {"total_count": 5, "jobs": [{"id": 1, "name": "x" * 201,
                    "steps": [{"number": i, "name": "x" * 201} for i in range(3)]}, {"id": 2}]}
        with patch.object(service, "_request", return_value=payload):
            result = json.loads(await self.call_jobs(limit=1, max_steps=2))
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(len(result["jobs"][0]["steps"]), 2)
        self.assertEqual(len(result["jobs"][0]["name"]), 200)
        self.assertTrue(result["truncated"])
        self.assertTrue(result["jobs"][0]["steps_truncated"])
        with patch.object(service, "_request", return_value={"total_count": 0, "jobs": []}):
            self.assertFalse(json.loads(await self.call_jobs())["truncated"])

    async def test_jobs_reject_invalid_inputs_before_fetch(self):
        for arguments in ({"run_id": 0}, {"run_id": 2**63}, {"limit": 21}, {"max_steps": 0},
                          {"max_steps": 51}, {"repo": "../private"}):
            with self.subTest(arguments=arguments), patch.object(service, "_request") as request:
                self.assertTrue((await self.call_jobs(**arguments)).startswith("Error:"))
                request.assert_not_called()

    async def test_jobs_reject_malformed_responses(self):
        for payload in ([], {"jobs": []}, {"total_count": -1, "jobs": []},
                        {"total_count": 1, "jobs": [None]}, {"total_count": 1, "jobs": [{"id": True}]},
                        {"total_count": 1, "jobs": [{"id": 1, "steps": {}}]},
                        {"total_count": 1, "jobs": [{"id": 1, "steps": [{"number": "1"}]}]}):
            with self.subTest(payload=payload), patch.object(service, "_request", return_value=payload):
                self.assertTrue((await self.call_jobs()).startswith("Error:"))

    async def test_jobs_host_pinning_http_errors_and_output_budget(self):
        body = b'{"total_count": 0, "jobs": []}'
        with patch.object(service, "fetch_page", return_value=(body, "application/json", "url")) as fetch:
            await self.call_jobs(limit=1)
        self.assertEqual(fetch.call_args.args[0], "https://api.github.com/repos/a/b/actions/runs/123/jobs?filter=latest&per_page=2")
        self.assertEqual(fetch.call_args.kwargs["allowed_host"], "api.github.com")
        for status in (403, 404, 429):
            with self.subTest(status=status), patch.object(service, "fetch_page", side_effect=ValueError(f"HTTP {status}")):
                self.assertIn(f"HTTP {status}", await self.call_jobs())
        payload = {"total_count": 20, "jobs": [{"id": i + 1,
                    "steps": [{"number": step, "name": "x" * 200} for step in range(50)]} for i in range(20)]}
        with patch.object(service, "_request", return_value=payload):
            self.assertIn("output exceeds", await self.call_jobs(limit=20, max_steps=50))


if __name__ == "__main__":
    unittest.main()
