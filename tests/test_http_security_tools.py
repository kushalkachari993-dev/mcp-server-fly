import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.http_security_utils import service, tool


class HttpSecurityToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("http-security-tests")
        tool.register(self.mcp)

    async def call(self, url="https://example.com/"):
        result = await self.mcp.call_tool("inspect_http_security_headers", {"url": url})
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_security_headers_are_summarized(self):
        headers = {"Content-Security-Policy": "default-src 'self'", "Strict-Transport-Security": "max-age=10",
                   "X-Content-Type-Options": "nosniff"}
        with patch.object(service, "request_public", return_value=(200, headers, b"", "https://example.com/")) as request:
            result = json.loads(await self.call())
        self.assertTrue(result["https"])
        self.assertEqual(result["present"]["content-security-policy"], "default-src 'self'")
        self.assertIn("referrer-policy", result["missing"])
        self.assertEqual(request.call_args.kwargs["method"], "HEAD")

    async def test_head_falls_back_to_get(self):
        with patch.object(service, "request_public", side_effect=[
            (405, {}, b"", "https://example.com/"),
            (200, {"Content-Security-Policy": "default-src 'none'"}, b"", "https://example.com/")
        ]) as request:
            result = json.loads(await self.call())
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.kwargs["method"], "GET")

    async def test_transport_errors_are_returned(self):
        with patch.object(service, "request_public", side_effect=ValueError("non-public address blocked")):
            self.assertIn("blocked", await self.call("http://localhost/"))


if __name__ == "__main__":
    unittest.main()
