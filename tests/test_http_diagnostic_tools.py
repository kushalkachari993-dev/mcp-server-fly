import json
import socket
import unittest
from unittest.mock import Mock, patch

import urllib3
from mcp.server.fastmcp import FastMCP

from app.tools.http_diagnostics import service, tool
from app.tools.webpage import service as transport


class HttpDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("http-diagnostic-tests")
        tool.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_redirect_relative_locations_statuses_and_downgrade(self):
        responses = [(301, {"Location": "/next"}, b"", "https://example.com/start"),
                     (307, {"location": "http://other.example/end"}, b"", "https://example.com/next"),
                     (404, {}, b"", "http://other.example/end")]
        with patch.object(service, "request_public", side_effect=responses) as request:
            data = json.loads(await self.call("inspect_redirect_chain", url="https://example.com/start"))
        self.assertTrue(data["completed"])
        self.assertEqual(data["http_status"], 404)
        self.assertEqual(data["followed_redirects"], 2)
        self.assertEqual(data["redirect_responses"], 2)
        self.assertTrue(data["https_downgrade_observed"])
        self.assertEqual([call.args[0] for call in request.call_args_list],
                         ["https://example.com/start", "https://example.com/next", "http://other.example/end"])
        self.assertTrue(all(call.kwargs["method"] == "HEAD" and call.kwargs["follow_redirects"] is False
                            and 0 < call.kwargs["timeout_seconds"] <= 25 for call in request.call_args_list))

    async def test_redirect_head_fallback_reports_get(self):
        for status in (405, 501):
            with self.subTest(status=status), patch.object(service, "request_public", side_effect=[
                (status, {}, b"", "https://example.com"), (200, {}, b"", "https://example.com")]) as request:
                data = json.loads(await self.call("inspect_redirect_chain", url="https://example.com"))
            self.assertEqual([call.kwargs["method"] for call in request.call_args_list], ["HEAD", "GET"])
            self.assertEqual(data["hops"][0]["method"], "GET")

    async def test_redirect_loops_ignore_fragments_and_default_ports(self):
        with patch.object(service, "request_public", return_value=(302, {"Location": "https://example.com:443/#fragment"}, b"", "https://example.com")) as request:
            data = json.loads(await self.call("inspect_redirect_chain", url="https://example.com"))
        self.assertTrue(data["loop_detected"])
        self.assertFalse(data["completed"])
        self.assertEqual(request.call_count, 1)
        self.assertEqual(data["followed_redirects"], 0)

    async def test_redirect_limit_retains_last_observed_response(self):
        responses = [(302, {"Location": f"/{index + 1}"}, b"", f"https://example.com/{index}") for index in range(4)]
        with patch.object(service, "request_public", side_effect=responses) as request:
            data = json.loads(await self.call("inspect_redirect_chain", url="https://example.com/0"))
        self.assertTrue(data["redirect_limit_reached"])
        self.assertEqual(request.call_count, 4)
        self.assertEqual(data["final_url"], "https://example.com/3")
        self.assertEqual(data["redirect_responses"], 4)
        self.assertEqual(data["followed_redirects"], 3)

    async def test_redirect_partial_errors_missing_or_invalid_location(self):
        for location in (None, "https://user:secret@example.com", "https://example.com:9000", "x" * 4097):
            headers = {} if location is None else {"Location": location}
            with self.subTest(location=str(location)[:50]), patch.object(service, "request_public", return_value=(302, headers, b"", "https://example.com")) as request:
                data = json.loads(await self.call("inspect_redirect_chain", url="https://example.com"))
            self.assertFalse(data["completed"])
            self.assertTrue(data["error"])
            self.assertEqual(len(data["hops"]), 1)
            self.assertEqual(request.call_count, 1)
        with patch.object(service, "request_public", side_effect=[
            (302, {"Location": "/next"}, b"", "https://example.com"), OSError("network unavailable")]):
            data = json.loads(await self.call("inspect_redirect_chain", url="https://example.com"))
        self.assertEqual(data["final_url"], "https://example.com")
        self.assertIn("network unavailable", data["error"])

    async def test_http_diagnostics_invalid_url_is_rejected_before_network(self):
        for name in ("inspect_redirect_chain", "inspect_http_cors"):
            for url in ("file:///tmp/file", "https://user:pass@example.com", "https://example.com:8000",
                        "https://example.com/a\n", "https://[broken", "", "x" * 4097):
                arguments = {"url": url}
                if name == "inspect_http_cors":
                    arguments["origin"] = "https://app.example"
                with self.subTest(name=name, url=url[:80]), patch.object(service, "request_public") as request:
                    self.assertTrue((await self.call(name, **arguments)).startswith("Error:"))
                    request.assert_not_called()

    async def test_redirect_private_destination_is_blocked_by_real_transport(self):
        response = Mock(status=302, headers={"Location": "http://127.0.0.1/private"})
        response.read.return_value = b""
        pool = Mock()
        pool.urlopen.return_value = response
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
        with patch.object(transport.socket, "getaddrinfo", side_effect=[public, private]), patch.object(
            transport.urllib3, "HTTPSConnectionPool", return_value=pool
        ), patch.object(transport.urllib3, "HTTPConnectionPool") as private_pool:
            data = json.loads(await self.call("inspect_redirect_chain", url="https://example.com"))
        self.assertIn("non-public", data["error"])
        self.assertEqual(len(data["hops"]), 1)
        private_pool.assert_not_called()

    async def test_redirect_budget_expires_between_hops(self):
        with patch.object(service, "request_public", return_value=(302, {"Location": "/next"}, b"", "https://example.com")) as request, patch.object(
            service.time, "monotonic", side_effect=[0, 0, 0, 1, 26, 26]
        ):
            data = service.trace_redirects("https://example.com")
        self.assertEqual(request.call_count, 1)
        self.assertIn("budget", data["error"])

    async def cors(self, preflight_headers, get_headers=None, status=204, **arguments):
        responses = [(status, preflight_headers, b"", "https://api.example/resource"),
                     (200, preflight_headers if get_headers is None else get_headers, b"", "https://api.example/resource")]
        with patch.object(service, "request_public", side_effect=responses) as request:
            output = await self.call("inspect_http_cors", **{"url": "https://api.example/resource", "origin": "https://app.example", **arguments})
        return json.loads(output), request

    async def test_cors_exact_origin_and_credentials_are_reported_without_sending_them(self):
        headers = {"Access-Control-Allow-Origin": "https://app.example", "Access-Control-Allow-Credentials": "true",
                   "Access-Control-Allow-Methods": "GET, DELETE", "Access-Control-Allow-Headers": "Authorization, X-Request"}
        data, request = await self.cors(headers, requested_method="DELETE", requested_headers_json='["X-Request", "Authorization"]')
        self.assertTrue(data["preflight"]["cors_allows_anonymous"])
        self.assertTrue(data["preflight"]["cors_allows_credentials"])
        self.assertTrue(data["get"]["origin_allows_credentials"])
        self.assertEqual([call.kwargs["method"] for call in request.call_args_list], ["OPTIONS", "GET"])
        self.assertEqual(request.call_args_list[0].kwargs["headers"]["Access-Control-Request-Method"], "DELETE")
        self.assertEqual(request.call_args_list[0].kwargs["headers"]["Access-Control-Request-Headers"], "authorization, x-request")
        for call in request.call_args_list:
            self.assertFalse(call.kwargs["follow_redirects"])
            self.assertNotIn("body", call.kwargs)
            self.assertNotIn("Authorization", call.kwargs["headers"])
            self.assertNotIn("Cookie", call.kwargs["headers"])

    async def test_cors_wildcard_origin_is_anonymous_only(self):
        data, _ = await self.cors({"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Credentials": "true"})
        self.assertTrue(data["preflight"]["cors_allows_anonymous"])
        self.assertFalse(data["preflight"]["cors_allows_credentials"])
        self.assertIn("Wildcard", " ".join(data["preflight"]["issues"]))

    async def test_cors_wildcard_headers_do_not_cover_authorization_or_credentials(self):
        headers = {"Access-Control-Allow-Origin": "https://app.example", "Access-Control-Allow-Credentials": "true",
                   "Access-Control-Allow-Methods": "*", "Access-Control-Allow-Headers": "*"}
        data, _ = await self.cors(headers, requested_method="PUT", requested_headers_json='["X-Custom"]')
        self.assertTrue(data["preflight"]["cors_allows_anonymous"])
        self.assertFalse(data["preflight"]["cors_allows_credentials"])
        data, _ = await self.cors(headers, requested_headers_json='["Authorization"]')
        self.assertFalse(data["preflight"]["cors_allows_anonymous"])

    async def test_cors_missing_headers_invalid_lists_and_statuses(self):
        data, _ = await self.cors({})
        self.assertFalse(data["preflight"]["cors_allows_anonymous"])
        data, _ = await self.cors({"Access-Control-Allow-Origin": "*"}, status=405)
        self.assertFalse(data["preflight"]["cors_allows_anonymous"])
        self.assertTrue(data["get"]["origin_allows_anonymous"])
        data, _ = await self.cors({"Access-Control-Allow-Origin": "https://app.example, https://other.example",
                                  "Access-Control-Allow-Methods": "GET,,POST", "Access-Control-Allow-Credentials": "TRUE"})
        self.assertFalse(data["preflight"]["cors_allows_anonymous"])
        self.assertTrue(data["preflight"]["issues"])
        self.assertIsNone(data["preflight"]["allowed_methods"])

    async def test_cors_get_safelisted_method_does_not_need_allow_methods(self):
        data, _ = await self.cors({"Access-Control-Allow-Origin": "https://app.example"})
        self.assertTrue(data["preflight"]["cors_allows_anonymous"])
        data, _ = await self.cors({"Access-Control-Allow-Origin": "https://app.example"}, requested_method="PATCH")
        self.assertFalse(data["preflight"]["cors_allows_anonymous"])

    async def test_cors_origin_serialization_opaque_origins_and_whitespace(self):
        for given, serialized in (("HTTPS://APP.EXAMPLE:443/", "https://app.example"),
                                  ("http://localhost:3000", "http://localhost:3000"), ("null", "null")):
            data, request = await self.cors({"Access-Control-Allow-Origin": " " + serialized + " "}, origin=given)
            self.assertEqual(data["origin"], serialized)
            self.assertTrue(data["get"]["origin_allows_anonymous"])
            self.assertEqual(request.call_args_list[0].kwargs["headers"]["Origin"], serialized)

    async def test_cors_invalid_inputs_do_not_request(self):
        inputs = [{"origin": origin} for origin in ("*", "ftp://example.com", "https://app.example/path", "https://user:pass@app.example",
                                                    "https://app.example?x=1", "https://app.example#fragment", "https://app.example\n", "https://app.example:0")]
        inputs += [{"requested_method": "post"}, {"requested_method": "CONNECT"}]
        inputs += [{"requested_headers_json": value} for value in ("{}", "not json", "[true]", '["X\nInject"]', '["*"]',
                                                                    json.dumps(["X-" + str(i) for i in range(21)]), "x" * 4001)]
        for arguments in inputs:
            with self.subTest(arguments=arguments), patch.object(service, "request_public") as request:
                output = await self.call("inspect_http_cors", **{"url": "https://api.example", "origin": "https://app.example", **arguments})
            self.assertTrue(output.startswith("Error:"))
            request.assert_not_called()

    async def test_cors_does_not_follow_redirects_or_test_redirect_target_policy(self):
        data, request = await self.cors({"Location": "http://127.0.0.1/private", "Access-Control-Allow-Origin": "*"}, status=302)
        self.assertFalse(data["preflight"]["cors_allows_anonymous"])
        self.assertTrue(all(call.args[0] == "https://api.example/resource" for call in request.call_args_list))

    async def test_cors_private_initial_destination_and_network_errors(self):
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch.object(transport.socket, "getaddrinfo", return_value=private), patch.object(transport.urllib3, "HTTPSConnectionPool") as pool:
            output = await self.call("inspect_http_cors", url="https://api.example", origin="https://app.example")
        self.assertIn("non-public", output)
        pool.assert_not_called()
        with patch.object(service, "request_public", side_effect=urllib3.exceptions.ReadTimeoutError(None, "/", "timeout")):
            self.assertTrue((await self.call("inspect_http_cors", url="https://api.example", origin="null")).startswith("Error:"))

    async def test_cors_header_limits_and_truncation(self):
        data, _ = await self.cors({"Access-Control-Allow-Origin": "*", "Vary": "x" * 2001})
        self.assertTrue(data["truncated"])
        self.assertEqual(len(data["get"]["headers"]["vary"]), 2000)
        with patch.object(service, "request_public", return_value=(200, {"Vary": "x" * 16001}, b"", "url")):
            self.assertIn("16000", await self.call("inspect_http_cors", url="https://api.example", origin="null"))

    async def test_cors_budget_is_shared_between_options_and_get(self):
        with patch.object(service, "request_public", return_value=(204, {"Access-Control-Allow-Origin": "*"}, b"", "url")) as request, patch.object(
            service.time, "monotonic", side_effect=[0, 0, 26]
        ):
            with self.assertRaisesRegex(ValueError, "budget"):
                service.inspect_cors("https://api.example", "https://app.example", "GET", "[]")
        self.assertEqual(request.call_count, 1)

    async def test_diagnostic_output_caps(self):
        for name, target, arguments in (
            ("inspect_redirect_chain", "trace_redirects", {"url": "https://example.com"}),
            ("inspect_http_cors", "inspect_cors", {"url": "https://example.com", "origin": "null"}),
        ):
            with patch.object(service, target, return_value={"large": "x" * 100001}):
                self.assertIn("output exceeds", await self.call(name, **arguments))


class SingleHopTransportTests(unittest.TestCase):
    def addresses(self):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]

    def test_single_hop_returns_redirect_without_requesting_destination(self):
        response = Mock(status=303, headers={"Location": "http://127.0.0.1/private"})
        response.read.side_effect = [b"redirect", b""]
        pool = Mock()
        pool.urlopen.return_value = response
        with patch.object(transport.socket, "getaddrinfo", return_value=self.addresses()) as resolve, patch.object(
            transport.urllib3, "HTTPSConnectionPool", return_value=pool
        ), patch.object(transport.urllib3, "HTTPConnectionPool") as private_pool:
            status, headers, body, url = transport.request_public("https://example.com", method="OPTIONS", follow_redirects=False)
        self.assertEqual((status, body, url), (303, b"redirect", "https://example.com"))
        self.assertEqual(headers["Location"], "http://127.0.0.1/private")
        self.assertEqual(pool.urlopen.call_args.args[0], "OPTIONS")
        self.assertEqual(resolve.call_count, 1)
        private_pool.assert_not_called()
        response.close.assert_called_once()
        pool.close.assert_called_once()

    def test_single_hop_retains_download_limit_and_host_pinning(self):
        response = Mock(status=302, headers={"Location": "/next"})
        response.read.return_value = b"x" * 9
        pool = Mock()
        pool.urlopen.return_value = response
        with patch.object(transport.socket, "getaddrinfo", return_value=self.addresses()), patch.object(
            transport.urllib3, "HTTPSConnectionPool", return_value=pool
        ) as constructor, patch.object(transport, "_MAX_BYTES", 8):
            with self.assertRaisesRegex(ValueError, "download limit"):
                transport.request_public("https://example.com", follow_redirects=False)
        self.assertEqual(constructor.call_args.args[0], "93.184.215.14")
        self.assertEqual(constructor.call_args.kwargs["server_hostname"], "example.com")


if __name__ == "__main__":
    unittest.main()
