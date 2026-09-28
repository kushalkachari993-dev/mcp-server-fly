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

            async def check(name, arguments, verify):
                result = await session.call_tool(name, arguments)
                text = _text_from_tool_result(result)
                if result.isError or text.startswith("Error:") or not verify(text):
                    raise RuntimeError(f"Tool test failed: {name}: {text}")
                print(f"PASS {name}: {text[:500]}")

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
            print("PASS: 21 authenticated tool calls returned correct results")


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

    asyncio.run(asyncio.wait_for(run_test(args.base_url, args.api_key), timeout=180))


if __name__ == "__main__":
    main()
