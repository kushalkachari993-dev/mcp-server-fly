import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from app.tools.dependency_audit_utils import service, tool


def response(payload, status=200, content_type="application/json"):
    return status, {"content-type": content_type}, json.dumps(payload).encode(), service._ENDPOINT


class DependencyAuditToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("dependency-audit-tests")
        tool.register(self.mcp)

    async def call(self, packages, limit=10):
        result = await self.mcp.call_tool("check_dependencies_batch", {
            "packages_json": json.dumps(packages), "limit": limit,
        })
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_batch_payload_and_aligned_results(self):
        packages = [{"ecosystem": "PyPI", "name": "requests", "version": "2.32.0"},
                    {"ecosystem": "npm", "name": "express", "version": "4.19.2"}]
        payload = {"results": [{"vulns": [{"id": "PYSEC-1", "aliases": ["CVE-1"], "summary": "Example"}]},
                               {"vulns": []}]}
        with patch.object(service, "request_public", return_value=response(payload)) as request:
            result = json.loads(await self.call(packages))
        self.assertEqual(result["package_count"], 2)
        self.assertEqual(result["vulnerable_package_count"], 1)
        self.assertEqual(result["packages"][0]["vulnerabilities"][0]["id"], "PYSEC-1")
        self.assertEqual(request.call_args.args, (service._ENDPOINT,))
        self.assertEqual(json.loads(request.call_args.kwargs["body"])["queries"], [
            {"package": {"ecosystem": "PyPI", "name": "requests"}, "version": "2.32.0"},
            {"package": {"ecosystem": "npm", "name": "express"}, "version": "4.19.2"},
        ])

    async def test_limits_and_pagination_are_marked(self):
        packages = [{"ecosystem": "PyPI", "name": "demo", "version": "1.0.0"}]
        payload = {"results": [{"vulns": [{"id": "one"}, {"id": "two"}], "next_page_token": "more"}]}
        with patch.object(service, "request_public", return_value=response(payload)):
            result = json.loads(await self.call(packages, limit=1))
        self.assertEqual(result["packages"][0]["vulnerability_count"], 1)
        self.assertTrue(result["packages"][0]["truncated"])

    async def test_invalid_input_and_response_do_not_escape(self):
        for packages in ([], [{"ecosystem": "PyPI", "name": "demo", "version": ">=1"}],
                         [{"ecosystem": "Unknown", "name": "demo", "version": "1.0"}]):
            with self.subTest(packages=packages), patch.object(service, "request_public") as request:
                self.assertTrue((await self.call(packages)).startswith("Error:"))
                request.assert_not_called()
        packages = [{"ecosystem": "PyPI", "name": "demo", "version": "1.0"}]
        with patch.object(service, "request_public", return_value=response({"results": []})):
            self.assertIn("do not match", await self.call(packages))


if __name__ == "__main__":
    unittest.main()
