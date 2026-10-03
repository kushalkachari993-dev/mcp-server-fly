"""Run one specialist agent against the existing authenticated SSE server."""

import asyncio
from urllib.parse import urlsplit

from .profiles import PROFILES


DEFAULT_BASE_URL = "https://mcpsever.fly.dev"
MAX_TASK_CHARS = 50_000


class AgentClientError(Exception):
    """An expected, user-actionable client failure."""


def sse_url(base_url: str) -> str:
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as exc:
        raise AgentClientError("Invalid MCP base URL.") from exc

    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not (parsed.scheme == "https" or local_http):
        raise AgentClientError("MCP base URL must use HTTPS, except for localhost.")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AgentClientError("MCP base URL must be a plain origin without credentials or query.")
    if parsed.path not in {"", "/"}:
        raise AgentClientError("MCP base URL must be the server origin, without a path.")
    if port is not None and not 1 <= port <= 65535:
        raise AgentClientError("Invalid MCP base URL port.")
    return base_url.rstrip("/") + "/sse"


async def run_agent(
    slug: str,
    task: str,
    *,
    model: str,
    mcp_api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    max_turns: int = 8,
    timeout_seconds: int = 180,
) -> str:
    """Run one bounded agent turn; the OpenAI API key comes from the environment."""
    if slug not in PROFILES:
        raise AgentClientError(f"Unknown agent: {slug}.")
    if not task.strip() or len(task) > MAX_TASK_CHARS:
        raise AgentClientError(f"Task must contain 1-{MAX_TASK_CHARS:,} characters.")
    if not model.strip():
        raise AgentClientError("Set --model or OPENAI_MODEL.")
    if not mcp_api_key:
        raise AgentClientError("Set MCP_API_KEY in the environment or .env file.")
    if not 1 <= max_turns <= 20:
        raise AgentClientError("max_turns must be between 1 and 20.")
    if not 30 <= timeout_seconds <= 900:
        raise AgentClientError("timeout_seconds must be between 30 and 900.")

    url = sse_url(base_url)
    try:
        from agents import Agent, RunConfig, Runner
        from agents.mcp import MCPServerSse, create_static_tool_filter
    except ImportError as exc:
        raise AgentClientError("Install the client dependencies: uv sync --project client") from exc

    profile = PROFILES[slug]
    server = MCPServerSse(
        params={
            "url": url,
            "headers": {"X-API-Key": mcp_api_key},
            "timeout": 30,
            "sse_read_timeout": timeout_seconds,
        },
        name="deployed-mcp",
        cache_tools_list=True,
        client_session_timeout_seconds=30,
        tool_filter=create_static_tool_filter(allowed_tool_names=list(profile.tools)),
    )

    try:
        async with asyncio.timeout(timeout_seconds):
            async with server:
                available = {tool.name for tool in await server.list_tools()}
                missing = sorted(set(profile.tools) - available)
                if missing:
                    raise AgentClientError(
                        "The MCP server is missing tools for this agent: " + ", ".join(missing)
                    )

                agent = Agent(
                    name=profile.name,
                    instructions=profile.instructions,
                    model=model,
                    mcp_servers=[server],
                )
                result = await Runner.run(
                    agent,
                    task,
                    max_turns=max_turns,
                    run_config=RunConfig(tracing_disabled=True),
                )
                if not isinstance(result.final_output, str) or not result.final_output.strip():
                    raise AgentClientError("The agent did not return a text answer.")
                return result.final_output
    except TimeoutError as exc:
        raise AgentClientError(f"Agent run timed out after {timeout_seconds} seconds.") from exc
