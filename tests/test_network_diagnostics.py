import json
import unittest
from unittest.mock import MagicMock, Mock, patch

from mcp.server.fastmcp import FastMCP

from app.tools.network_diagnostics import service, tool


class NetworkDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("network-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_dns_lookup_returns_bounded_records(self):
        answer = {"Status": 0, "Answer": [
            {"name": "example.com.", "type": 15, "TTL": 300, "data": "10 mail.example.com."},
            {"name": "example.com.", "type": 15, "TTL": 300, "data": "20 mail2.example.com."},
        ]}
        with patch.object(service, "fetch_page", return_value=(json.dumps(answer).encode(), "application/dns-json", "url")) as fetch:
            result = json.loads(await self.call("lookup_dns_records", domain="example.com", record_type="MX", limit=1))
        self.assertEqual(result["records"][0]["value"], "10 mail.example.com.")
        self.assertTrue(result["truncated"])
        self.assertEqual(fetch.call_args.kwargs["allowed_host"], "cloudflare-dns.com")
        self.assertIn("type=MX", fetch.call_args.args[0])

    async def test_dns_handles_service_name_nxdomain_and_invalid_inputs(self):
        with patch.object(service, "fetch_page", return_value=(b'{"Status":3}', "application/dns-json", "url")):
            result = json.loads(await self.call("lookup_dns_records", domain="_dmarc.example.com", record_type="TXT"))
        self.assertEqual(result["dns_status"], 3)
        self.assertEqual(result["records"], [])
        for args in ({"domain": "localhost"}, {"domain": "example.com/path"},
                     {"domain": "example.com", "record_type": "ANY"},
                     {"domain": "example.com", "limit": 51}):
            with self.subTest(args=args):
                self.assertTrue((await self.call("lookup_dns_records", **args)).startswith("Error:"))

    async def test_tls_certificate_uses_pinned_address_and_verified_hostname(self):
        secure = Mock()
        secure.getpeercert.return_value = {
            "notBefore": "Jan  1 00:00:00 2026 GMT", "notAfter": "Jan  1 00:00:00 2030 GMT",
            "issuer": ((('organizationName', 'Example CA'),),),
            "subjectAltName": (("DNS", "example.com"), ("DNS", "www.example.com")),
        }
        context = Mock()
        context.wrap_socket.return_value = MagicMock()
        context.wrap_socket.return_value.__enter__.return_value = secure
        connection = MagicMock()
        with patch.object(service, "_public_destination", return_value=(None, "example.com", 443, "93.184.215.14")), patch.object(
            service.socket, "create_connection", return_value=connection
        ) as connect, patch.object(service.ssl, "create_default_context", return_value=context):
            result = json.loads(await self.call("inspect_tls_certificate", domain="example.com"))
        connect.assert_called_once_with(("93.184.215.14", 443), timeout=5)
        self.assertEqual(context.wrap_socket.call_args.kwargs["server_hostname"], "example.com")
        self.assertEqual(result["issuer"], ["Example CA"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["dns_names"], ["example.com", "www.example.com"])

    async def test_tls_rejects_invalid_and_non_public_destinations(self):
        self.assertTrue((await self.call("inspect_tls_certificate", domain="localhost")).startswith("Error:"))
        with patch.object(service, "_public_destination", side_effect=ValueError("non-public address blocked")):
            self.assertIn("blocked", await self.call("inspect_tls_certificate", domain="example.com"))


if __name__ == "__main__":
    unittest.main()
