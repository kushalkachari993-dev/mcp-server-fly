import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.vulnerability_utils import service, tool


def response(payload, status=200, content_type="application/json"):
    return status, {"Content-Type": content_type}, json.dumps(payload).encode(), "https://api.osv.dev"


class AdvisoryDetailsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("advisory-details-tests")
        tool.register(self.mcp)

    async def call(self, **arguments):
        result = await self.mcp.call_tool("get_vulnerability_details", {
            "advisory_id": "GHSA-example", **arguments,
        })
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_affected_ranges_preserve_fix_types_and_withdrawal(self):
        payload = {"id": "GHSA-example", "summary": "An advisory", "details": "More details",
                   "withdrawn": "2026-01-01T00:00:00Z", "aliases": ["CVE-example"],
                   "affected": [{"package": {"name": "demo", "ecosystem": "npm"},
                                 "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "1.2.3"}]},
                                            {"type": "GIT", "repo": "https://example.com/git",
                                             "events": [{"introduced": "abc"}, {"fixed": "def"}]}]}],
                   "references": [{"type": "FIX", "url": "https://example.com/fix"}]}
        with patch.object(service, "request_public", return_value=response(payload)) as request:
            result = json.loads(await self.call())
        self.assertEqual(result["affected"][0]["ranges"][0]["events"][1], {"fixed": "1.2.3"})
        self.assertEqual(result["affected"][0]["ranges"][1]["type"], "GIT")
        self.assertEqual(result["withdrawn"], payload["withdrawn"])
        self.assertFalse(result["truncated"])
        request.assert_called_once_with("https://api.osv.dev/v1/vulns/GHSA-example",
                                        headers={"Accept": "application/json"}, allowed_host="api.osv.dev")

    async def test_omissions_and_missing_optional_data(self):
        payload = {"id": "GHSA-example", "details": "x" * 101, "aliases": ["alias"] * 21,
                   "affected": [{"package": {"name": "demo", "ecosystem": "PyPI"}}] * 2}
        with patch.object(service, "request_public", return_value=response(payload)):
            result = json.loads(await self.call(max_chars=100, max_affected=1))
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["details"]), 100)
        self.assertEqual(len(result["aliases"]), 20)
        self.assertEqual(len(result["affected"]), 1)
        with patch.object(service, "request_public", return_value=response({"id": "GHSA-example"})):
            result = json.loads(await self.call())
        self.assertEqual(result["affected"], [])
        self.assertIsNone(result["withdrawn"])

    async def test_invalid_inputs_do_not_make_requests(self):
        for arguments in ({"advisory_id": "../private"}, {"advisory_id": "https://example.com"},
                          {"advisory_id": "GHSA-test\n"}, {"max_affected": 0}, {"max_chars": 20001}):
            with self.subTest(arguments=arguments), patch.object(service, "request_public") as request:
                self.assertTrue((await self.call(**arguments)).startswith("Error:"))
                request.assert_not_called()

    async def test_malformed_responses_and_http_errors(self):
        affected = {"package": {"name": "demo", "ecosystem": "npm"}, "ranges": [{"type": [], "events": []}]}
        for payload in ([], {}, {"id": "GHSA-example", "affected": [affected]},
                        {"id": "GHSA-example", "affected": [{"package": {}}]},
                        {"id": "GHSA-example", "references": None},
                        {"id": "GHSA-example", "severity": [None]}):
            with self.subTest(payload=payload), patch.object(service, "request_public", return_value=response(payload)):
                self.assertTrue((await self.call()).startswith("Error:"))
        for status in (404, 429, 500):
            with patch.object(service, "request_public", return_value=response({}, status=status)):
                self.assertIn(f"HTTP {status}", await self.call())
        with patch.object(service, "request_public", return_value=response({}, content_type="text/html")):
            self.assertIn("content type", await self.call())

    async def test_invalid_json_and_download_errors(self):
        with patch.object(service, "request_public", return_value=(200, {"content-type": "application/json"}, b"{", "url")):
            self.assertIn("invalid JSON", await self.call())
        with patch.object(service, "request_public", side_effect=ValueError("non-public address blocked")):
            self.assertIn("blocked", await self.call())


if __name__ == "__main__":
    unittest.main()
