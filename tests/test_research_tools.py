import json
import socket
import unittest
from unittest.mock import Mock, patch

import urllib3
from mcp.server.fastmcp import FastMCP

from app.tools.cron_utils import tool as cron_tools
from app.tools.schema_utils import tool as schema_tools
from app.tools.webpage import service as webpage_service
from app.tools.webpage import tool as webpage_tools
from app.tools.yaml_utils import tool as yaml_tools


def _addresses(ip="93.184.215.14"):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


def _response(body=b"Hello", status=200, headers=None):
    response = Mock(status=status, headers=headers or {"Content-Type": "text/plain"})
    response.read.side_effect = [body, b""]
    return response


class ResearchToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("research-tests")
        for module in (webpage_tools, schema_tools, yaml_tools, cron_tools):
            module.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_webpage_extracts_article_and_removes_clutter(self):
        body = b'''<html><head><title>Example</title></head><body>
            <nav>Menu<script>nested script</script></nav><header>Header</header>
            <main><article><h1>News</h1><p>A useful <b>article</b>.</p>
            <script>alert(1)</script><p hidden>Hidden</p></article></main>
            <footer>Footer</footer></body></html>'''
        with patch.object(webpage_tools, "fetch_page", return_value=(body, "text/html", "https://example.com/")):
            result = json.loads(await self.call("get_webpage_text", url="https://example.com/"))
        self.assertEqual(result["title"], "Example")
        self.assertIn("News", result["text"])
        self.assertIn("article", result["text"])
        for unwanted in ("Menu", "Header", "Footer", "Hidden", "alert"):
            self.assertNotIn(unwanted, result["text"])
        self.assertFalse(result["truncated"])

    async def test_webpage_truncates_plain_text(self):
        with patch.object(webpage_tools, "fetch_page", return_value=(b"a" * 200, "text/plain", "https://example.com/")):
            result = json.loads(await self.call("get_webpage_text", url="https://example.com/", max_chars=100))
        self.assertEqual(len(result["text"]), 100)
        self.assertTrue(result["truncated"])

    async def test_webpage_rejects_bad_limits_and_network_errors(self):
        self.assertTrue((await self.call("get_webpage_text", url="https://example.com", max_chars=99)).startswith("Error:"))
        with patch.object(webpage_tools, "fetch_page", side_effect=urllib3.exceptions.ReadTimeoutError(None, "/", "timeout")):
            self.assertTrue((await self.call("get_webpage_text", url="https://example.com")).startswith("Error:"))

    async def test_schema_validates_required_fields_and_types(self):
        schema = json.dumps({"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]})
        good = json.loads(await self.call("validate_json_schema", value='{"count":2}', schema=schema))
        self.assertEqual(good, {"valid": True, "errors": [], "truncated": False})
        bad = json.loads(await self.call("validate_json_schema", value='{"count":"two"}', schema=schema))
        self.assertFalse(bad["valid"])
        self.assertEqual(bad["errors"][0]["path"], "/count")
        missing = json.loads(await self.call("validate_json_schema", value="{}", schema=schema))
        self.assertFalse(missing["valid"])

    async def test_schema_local_references_and_format_checks(self):
        schema = '{"$defs":{"address":{"type":"string","format":"email"}},"$ref":"#/$defs/address"}'
        result = json.loads(await self.call("validate_json_schema", value='"not-an-email"', schema=schema))
        self.assertFalse(result["valid"])

    async def test_schema_boolean_and_invalid_schemas(self):
        self.assertTrue(json.loads(await self.call("validate_json_schema", value="null", schema="true"))["valid"])
        self.assertFalse(json.loads(await self.call("validate_json_schema", value="null", schema="false"))["valid"])
        for schema in ('[]', '{', '{"type":"unknown"}', '{"$schema":"https://unknown.example/schema"}'):
            with self.subTest(schema=schema):
                self.assertTrue((await self.call("validate_json_schema", value="{}", schema=schema)).startswith("Error:"))

    async def test_schema_remote_reference_is_blocked(self):
        result = await self.call("validate_json_schema", value="{}", schema='{"$ref":"https://example.com/schema.json"}')
        self.assertTrue(result.startswith("Error:"))

    async def test_schema_error_count_is_capped(self):
        result = json.loads(await self.call(
            "validate_json_schema", value=json.dumps(["wrong"] * 51),
            schema='{"type":"array","items":{"type":"integer"}}',
        ))
        self.assertEqual(len(result["errors"]), 50)
        self.assertTrue(result["truncated"])

    async def test_schema_pathological_regex_times_out(self):
        result = await self.call(
            "validate_json_schema", value=json.dumps("a" * 80 + "!"),
            schema='{"type":"string","pattern":"^(a+)+$"}',
        )
        self.assertIn("3-second limit", result)

    async def test_yaml_preserves_dates_and_json_types(self):
        result = json.loads(await self.call("yaml_to_json", value='name: Ada\nactive: true\ncreated: 2026-09-28\ncode: "001"\n'))
        self.assertEqual(result, {"name": "Ada", "active": True, "created": "2026-09-28", "code": "001"})

    async def test_yaml_round_trip_with_nested_values(self):
        value = {"users": [{"name": "Ada", "enabled": False}], "count": 2, "empty": None}
        converted = await self.call("json_to_yaml", value=json.dumps(value))
        self.assertEqual(json.loads(await self.call("yaml_to_json", value=converted)), value)

    async def test_yaml_shared_aliases_and_merge_keys(self):
        value = "defaults: &defaults {city: London}\nuser:\n  <<: *defaults\n  name: Ada\n"
        result = json.loads(await self.call("yaml_to_json", value=value))
        self.assertEqual(result["user"], {"city": "London", "name": "Ada"})

    async def test_yaml_rejects_unsafe_and_non_json_values(self):
        for value in (
            "!!python/object/apply:builtins.str [unsafe]", "1: value", "name: A\nname: B",
            "value: .nan", "value: !!binary SGVsbG8=", "value: &loop [*loop]",
            "---\na: 1\n---\na: 2", "a: [",
        ):
            with self.subTest(value=value):
                self.assertTrue((await self.call("yaml_to_json", value=value)).startswith("Error:"))

    async def test_yaml_rejects_alias_expansion_and_large_input(self):
        aliases = "a0: &a0 [0,0,0,0,0,0,0,0,0,0]\n"
        for level in range(1, 6):
            aliases += f"a{level}: &a{level} [" + ",".join([f"*a{level - 1}"] * 10) + "]\n"
        self.assertTrue((await self.call("yaml_to_json", value=aliases)).startswith("Error:"))
        self.assertTrue((await self.call("yaml_to_json", value=" " * 200001)).startswith("Error:"))
        self.assertTrue((await self.call("json_to_yaml", value="NaN")).startswith("Error:"))

    async def test_cron_preview_and_explicit_offset(self):
        result = json.loads(await self.call(
            "cron_next_runs", expression="*/15 * * * *", count=2,
            timezone_name="UTC", from_datetime="2026-09-28T05:30:00+05:30",
        ))
        self.assertEqual(result["next_runs"], ["2026-09-28T00:15:00+00:00", "2026-09-28T00:30:00+00:00"])

    async def test_cron_timezone_across_dst(self):
        result = json.loads(await self.call(
            "cron_next_runs", expression="0 9 * * *", count=2,
            timezone_name="Europe/London", from_datetime="2026-03-28T10:00:00+00:00",
        ))
        self.assertEqual(result["next_runs"], ["2026-03-29T09:00:00+01:00", "2026-03-30T09:00:00+01:00"])

    async def test_cron_rejects_invalid_and_impossible_schedules(self):
        for arguments in (
            {"expression": "invalid"}, {"expression": "61 * * * *"},
            {"expression": "0 0 30 2 *"}, {"expression": "* * * * *", "count": 0},
            {"expression": "* * * * *", "count": 21},
            {"expression": "* * * * *", "timezone_name": "Not/AZone"},
            {"expression": "* * * * *", "from_datetime": "invalid"},
        ):
            with self.subTest(arguments=arguments):
                self.assertTrue((await self.call("cron_next_runs", **arguments)).startswith("Error:"))


class WebpageRequestTests(unittest.TestCase):
    def test_connects_to_pinned_ip_with_original_tls_name(self):
        response = _response()
        pool = Mock()
        pool.urlopen.return_value = response
        with patch.object(webpage_service.socket, "getaddrinfo", return_value=_addresses()), patch.object(
            webpage_service.urllib3, "HTTPSConnectionPool", return_value=pool
        ) as create_pool:
            body, _, final_url = webpage_service.fetch_page("https://example.com/page?q=test")
        self.assertEqual(body, b"Hello")
        self.assertEqual(final_url, "https://example.com/page?q=test")
        create_pool.assert_called_once_with("93.184.215.14", port=443, assert_hostname="example.com", server_hostname="example.com")
        self.assertEqual(pool.urlopen.call_args.kwargs["headers"]["Host"], "example.com")
        self.assertFalse(pool.urlopen.call_args.kwargs["redirect"])
        response.close.assert_called_once()
        pool.close.assert_called_once()

    def test_private_redirect_is_blocked_before_connection(self):
        pool = Mock()
        pool.urlopen.return_value = _response(status=302, headers={"Location": "http://127.0.0.1/private"})
        with patch.object(webpage_service.socket, "getaddrinfo", side_effect=[_addresses(), _addresses("127.0.0.1")]), patch.object(
            webpage_service.urllib3, "HTTPSConnectionPool", return_value=pool
        ), patch.object(webpage_service.urllib3, "HTTPConnectionPool") as http_pool:
            with self.assertRaisesRegex(ValueError, "non-public"):
                webpage_service.fetch_page("https://example.com/")
            http_pool.assert_not_called()

    def test_private_initial_host_and_mixed_dns_are_blocked(self):
        for addresses in (_addresses("10.0.0.1"), _addresses() + _addresses("127.0.0.1")):
            with self.subTest(addresses=addresses), patch.object(webpage_service.socket, "getaddrinfo", return_value=addresses):
                with self.assertRaisesRegex(ValueError, "non-public"):
                    webpage_service.fetch_page("https://example.com/")

    def test_download_size_and_non_text_content_are_rejected(self):
        for response, expected in (
            (_response(body=b"x" * 9), "download limit"),
            (_response(headers={"Content-Type": "application/pdf"}), "Only HTML"),
            (_response(status=404), "HTTP 404"),
        ):
            pool = Mock()
            pool.urlopen.return_value = response
            with self.subTest(expected=expected), patch.object(webpage_service, "_MAX_BYTES", 8), patch.object(
                webpage_service.socket, "getaddrinfo", return_value=_addresses()
            ), patch.object(webpage_service.urllib3, "HTTPSConnectionPool", return_value=pool):
                with self.assertRaisesRegex(ValueError, expected):
                    webpage_service.fetch_page("https://example.com/")
                response.close.assert_called_once()

    def test_invalid_urls_are_rejected(self):
        for url in ("file:///tmp/file", "http://", "https://user:password@example.com/", "https://example.com:9000/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                webpage_service.fetch_page(url)


if __name__ == "__main__":
    unittest.main()
