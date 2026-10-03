import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.github_utils import service, tool


class GithubCommitToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("github-commit-tests")
        tool.register(self.mcp)

    async def call(self, **arguments):
        result = await self.mcp.call_tool("get_github_commit", {"owner": "a", "repo": "b", "ref": "main", **arguments})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_commit_metadata_and_files(self):
        payload = {"sha": "a" * 40, "html_url": "https://github.com/a/b/commit/abc",
                   "commit": {"message": "Fix issue", "author": {"name": "Ada", "email": "ada@example.com", "date": "2026-01-01"},
                              "committer": {"name": "Bot", "email": "bot@example.com", "date": "2026-01-02"},
                              "verification": {"verified": True, "reason": "valid"}},
                   "parents": [{"sha": "b" * 40}], "stats": {"additions": 2, "deletions": 1, "total": 3},
                   "files": [{"filename": "app.py", "status": "modified", "additions": 2, "deletions": 1, "changes": 3}]}
        with patch.object(service, "_request", return_value=payload) as request:
            result = json.loads(await self.call())
        self.assertEqual(result["message"], "Fix issue")
        self.assertTrue(result["verification"]["verified"])
        self.assertEqual(result["files"][0]["path"], "app.py")
        request.assert_called_once_with("repos/a/b/commits/main")

    async def test_invalid_ref_and_file_response(self):
        with patch.object(service, "_request") as request:
            self.assertTrue((await self.call(ref="../secret")).startswith("Error:"))
            request.assert_not_called()
        with patch.object(service, "_request", return_value={"sha": "a", "commit": {}, "files": [{}]}):
            self.assertTrue((await self.call()).startswith("Error:"))


if __name__ == "__main__":
    unittest.main()
