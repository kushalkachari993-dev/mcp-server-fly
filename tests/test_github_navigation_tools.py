import json
import socket
import unittest
from unittest.mock import Mock, patch

from mcp.server.fastmcp import FastMCP
from app.tools.github_navigation import service, tool
from app.tools.webpage import service as webpage_service


SHA = "a" * 40


def response(data, headers=None):
    return (200, {"Content-Type": "application/json", **(headers or {})}, json.dumps(data).encode(), "")


def repository(**values):
    return {"id": 1, "private": False, "full_name": "a/b", "default_branch": "main", **values}


def tree_row(path, kind="blob", mode="100644"):
    return {"path": path, "type": kind, "mode": mode, "sha": SHA}


class GitHubNavigationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("github-navigation")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_repository_selected_metadata_and_anonymous_fixed_host(self):
        data = repository(archived=True, disabled=False, fork=False, stargazers_count=12, watchers_count=12,
                          subscribers_count=3, open_issues_count=4, description="About",
                          license={"key": "mit", "spdx_id": "MIT", "name": "MIT License"})
        with patch.object(service, "request_public", return_value=response(data)) as request:
            report = json.loads(await self.call("get_github_repository", owner="a", repo="b"))
        self.assertEqual(report["default_branch"], "main")
        self.assertTrue(report["archived"])
        self.assertEqual(report["stars"], 12)
        self.assertEqual(report["subscribers"], 3)
        self.assertEqual(report["open_issues_and_prs"], 4)
        self.assertEqual(report["license"]["spdx_id"], "MIT")
        self.assertIsNone(report["language"])
        args, kwargs = request.call_args
        self.assertEqual(args[0], "https://api.github.com/repos/a/b")
        self.assertFalse(kwargs["follow_redirects"])
        self.assertEqual(kwargs["allowed_host"], "api.github.com")
        self.assertNotIn("Authorization", kwargs["headers"])

    async def test_repository_nullable_license_text_limits_and_visibility(self):
        with patch.object(service, "request_public", return_value=response(repository(description="x" * 2001, topics=["topic"] * 51))):
            report = json.loads(await self.call("get_github_repository", owner="a", repo="b"))
        self.assertIsNone(report["license"])
        self.assertTrue(report["truncated"])
        self.assertEqual(len(report["topics"]), 50)
        for data in (repository(private=True), repository(private=None), {}, repository(topics="bad")):
            with patch.object(service, "request_public", return_value=response(data)):
                self.assertTrue((await self.call("get_github_repository", owner="a", repo="b")).startswith("Error:"))

    async def test_default_tree_resolves_branch_and_reports_all_truncation_sources(self):
        data = {"sha": SHA, "truncated": True, "tree": [tree_row("x.py"), tree_row("dir", "tree", "040000")]}
        with patch.object(service, "request_public", side_effect=[response(repository()), response(data)]) as request:
            report = json.loads(await self.call("list_github_repository_tree", owner="a", repo="b", limit=1))
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[1].args[0], "https://api.github.com/repos/a/b/git/trees/main?recursive=1")
        self.assertEqual(report["tree_sha"], SHA)
        self.assertEqual(report["ref"], "main")
        self.assertEqual(report["provider_entry_count"], 2)
        self.assertTrue(report["provider_truncated"])
        self.assertTrue(report["listing_truncated"])
        self.assertTrue(report["truncated"])
        self.assertIsNone(report["entries"][0]["size_bytes"])

    async def test_explicit_tree_ref_encoding_nonrecursive_symlinks_submodules_and_sizes(self):
        rows = [tree_row("link", mode="120000"), tree_row("sub", "commit", "160000"),
                {**tree_row("exec", mode="100755"), "size": 10}]
        with patch.object(service, "request_public", return_value=response({"sha": SHA, "tree": rows, "truncated": False})) as request:
            report = json.loads(await self.call("list_github_repository_tree", owner="a", repo="b", ref="feature/test", recursive=False))
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], "https://api.github.com/repos/a/b/git/trees/feature%2Ftest")
        self.assertTrue(report["entries"][0]["symlink"])
        self.assertTrue(report["entries"][1]["submodule"])
        self.assertEqual(report["entries"][2]["size_bytes"], 10)
        self.assertFalse(report["truncated"])

    async def test_empty_tree_and_invalid_tree_metadata(self):
        with patch.object(service, "request_public", return_value=response({"sha": SHA, "tree": [], "truncated": False})):
            report = json.loads(await self.call("list_github_repository_tree", owner="a", repo="b", ref=SHA))
        self.assertEqual(report["entries"], [])
        for data in ({"sha": "bad", "tree": [], "truncated": False},
                     {"sha": SHA, "tree": [], "truncated": "false"},
                     {"sha": SHA, "tree": [{**tree_row("x"), "type": []}], "truncated": False},
                     {"sha": SHA, "tree": [{**tree_row("x"), "size": -1}], "truncated": False}):
            with patch.object(service, "request_public", return_value=response(data)):
                self.assertTrue((await self.call("list_github_repository_tree", owner="a", repo="b", ref=SHA)).startswith("Error:"))

    async def test_reviews_states_commits_and_exact_page_link_metadata(self):
        rows = [{"id": 1, "state": "APPROVED", "commit_id": SHA, "body": "x" * 101, "user": {"login": "alice"}},
                {"id": 2, "state": "DISMISSED", "commit_id": "b" * 40, "body": "", "user": None}]
        with patch.object(service, "request_public", return_value=response(rows, {"Link": '<https://api.github.com/next>; rel="next"'})) as request:
            report = json.loads(await self.call("get_github_pr_reviews", owner="a", repo="b", number=9, limit=2, page=3, max_body_chars=100))
        self.assertEqual(request.call_args.args[0], "https://api.github.com/repos/a/b/pulls/9/reviews?per_page=2&page=3")
        self.assertEqual(report["page_state_counts"], {"APPROVED": 1, "DISMISSED": 1})
        self.assertEqual(report["reviews"][0]["commit_id"], SHA)
        self.assertTrue(report["reviews"][0]["body_truncated"])
        self.assertIsNone(report["reviews"][1]["author"])
        self.assertTrue(report["has_more"])
        self.assertEqual(report["next_page"], 4)
        self.assertNotIn("approved", {key.lower() for key in report})

    async def test_review_comments_locations_replies_and_file_comments_preserved(self):
        rows = [{"id": 1, "path": "x.py", "pull_request_review_id": 9, "in_reply_to_id": 3,
                 "line": None, "original_line": 10, "start_line": None, "side": "RIGHT",
                 "original_commit_id": SHA, "diff_hunk": "private source", "body": "Please fix"},
                {"id": 2, "path": "x.py", "subject_type": "file", "line": None}]
        with patch.object(service, "request_public", return_value=response(rows)) as request:
            result = await self.call("get_github_pr_review_comments", owner="a", repo="b", number=2)
        report = json.loads(result)
        self.assertEqual(request.call_args.args[0], "https://api.github.com/repos/a/b/pulls/2/comments?per_page=20&page=1")
        self.assertIsNone(report["comments"][0]["line"])
        self.assertEqual(report["comments"][0]["original_line"], 10)
        self.assertEqual(report["comments"][0]["in_reply_to_id"], 3)
        self.assertEqual(report["comments"][1]["subject_type"], "file")
        self.assertNotIn("private source", result)
        self.assertNotIn("outdated", report["comments"][0])
        self.assertNotIn("resolved", report["comments"][0])

    async def test_empty_pages_deleted_authors_nullable_dates_and_page_ceiling(self):
        for name in ("get_github_pr_reviews", "get_github_pr_review_comments"):
            with patch.object(service, "request_public", return_value=response([])):
                report = json.loads(await self.call(name, owner="a", repo="b", number=1))
            self.assertFalse(report["has_more"])
            self.assertIsNone(report["next_page"])
            with patch.object(service, "request_public", return_value=response([], {"Link": '<https://api.github.com/next>; rel="next"'})):
                report = json.loads(await self.call(name, owner="a", repo="b", number=1, page=1000))
            self.assertTrue(report["pagination_limit_reached"])
            self.assertIsNone(report["next_page"])
        with patch.object(service, "request_public", return_value=response([{"id": 1, "state": "PENDING", "submitted_at": None}])):
            report = json.loads(await self.call("get_github_pr_reviews", owner="a", repo="b", number=1))
        self.assertIsNone(report["reviews"][0]["submitted_at"])
        self.assertIsNone(report["reviews"][0]["commit_id"])

    async def test_invalid_arguments_never_call_network(self):
        cases = [("get_github_repository", {"owner": "../a"}),
                 ("list_github_repository_tree", {"ref": "a?b"}),
                 ("list_github_repository_tree", {"limit": 0}),
                 ("get_github_pr_reviews", {"number": 0}),
                 ("get_github_pr_reviews", {"page": 1001}),
                 ("get_github_pr_review_comments", {"limit": 51}),
                 ("get_github_pr_review_comments", {"max_body_chars": 99})]
        for name, args in cases:
            arguments = {"owner": "a", "repo": "b"}
            if name in {"get_github_pr_reviews", "get_github_pr_review_comments"}:
                arguments["number"] = 1
            with patch.object(service, "request_public") as request:
                self.assertTrue((await self.call(name, **{**arguments, **args})).startswith("Error:"))
                request.assert_not_called()

    async def test_malformed_pages_and_remote_errors_are_explicit(self):
        for name, rows in (("get_github_pr_reviews", [{}]), ("get_github_pr_reviews", [{"id": 1, "state": []}]),
                           ("get_github_pr_review_comments", [{"id": 1, "path": "x", "line": -1}]),
                           ("get_github_pr_review_comments", {})):
            with patch.object(service, "request_public", return_value=response(rows)):
                self.assertTrue((await self.call(name, owner="a", repo="b", number=1)).startswith("Error:"))
        for status in (301, 403, 404, 409, 429):
            with patch.object(service, "request_public", return_value=(status, {}, b"remote secret", "")):
                result = await self.call("get_github_repository", owner="a", repo="b")
            self.assertIn(str(status), result)
            self.assertNotIn("remote secret", result)
        for headers, body in (({"Content-Type": "text/html"}, b"<html>bad</html>"),
                              ({"Content-Type": "application/json"}, b"invalid")):
            with patch.object(service, "request_public", return_value=(200, headers, body, "")):
                self.assertTrue((await self.call("get_github_repository", owner="a", repo="b")).startswith("Error:"))

    async def test_tree_paths_and_output_budget_are_flagged_or_rejected(self):
        data = {"sha": SHA, "truncated": False, "tree": [tree_row("x" * 2001)]}
        with patch.object(service, "request_public", return_value=response(data)):
            report = json.loads(await self.call("list_github_repository_tree", owner="a", repo="b", ref=SHA))
        self.assertTrue(report["text_truncated"])
        self.assertTrue(report["entries"][0]["path_truncated"])
        rows = [{"id": i + 1, "state": "COMMENTED", "body": "x" * 10000} for i in range(50)]
        with patch.object(service, "request_public", return_value=response(rows)):
            result = await self.call("get_github_pr_reviews", owner="a", repo="b", number=1, limit=50, max_body_chars=10000)
        self.assertTrue(result.startswith("Error:"))
        self.assertIn("Output exceeds", result)

    async def test_shared_network_public_address_guard_and_download_limit(self):
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch.object(webpage_service.socket, "getaddrinfo", return_value=private), patch.object(
            webpage_service.urllib3, "HTTPSConnectionPool") as pool:
            self.assertIn("blocked", await self.call("get_github_repository", owner="a", repo="b"))
            pool.assert_not_called()
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
        response_mock = Mock(status=200, headers={"Content-Type": "application/json"})
        response_mock.read.side_effect = [b"x" * 1000001]
        with patch.object(webpage_service.socket, "getaddrinfo", return_value=public), patch.object(
            webpage_service.urllib3, "HTTPSConnectionPool") as pool:
            pool.return_value.urlopen.return_value = response_mock
            self.assertIn("1 MB", await self.call("list_github_repository_tree", owner="a", repo="b", ref=SHA))

    async def test_four_tools_registered(self):
        self.assertEqual({item.name for item in await self.mcp.list_tools()}, {
            "get_github_repository", "list_github_repository_tree", "get_github_pr_reviews", "get_github_pr_review_comments"})


if __name__ == "__main__":
    unittest.main()
