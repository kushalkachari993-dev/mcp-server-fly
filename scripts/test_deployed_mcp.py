import argparse
import asyncio
import os
import json
import math
from pathlib import Path
from urllib.parse import urljoin

from dotenv import load_dotenv
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


DEFAULT_BASE_URL = "https://mcpsever.fly.dev"


def _text_from_tool_result(result) -> str:
    parts = []
    for item in result.content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(str(item))
    return "\n".join(parts)


async def run_test(base_url: str, api_key: str) -> None:
    base_url = base_url.rstrip("/") + "/"
    sse_url = urljoin(base_url, "sse")
    headers = {"X-API-Key": api_key}

    print(f"Connecting to MCP server: {sse_url}")

    async with sse_client(sse_url, headers=headers, timeout=20) as streams:
        async with ClientSession(*streams) as session:
            initialize_result = await session.initialize()
            print(f"Connected: {initialize_result.serverInfo.name}")
            print(f"Protocol: {initialize_result.protocolVersion}")

            tools_result = await session.list_tools()
            tool_names = [tool.name for tool in tools_result.tools]
            print(f"Tools ({len(tool_names)}): {', '.join(tool_names)}")
            expected_tools = {
                "csv_to_json", "json_to_csv", "query_json", "compare_json",
                "timestamp_to_datetime", "datetime_to_timestamp",
                "get_webpage_text", "validate_json_schema", "yaml_to_json",
                "json_to_yaml", "cron_next_runs",
                "read_rss_feed", "extract_webpage_links", "extract_html_tables",
                "summarize_numbers", "diff_text", "convert_units",
                "extract_pdf_text", "get_github_file", "get_github_issue",
                "get_github_pull_request", "list_github_releases", "inspect_openapi",
                "get_npm_package", "check_package_vulnerabilities",
                "list_github_workflow_runs", "query_json_advanced",
                "list_github_workflow_jobs", "inspect_dependency_manifest", "analyze_sql", "compare_versions",
                "compare_lockfiles", "get_vulnerability_details", "apply_json_patch", "analyze_jsonl_logs",
                "check_http_endpoints", "get_github_commit_checks", "inspect_dockerfile", "inspect_http_cache",
                "inspect_docker_compose", "inspect_github_actions", "inspect_redirect_chain", "inspect_http_cors",
                "inspect_fly_config", "compare_env_keys", "inspect_kubernetes_manifest", "inspect_sbom",
                "inspect_junit_report", "inspect_sarif_report", "inspect_prometheus_metrics", "analyze_access_logs",
                "inspect_lcov_report", "inspect_cobertura_report", "inspect_har", "inspect_k6_summary",
                "compare_coverage_reports", "compare_junit_reports", "compare_har_reports", "compare_k6_summaries",
                "inspect_graphql_schema", "validate_graphql_operation", "compare_graphql_schemas", "inspect_postman_collection",
                "compare_docker_compose", "compare_kubernetes_manifests", "compare_github_actions", "compare_fly_configs",
                "profile_csv", "validate_csv_schema", "compare_csv_tables", "redact_csv_columns",
                "inspect_sql_schema", "compare_sql_schemas", "transpile_sql", "extract_sql_lineage",
            }
            missing = expected_tools - set(tool_names)
            if missing:
                raise RuntimeError(f"Deployed tools missing: {', '.join(sorted(missing))}")

            calculate_result = await session.call_tool(
                "calculate",
                {"expression": "sqrt(144) + 8 * 2"},
            )
            print("\ncalculate result:")
            print(_text_from_tool_result(calculate_result))

            json_result = await session.call_tool(
                "format_json",
                {"value": "{\"ok\":true,\"count\":2}", "indent": 2},
            )
            print("\nformat_json result:")
            print(_text_from_tool_result(json_result))

            successful_calls = 2

            async def check(name, arguments, verify):
                nonlocal successful_calls
                result = await session.call_tool(name, arguments)
                text = _text_from_tool_result(result)
                if result.isError or text.startswith("Error:") or not verify(text):
                    raise RuntimeError(f"Tool test failed: {name}: {text}")
                successful_calls += 1
                print(f"PASS {name}: {text[:500]}")
                return text

            if calculate_result.isError or not _text_from_tool_result(calculate_result).endswith("= 28.0"):
                raise RuntimeError("Calculator smoke test failed")
            if json_result.isError or json.loads(_text_from_tool_result(json_result)) != {"ok": True, "count": 2}:
                raise RuntimeError("JSON formatting smoke test failed")

            await check("csv_to_json", {"csv_text": "name,city\nAda,London\n"},
                        lambda text: json.loads(text) == [{"name": "Ada", "city": "London"}])
            await check("json_to_csv", {"value": '[{"name":"Ada","city":"London"}]'},
                        lambda text: text == "name,city\nAda,London\n")
            await check("query_json", {"value": '{"users":[{"name":"Ada"}]}', "pointer": "/users/0/name"},
                        lambda text: json.loads(text) == "Ada")
            await check("compare_json", {"before": '{"count":1}', "after": '{"count":2}'},
                        lambda text: json.loads(text)["differences"] == [
                            {"path": "/count", "type": "changed", "before": 1, "after": 2}])
            await check("timestamp_to_datetime", {"timestamp": 0},
                        lambda text: text == "1970-01-01T00:00:00+00:00")
            await check("datetime_to_timestamp", {"datetime_text": "1970-01-01T00:00:00Z"},
                        lambda text: text == "0")
            await check("get_webpage_text", {"url": "https://example.com", "max_chars": 2000},
                        lambda text: json.loads(text)["title"] == "Example Domain"
                        and "documentation examples" in json.loads(text)["text"])
            schema = '{"type":"object","properties":{"count":{"type":"integer"}},"required":["count"]}'
            await check("validate_json_schema", {"value": '{"count":2}', "schema": schema},
                        lambda text: json.loads(text)["valid"] is True)
            await check("validate_json_schema", {"value": '{"count":"wrong"}', "schema": schema},
                        lambda text: json.loads(text)["valid"] is False)
            await check("yaml_to_json", {"value": "name: Ada\nenabled: true\n"},
                        lambda text: json.loads(text) == {"name": "Ada", "enabled": True})
            await check("json_to_yaml", {"value": '{"name":"Ada","enabled":true}'},
                        lambda text: text == "name: Ada\nenabled: true\n")
            await check("cron_next_runs", {"expression": "*/15 * * * *", "count": 2,
                        "from_datetime": "2026-09-28T00:00:00Z"},
                        lambda text: json.loads(text)["next_runs"] == [
                            "2026-09-28T00:15:00+00:00", "2026-09-28T00:30:00+00:00"])
            await check("extract_webpage_links", {"url": "https://example.com", "limit": 10},
                        lambda text: any("iana.org" in link["url"] for link in json.loads(text)["links"]))
            await check("extract_html_tables", {"url": "https://docs.python.org/3.12/library/statistics.html",
                        "max_tables": 1, "max_rows": 20},
                        lambda text: any("mean" in cell for table in json.loads(text)["tables"]
                                         for row in table["rows"] for cell in row))
            await check("read_rss_feed", {"url": "https://www.djangoproject.com/rss/weblog/", "limit": 2},
                        lambda text: bool(json.loads(text)["title"]) and bool(json.loads(text)["entries"]))
            await check("summarize_numbers", {"values": [1, 2, 3, 4]},
                        lambda text: json.loads(text)["mean"] == 2.5
                        and math.isclose(json.loads(text)["population_stddev"], math.sqrt(1.25)))
            await check("diff_text", {"before": "old\n", "after": "new\n"},
                        lambda text: not json.loads(text)["equal"] and "-old\n+new\n" in json.loads(text)["diff"])
            await check("convert_units", {"value": 36, "from_unit": "kilometer/hour", "to_unit": "meter/second"},
                        lambda text: math.isclose(json.loads(text)["result"], 10))
            await check("convert_units", {"value": 0, "from_unit": "degC", "to_unit": "degF"},
                        lambda text: math.isclose(json.loads(text)["result"], 32))
            await check("extract_pdf_text", {
                "url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
                "max_pages": 1},
                lambda text: "Dummy PDF file" in json.loads(text)["pages"][0]["text"])
            await check("get_github_file", {"owner": "kushalkachari993-dev",
                                            "repo": "mcp-server-fly", "path": "README.md", "max_chars": 1000},
                        lambda text: "MCPSever" in json.loads(text)["content"])
            await check("get_github_issue", {"owner": "pallets", "repo": "flask", "number": 6165},
                        lambda text: json.loads(text)["number"] == 6165)
            await check("get_github_pull_request", {"owner": "pallets", "repo": "flask",
                                                    "number": 6162, "max_files": 2},
                        lambda text: json.loads(text)["number"] == 6162
                        and bool(json.loads(text)["files"]))
            await check("list_github_releases", {"owner": "pallets", "repo": "flask", "limit": 1},
                        lambda text: bool(json.loads(text)["releases"]))
            await check("inspect_openapi", {
                "url": "https://raw.githubusercontent.com/OAI/OpenAPI-Specification/main/_archive_/schemas/v3.0/pass/petstore.yaml",
                "max_operations": 5},
                lambda text: json.loads(text)["title"] == "Swagger Petstore"
                and any(item["path"] == "/pets" for item in json.loads(text)["operations"]))
            await check("get_npm_package", {"name": "@types/node"},
                        lambda text: json.loads(text)["name"] == "@types/node"
                        and bool(json.loads(text)["version"]))
            advisory_text = await check("check_package_vulnerabilities", {
                "ecosystem": "npm", "name": "lodash", "version": "4.17.20", "limit": 3},
                lambda text: bool(json.loads(text)["vulnerabilities"])
                and json.loads(text)["name"] == "lodash")
            workflow_text = await check("list_github_workflow_runs", {"owner": "pallets", "repo": "flask", "limit": 2},
                                        lambda text: bool(json.loads(text)["runs"])
                                        and json.loads(text)["repo"] == "flask")
            await check("query_json_advanced", {
                "value": '{"users":[{"name":"Ada","active":true},{"name":"Bob","active":false}]}',
                "expression": "users[?active].name"},
                lambda text: json.loads(text) == ["Ada"])
            run_id = json.loads(workflow_text)["runs"][0]["id"]
            await check("list_github_workflow_jobs", {
                "owner": "pallets", "repo": "flask", "run_id": run_id, "limit": 2, "max_steps": 3},
                lambda text: json.loads(text)["run_id"] == run_id and isinstance(json.loads(text)["jobs"], list))
            await check("inspect_dependency_manifest", {
                "content": '{"dependencies":{"demo":"^1.0.0"}}', "format": "package.json"},
                lambda text: json.loads(text)["dependencies"][0]["requirement"] == "^1.0.0")
            await check("analyze_sql", {"sql": "SELECT id FROM users", "dialect": "postgres"},
                        lambda text: json.loads(text)["statements"][0]["tables"] == ["users"]
                        and json.loads(text)["statements"][0]["columns"] == ["id"])
            await check("compare_versions", {"first": "1.9.0", "second": "1.10.0", "scheme": "semver"},
                        lambda text: json.loads(text)["comparison"] == -1)
            await check("compare_lockfiles", {
                "before": '{"lockfileVersion":3,"packages":{"node_modules/demo":{"version":"1.0.0"}}}',
                "after": '{"lockfileVersion":3,"packages":{"node_modules/demo":{"version":"2.0.0"}}}',
                "format": "package-lock.json"},
                lambda text: json.loads(text)["counts"]["changed"] == 1
                and json.loads(text)["changes"][0]["after_versions"] == ["2.0.0"])
            advisory_id = json.loads(advisory_text)["vulnerabilities"][0]["id"]
            await check("get_vulnerability_details", {"advisory_id": advisory_id, "max_affected": 2},
                        lambda text: json.loads(text)["id"] == advisory_id and bool(json.loads(text)["affected"]))
            await check("apply_json_patch", {
                "value": '{"enabled":false}',
                "patch": '[{"op":"replace","path":"/enabled","value":true}]'},
                lambda text: json.loads(text) == {"enabled": True})
            await check("analyze_jsonl_logs", {
                "content": '{"level":"error","message":"failed","timestamp":"2026-01-01T12:00:00Z"}\n'},
                lambda text: json.loads(text)["error_count"] == 1 and json.loads(text)["parsed_entries"] == 1)
            await check("check_http_endpoints", {
                "endpoints_json": json.dumps([{"name": "health", "url": urljoin(base_url, "health"), "expected_status": 200}])},
                lambda text: json.loads(text)["all_matched"] and json.loads(text)["endpoints"][0]["http_status"] == 200)
            commit_sha = json.loads(workflow_text)["runs"][0]["sha"]
            await check("get_github_commit_checks", {
                "owner": "pallets", "repo": "flask", "ref": commit_sha, "limit": 3},
                lambda text: json.loads(text)["sha"] == commit_sha
                and isinstance(json.loads(text)["check_runs"]["runs"], list)
                and isinstance(json.loads(text)["legacy_statuses"]["statuses"], list))
            await check("inspect_dockerfile", {
                "content": 'FROM python:3.12-slim AS app\nUSER 1000\nEXPOSE 8000\nCMD ["python", "app.py"]\n'},
                lambda text: json.loads(text)["stage_count"] == 1
                and json.loads(text)["stages"][0]["declared_user"]["value"] == "1000"
                and json.loads(text)["stages"][0]["cmd"]["form"] == "exec")
            await check("inspect_http_cache", {"url": "https://example.com"},
                        lambda text: json.loads(text)["http_status"] == 200
                        and {"browser", "shared"} == set(json.loads(text)["scopes"]))
            await check("inspect_docker_compose", {
                "content": 'services:\n  web:\n    image: nginx:stable\n    ports: ["8080:80"]\n    environment: {MODE: production}\n'},
                lambda text: json.loads(text)["service_count"] == 1
                and json.loads(text)["services"][0]["environment_names"] == ["MODE"])
            await check("inspect_github_actions", {
                "content": 'on: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n'},
                lambda text: [event["name"] for event in json.loads(text)["events"]] == ["push", "pull_request"]
                and json.loads(text)["jobs"][0]["steps"][0]["uses"] == "actions/checkout@v4")
            await check("inspect_redirect_chain", {"url": "https://example.com"},
                        lambda text: json.loads(text)["completed"] and json.loads(text)["http_status"] == 200
                        and bool(json.loads(text)["hops"]))
            await check("inspect_http_cors", {"url": "https://example.com", "origin": "https://app.example"},
                        lambda text: json.loads(text)["origin"] == "https://app.example"
                        and json.loads(text)["get"]["http_status"] == 200
                        and isinstance(json.loads(text)["preflight"]["cors_allows_anonymous"], bool))
            await check("inspect_fly_config", {
                "content": 'app = "demo"\n[http_service]\ninternal_port = 8000\nauto_stop_machines = "stop"\nauto_start_machines = true\n'},
                lambda text: json.loads(text)["app"] == "demo"
                and json.loads(text)["services"][0]["auto_stop_machines"] == "stop")
            await check("compare_env_keys", {
                "template": 'TOKEN=\nPORT=8000\n', "available_keys_json": '["TOKEN"]'},
                lambda text: json.loads(text)["missing"] == ["PORT"]
                and json.loads(text)["matched"] == ["TOKEN"])
            await check("inspect_kubernetes_manifest", {
                "content": 'apiVersion: v1\nkind: Pod\nmetadata: {name: demo}\nspec:\n  containers: [{name: web, image: nginx:stable}]\n'},
                lambda text: json.loads(text)["object_count"] == 1
                and json.loads(text)["objects"][0]["pod"]["containers"][0]["image"] == "nginx:stable")
            await check("inspect_sbom", {
                "content": '{"bomFormat":"CycloneDX","specVersion":"1.7","components":[{"type":"library","name":"demo","version":"1.0.0","bom-ref":"demo"}]}'},
                lambda text: json.loads(text)["component_count"] == 1
                and json.loads(text)["components"][0]["version"] == "1.0.0")
            await check("inspect_junit_report", {
                "content": '<testsuite tests="2"><testcase name="ok" time="0.1"/><testcase name="broken"><failure message="assert failed"/></testcase></testsuite>'},
                lambda text: json.loads(text)["test_count"] == 2
                and json.loads(text)["outcomes"]["failed"] == 1)
            await check("inspect_sarif_report", {
                "content": '{"version":"2.1.0","runs":[{"tool":{"driver":{"name":"demo"}},"results":[{"ruleId":"R1","level":"warning","message":{"text":"reported issue"}}]}]}'},
                lambda text: json.loads(text)["result_count"] == 1
                and json.loads(text)["results"][0]["rule_id"] == "R1"
                and json.loads(text)["reported_level_counts"] == {"warning": 1})
            await check("inspect_prometheus_metrics", {
                "content": '# TYPE requests_total counter\nrequests_total{code="200"} 3\n'},
                lambda text: json.loads(text)["sample_count"] == 1
                and json.loads(text)["families"][0]["samples"][0]["value"] == 3)
            await check("analyze_access_logs", {
                "content": '192.0.2.8 - user [10/Oct/2000:13:55:36 -0700] "GET /health?token=hidden HTTP/1.1" 200 12 "-" "agent"'},
                lambda text: json.loads(text)["parsed_entries"] == 1
                and json.loads(text)["paths"] == [{"method": "GET", "path": "/health", "count": 1}]
                and json.loads(text)["total_reported_bytes"] == 12)
            await check("inspect_lcov_report", {
                "content": 'SF:app.py\nDA:1,2\nDA:2,0\nLF:2\nLH:1\nend_of_record\n'},
                lambda text: json.loads(text)["observed_record_totals"]["lines"]["coverage_percent"] == 50
                and json.loads(text)["files"][0]["uncovered_lines"] == [2])
            await check("inspect_cobertura_report", {
                "content": '<coverage><packages><package name="demo"><classes><class name="App" filename="app.py"><lines><line number="1" hits="2"/><line number="2" hits="0"/></lines></class></classes></package></packages></coverage>'},
                lambda text: json.loads(text)["class_count"] == 1
                and json.loads(text)["observed_class_lines"]["coverage_percent"] == 50)
            await check("inspect_har", {
                "content": '{"log":{"version":"1.2","entries":[{"request":{"method":"GET","url":"https://example.com/health?token=hidden"},"response":{"status":200,"bodySize":12},"time":25,"timings":{"wait":20,"receive":5}}]}}'},
                lambda text: json.loads(text)["entry_count"] == 1
                and json.loads(text)["entries"][0]["target"]["path"] == "/health"
                and json.loads(text)["duration_ms"]["mean"] == 25)
            await check("inspect_k6_summary", {
                "content": '{"metrics":{"http_reqs":{"type":"counter","contains":"default","values":{"count":10,"rate":2},"thresholds":{"count>5":{"ok":true}}}},"state":{"testRunDurationMs":5000}}'},
                lambda text: json.loads(text)["metric_count"] == 1
                and json.loads(text)["duration_seconds"] == 5
                and json.loads(text)["all_reported_thresholds_passed"] is True)
            await check("compare_coverage_reports", {
                "before": 'SF:app.py\nDA:1,1\nend_of_record\n',
                "after": 'SF:app.py\nDA:1,0\nend_of_record\n'},
                lambda text: json.loads(text)["matching"]["matched_count"] == 1
                and json.loads(text)["line_change_counts"]["newly_uncovered_lines"] == 1)
            await check("compare_junit_reports", {
                "before": '<testsuite name="demo"><testcase name="test" classname="App" time="1"/></testsuite>',
                "after": '<testsuite name="demo"><testcase name="test" classname="App" time="2"><failure/></testcase></testsuite>'},
                lambda text: json.loads(text)["newly_failing_count"] == 1
                and json.loads(text)["comparisons"][0]["duration_seconds"]["delta"] == 1)
            await check("compare_har_reports", {
                "before": '{"log":{"version":"1.2","entries":[{"request":{"method":"GET","url":"https://example.com/health"},"response":{"status":200},"time":10}]}}',
                "after": '{"log":{"version":"1.2","entries":[{"request":{"method":"GET","url":"https://example.com/health"},"response":{"status":500},"time":20}]}}'},
                lambda text: json.loads(text)["matching"]["matched_count"] == 1
                and json.loads(text)["comparisons"][0]["duration_ms"]["mean"]["delta"] == 10)
            await check("compare_k6_summaries", {
                "before": '{"metrics":{"latency":{"type":"trend","contains":"time","values":{"p(95)":20},"thresholds":{"p(95)<30":{"ok":true}}}}}',
                "after": '{"metrics":{"latency":{"type":"trend","contains":"time","values":{"p(95)":40},"thresholds":{"p(95)<30":{"ok":false}}}}}'},
                lambda text: json.loads(text)["newly_failing_threshold_count"] == 1
                and json.loads(text)["metric_comparisons"][0]["values"][0]["delta"] == 20)
            await check("inspect_graphql_schema", {"schema_sdl": 'type Query { hello: String }'},
                lambda text: json.loads(text)["operation_roots"]["query"] == "Query"
                and json.loads(text)["field_count"] == 1)
            await check("validate_graphql_operation", {
                "schema_sdl": 'type Query { hello: String }', "document": 'query Get { hello }'},
                lambda text: json.loads(text)["valid"] is True
                and json.loads(text)["operation_count"] == 1)
            await check("compare_graphql_schemas", {
                "before_sdl": 'type Query { old: String }', "after_sdl": 'type Query { hello: String }'},
                lambda text: json.loads(text)["breaking_change_count"] == 1
                and json.loads(text)["breaking_changes"][0]["kind"] == "FIELD_REMOVED")
            await check("inspect_postman_collection", {
                "content": '{"info":{"name":"demo","schema":"https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},"auth":{"type":"bearer"},"item":[{"name":"health","request":{"method":"GET","url":"https://example.com/health?token=hidden"}}]}'},
                lambda text: json.loads(text)["request_count"] == 1
                and json.loads(text)["requests"][0]["target"]["path"] == "/health"
                and json.loads(text)["requests"][0]["effective_declared_auth_type"] == "bearer")
            await check("compare_docker_compose", {
                "before": 'services: {web: {image: "app:1"}}',
                "after": 'services: {web: {image: "app:2"}, worker: {image: "app:2"}}'},
                lambda text: json.loads(text)["changed_count"] == 1
                and json.loads(text)["matching"]["added"] == [{"name": "worker"}])
            await check("compare_kubernetes_manifests", {
                "before": 'apiVersion: v1\nkind: Pod\nmetadata: {name: app}\nspec: {containers: [{name: web, image: "app:1"}]}',
                "after": 'apiVersion: v1\nkind: Pod\nmetadata: {name: app}\nspec: {containers: [{name: web, image: "app:2"}]}'},
                lambda text: json.loads(text)["matching"]["matched_count"] == 1
                and json.loads(text)["changed_count"] == 1)
            await check("compare_github_actions", {
                "before": 'on: push\njobs: {test: {steps: [{uses: "actions/checkout@v4"}]}}',
                "after": 'on: push\njobs: {test: {steps: [{uses: "actions/checkout@v5"}]}}'},
                lambda text: json.loads(text)["changed_count"] == 1
                and json.loads(text)["comparisons"][0]["changes"][0]["path"] == "/steps")
            await check("compare_fly_configs", {
                "before": 'app = "demo"\n[http_service]\ninternal_port = 8000\nauto_stop_machines = "stop"\n',
                "after": 'app = "demo"\n[http_service]\ninternal_port = 8000\nauto_stop_machines = "off"\n'},
                lambda text: json.loads(text)["selected_fields_equal"] is False
                and json.loads(text)["configuration_changes"][0]["path"] == "/services")
            await check("profile_csv", {"csv_text": 'id,note\n001,ok\n001,ok\n002,\n'},
                lambda text: json.loads(text)["row_count"] == 3
                and json.loads(text)["duplicate_row_count"] == 1
                and json.loads(text)["columns"][1]["empty_count"] == 1)
            await check("validate_csv_schema", {
                "csv_text": 'id,code\n001,ok\n002,\n', "required_columns_json": '["id","code"]',
                "schema_json": '{"type":"object","properties":{"code":{"type":"string","minLength":1}}}'},
                lambda text: json.loads(text)["valid"] is False
                and json.loads(text)["invalid_rows"] == [2]
                and json.loads(text)["errors"][0]["keyword"] == "minLength")
            await check("compare_csv_tables", {
                "before": 'id,value\n001,old\n002,same\n', "after": 'id,value\n001,new\n003,added\n',
                "key_columns_json": '["id"]'},
                lambda text: json.loads(text)["changed_row_count"] == 1
                and json.loads(text)["added_row_count"] == 1
                and json.loads(text)["removed_row_count"] == 1)
            await check("redact_csv_columns", {
                "csv_text": 'id,token\n001,private-token\n', "columns_json": '["token"]'},
                lambda text: json.loads(text)["replacement_count"] == 1
                and json.loads(text)["csv"] == 'id,token\r\n001,[REDACTED]\r\n'
                and "private-token" not in text)
            await check("inspect_sql_schema", {"ddl": 'CREATE TABLE users(id INT PRIMARY KEY, name TEXT NOT NULL)'},
                lambda text: json.loads(text)["tables"][0]["primary_key"]["columns"] == ["id"]
                and json.loads(text)["column_count"] == 2)
            await check("compare_sql_schemas", {
                "before": 'CREATE TABLE users(id INT)', "after": 'CREATE TABLE users(id BIGINT)'},
                lambda text: json.loads(text)["counts"]["changed_columns"] == 1
                and json.loads(text)["selected_fields_equal"] is False)
            await check("transpile_sql", {
                "sql": 'SELECT TOP 2 [id] FROM [users]', "source_dialect": "tsql", "target_dialect": "postgres"},
                lambda text: json.loads(text)["statement_count"] == 1
                and "LIMIT 2" in json.loads(text)["statements"][0])
            await check("extract_sql_lineage", {
                "sql": 'WITH recent AS (SELECT id FROM users) SELECT id FROM recent', "column": "id"},
                lambda text: json.loads(text)["column_references_resolved"] is True
                and json.loads(text)["sources"][0]["table"]["identity"] == ["users"]
                and json.loads(text)["sources"][0]["column"] == "id")
            print(f"PASS: {successful_calls} authenticated tool calls returned correct results")


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(description="Test the deployed MCP server.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("MCP_BASE_URL", DEFAULT_BASE_URL),
        help=f"MCP server base URL. Default: {DEFAULT_BASE_URL}",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("MCP_API_KEY"),
        help="MCP API key. Defaults to MCP_API_KEY environment variable.",
    )
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit(
            "Missing API key. Set MCP_API_KEY or pass --api-key your_key."
        )

    asyncio.run(asyncio.wait_for(run_test(args.base_url, args.api_key), timeout=240))


if __name__ == "__main__":
    main()
