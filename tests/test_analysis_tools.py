import json
import math
import socket
import unittest
from unittest.mock import Mock, patch

from mcp.server.fastmcp import FastMCP

from app.tools.number_utils import tool as number_tools
from app.tools.rss_utils import tool as rss_tools
from app.tools.text_utils import tool as text_tools
from app.tools.unit_utils import tool as unit_tools
from app.tools.webpage import service as webpage_service
from app.tools.webpage import tool as webpage_tools


class AnalysisToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("analysis-tests")
        for module in (webpage_tools, rss_tools, number_tools, text_tools, unit_tools):
            module.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def html(self, name, body, **arguments):
        with patch.object(webpage_tools, "fetch_page", return_value=(body.encode(), "text/html", "https://example.com/dir/page")):
            return json.loads(await self.call(name, url="https://example.com/old", **arguments))

    async def test_links_resolve_relative_base_and_duplicates(self):
        body = '''<base href="/docs/"><a href="guide#first">Guide</a>
                  <a href="guide#second">Duplicate</a><a href="../news">News</a>
                  <a href="//other.example/post">External</a>'''
        result = await self.html("extract_webpage_links", body)
        self.assertEqual(result["url"], "https://example.com/dir/page")
        self.assertEqual(result["links"], [
            {"url": "https://example.com/docs/guide", "text": "Guide"},
            {"url": "https://example.com/news", "text": "News"},
            {"url": "https://other.example/post", "text": "External"},
        ])
        self.assertFalse(result["truncated"])

    async def test_links_filter_hostname_and_skip_non_web_links(self):
        body = '''<a href="/ok">OK</a><a href="https://sub.example.com">Subdomain</a>
                  <a href="#section">Fragment</a><a href="javascript:alert(1)">JS</a>
                  <a href="mailto:a@example.com">Mail</a><a href="file:///tmp/a">File</a>
                  <a href="https://user:password@example.com">Credentials</a>
                  <a href="http://[invalid">Bad URL</a>'''
        result = await self.html("extract_webpage_links", body, same_domain_only=True)
        self.assertEqual(result["links"], [{"url": "https://example.com/ok", "text": "OK"}])

    async def test_links_image_labels_and_limit(self):
        body = '<a href="/one"><img alt="Image link"></a><a href="/two" aria-label="Two"></a>'
        result = await self.html("extract_webpage_links", body, limit=1)
        self.assertEqual(result["links"][0]["text"], "Image link")
        self.assertTrue(result["truncated"])
        result = await self.html("extract_webpage_links", body, limit=2)
        self.assertEqual(result["links"][1]["text"], "Two")
        self.assertFalse(result["truncated"])

    async def test_links_honor_external_base_with_same_domain_filter(self):
        body = '<base href="https://other.example/"><a href="/post">Post</a>'
        self.assertEqual((await self.html("extract_webpage_links", body, same_domain_only=True))["links"], [])

    async def test_web_extractors_reject_limits_plain_text_and_network_errors(self):
        for name, arguments in (
            ("extract_webpage_links", {"limit": 0}), ("extract_webpage_links", {"limit": 501}),
            ("extract_html_tables", {"max_rows": 0}), ("extract_html_tables", {"max_rows": 1001}),
            ("extract_html_tables", {"max_tables": 21}),
        ):
            with self.subTest(name=name, arguments=arguments):
                self.assertTrue((await self.call(name, url="https://example.com", **arguments)).startswith("Error:"))
        for name in ("extract_webpage_links", "extract_html_tables"):
            with patch.object(webpage_tools, "fetch_page", return_value=(b"Hello", "text/plain", "https://example.com")):
                self.assertTrue((await self.call(name, url="https://example.com")).startswith("Error:"))
            with patch.object(webpage_tools, "fetch_page", side_effect=ValueError("blocked")):
                self.assertIn("blocked", await self.call(name, url="https://example.com"))

    async def test_tables_headers_caption_and_missing_cells(self):
        body = '''<table><caption>Users</caption><thead><tr><th>Name</th><th>City</th></tr></thead>
                  <tbody><tr><td>Ada</td><td>London</td></tr><tr><td>Bob</td></tr></tbody></table>'''
        result = await self.html("extract_html_tables", body)
        self.assertEqual(result["tables"], [{"caption": "Users", "headers": ["Name", "City"],
                         "rows": [["Ada", "London"], ["Bob", ""]], "truncated": False}])

    async def test_tables_rowspan_colspan_and_generated_headers(self):
        body = '''<table><tr><td rowspan="2">A</td><td colspan="2">B</td></tr>
                  <tr><td>C</td><td>D</td></tr></table>'''
        result = await self.html("extract_html_tables", body)
        self.assertEqual(result["tables"][0]["headers"], ["column_1", "column_2", "column_3"])
        self.assertEqual(result["tables"][0]["rows"], [["A", "B", "B"], ["A", "C", "D"]])

    async def test_tables_limits_and_nested_tables(self):
        body = '''<table><tr><th>A</th></tr><tr><td>One<table><tr><td>Nested</td></tr></table></td></tr>
                  <tr><td>Two</td></tr></table><table><tr><td>Other</td></tr></table>'''
        result = await self.html("extract_html_tables", body, max_tables=1, max_rows=1)
        self.assertEqual(result["tables"][0]["rows"], [["One"]])
        self.assertTrue(result["tables"][0]["truncated"])
        self.assertTrue(result["truncated"])

    async def test_tables_empty_and_exact_row_limit(self):
        self.assertEqual((await self.html("extract_html_tables", "<p>No table</p>"))["tables"], [])
        body = '<table><tr><th>A</th></tr><tr><td>One</td></tr></table>'
        self.assertFalse((await self.html("extract_html_tables", body, max_rows=1))["truncated"])

    async def test_tables_reject_huge_invalid_or_overlapping_spans(self):
        for body in (
            '<table><tr><td colspan="51">Too wide</td></tr></table>',
            '<table><tr><td rowspan="1001">Too long</td></tr></table>',
            '<table><tr><td colspan="no">Invalid</td></tr></table>',
            '<table><tr><td>A</td><td rowspan="2">B</td></tr><tr><td colspan="2">C</td></tr></table>',
        ):
            with self.subTest(body=body), patch.object(webpage_tools, "fetch_page", return_value=(body.encode(), "text/html", "https://example.com")):
                self.assertTrue((await self.call("extract_html_tables", url="https://example.com")).startswith("Error:"))

    async def test_tables_cell_truncation_and_output_budget(self):
        result = await self.html("extract_html_tables", '<table><tr><td>' + 'a' * 2001 + '</td></tr></table>')
        self.assertEqual(len(result["tables"][0]["rows"][0][0]), 2000)
        self.assertTrue(result["truncated"])
        body = '<table>' + ('<tr><td colspan="50">' + 'a' * 2000 + '</td></tr>') * 3 + '</table>'
        with patch.object(webpage_tools, "fetch_page", return_value=(body.encode(), "text/html", "https://example.com")):
            self.assertIn("output limit", await self.call("extract_html_tables", url="https://example.com"))

    async def test_rss_feed_fields_and_limit(self):
        body = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>News</title>
            <link>https://example.com/</link><description>Updates</description>
            <item><title>First</title><link>/first</link><pubDate>Tue, 29 Sep 2026 09:00:00 GMT</pubDate>
            <description>&lt;p&gt;A useful &lt;b&gt;update&lt;/b&gt;&lt;/p&gt;</description></item>
            <item><title>Second</title><link>https://example.com/second</link></item></channel></rss>'''
        with patch.object(rss_tools, "fetch_page", return_value=(body, "application/rss+xml", "https://example.com/news/feed")) as fetch:
            result = json.loads(await self.call("read_rss_feed", url="https://example.com/feed", limit=1))
        self.assertEqual(result["title"], "News")
        self.assertEqual(result["entries"][0], {"title": "First", "url": "https://example.com/first",
                         "published": "Tue, 29 Sep 2026 09:00:00 GMT", "summary": "A useful update"})
        self.assertTrue(result["truncated"])
        self.assertIn("application/rss+xml", fetch.call_args.kwargs["media_types"])

    async def test_atom_feed_relative_links_and_updated(self):
        body = b'''<feed xmlns="http://www.w3.org/2005/Atom"><title>Releases</title>
            <id>urn:feed</id><updated>2026-09-29T00:00:00Z</updated><entry><id>urn:entry</id>
            <title>Version 1</title><updated>2026-09-29T00:00:00Z</updated>
            <link href="../release"/><summary>Shipped</summary></entry></feed>'''
        with patch.object(rss_tools, "fetch_page", return_value=(body, "application/atom+xml", "https://example.com/news/feed")):
            result = json.loads(await self.call("read_rss_feed", url="https://example.com/feed"))
        self.assertEqual(result["feed_type"], "atom10")
        self.assertEqual(result["entries"][0]["url"], "https://example.com/release")
        self.assertEqual(result["entries"][0]["published"], "2026-09-29T00:00:00Z")

    async def test_rss_rejects_unrecognized_content_limits_and_network_errors(self):
        for limit in (0, 51):
            self.assertTrue((await self.call("read_rss_feed", url="https://example.com/feed", limit=limit)).startswith("Error:"))
        with patch.object(rss_tools, "fetch_page", return_value=(b'<html>Not a feed</html>', "text/plain", "https://example.com/feed")):
            self.assertIn("recognized", await self.call("read_rss_feed", url="https://example.com/feed"))
        with patch.object(rss_tools, "fetch_page", side_effect=ValueError("private address blocked")):
            self.assertIn("blocked", await self.call("read_rss_feed", url="https://example.com/feed"))

    async def test_rss_empty_feed_and_recoverable_parse_warning(self):
        body = b'<rss version="2.0"><channel><title>Empty</title></channel></rss>'
        with patch.object(rss_tools, "fetch_page", return_value=(body, "application/rss+xml", "https://example.com/feed")):
            result = json.loads(await self.call("read_rss_feed", url="https://example.com/feed"))
        self.assertEqual(result["entries"], [])
        self.assertFalse(result["truncated"])
        body = b'<rss version="2.0"><channel><title>Broken</title><item><title>Partial</title></item>'
        with patch.object(rss_tools, "fetch_page", return_value=(body, "application/rss+xml", "https://example.com/feed")):
            result = json.loads(await self.call("read_rss_feed", url="https://example.com/feed"))
        self.assertTrue(result["parse_warning"])
        self.assertEqual(result["entries"][0]["title"], "Partial")

    async def test_rss_does_not_fetch_entities_and_skips_non_web_links(self):
        body = b'''<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
            <rss version="2.0"><channel><title>Safe</title><item><title>Item</title>
            <link>javascript:alert(1)</link><description>&xxe;</description></item></channel></rss>'''
        with patch.object(rss_tools, "fetch_page", return_value=(body, "application/rss+xml", "https://example.com/feed")), patch(
            "urllib.request.urlopen", side_effect=AssertionError("Parser attempted networking")
        ):
            result = json.loads(await self.call("read_rss_feed", url="https://example.com/feed"))
        self.assertEqual(result["entries"][0]["url"], "")
        self.assertNotIn("root:", result["entries"][0]["summary"])

    async def test_number_summary_and_standard_deviations(self):
        result = json.loads(await self.call("summarize_numbers", values=[1, 2, 3, 4]))
        self.assertEqual({key: result[key] for key in ("count", "sum", "min", "max", "mean", "median")},
                         {"count": 4, "sum": 10, "min": 1, "max": 4, "mean": 2.5, "median": 2.5})
        self.assertAlmostEqual(result["population_stddev"], math.sqrt(1.25))
        self.assertAlmostEqual(result["sample_stddev"], math.sqrt(5 / 3))

    async def test_number_summary_singleton_negative_and_precise_sum(self):
        result = json.loads(await self.call("summarize_numbers", values=[-2.5]))
        self.assertEqual(result["population_stddev"], 0)
        self.assertIsNone(result["sample_stddev"])
        self.assertEqual(json.loads(await self.call("summarize_numbers", values=[1e16, 1, -1e16]))["sum"], 1)

    async def test_number_summary_rejects_empty_large_and_non_finite_inputs(self):
        for values in ([], [1] * 10001, [float("nan")], [float("inf")], [1e308, 1e308]):
            with self.subTest(length=len(values)):
                self.assertTrue((await self.call("summarize_numbers", values=values)).startswith("Error:"))

    async def test_number_summary_rejects_boolean_and_string_coercion(self):
        for values in ([True], ["2"]):
            with self.subTest(values=values), self.assertRaises(Exception):
                await self.call("summarize_numbers", values=values)

    async def test_diff_add_remove_and_context(self):
        result = json.loads(await self.call("diff_text", before="keep\nold\n", after="keep\nnew\n"))
        self.assertEqual(result, {"equal": False, "diff": "--- before\n+++ after\n@@ -1,2 +1,2 @@\n keep\n-old\n+new\n", "truncated": False})
        result = json.loads(await self.call("diff_text", before="keep\nold\n", after="keep\nnew\n", context_lines=0))
        self.assertNotIn(" keep", result["diff"])

    async def test_diff_identical_empty_and_missing_final_newline(self):
        self.assertEqual(json.loads(await self.call("diff_text", before="", after="")), {"equal": True, "diff": "", "truncated": False})
        result = json.loads(await self.call("diff_text", before="same", after="same\n"))
        self.assertFalse(result["equal"])
        self.assertIn("\\ No newline at end of file", result["diff"])
        self.assertIn("-same\n", result["diff"])
        self.assertIn("+same\n", result["diff"])

    async def test_diff_preserves_crlf_changes_and_truncation(self):
        result = json.loads(await self.call("diff_text", before="a\r\n", after="a\n"))
        self.assertIn("-a\r\n", result["diff"])
        result = json.loads(await self.call("diff_text", before="a" * 500, after="b" * 500, max_chars=100))
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["diff"]), 100)

    async def test_diff_rejects_invalid_limits_and_oversized_input(self):
        for arguments in ({"context_lines": -1}, {"context_lines": 11}, {"max_chars": 99},
                          {"before": "a" * 100001}, {"after": "a\n" * 1001}):
            with self.subTest(arguments=list(arguments)):
                params = {"before": "", "after": "", **arguments}
                self.assertTrue((await self.call("diff_text", **params)).startswith("Error:"))

    async def test_units_length_speed_area_and_temperature(self):
        for value, source, target, expected in (
            (1, "kilometer", "meter", 1000), (36, "kilometer/hour", "meter/second", 10),
            (1, "meter**2", "centimeter^2", 10000), (0, "degC", "degF", 32),
            (32, "degF", "degC", 0), (0, "degC", "kelvin", 273.15),
            (1, "delta_degC", "delta_degF", 1.8),
        ):
            with self.subTest(source=source, target=target):
                result = json.loads(await self.call("convert_units", value=value, from_unit=source, to_unit=target))
                self.assertAlmostEqual(result["result"], expected)

    async def test_units_reject_incompatible_unknown_and_dangerous_expressions(self):
        for source, target in (
            ("meter", "second"), ("not_a_unit", "meter"), ("USD", "EUR"),
            ("meter**99", "meter"), ("meter**2**12", "meter"), ("2*meter", "meter"),
            ("meter; import os", "meter"), ("a" * 101, "meter"), ("", "meter"),
        ):
            with self.subTest(source=source):
                self.assertTrue((await self.call("convert_units", value=1, from_unit=source, to_unit=target)).startswith("Error:"))
        self.assertTrue((await self.call("convert_units", value=float("inf"), from_unit="meter", to_unit="meter")).startswith("Error:"))


class FeedRequestTests(unittest.TestCase):
    def test_xml_media_type_requires_explicit_opt_in(self):
        response = Mock(status=200, headers={"Content-Type": "application/rss+xml; charset=utf-8"})
        response.read.side_effect = [b"<rss/>", b""]
        pool = Mock()
        pool.urlopen.return_value = response
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
        with patch.object(webpage_service.socket, "getaddrinfo", return_value=addresses), patch.object(
            webpage_service.urllib3, "HTTPSConnectionPool", return_value=pool
        ):
            body, _, _ = webpage_service.fetch_page("https://example.com/feed", media_types=rss_tools._FEED_TYPES)
        self.assertEqual(body, b"<rss/>")
        self.assertIn("application/rss+xml", pool.urlopen.call_args.kwargs["headers"]["Accept"])

    def test_feed_fetch_still_blocks_private_destinations(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch.object(webpage_service.socket, "getaddrinfo", return_value=addresses), patch.object(
            webpage_service.urllib3, "HTTPSConnectionPool"
        ) as pool:
            with self.assertRaisesRegex(ValueError, "non-public"):
                webpage_service.fetch_page("https://example.com/feed", media_types=rss_tools._FEED_TYPES)
            pool.assert_not_called()


if __name__ == "__main__":
    unittest.main()
