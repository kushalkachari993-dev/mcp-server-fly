import socket
import unittest
from unittest.mock import Mock, patch

from mcp.server.fastmcp import FastMCP

from app.tools.http_client import tool as http_tools
from app.tools.url_fetcher import tool as fetch_tools
from app.tools.webpage import service as webpage_service


def _addresses(ip="93.184.215.14"):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


def _response(status=200, headers=None, body=b"Hello"):
    response = Mock(status=status, headers=headers or {"content-type": "text/plain"})
    response.read.side_effect = [body, b""]
    return response


class PublicTransportTests(unittest.TestCase):
    def test_private_redirect_is_blocked_before_connection(self):
        pool = Mock()
        pool.urlopen.return_value = _response(status=302, headers={"Location": "http://127.0.0.1/private"})
        with patch.object(webpage_service.socket, "getaddrinfo", side_effect=[_addresses(), _addresses("127.0.0.1")]), patch.object(
            webpage_service.urllib3, "HTTPSConnectionPool", return_value=pool
        ), patch.object(webpage_service.urllib3, "HTTPConnectionPool") as private_pool:
            with self.assertRaisesRegex(ValueError, "non-public"):
                webpage_service.request_public("https://example.com/start")
            private_pool.assert_not_called()

    def test_cross_origin_redirect_strips_credentials_and_blocks_body(self):
        first = Mock()
        first.urlopen.return_value = _response(status=302, headers={"Location": "https://other.example/next"})
        second = Mock()
        second.urlopen.return_value = _response()
        with patch.object(webpage_service.socket, "getaddrinfo", return_value=_addresses()), patch.object(
            webpage_service.urllib3, "HTTPSConnectionPool", side_effect=[first, second]
        ):
            status, _, body, final_url = webpage_service.request_public(
                "https://example.com/start", headers={"Authorization": "Bearer secret", "Accept": "text/plain"}
            )
        self.assertEqual((status, body, final_url), (200, b"Hello", "https://other.example/next"))
        self.assertNotIn("Authorization", second.urlopen.call_args.kwargs["headers"])
        self.assertEqual(second.urlopen.call_args.kwargs["headers"]["Accept"], "text/plain")

        first = Mock()
        first.urlopen.return_value = _response(status=307, headers={"Location": "https://other.example/next"})
        with patch.object(webpage_service.socket, "getaddrinfo", return_value=_addresses()), patch.object(
            webpage_service.urllib3, "HTTPSConnectionPool", return_value=first
        ):
            with self.assertRaisesRegex(ValueError, "request body"):
                webpage_service.request_public("https://example.com/start", method="POST", body=b"secret")
        self.assertEqual(first.urlopen.call_count, 1)

    def test_fetch_page_accepts_lowercase_content_type(self):
        pool = Mock()
        pool.urlopen.return_value = _response(headers={"content-type": "text/plain"})
        with patch.object(webpage_service.socket, "getaddrinfo", return_value=_addresses()), patch.object(
            webpage_service.urllib3, "HTTPSConnectionPool", return_value=pool
        ):
            body, content_type, _ = webpage_service.fetch_page("https://example.com/")
        self.assertEqual((body, content_type), (b"Hello", "text/plain"))


class PublicClientToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("http-tests")
        http_tools.register(self.mcp)
        fetch_tools.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_clients_use_shared_transport(self):
        with patch.object(http_tools, "request_public", return_value=(201, {"Content-Type": "text/plain"}, b"created", "https://example.com/done")) as request:
            result = await self.call("http_request", url="https://example.com/", method="POST", body="hello")
        self.assertIn("Status: 201", result)
        self.assertEqual(request.call_args.kwargs["body"], b"hello")
        with patch.object(fetch_tools, "request_public", return_value=(404, {"content-type": "text/plain"}, b"missing", "https://example.com/")):
            result = await self.call("fetch_url", url="https://example.com/")
        self.assertIn("Status: 404", result)
        self.assertIn("missing", result)

    async def test_client_rejects_host_override(self):
        result = await self.call("http_request", url="https://example.com/", headers_json='{"Host":"localhost"}')
        self.assertIn("managed by the server", result)
        result = await self.call("http_request", url="https://example.com/", headers_json='{"X-Test":"bad\\r\\nvalue"}')
        self.assertIn("invalid or oversized", result)
        result = await self.call("http_request", url="https://example.com/", headers_json="x" * 8001)
        self.assertIn("8000 characters", result)


if __name__ == "__main__":
    unittest.main()
