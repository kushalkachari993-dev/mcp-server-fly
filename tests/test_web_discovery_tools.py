import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.web_discovery import service as discovery_service
from app.tools.web_discovery import tool as discovery_tools
from app.tools.webpage import tool as webpage_tools


class WebDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("web-discovery-tests")
        discovery_tools.register(self.mcp)
        webpage_tools.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_sitemap_urlset_and_index(self):
        body = b'''<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.com/one</loc><lastmod>2026-09-30</lastmod></url>
          <url><loc>https://example.com/two</loc></url>
        </urlset>'''
        with patch.object(discovery_service, "fetch_page", return_value=(body, "application/xml", "https://example.com/sitemap.xml")):
            result = json.loads(await self.call("read_sitemap", url="https://example.com/sitemap.xml", limit=1))
        self.assertEqual(result["kind"], "urlset")
        self.assertEqual(result["entries"], [{"url": "https://example.com/one", "lastmod": "2026-09-30"}])
        self.assertTrue(result["truncated"])
        index = b'<sitemapindex><sitemap><loc>https://example.com/child.xml</loc></sitemap></sitemapindex>'
        with patch.object(discovery_service, "fetch_page", return_value=(index, "application/xml", "https://example.com/index.xml")) as fetch:
            result = json.loads(await self.call("read_sitemap", url="https://example.com/index.xml"))
        self.assertEqual(result["kind"], "sitemapindex")
        self.assertEqual(result["entries"][0]["url"], "https://example.com/child.xml")
        fetch.assert_called_once()

    async def test_sitemap_rejects_unsafe_xml_and_invalid_destinations(self):
        for body in (b'<!DOCTYPE foo [<!ENTITY x "boom">]><urlset/>',
                     b'<urlset><url>', b'<html/>', b'\xff'):
            with self.subTest(body=body), patch.object(discovery_service, "fetch_page", return_value=(body, "application/xml", "https://example.com/sitemap.xml")):
                self.assertTrue((await self.call("read_sitemap", url="https://example.com/sitemap.xml")).startswith("Error:"))
        with patch.object(discovery_service, "fetch_page", side_effect=ValueError("non-public address blocked")):
            self.assertIn("blocked", await self.call("read_sitemap", url="http://localhost/sitemap.xml"))
        invalid_entry = b'<urlset><url><loc>file:///etc/passwd</loc></url></urlset>'
        result = discovery_service._parse_sitemap(invalid_entry, "https://example.com/sitemap.xml", 10)
        self.assertEqual(result["invalid_entries"], 1)
        self.assertEqual(result["entries"], [])
        self.assertTrue((await self.call("read_sitemap", url="https://example.com/", limit=0)).startswith("Error:"))

    async def test_robots_groups_sitemaps_and_root_url(self):
        body = b'''User-agent: Bot
        Disallow: /private
        Allow: /public
        Sitemap: https://example.com/sitemap.xml
        User-agent: Other
        Disallow: /tmp
        '''
        with patch.object(discovery_service, "request_public", return_value=(200, {"Content-Type": "text/plain; charset=utf-8"}, body, "https://example.com/robots.txt")) as request:
            result = json.loads(await self.call("inspect_robots_txt", site_url="https://example.com/deep/page"))
        self.assertTrue(result["found"])
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(result["groups"][0]["rules"][0]["path"], "/private")
        self.assertEqual(result["sitemaps"], ["https://example.com/sitemap.xml"])
        self.assertEqual(request.call_args.args[0], "https://example.com/robots.txt")
        self.assertNotIn("allowed_host", request.call_args.kwargs)

    async def test_robots_missing_errors_and_limits(self):
        with patch.object(discovery_service, "request_public", return_value=(404, {}, b"", "https://example.com/robots.txt")):
            result = json.loads(await self.call("inspect_robots_txt", site_url="https://example.com"))
        self.assertFalse(result["found"])
        self.assertEqual(result["http_status"], 404)
        with patch.object(discovery_service, "request_public", return_value=(503, {}, b"", "https://example.com/robots.txt")):
            self.assertIn("HTTP 503", await self.call("inspect_robots_txt", site_url="https://example.com"))
        for site_url in ("http://example.com", "https://example.com:8000/", "https://user:pass@example.com/"):
            with self.subTest(site_url=site_url):
                self.assertTrue((await self.call("inspect_robots_txt", site_url=site_url)).startswith("Error:"))
        body = b'User-agent: *\nDisallow: /one\nDisallow: /two\n'
        with patch.object(discovery_service, "request_public", return_value=(200, {"content-type": "text/plain"}, body, "https://example.com/robots.txt")):
            result = json.loads(await self.call("inspect_robots_txt", site_url="https://example.com", max_rules=1))
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["groups"][0]["rules"]), 1)

    async def test_page_metadata_canonical_and_repeated_social_tags(self):
        body = b'''<html><head><title>Example</title>
          <meta name="description" content="A page">
          <meta name="robots" content="noindex">
          <link rel="canonical" href="/canonical">
          <meta property="og:title" content="First">
          <meta property="og:image" content="https://example.com/one.png">
          <meta property="og:image" content="https://example.com/two.png">
          <meta name="twitter:card" content="summary_large_image">
        </head></html>'''
        with patch.object(webpage_tools, "fetch_page", return_value=(body, "text/html", "https://example.com/page")):
            result = json.loads(await self.call("inspect_page_metadata", url="https://example.com/page"))
        self.assertEqual(result["canonical"], "https://example.com/canonical")
        self.assertEqual(result["description"], "A page")
        self.assertEqual(result["open_graph"]["og:image"], ["https://example.com/one.png", "https://example.com/two.png"])
        self.assertEqual(result["twitter"]["twitter:card"], ["summary_large_image"])
        with patch.object(webpage_tools, "fetch_page", return_value=(b"plain", "text/plain", "https://example.com/")):
            self.assertIn("HTML webpage", await self.call("inspect_page_metadata", url="https://example.com/"))


if __name__ == "__main__":
    unittest.main()
