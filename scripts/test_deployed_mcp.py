import argparse
import asyncio
import os
from urllib.parse import urljoin

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


def main() -> None:
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

    asyncio.run(run_test(args.base_url, args.api_key))


if __name__ == "__main__":
    main()
