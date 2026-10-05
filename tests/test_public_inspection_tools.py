import json
import socket
import stat
import unittest
import warnings
import zipfile
from io import BytesIO
from unittest.mock import Mock, patch

from mcp.server.fastmcp import FastMCP
from app.tools.public_inspection import service, tool
from app.tools.webpage import service as webpage_service


def archive_bytes():
    output = BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("dir/", "")
            archive.writestr("dir/file.txt", "hello" * 1000)
            archive.writestr("dir/file.txt", "again")
            archive.writestr("../outside", "secret")
            symlink = zipfile.ZipInfo("link")
            symlink.create_system = 3
            symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(symlink, "../outside")
    return output.getvalue()


class PublicInspectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("public-inspection")
        tool.register(self.mcp)

    async def call(self, name, **args):
        result = await self.mcp.call_tool(name, args)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_comments_exact_page_size_link_and_body_truncation(self):
        rows = [{"id": 7, "user": {"login": "maintainer"}, "body": "x" * 150, "author_association": "MEMBER"}]
        headers = {"Content-Type": "application/json", "Link": '<https://api.github.com/next>; rel="next"'}
        with patch.object(service, "request_public", return_value=(200, headers, json.dumps(rows).encode(), "")) as request:
            report = json.loads(await self.call("get_github_issue_comments", owner="a", repo="b", number=2,
                                              limit=1, page=3, max_body_chars=100))
        self.assertTrue(report["has_more"])
        self.assertEqual(report["next_page"], 4)
        self.assertEqual(report["comments"][0]["author"], "maintainer")
        self.assertTrue(report["comments"][0]["body_truncated"])
        self.assertEqual(len(report["comments"][0]["body"]), 100)
        args, kwargs = request.call_args
        self.assertEqual(args[0], "https://api.github.com/repos/a/b/issues/2/comments?per_page=1&page=3")
        self.assertEqual(kwargs["allowed_host"], "api.github.com")
        self.assertFalse(kwargs["follow_redirects"])
        self.assertNotIn("Authorization", kwargs["headers"])

    async def test_comments_deleted_author_empty_and_malformed(self):
        for rows in ([], [{"id": 1, "user": None, "body": None}]):
            with patch.object(service, "request_public", return_value=(200, {"content-type": "application/json"}, json.dumps(rows).encode(), "")):
                report = json.loads(await self.call("get_github_issue_comments", owner="a", repo="b", number=1))
            self.assertFalse(report["has_more"])
            self.assertFalse(report["truncated"])
        for body in (b"not json", b"{}", b'[{"id":"wrong"}]'):
            with patch.object(service, "request_public", return_value=(200, {"content-type": "application/json"}, body, "")):
                self.assertTrue((await self.call("get_github_issue_comments", owner="a", repo="b", number=1)).startswith("Error:"))

    async def test_pr_diff_media_type_prefix_shortening_and_empty(self):
        diff = "diff --git a/x b/x\n" + "+source\n" * 30
        with patch.object(service, "request_public", return_value=(200, {"Content-Type": "application/vnd.github.v3.diff; charset=utf-8"}, diff.encode(), "")) as request:
            report = json.loads(await self.call("get_github_pr_diff", owner="a", repo="b", number=3, max_chars=100))
        self.assertEqual(report["diff"], diff[:100])
        self.assertEqual(report["downloaded_chars"], len(diff))
        self.assertTrue(report["truncated"])
        self.assertEqual(request.call_args.kwargs["headers"]["Accept"], "application/vnd.github.diff")
        with patch.object(service, "request_public", return_value=(200, {"Content-Type": "application/vnd.github.diff"}, b"", "")):
            self.assertEqual(json.loads(await self.call("get_github_pr_diff", owner="a", repo="b", number=3))["diff"], "")

    async def test_github_errors_and_argument_validation_before_network(self):
        for name in ("get_github_issue_comments", "get_github_pr_diff"):
            for args in ({"owner": "../a"}, {"repo": ".."}, {"number": 0}):
                arguments = {"owner": "a", "repo": "b", "number": 1, **args}
                with patch.object(service, "request_public") as request:
                    self.assertTrue((await self.call(name, **arguments)).startswith("Error:"))
                    request.assert_not_called()
            with patch.object(service, "request_public", return_value=(403, {}, b"private error", "")):
                result = await self.call(name, owner="a", repo="b", number=1)
                self.assertIn("403", result)
                self.assertNotIn("private error", result)
        for headers, body in (({"Content-Type": "application/json"}, b"{}"),
                              ({"Content-Type": "text/plain"}, b"not diff"),
                              ({"Content-Type": "text/plain"}, b"\xff")):
            with patch.object(service, "request_public", return_value=(200, headers, body, "")):
                self.assertTrue((await self.call("get_github_pr_diff", owner="a", repo="b", number=1)).startswith("Error:"))

    async def test_archive_metadata_totals_warnings_and_no_member_reads(self):
        body = archive_bytes()
        with patch.object(service, "fetch_page", return_value=(body, "application/zip", "https://example.com/files.zip")), patch.object(
            zipfile.ZipFile, "open", side_effect=AssertionError("Must not decompress")):
            report = json.loads(await self.call("extract_archive_manifest", url="https://example.com/files.zip"))
        self.assertEqual(report["entry_count"], 5)
        self.assertEqual(report["duplicate_name_count"], 1)
        self.assertEqual(report["path_warning_count"], 1)
        self.assertTrue(report["files"][4]["symlink"])
        self.assertEqual(report["declared_uncompressed_bytes"], 5021)
        self.assertFalse(report["contents_verified"])
        with patch.object(service, "fetch_page", return_value=(body, "application/zip", "https://example.com/files.zip")):
            short = json.loads(await self.call("extract_archive_manifest", url="https://example.com/files.zip", limit=1))
        self.assertEqual(short["entry_count"], 5)
        self.assertTrue(short["truncated"])

    async def test_archive_empty_corrupt_and_entry_limits(self):
        empty = BytesIO()
        with zipfile.ZipFile(empty, "w"):
            pass
        self.assertEqual(service._archive_manifest(empty.getvalue(), 1)["entry_count"], 0)
        for body in (b"not zip", archive_bytes()[:-30], b"x" * 1000001):
            with patch.object(service, "fetch_page", return_value=(body, "application/zip", "https://example.com/a.zip")):
                self.assertTrue((await self.call("extract_archive_manifest", url="https://example.com/a.zip")).startswith("Error:"))
        with patch.object(zipfile.ZipFile, "infolist", return_value=[None] * 5001):
            with self.assertRaisesRegex(ValueError, "5000"):
                service._archive_manifest(empty.getvalue(), 1)

    async def test_forms_owners_labels_disabled_fieldsets_and_values_omitted(self):
        html = b'''<base href="/base/"><label for="email">Email</label>
        <form id="f" method="POST" action="submit?token=secret"><input id="email" name="email" type="email" required value="private">
        <input type="hidden" name="csrf" value="secret"><label>Message<textarea name="msg">private textarea</textarea></label>
        <fieldset disabled><legend><input name="legend"></legend><input name="disabled"></fieldset>
        <select name="choices" multiple><option value="secret">Private choice</option><option>Other</option></select>
        <button formaction="/other?token=secret" formmethod="get">Send</button></form>
        <input form="f" name="external"><input form="missing" name="orphan">
        <template><form><input name="template"></form></template>'''
        with patch.object(service, "fetch_page", return_value=(html, "text/html", "https://example.com/page")):
            result = await self.call("extract_html_forms", url="https://example.com/page")
        self.assertNotIn("secret", result)
        self.assertNotIn("private textarea", result)
        self.assertNotIn("Private choice", result)
        report = json.loads(result)
        form = report["forms"][0]
        self.assertEqual(form["method"], "post")
        self.assertEqual(form["action"]["url"], "https://example.com/base/submit")
        self.assertTrue(form["action"]["query_omitted"])
        fields = {field["name"]: field for field in form["fields"]}
        self.assertEqual(fields["email"]["label"], "Email")
        self.assertTrue(fields["email"]["required_declared"])
        self.assertEqual(fields["msg"]["label"], "Message")
        self.assertFalse(fields["legend"]["disabled"])
        self.assertTrue(fields["disabled"]["disabled"])
        self.assertEqual(fields["choices"]["option_count"], 2)
        self.assertIn("external", fields)
        self.assertEqual(report["unassociated_controls"], 1)
        self.assertEqual(report["form_count"], 1)

    async def test_forms_default_action_base_overrides_and_unsupported_actions(self):
        html = b'''<base href="https://other.example/base/"><form id="a"><input name="x" form="b"></form>
        <form id="b" action="javascript:send()" method="invalid"></form>
        <form action="https://user:pass@example.com/"></form><form action="/relative"></form>'''
        report = service._forms(html, "text/html", "https://example.com/page", 20, 100)
        self.assertEqual(report["forms"][0]["action"]["url"], "https://example.com/page")
        self.assertEqual(report["forms"][0]["field_count"], 0)
        self.assertEqual(report["forms"][1]["field_count"], 1)
        self.assertFalse(report["forms"][1]["action"]["supported"])
        self.assertEqual(report["forms"][1]["method"], "get")
        self.assertFalse(report["forms"][2]["action"]["supported"])
        self.assertEqual(report["forms"][3]["action"]["url"], "https://other.example/relative")

    async def test_forms_listing_limits_and_nesting_bound(self):
        html = b'<form><input name="a"><input name="b"></form><form></form>'
        report = service._forms(html, "text/html", "https://example.com", 1, 1)
        self.assertEqual(report["form_count"], 2)
        self.assertEqual(report["forms"][0]["field_count"], 2)
        self.assertTrue(report["truncated"])
        with self.assertRaisesRegex(ValueError, "nesting"):
            service._forms(b"<div>" * 101 + b"</div>" * 101, "text/html", "https://example.com", 20, 100)
        with self.assertRaises(ValueError):
            service._forms(b"text", "text/plain", "https://example.com", 20, 100)

    async def test_new_url_tools_use_public_host_guard_and_download_cap(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        for name in ("extract_archive_manifest", "extract_html_forms"):
            with patch.object(webpage_service.socket, "getaddrinfo", return_value=addresses), patch.object(
                webpage_service.urllib3, "HTTPSConnectionPool") as pool:
                self.assertIn("blocked", await self.call(name, url="https://localhost/a"))
                pool.assert_not_called()
        response = Mock(status=200, headers={"Content-Type": "application/zip"})
        response.read.side_effect = [b"x" * 1000001]
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
        with patch.object(webpage_service.socket, "getaddrinfo", return_value=public), patch.object(
            webpage_service.urllib3, "HTTPSConnectionPool") as pool:
            pool.return_value.urlopen.return_value = response
            self.assertIn("1 MB", await self.call("extract_archive_manifest", url="https://example.com/a.zip"))

    async def test_limits_and_four_registered_tools(self):
        self.assertEqual({t.name for t in await self.mcp.list_tools()}, {
            "get_github_issue_comments", "get_github_pr_diff", "extract_archive_manifest", "extract_html_forms"})
        for name, args in (("extract_archive_manifest", {"url": "https://example.com", "limit": 0}),
                           ("extract_html_forms", {"url": "https://example.com", "max_fields": 501}),
                           ("get_github_issue_comments", {"owner": "a", "repo": "b", "number": 1, "page": 1001}),
                           ("get_github_pr_diff", {"owner": "a", "repo": "b", "number": 1, "max_chars": 99})):
            with patch.object(service, "fetch_page") as fetch, patch.object(service, "request_public") as request:
                self.assertTrue((await self.call(name, **args)).startswith("Error:"))
                fetch.assert_not_called()
                request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
