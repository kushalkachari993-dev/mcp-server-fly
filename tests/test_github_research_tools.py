import base64
import json
import socket
import unittest
from unittest.mock import Mock, patch

from mcp.server.fastmcp import FastMCP
from app.tools.github_research import service, tool
from app.tools.github_navigation import service as navigation
from app.tools.webpage import service as transport


SHA = "a" * 40
NEXT = {"Link": '<https://api.github.com/ignored?page=2>; rel="next"'}
TOOLS = {
    "list_github_issues", "list_github_pull_requests", "list_github_branches", "list_github_tags",
    "list_github_commits", "list_github_contributors", "get_github_repository_languages",
    "get_github_repository_license", "list_github_workflows", "get_github_workflow_run",
    "get_github_workflow_job", "get_github_release", "list_github_release_assets",
}


class GitHubResearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("github-research")
        tool.register(self.mcp)

    async def call(self, name, **args):
        result = await self.mcp.call_tool(name, {"owner": "a", "repo": "b", **args})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def report(self, name, data, headers=None, **args):
        with patch.object(service, "_request", return_value=(data, headers or {})) as request:
            result = json.loads(await self.call(name, **args))
        return result, request

    async def test_thirteen_tools_registered(self):
        self.assertEqual({item.name for item in await self.mcp.list_tools()}, TOOLS)

    async def test_issue_filter_pagination_and_body_limits(self):
        rows = [{"id": 1, "number": 2, "title": "Bug", "body": "x" * 101, "labels": [{"name": "bug"}]},
                {"id": 2, "number": 3, "pull_request": {}}]
        report, request = await self.report("list_github_issues", rows, NEXT, state="all", labels="bug,api",
                                            limit=2, page=3, max_body_chars=100)
        self.assertEqual(request.call_args.args, ("repos/a/b", "/issues", {
            "state": "all", "sort": "updated", "direction": "desc", "labels": "bug,api", "per_page": 2, "page": 3}))
        self.assertEqual(report["scanned_items"], 2)
        self.assertEqual(report["excluded_pull_requests"], 1)
        self.assertEqual(report["returned_items"], 1)
        self.assertTrue(report["issues"][0]["body_truncated"])
        self.assertTrue(report["has_more"])
        self.assertEqual(report["next_page"], 4)
        report, _ = await self.report("list_github_issues", [{"id": 1, "pull_request": {}}], NEXT, limit=1)
        self.assertEqual(report["issues"], [])
        self.assertTrue(report["has_more"])

    async def test_pr_filters_and_base_head_commits(self):
        data = [{"id": 3, "number": 5, "draft": True, "head": {"ref": "feature/x", "sha": SHA},
                 "base": {"ref": "main", "sha": "b" * 40}, "body": "not returned"}]
        report, request = await self.report("list_github_pull_requests", data, state="closed", base="main", head="alice:feature/x")
        self.assertEqual(request.call_args.args[2]["head"], "alice:feature/x")
        self.assertEqual(report["pull_requests"][0]["head"]["sha"], SHA)
        self.assertTrue(report["pull_requests"][0]["draft"])
        self.assertNotIn("body", report["pull_requests"][0])

    async def test_branches_and_tags_preserve_names_shas_and_protection(self):
        rows = [{"name": "release/v2", "protected": True, "commit": {"sha": SHA}}]
        branches, _ = await self.report("list_github_branches", rows)
        tags, _ = await self.report("list_github_tags", rows)
        self.assertEqual(branches["branches"][0], {"name": "release/v2", "sha": SHA, "protected": True})
        self.assertEqual(tags["tags"][0]["commit_sha"], SHA)
        self.assertFalse(tags["truncated"])

    async def test_commit_history_filters_parents_and_provider_verification(self):
        rows = [{"sha": SHA, "author": None, "parents": [{"sha": "b" * 40}],
                 "commit": {"message": "x" * 101, "author": {"email": "private@example.com", "date": "2026-10-05"},
                            "verification": {"verified": True, "reason": "valid", "signature": "secret"}}}]
        report, request = await self.report("list_github_commits", rows, ref="feature/x", path="src/x.py", max_message_chars=100)
        self.assertEqual(request.call_args.args[2]["sha"], "feature/x")
        self.assertEqual(request.call_args.args[2]["path"], "src/x.py")
        commit = report["commits"][0]
        self.assertTrue(commit["provider_verified"])
        self.assertTrue(commit["message_truncated"])
        self.assertEqual(commit["parent_shas"], ["b" * 40])
        self.assertNotIn("private@example.com", json.dumps(report))
        self.assertNotIn("secret", json.dumps(report))

    async def test_contributors_counts_and_empty_repository_204(self):
        report, request = await self.report("list_github_contributors", [{"id": 1, "login": "alice", "contributions": 4}])
        self.assertEqual(report["contributors"][0]["contributions"], 4)
        self.assertTrue(request.call_args.kwargs["allow_empty_list"])
        with patch.object(navigation, "request_public", return_value=(204, {}, b"", "")):
            report = json.loads(await self.call("list_github_contributors"))
        self.assertEqual(report["contributors"], [])
        # 204 is accepted only for endpoints that explicitly allow empty lists.
        with patch.object(navigation, "request_public", return_value=(204, {}, b"", "")):
            self.assertIn("204", await self.call("get_github_repository_languages"))

    async def test_language_shares_use_full_response_and_handle_empty(self):
        report, _ = await self.report("get_github_repository_languages", {"Python": 75, "JavaScript": 25}, limit=1)
        self.assertEqual(report["languages"], [{"language": "Python", "bytes": 75, "percent": 75.0}])
        self.assertEqual(report["total_reported_bytes"], 100)
        self.assertTrue(report["truncated"])
        empty, _ = await self.report("get_github_repository_languages", {})
        self.assertEqual(empty["total_reported_bytes"], 0)
        zero, _ = await self.report("get_github_repository_languages", {"Python": 0})
        self.assertEqual(zero["languages"][0]["percent"], 0)

    async def test_license_inline_decoding_ref_and_shortening(self):
        content = "License café\n" * 20
        encoded = base64.b64encode(content.encode()).decode()
        data = {"sha": SHA, "encoding": "base64", "size": len(content.encode()), "content": encoded[:50] + "\n" + encoded[50:],
                "path": "LICENSE", "license": {"spdx_id": "NOASSERTION", "name": "Other"}}
        report, request = await self.report("get_github_repository_license", data, ref="main", max_chars=100)
        self.assertEqual(request.call_args.args, ("repos/a/b", "/license", {"ref": "main"}))
        self.assertEqual(report["content"], content[:100])
        self.assertTrue(report["content_truncated"])
        self.assertEqual(report["spdx_id"], "NOASSERTION")
        self.assertEqual(report["decoded_bytes"], len(content.encode()))

    async def test_workflow_listing_envelope_total_and_provider_state(self):
        data = {"total_count": 3, "workflows": [{"id": 9, "name": "CI", "path": ".github/workflows/ci.yml", "state": "disabled_manually"}]}
        report, request = await self.report("list_github_workflows", data, NEXT, limit=1)
        self.assertEqual(request.call_args.args[1], "/actions/workflows")
        self.assertEqual(report["total_count"], 3)
        self.assertEqual(report["workflows"][0]["state"], "disabled_manually")
        self.assertTrue(report["has_more"])

    async def test_workflow_run_attempt_actors_and_pending_conclusion(self):
        data = {"id": 2**40, "workflow_id": 9, "run_attempt": 2, "status": "in_progress", "conclusion": None,
                "head_sha": SHA, "pull_requests": [{"number": 4}], "actor": {"login": "alice"},
                "triggering_actor": {"login": "bob"}}
        report, request = await self.report("get_github_workflow_run", data, run_id=2**40)
        self.assertEqual(request.call_args.args[1], f"/actions/runs/{2**40}")
        self.assertEqual(report["run_attempt"], 2)
        self.assertIsNone(report["conclusion"])
        self.assertEqual(report["triggering_actor"]["login"], "bob")
        self.assertEqual(report["pull_request_numbers"], [4])

    async def test_workflow_job_steps_runner_and_step_limit(self):
        data = {"id": 5, "run_id": 9, "runner_name": "worker", "labels": ["self-hosted"], "steps": [
            {"number": 1, "name": "Build", "status": "completed", "conclusion": "failure"},
            {"number": 2, "name": "Deploy", "status": "queued", "conclusion": None}]}
        report, _ = await self.report("get_github_workflow_job", data, job_id=5, max_steps=1)
        self.assertEqual(report["step_count"], 2)
        self.assertTrue(report["steps_truncated"])
        self.assertEqual(report["steps"][0]["conclusion"], "failure")
        self.assertEqual(report["runner_name"], "worker")

    async def test_release_latest_and_tag_route_with_returned_release_id(self):
        data = {"id": 7, "tag_name": "v1", "body": "x" * 101, "prerelease": False, "assets": [{"id": 8}]}
        latest, request = await self.report("get_github_release", data, max_body_chars=100)
        self.assertEqual(request.call_args.args[1], "/releases/latest")
        self.assertEqual(latest["id"], 7)
        self.assertTrue(latest["body_truncated"])
        self.assertEqual(latest["embedded_asset_count"], 1)
        tagged, request = await self.report("get_github_release", data, tag="release/v1")
        self.assertEqual(request.call_args.args[1], "/releases/tags/release%2Fv1")
        self.assertEqual(tagged["selector"], "release/v1")

    async def test_assets_download_links_and_declared_digest_no_download(self):
        rows = [{"id": 8, "name": "tool.zip", "size": 100, "digest": "sha256:abc", "download_count": 4,
                 "browser_download_url": "https://example.com/tool.zip"}]
        report, request = await self.report("list_github_release_assets", rows, NEXT, release_id=7, limit=1)
        request.assert_called_once()
        self.assertEqual(request.call_args.args[1], "/releases/7/assets")
        self.assertEqual(report["assets"][0]["digest"], "sha256:abc")
        self.assertEqual(report["assets"][0]["download_url"], "https://example.com/tool.zip")
        self.assertTrue(report["has_more"])

    async def test_every_list_exact_page_sizes_no_extra_fetches_and_empty_pages(self):
        for name, args, data in (
            ("list_github_issues", {}, []), ("list_github_pull_requests", {}, []),
            ("list_github_branches", {}, []), ("list_github_tags", {}, []), ("list_github_commits", {}, []),
            ("list_github_contributors", {}, []), ("list_github_workflows", {}, {"total_count": 0, "workflows": []}),
            ("list_github_release_assets", {"release_id": 1}, [])):
            with self.subTest(name=name):
                report, request = await self.report(name, data, NEXT, limit=2, page=1000, **args)
                request.assert_called_once()
                self.assertEqual(request.call_args.args[2]["per_page"], 2)
                self.assertTrue(report["pagination_limit_reached"])
                self.assertIsNone(report["next_page"])
                self.assertEqual(report["returned_items"], 0)

    async def test_invalid_inputs_fail_before_network(self):
        cases = [("list_github_issues", {"state": "bad"}), ("list_github_issues", {"labels": "a\nb"}),
                 ("list_github_pull_requests", {"head": "alice:"}), ("list_github_pull_requests", {"head": "branch"}),
                 ("list_github_branches", {"limit": 51}), ("list_github_tags", {"page": 0}),
                 ("list_github_commits", {"path": "../x"}), ("list_github_commits", {"ref": "a?b"}),
                 ("list_github_contributors", {"owner": "../a"}), ("get_github_repository_languages", {"limit": 0}),
                 ("get_github_repository_license", {"max_chars": 99}), ("list_github_workflows", {"page": 1001}),
                 ("get_github_workflow_run", {"run_id": 0}), ("get_github_workflow_job", {"job_id": 1, "max_steps": 101}),
                 ("get_github_release", {"tag": "../x"}), ("list_github_release_assets", {"release_id": -1})]
        for name, args in cases:
            with self.subTest(name=name, args=args), patch.object(service, "_request") as request:
                self.assertTrue((await self.call(name, **args)).startswith("Error:"))
                request.assert_not_called()

    async def test_malformed_responses_for_all_thirteen_tools(self):
        cases = [("list_github_issues", {}, [{}]), ("list_github_pull_requests", {}, [{"id": 1}]),
                 ("list_github_branches", {}, [{"name": "x", "commit": {"sha": "bad"}}]),
                 ("list_github_tags", {}, [None]), ("list_github_commits", {}, [{"sha": SHA, "parents": [None]}]),
                 ("list_github_contributors", {}, [{"id": 1, "contributions": -1}]),
                 ("get_github_repository_languages", {}, {"Python": True}),
                 ("get_github_repository_license", {}, {"encoding": "base64", "sha": SHA, "size": 4, "content": "bad!"}),
                 ("list_github_workflows", {}, {"total_count": 0, "workflows": [{"id": 1}]}),
                 ("get_github_workflow_run", {"run_id": 1}, {"id": 2}),
                 ("get_github_workflow_job", {"job_id": 1}, {"id": 1, "steps": [{"number": -1}]}),
                 ("get_github_release", {}, {"id": 1, "assets": {}}),
                 ("list_github_release_assets", {"release_id": 1}, [{"id": "bad"}])]
        for name, args, data in cases:
            with self.subTest(name=name), patch.object(service, "_request", return_value=(data, {})):
                self.assertTrue((await self.call(name, **args)).startswith("Error:"))

    async def test_request_encoding_no_tokens_and_provider_errors(self):
        rows = [{"id": 1, "number": 1}]
        with patch.object(navigation, "request_public", return_value=(200, {"Content-Type": "application/json"}, json.dumps(rows).encode(), "")) as request:
            await self.call("list_github_issues", labels="bug,needs review")
        args, kwargs = request.call_args
        self.assertIn("labels=bug%2Cneeds+review", args[0])
        self.assertEqual(kwargs["allowed_host"], "api.github.com")
        self.assertFalse(kwargs["follow_redirects"])
        self.assertNotIn("Authorization", kwargs["headers"])
        for status in (301, 403, 404, 409, 429):
            with patch.object(navigation, "request_public", return_value=(status, {}, b"secret details", "")):
                result = await self.call("get_github_repository_languages")
            self.assertIn(str(status), result)
            self.assertNotIn("secret details", result)

    async def test_output_expansion_is_atomic_and_no_partial_release_notes(self):
        with patch.object(service, "_request", return_value=([{"id": 1, "number": 1, "body": "é" * 10000}] * 50, {})):
            result = await self.call("list_github_issues", limit=50, max_body_chars=10000)
        self.assertTrue(result.startswith("Error:"))
        self.assertIn("Output exceeds", result)

    async def test_public_destination_guard_and_download_limit_are_reused(self):
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch.object(transport.socket, "getaddrinfo", return_value=private), patch.object(
            transport.urllib3, "HTTPSConnectionPool") as pool:
            self.assertIn("blocked", await self.call("list_github_tags"))
            pool.assert_not_called()
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
        response = Mock(status=200, headers={"Content-Type": "application/json"})
        response.read.side_effect = [b"x" * 1000001]
        with patch.object(transport.socket, "getaddrinfo", return_value=public), patch.object(
            transport.urllib3, "HTTPSConnectionPool") as pool:
            pool.return_value.urlopen.return_value = response
            self.assertIn("1 MB", await self.call("list_github_tags"))


if __name__ == "__main__":
    unittest.main()
