import base64
import json
import socket
import unittest
from io import BytesIO
from unittest.mock import Mock, patch

from mcp.server.fastmcp import FastMCP
from pypdf import PdfWriter

from app.tools.github_utils import service as github_service
from app.tools.github_utils import tool as github_tools
from app.tools.openapi_utils import service as openapi_service
from app.tools.openapi_utils import tool as openapi_tools
from app.tools.pdf_utils import service as pdf_service
from app.tools.pdf_utils import tool as pdf_tools
from app.tools.webpage import service as webpage_service


def _blank_pdf(pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class DocumentToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("document-tests")
        for module in (pdf_tools, github_tools, openapi_tools):
            module.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_pdf_blank_page_and_page_selection(self):
        body = _blank_pdf(2)
        with patch.object(pdf_tools, "fetch_page", return_value=(body, "application/pdf", "https://example.com/a.pdf")):
            result = json.loads(await self.call("extract_pdf_text", url="https://example.com/a.pdf", max_pages=1))
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(result["pages"], [{"number": 1, "text": ""}])
        self.assertTrue(result["truncated"])
        self.assertTrue(result["scanned_possible"])
        with patch.object(pdf_tools, "fetch_page", return_value=(body, "application/pdf", "https://example.com/a.pdf")):
            result = json.loads(await self.call("extract_pdf_text", url="https://example.com/a.pdf", start_page=2))
        self.assertEqual(result["pages"], [{"number": 2, "text": ""}])
        self.assertFalse(result["truncated"])

    async def test_pdf_invalid_input_and_limits(self):
        body = _blank_pdf()
        for arguments in ({"start_page": 0}, {"start_page": 2}, {"max_pages": 11}, {"max_chars": 99}):
            with self.subTest(arguments=arguments), patch.object(
                pdf_tools, "fetch_page", return_value=(body, "application/pdf", "https://example.com/a.pdf")
            ):
                self.assertTrue((await self.call("extract_pdf_text", url="https://example.com/a.pdf", **arguments)).startswith("Error:"))
        with patch.object(pdf_tools, "fetch_page", return_value=(b"not a PDF", "application/pdf", "https://example.com/a.pdf")):
            self.assertIn("not a PDF", await self.call("extract_pdf_text", url="https://example.com/a.pdf"))
        with patch.object(pdf_tools, "fetch_page", side_effect=ValueError("non-public blocked")):
            self.assertIn("blocked", await self.call("extract_pdf_text", url="https://example.com/a.pdf"))

    async def test_pdf_worker_rejects_busy_slot(self):
        self.assertTrue(pdf_service._PDF_SLOT.acquire(blocking=False))
        try:
            with self.assertRaisesRegex(ValueError, "busy"):
                pdf_service.extract_pdf(_blank_pdf(), 1, 1, 100)
        finally:
            pdf_service._PDF_SLOT.release()

    async def test_github_file_decodes_utf8_and_truncates(self):
        payload = {"type": "file", "encoding": "base64", "size": 120,
                   "sha": "abc123", "content": base64.b64encode(b"a" * 120).decode()}
        with patch.object(github_service, "_request", return_value=payload) as request:
            result = json.loads(await self.call("get_github_file", owner="psf", repo="requests", path="docs/file.txt",
                                                ref="main", max_chars=100))
        self.assertEqual(result["content"], "a" * 100)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["sha"], "abc123")
        request.assert_called_once_with("repos/psf/requests/contents/docs/file.txt", {"ref": "main"})

    async def test_github_file_rejects_directories_binary_and_bad_paths(self):
        for data in ({"type": "dir"}, {"type": "file", "encoding": "base64", "size": 1000001, "content": ""},
                     {"type": "file", "encoding": "base64", "size": 1, "content": "/w=="}):
            with self.subTest(data=data), patch.object(github_service, "_request", return_value=data):
                self.assertTrue((await self.call("get_github_file", owner="psf", repo="requests", path="README.md")).startswith("Error:"))
        for path in ("", "../.env", "a//b", "a\\b", "/etc/passwd"):
            with self.subTest(path=path), patch.object(github_service, "_request") as request:
                self.assertTrue((await self.call("get_github_file", owner="psf", repo="requests", path=path)).startswith("Error:"))
                request.assert_not_called()

    async def test_github_issue_and_pr_are_distinct(self):
        issue = {"number": 7, "title": "Fix it", "state": "open", "html_url": "https://github.com/a/b/issues/7",
                 "user": {"login": "ada"}, "labels": [{"name": "bug"}], "body": "Details"}
        with patch.object(github_service, "_request", return_value=issue):
            result = json.loads(await self.call("get_github_issue", owner="a", repo="b", number=7))
        self.assertEqual(result["author"], "ada")
        self.assertEqual(result["labels"], ["bug"])
        with patch.object(github_service, "_request", return_value={**issue, "pull_request": {}}):
            self.assertIn("pull request", await self.call("get_github_issue", owner="a", repo="b", number=7))

    async def test_github_pr_changed_files_and_limit(self):
        pr = {"number": 3, "title": "Add API", "state": "closed", "draft": False, "merged": True,
              "changed_files": 2, "base": {"ref": "main"}, "head": {"ref": "feature"}, "body": "Why"}
        files = [{"filename": "app.py", "status": "modified", "additions": 2, "deletions": 1}]
        with patch.object(github_service, "_request", side_effect=[pr, files]) as request:
            result = json.loads(await self.call("get_github_pull_request", owner="a", repo="b", number=3, max_files=1))
        self.assertEqual(result["files"][0]["path"], "app.py")
        self.assertTrue(result["truncated"])
        self.assertTrue(result["merged"])
        self.assertEqual(request.call_args_list[1].args[1], {"per_page": 1})
        with patch.object(github_service, "_request", return_value={**pr, "changed_files": 0}) as request:
            result = json.loads(await self.call("get_github_pull_request", owner="a", repo="b", number=3))
        self.assertEqual(len(request.call_args_list), 1)
        self.assertEqual(result["files"], [])

    async def test_github_releases_and_invalid_parameters(self):
        releases = [{"tag_name": "v1", "name": "First", "html_url": "https://github.com/a/b/releases/tag/v1",
                     "published_at": "2026-09-29T00:00:00Z", "prerelease": False, "body": "Notes"},
                    {"tag_name": "v0", "name": "Old"}]
        with patch.object(github_service, "_request", return_value=releases):
            result = json.loads(await self.call("list_github_releases", owner="a", repo="b", limit=1))
        self.assertEqual(result["releases"][0]["tag"], "v1")
        self.assertTrue(result["truncated"])
        for name, args in (("get_github_issue", {"number": 0}),
                           ("get_github_pull_request", {"number": 1, "max_files": 0}),
                           ("list_github_releases", {"limit": 21}),
                           ("get_github_file", {"path": "README.md", "max_chars": 99})):
            with self.subTest(name=name):
                self.assertTrue((await self.call(name, owner="a", repo="b", **args)).startswith("Error:"))

    async def test_github_api_pins_host_on_redirect(self):
        with patch.object(github_service, "fetch_page", return_value=(b'{}', "application/json", "https://api.github.com/")) as fetch:
            self.assertEqual(github_service._request("repos/a/b"), {})
        self.assertEqual(fetch.call_args.kwargs["allowed_host"], "api.github.com")
        self.assertIn("application/json", fetch.call_args.kwargs["media_types"])
        response = Mock(status=302, headers={"Location": "https://other.example/data"})
        pool = Mock()
        pool.urlopen.return_value = response
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
        with patch.object(webpage_service.socket, "getaddrinfo", return_value=addresses), patch.object(
            webpage_service.urllib3, "HTTPSConnectionPool", return_value=pool
        ):
            with self.assertRaisesRegex(ValueError, "not allowed"):
                webpage_service.fetch_page("https://api.github.com/repos/a/b", media_types={"application/json"},
                                           allowed_host="api.github.com")
        self.assertEqual(pool.urlopen.call_count, 1)

    async def test_openapi_json_security_override_and_refs(self):
        spec = {"openapi": "3.1.0", "info": {"title": "Demo", "version": "1.0"},
                "servers": [{"url": "https://example.com"}], "security": [{"apiKey": []}],
                "paths": {"/items": {"get": {"summary": "List", "operationId": "listItems", "tags": ["items"]},
                                     "post": {"summary": "Create", "security": []},
                                     "delete": {"$ref": "https://elsewhere.example/delete.yml"}},
                          "/remote": {"$ref": "https://elsewhere.example/paths.yml"}}}
        with patch.object(openapi_tools, "fetch_page", return_value=(json.dumps(spec).encode(), "application/json", "https://example.com/openapi.json")):
            result = json.loads(await self.call("inspect_openapi", url="https://example.com/openapi.json", max_operations=1))
        self.assertEqual(result["title"], "Demo")
        self.assertEqual(result["operations"][0]["security_schemes"], ["apiKey"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["unresolved_path_refs"], 0)
        result = openapi_service.inspect_spec(json.dumps(spec).encode(), "https://example.com/openapi.json", 10)
        self.assertEqual(result["operations"][1]["security_schemes"], [])
        self.assertEqual(result["unresolved_path_refs"], 1)
        self.assertEqual(result["unresolved_operation_refs"], 1)

    async def test_openapi_yaml_and_invalid_input(self):
        yaml_spec = b'''openapi: 3.0.3
info: {title: Test API, version: '2'}
paths:
  /pets:
    get:
      summary: List pets
'''
        with patch.object(openapi_tools, "fetch_page", return_value=(yaml_spec, "text/yaml", "https://example.com/openapi.yaml")):
            result = json.loads(await self.call("inspect_openapi", url="https://example.com/openapi.yaml"))
        self.assertEqual(result["operations"][0]["method"], "GET")
        for body in (b'{"swagger":"2.0","info":{},"paths":{}}', b'{', b'openapi: 3.0.0\npaths: []',
                     b'openapi: 3.0.0\ninfo: {}\npaths: {}\ninfo: {}', b'\xff', b' ' * 200001):
            with self.subTest(body=body[:40]), patch.object(openapi_tools, "fetch_page", return_value=(body, "text/plain", "https://example.com/spec")):
                self.assertTrue((await self.call("inspect_openapi", url="https://example.com/spec")).startswith("Error:"))
        self.assertTrue((await self.call("inspect_openapi", url="https://example.com", max_operations=201)).startswith("Error:"))

    async def test_openapi_blocks_private_fetches(self):
        with patch.object(openapi_tools, "fetch_page", side_effect=ValueError("non-public address blocked")):
            self.assertIn("blocked", await self.call("inspect_openapi", url="http://localhost/openapi.yaml"))


if __name__ == "__main__":
    unittest.main()
