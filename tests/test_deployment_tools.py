import json
import socket
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import urllib3
from mcp.server.fastmcp import FastMCP

from app.tools.dockerfile_utils import service as docker_service, tool as docker_tool
from app.tools.endpoint_utils import service as endpoint_service, tool as endpoint_tool
from app.tools.github_utils import service as github_service, tool as github_tool
from app.tools.http_cache_utils import service as cache_service, tool as cache_tool
from app.tools.webpage import service as transport


class DeploymentToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = FastMCP("deployment-tests")
        for module in (docker_tool, endpoint_tool, github_tool, cache_tool):
            module.register(self.mcp)

    async def call(self, name, **arguments):
        result = await self.mcp.call_tool(name, arguments)
        content = result[0] if isinstance(result, tuple) else result
        return "\n".join(item.text for item in content if item.type == "text")

    async def test_endpoints_return_mixed_results_in_input_order(self):
        inputs = [{"name": "ok", "url": "https://example.com/ok"},
                  {"url": "https://example.com/missing", "expected_status": 204},
                  {"url": "https://example.com/slow"}]

        def request(url, **kwargs):
            self.assertEqual(kwargs, {"timeout_seconds": 10})
            if url.endswith("slow"):
                raise urllib3.exceptions.ReadTimeoutError(None, url, "timeout")
            return (200 if url.endswith("ok") else 404), {}, b"", url + "/final"

        with patch.object(endpoint_service, "request_public", side_effect=request):
            result = json.loads(await self.call("check_http_endpoints", endpoints_json=json.dumps(inputs)))
        self.assertEqual((result["count"], result["passed"], result["failed"]), (3, 1, 2))
        self.assertFalse(result["all_matched"])
        self.assertEqual([row["url"] for row in result["endpoints"]], [row["url"] for row in inputs])
        self.assertEqual(result["endpoints"][1]["http_status"], 404)
        self.assertEqual(result["endpoints"][0]["final_url"], inputs[0]["url"] + "/final")
        self.assertIsNone(result["endpoints"][2]["http_status"])
        self.assertIn("ReadTimeoutError", result["endpoints"][2]["error"])
        self.assertTrue(all(row["elapsed_ms"] >= 0 for row in result["endpoints"]))

    async def test_endpoint_batch_caps_concurrency_at_two(self):
        active = peak = calls = 0
        lock, barrier = threading.Lock(), threading.Barrier(2)

        def request(url, **kwargs):
            nonlocal active, peak, calls
            with lock:
                calls += 1
                number = calls
                active += 1
                peak = max(peak, active)
            if number <= 2:
                barrier.wait(timeout=2)
            time.sleep(0.02)
            with lock:
                active -= 1
            return 200, {}, b"", url

        inputs = [{"url": f"https://example.com/{index}"} for index in range(5)]
        with patch.object(endpoint_service, "request_public", side_effect=request):
            result = json.loads(await self.call("check_http_endpoints", endpoints_json=json.dumps(inputs)))
        self.assertEqual((peak, calls), (2, 5))
        self.assertTrue(result["all_matched"])

    async def test_endpoint_inputs_are_validated_before_network(self):
        invalid = ["[]", "{}", "not json", "x" * 25001,
                   json.dumps([{"url": "https://example.com"}] * 6),
                   '[null]', '[{"url":1}]', '[{"url":"https://example.com","name":1}]',
                   '[{"url":"https://example.com","expected_status":true}]',
                   '[{"url":"https://example.com","expected_status":200.0}]',
                   '[{"url":"https://example.com","expected_status":600}]',
                   '[{"url":"https://example.com","headers":{}}]']
        for url in ("file:///tmp/data", "https://user:secret@example.com", "https://example.com:8000",
                    "https://example.com:bad", "https://example.com/\nfoo", "https://[broken", ""):
            invalid.append(json.dumps([{"url": url}]))
        for value in invalid:
            with self.subTest(value=value[:100]), patch.object(endpoint_service, "request_public") as request:
                self.assertTrue((await self.call("check_http_endpoints", endpoints_json=value)).startswith("Error:"))
                request.assert_not_called()

    async def test_endpoint_network_errors_are_per_endpoint_and_bounded(self):
        for error in (ValueError("non-public destination"), OSError("network unavailable"),
                      ValueError("x" * 1000)):
            with self.subTest(error=str(error)[:50]), patch.object(endpoint_service, "request_public", side_effect=error):
                result = json.loads(await self.call("check_http_endpoints", endpoints_json='[{"url":"https://example.com"}]'))
            self.assertEqual(result["failed"], 1)
            self.assertLessEqual(len(result["endpoints"][0]["error"]), 500)

    async def test_new_http_tools_block_private_redirects_with_shared_transport(self):
        for name, arguments in (
            ("check_http_endpoints", {"endpoints_json": '[{"url":"https://example.com"}]'}),
            ("inspect_http_cache", {"url": "https://example.com"}),
        ):
            response = Mock(status=302, headers={"Location": "http://127.0.0.1/private"})
            pool = Mock()
            pool.urlopen.return_value = response
            addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]
            private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
            with self.subTest(name=name), patch.object(transport.socket, "getaddrinfo", side_effect=[addresses, private]), patch.object(
                transport.urllib3, "HTTPSConnectionPool", return_value=pool
            ), patch.object(transport.urllib3, "HTTPConnectionPool") as private_pool:
                output = await self.call(name, **arguments)
            self.assertIn("non-public", output)
            private_pool.assert_not_called()

    async def checks(self, **arguments):
        return await self.call("get_github_commit_checks", owner="a", repo="b", ref="feature/tools", **arguments)

    def github_payloads(self):
        sha = "a" * 40
        legacy = {"sha": sha, "state": "failure", "total_count": 2, "statuses": [
            {"id": 1, "context": "lint", "state": "error"}, {"id": 2, "context": "deploy", "state": "pending"}]}
        checks = {"total_count": 3, "check_runs": [
            {"id": 3, "name": "test", "head_sha": sha, "status": "completed", "conclusion": "failure"},
            {"id": 4, "name": "build", "head_sha": sha, "status": "in_progress", "conclusion": None},
            {"id": 5, "name": "docs", "head_sha": sha, "status": "completed", "conclusion": "neutral"}]}
        return legacy, checks

    async def test_commit_checks_pin_sha_and_separate_legacy_states(self):
        legacy, checks = self.github_payloads()
        with patch.object(github_service, "_request", side_effect=[legacy, checks]) as request:
            result = json.loads(await self.checks())
        self.assertEqual(request.call_args_list[0].args,
                         ("repos/a/b/commits/feature%2Ftools/status", {"per_page": 11}))
        self.assertEqual(request.call_args_list[1].args,
                         (f"repos/a/b/commits/{legacy['sha']}/check-runs", {"filter": "latest", "per_page": 11}))
        self.assertEqual(result["observed"], {"pending_check_runs": 1, "failed_check_runs": 1,
                                               "pending_statuses": 1, "failed_statuses": 1})
        self.assertEqual(result["legacy_statuses"]["combined_state"], "failure")
        self.assertFalse(result["truncated"])
        self.assertIsNone(result["check_runs"]["runs"][1]["conclusion"])

    async def test_commit_checks_report_pagination_and_string_truncation(self):
        legacy, checks = self.github_payloads()
        checks["check_runs"][0]["name"] = "x" * 201
        with patch.object(github_service, "_request", side_effect=[legacy, checks]):
            result = json.loads(await self.checks(limit=1))
        self.assertTrue(result["check_runs"]["truncated"])
        self.assertTrue(result["legacy_statuses"]["truncated"])
        self.assertEqual(len(result["check_runs"]["runs"]), 1)
        self.assertEqual(len(result["check_runs"]["runs"][0]["name"]), 200)
        self.assertTrue(result["truncated"])

    async def test_empty_commit_checks_do_not_claim_pass(self):
        legacy = {"sha": "a" * 40, "state": "pending", "total_count": 0, "statuses": []}
        with patch.object(github_service, "_request", side_effect=[legacy, {"total_count": 0, "check_runs": []}]):
            result = json.loads(await self.checks())
        self.assertTrue(result["check_runs"]["empty"])
        self.assertTrue(result["legacy_statuses"]["empty"])
        self.assertEqual(result["legacy_statuses"]["combined_state"], "pending")
        self.assertIn("empty results do not mean CI passed", " ".join(result["notes"]))

    async def test_commit_checks_reject_malformed_api_data(self):
        legacy, checks = self.github_payloads()
        invalid_legacy = [[], {}, {**legacy, "sha": "../escape"}, {**legacy, "sha": "a" * 41},
                          {**legacy, "state": {}}, {**legacy, "total_count": True},
                          {**legacy, "statuses": [None]},
                          {**legacy, "statuses": [{"id": True, "context": "test", "state": "success"}]},
                          {**legacy, "statuses": [{"id": 1, "context": "test", "state": []}]}]
        invalid_checks = [[], {}, {**checks, "total_count": -1}, {**checks, "total_count": True},
                          {**checks, "check_runs": [None]},
                          {**checks, "check_runs": [{**checks["check_runs"][0], "head_sha": "b" * 40}]},
                          {**checks, "check_runs": [{**checks["check_runs"][0], "status": {}}]},
                          {**checks, "check_runs": [{**checks["check_runs"][0], "conclusion": []}]}]
        for first, second in [(data, checks) for data in invalid_legacy] + [(legacy, data) for data in invalid_checks]:
            with self.subTest(first=first, second=second), patch.object(github_service, "_request", side_effect=[first, second]):
                self.assertTrue((await self.checks()).startswith("Error:"))

    async def test_commit_checks_invalid_input_and_host_pinning(self):
        for arguments in ({"ref": "../escape"}, {"ref": "main/"}, {"owner": "../a"}, {"limit": 0}, {"limit": 21}):
            with self.subTest(arguments=arguments), patch.object(github_service, "_request") as request:
                output = await self.call("get_github_commit_checks", **{"owner": "a", "repo": "b", "ref": "main", **arguments})
            self.assertTrue(output.startswith("Error:"))
            request.assert_not_called()
        legacy, checks = self.github_payloads()
        responses = [(json.dumps(payload).encode(), "application/json", "url") for payload in (legacy, checks)]
        with patch.object(github_service, "fetch_page", side_effect=responses) as fetch:
            await self.checks()
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(all(call.kwargs["allowed_host"] == "api.github.com" for call in fetch.call_args_list))
        for status in (403, 404, 429):
            with patch.object(github_service, "fetch_page", side_effect=ValueError(f"HTTP {status}")):
                self.assertIn(f"HTTP {status}", await self.checks())

    async def test_dockerfile_multistage_summary_and_declared_settings(self):
        content = ('# syntax=docker/dockerfile:1\nARG BASE=python:3.12-slim\n'
                   'FROM --platform=$BUILDPLATFORM ${BASE} AS build\n'
                   'RUN echo hello \\\n  && echo world\nUSER builder\n'
                   'FROM build AS runtime\nWORKDIR /app\nUSER 1000:1000\nEXPOSE 8000 9000/udp\n'
                   'ENTRYPOINT ["python", "-m"]\nCMD ["app"]\nCMD ["server"]\n')
        result = json.loads(await self.call("inspect_dockerfile", content=content))
        self.assertEqual(result["stage_count"], 2)
        build, runtime = result["stages"]
        self.assertEqual(build["base_image"], "${BASE}")
        self.assertEqual(build["platform"], "$BUILDPLATFORM")
        self.assertEqual(runtime["parent_stage"], 0)
        self.assertEqual(runtime["declared_user"]["value"], "1000:1000")
        self.assertEqual(runtime["declared_ports"], ["8000", "9000/udp"])
        self.assertEqual(runtime["cmd"]["value"], ["server"])
        self.assertEqual(runtime["entrypoint"]["form"], "exec")
        self.assertEqual(result["global_args"][0]["value"], "BASE=python:3.12-slim")
        self.assertEqual(result["instruction_counts"]["RUN"], 1)
        self.assertFalse(result["truncated"])

    async def test_dockerfile_escape_directive_crlf_shell_and_unset_user(self):
        content = '# escape=`\r\nFROM base\r\nRUN echo a `\r\n && echo b\r\nCMD echo "hello world"\r\n'
        result = json.loads(await self.call("inspect_dockerfile", content=content))
        self.assertEqual(result["instruction_count"], 3)
        self.assertIsNone(result["stages"][0]["declared_user"])
        self.assertEqual(result["stages"][0]["cmd"]["form"], "shell")
        self.assertEqual(result["stages"][0]["cmd"]["line"], 5)

    async def test_dockerfile_does_not_infer_inherited_commands_or_users(self):
        result = json.loads(await self.call("inspect_dockerfile", content='FROM base AS builder\nUSER app\nCMD ["run"]\nFROM builder\n'))
        self.assertEqual(result["stages"][1]["parent_stage"], 0)
        self.assertIsNone(result["stages"][1]["cmd"])
        self.assertIsNone(result["stages"][1]["declared_user"])

    async def test_dockerfile_unicode_line_separators_in_command_are_preserved(self):
        content = 'FROM base\nCMD ["print", "caf\u00e9\u2028text"]\n'
        result = json.loads(await self.call("inspect_dockerfile", content=content))
        self.assertEqual(result["stages"][0]["cmd"]["value"], ["print", "caf\u00e9\u2028text"])

    async def test_dockerfile_rejects_malformed_or_unsupported_content(self):
        for content in ("", "# only a comment", "RUN echo hello", "FROM", "FROM base extra", "FROM base\nUSER",
                        "FROM base\nRUN echo hello \\", "FROM base\nUNKNOWN value\n", "FROM base AS a\nFROM base AS A\n",
                        "FROM base\nRUN <<EOF\necho hi\nEOF\n", "FROM base\0", "x" * 200001):
            with self.subTest(content=content[:100]):
                self.assertTrue((await self.call("inspect_dockerfile", content=content)).startswith("Error:"))

    async def test_dockerfile_resource_limits_truncation_and_output_budget(self):
        for content in ("FROM base\n" * 21, "FROM base\n" + "RUN true\n" * 1000,
                        "# comment\n" * 5000 + "FROM base\n"):
            self.assertTrue((await self.call("inspect_dockerfile", content=content)).startswith("Error:"))
        result = json.loads(await self.call("inspect_dockerfile", content="FROM base\nUSER " + "x" * 2001 + "\nEXPOSE " + " ".join(str(i) for i in range(101))))
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["stages"][0]["declared_user"]["value"]), 2000)
        self.assertEqual(len(result["stages"][0]["declared_ports"]), 100)
        large = "\n".join("ARG X" + str(i) + "=" + "x" * 1990 for i in range(60)) + "\nFROM base\n"
        self.assertIn("output exceeds", await self.call("inspect_dockerfile", content=large))

    async def test_dockerfile_inspects_actual_project_dockerfile(self):
        content = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
        result = json.loads(await self.call("inspect_dockerfile", content=content))
        self.assertEqual(result["stage_count"], 1)
        self.assertEqual(result["stages"][0]["declared_ports"], ["8000"])
        self.assertIn("uvicorn", result["stages"][0]["cmd"]["value"])

    async def cache(self, header=None, **headers):
        if header is not None:
            headers["Cache-Control"] = header
        with patch.object(cache_service, "request_public", return_value=(200, headers, b"", "https://example.com/final")):
            return json.loads(await self.call("inspect_http_cache", url="https://example.com"))

    async def test_cache_separates_browser_and_shared_lifetimes(self):
        result = await self.cache('PUBLIC, MAX-AGE="60", s-maxage=600, stale-while-revalidate=30', Age="20", ETag='"v1"')
        self.assertEqual(result["scopes"]["browser"]["freshness_lifetime_seconds"], 60)
        self.assertEqual(result["scopes"]["shared"]["freshness_lifetime_seconds"], 600)
        self.assertEqual(result["scopes"]["shared"]["freshness_source"], "s-maxage")
        self.assertEqual(result["seconds"]["stale-while-revalidate"], 30)
        self.assertTrue(result["scopes"]["shared"]["revalidate_when_stale"])
        self.assertFalse(result["scopes"]["browser"]["revalidate_when_stale"])
        self.assertTrue(result["valid_cache_control"])
        self.assertEqual(result["headers"]["age"], "20")
        self.assertEqual(result["headers"]["etag"], '"v1"')

    async def test_cache_no_cache_is_not_no_store(self):
        result = await self.cache("no-cache, max-age=60")
        self.assertEqual(result["scopes"]["browser"]["storage"], "not_prohibited")
        self.assertEqual(result["scopes"]["browser"]["revalidate_before_reuse"], "required")
        result = await self.cache("no-store, public, max-age=60")
        self.assertTrue(all(scope["storage"] == "prohibited" for scope in result["scopes"].values()))

    async def test_cache_must_understand_no_store_is_conditional(self):
        result = await self.cache("must-understand, no-store")
        self.assertTrue(all(scope["storage"] == "conditional_must_understand" for scope in result["scopes"].values()))
        result = await self.cache("must-understand, no-store, private")
        self.assertEqual(result["scopes"]["shared"]["storage"], "prohibited")

    async def test_cache_qualified_field_lists_and_conflicting_directives(self):
        result = await self.cache('private="Set-Cookie, X-User", no-cache="ETag, X-User"')
        self.assertEqual(result["private_fields"], ["set-cookie", "x-user"])
        self.assertEqual(result["no_cache_fields"], ["etag", "x-user"])
        self.assertEqual(result["scopes"]["shared"]["storage"], "conditional_field_exclusion")
        self.assertEqual(result["scopes"]["browser"]["revalidate_before_reuse"], "listed_fields")
        result = await self.cache("public, private, max-age=60")
        self.assertFalse(result["valid_cache_control"])
        self.assertEqual(result["scopes"]["shared"]["storage"], "prohibited")
        self.assertTrue(any("conflict" in issue for issue in result["issues"]))

    async def test_cache_duplicate_and_invalid_numeric_values_are_not_guessed(self):
        for header in ("max-age=60, max-age=120", "max-age=60, max-age=60", "max-age=-1", "max-age=1.5",
                       "max-age", 'max-age="abc"', "max-age=" + "9" * 20):
            with self.subTest(header=header):
                result = await self.cache(header)
            self.assertIsNone(result["scopes"]["browser"]["freshness_lifetime_seconds"])
            self.assertFalse(result["valid_cache_control"])
            self.assertTrue(result["issues"])

    async def test_cache_malformed_quotes_and_field_lists_are_explicit(self):
        for header in ('max-age="60', "private=\"\"", 'no-cache="a,,b"', "no-cache, no-cache", "no-store=true"):
            with self.subTest(header=header):
                result = await self.cache(header)
            self.assertFalse(result["valid_cache_control"])
            self.assertTrue(result["issues"])
        result = await self.cache('custom="a, b", max-age=0')
        self.assertEqual(result["directives"][0]["value"], "a, b")
        self.assertEqual(result["scopes"]["browser"]["freshness_lifetime_seconds"], 0)

    async def test_cache_missing_headers_expires_and_vary_star(self):
        result = await self.cache()
        self.assertEqual(result["directives"], [])
        self.assertEqual(result["scopes"]["browser"]["freshness_source"], "unspecified")
        result = await self.cache(Expires="Wed, 21 Oct 2026 07:28:00 GMT", Vary="*")
        self.assertEqual(result["scopes"]["browser"]["freshness_source"], "expires")
        self.assertIsNone(result["scopes"]["browser"]["freshness_lifetime_seconds"])
        self.assertTrue(any("Vary: *" in note for note in result["notes"]))

    async def test_cache_head_fallback_and_error_status_are_reported(self):
        for status in (405, 501):
            with self.subTest(status=status), patch.object(cache_service, "request_public", side_effect=[
                (status, {}, b"", "https://example.com"),
                (404, {"Cache-Control": "no-store"}, b"", "https://example.com/final")]) as request:
                result = json.loads(await self.call("inspect_http_cache", url="https://example.com"))
            self.assertEqual([call.kwargs["method"] for call in request.call_args_list], ["HEAD", "GET"])
            self.assertEqual(result["http_status"], 404)
            self.assertEqual(result["method"], "GET")
            self.assertEqual(result["final_url"], "https://example.com/final")

    async def test_cache_limits_truncation_and_network_errors(self):
        for header in ("x" * 16001, ",".join("custom" for _ in range(101))):
            with patch.object(cache_service, "request_public", return_value=(200, {"Cache-Control": header}, b"", "url")):
                self.assertTrue((await self.call("inspect_http_cache", url="https://example.com")).startswith("Error:"))
        result = await self.cache("max-age=60", ETag="x" * 2001)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["headers"]["etag"]), 2000)
        with patch.object(cache_service, "request_public", side_effect=OSError("unavailable")):
            self.assertIn("unavailable", await self.call("inspect_http_cache", url="https://example.com"))


if __name__ == "__main__":
    unittest.main()
