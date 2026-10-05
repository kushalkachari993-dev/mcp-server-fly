import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP
from app.tools.developer_search import service, tool


DIFF = '''diff --git a/x.py b/x.py
index 111..222 100644
--- a/x.py
+++ b/x.py
@@ -1,2 +1,2 @@ def run():
-old
+new
 same
'''


class DeveloperSearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("developer-search")
        tool.register(self.mcp)

    async def call(self, name, **args):
        result = await self.mcp.call_tool(name, args)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_issue_search_query_pagination_and_bounded_body(self):
        data = {"total_count": 51, "incomplete_results": True, "items": [
            {"number": 1, "title": "Bug", "body": "x" * 3000, "state": "open"}]}
        with patch.object(service, "_request", return_value=data) as request:
            report = json.loads(await self.call("search_github_issues", query="timeout repo:a/b", limit=2, page=2))
        request.assert_called_once_with("search/issues", {"q": "timeout repo:a/b is:issue", "per_page": 2, "page": 2})
        self.assertTrue(report["has_more"])
        self.assertTrue(report["incomplete_results"])
        self.assertEqual(len(report["results"][0]["body"]), 2000)
        self.assertTrue(report["results"][0]["body_truncated"])

    async def test_code_auth_fixed_host_no_redirects_and_public_filter(self):
        data = {"total_count": 2, "incomplete_results": False, "items": [
            {"path": "x.py", "repository": {"private": False, "full_name": "a/b"}},
            {"path": "private", "repository": {"private": True}}]}
        response = (200, {"Content-Type": "application/json"}, json.dumps(data).encode(), "")
        with patch.dict(service.os.environ, {"GITHUB_SEARCH_TOKEN": "test-secret"}), patch.object(service, "request_public", return_value=response) as request:
            result = await self.call("search_github_code", query="run repo:a/b")
        report = json.loads(result)
        self.assertEqual(report["results"][0]["repository"], "a/b")
        self.assertEqual(report["excluded_nonpublic_or_unknown"], 1)
        self.assertNotIn("test-secret", result)
        args, kwargs = request.call_args
        self.assertTrue(args[0].startswith("https://api.github.com/search/code?"))
        self.assertIn("is%3Apublic", args[0])
        self.assertFalse(kwargs["follow_redirects"])
        self.assertEqual(kwargs["allowed_host"], "api.github.com")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-secret")

    async def test_search_invalid_inputs_and_response_metadata(self):
        for name in ("search_github_code", "search_github_issues"):
            for args in ({"query": ""}, {"query": "a\nb"}, {"query": "x" * 501},
                         {"query": "x", "limit": 51}, {"query": "x", "page": 21}, {"query": "a OR b"}):
                with patch.object(service, "_request") as request, patch.object(service, "request_public") as public:
                    self.assertTrue((await self.call(name, **args)).startswith("Error:"))
                    request.assert_not_called()
                    public.assert_not_called()
        with patch.dict(service.os.environ, {}, clear=True):
            self.assertIn("GITHUB_SEARCH_TOKEN", await self.call("search_github_code", query="x"))
        with patch.object(service, "_request", return_value={"items": []}):
            self.assertTrue((await self.call("search_github_issues", query="x")).startswith("Error:"))

    async def test_code_errors_never_echo_token_or_remote_body(self):
        for status in (401, 403, 422, 302):
            with patch.dict(service.os.environ, {"GITHUB_SEARCH_TOKEN": "test-secret"}), patch.object(
                service, "request_public", return_value=(status, {}, b"test-secret", "")):
                result = await self.call("search_github_code", query="x")
            self.assertIn(str(status), result)
            self.assertNotIn("test-secret", result)
        with patch.dict(service.os.environ, {"GITHUB_SEARCH_TOKEN": "test-secret"}), patch.object(
            service, "request_public", side_effect=OSError("test-secret")):
            self.assertNotIn("test-secret", await self.call("search_github_code", query="x"))

    async def test_diff_counts_context_no_source_and_default_hunk_lengths(self):
        report = json.loads(await self.call("inspect_git_diff", content=DIFF))
        self.assertEqual((report["additions"], report["deletions"]), (1, 1))
        self.assertEqual(report["files"][0]["hunk_contexts"], ["def run():"])
        self.assertFalse(report["symbols_inferred"])
        single = DIFF.replace("@@ -1,2 +1,2 @@ def run():", "@@ -1 +1 @@").replace(" same\n", "")
        self.assertEqual(json.loads(await self.call("inspect_git_diff", content=single))["additions"], 1)

    async def test_diff_new_deleted_rename_copy_binary_mode_and_totals(self):
        text = '''diff --git a/new b/new
new file mode 100644
--- /dev/null
+++ b/new
@@ -0,0 +1 @@
+hello
diff --git a/old b/old
deleted file mode 100644
--- a/old
+++ /dev/null
@@ -1 +0,0 @@
-bye
diff --git a/a b/b
similarity index 100%
rename from a
rename to b
diff --git a/c b/d
copy from c
copy to d
diff --git a/img b/img
Binary files a/img and b/img differ
diff --git a/script b/script
old mode 100644
new mode 100755
'''
        report = json.loads(await self.call("inspect_git_diff", content=text))
        self.assertEqual([f["status"] for f in report["files"]], ["added", "deleted", "renamed", "copied", "modified", "modified"])
        self.assertTrue(report["files"][4]["binary"])
        report = json.loads(await self.call("inspect_git_diff", content=text, limit=1))
        self.assertEqual(report["file_count"], 6)
        self.assertEqual((report["additions"], report["deletions"]), (1, 1))
        self.assertTrue(report["truncated"])

    async def test_diff_quoted_octal_spaces_and_headerlike_source(self):
        text = 'diff --git "a/caf\\303\\251 x" "b/caf\\303\\251 x"\n--- "a/caf\\303\\251 x"\n+++ "b/caf\\303\\251 x"\n@@ -0,0 +1,2 @@\n+diff --git a/fake b/fake\n++++ misleading\n'
        report = json.loads(await self.call("inspect_git_diff", content=text))
        self.assertEqual(report["files"][0]["after_path"], "café x")
        self.assertEqual(report["file_count"], 1)
        self.assertEqual(report["additions"], 2)

    async def test_diff_rejects_incomplete_mismatched_combined_and_limits(self):
        for content in (DIFF.replace(" same\n", ""), DIFF + "+extra\n", "diff --cc file\n",
                        "--- a/x\n+++ b/x\n", "junk", "x" * 200001):
            self.assertTrue((await self.call("inspect_git_diff", content=content)).startswith("Error:"))
        self.assertEqual(json.loads(await self.call("inspect_git_diff", content=""))["file_count"], 0)
        self.assertTrue((await self.call("inspect_git_diff", content=DIFF, limit=0)).startswith("Error:"))

    async def test_three_tools_registered(self):
        self.assertEqual({t.name for t in await self.mcp.list_tools()}, {
            "search_github_code", "search_github_issues", "inspect_git_diff"})


if __name__ == "__main__":
    unittest.main()
