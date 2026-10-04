import asyncio
import contextlib
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from agent_client import PROFILES
from agent_client.__main__ import main
from agent_client.runner import AgentClientError, mcp_url, run_agent, sse_url
from app.tools.registry import register_all_tools


class AgentProfileTests(unittest.TestCase):
    def test_each_profile_uses_registered_tools_only(self):
        mcp = FastMCP("agent-profile-tests")
        with contextlib.redirect_stdout(io.StringIO()):
            register_all_tools(mcp)
        registered = {tool.name for tool in asyncio.run(mcp.list_tools())}

        self.assertEqual(len(PROFILES), 4)
        for profile in PROFILES.values():
            with self.subTest(profile=profile.slug):
                self.assertEqual(len(profile.tools), len(set(profile.tools)))
                self.assertTrue(set(profile.tools) <= registered)
                self.assertNotIn("http_request", profile.tools)

    def test_url_requires_plain_secure_origin(self):
        self.assertEqual(sse_url("https://mcpsever.fly.dev/"), "https://mcpsever.fly.dev/sse")
        self.assertEqual(sse_url("http://127.0.0.1:8000"), "http://127.0.0.1:8000/sse")
        self.assertEqual(mcp_url("https://mcpsever.fly.dev/", "streamable-http"),
                         "https://mcpsever.fly.dev/mcp")
        for value in (
            "http://example.com",
            "https://user:pass@example.com",
            "https://example.com/mcp",
            "https://example.com/?key=secret",
            "https://example.com:bad",
            "https:///missing-host",
        ):
            with self.subTest(value=value), self.assertRaises(AgentClientError):
                sse_url(value)


class AgentRunnerTests(unittest.IsolatedAsyncioTestCase):
    def fake_sdk(self, *, available=None, list_error=None):
        calls = {}
        names = set(available or PROFILES["research-briefing"].tools)

        class FakeServer:
            def __init__(self, **kwargs):
                calls["server_kwargs"] = kwargs
                self.closed = False
                calls["server"] = self

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                self.closed = True

            async def list_tools(self):
                if list_error:
                    raise list_error
                return [types.SimpleNamespace(name=name) for name in names]

        class FakeAgent:
            def __init__(self, **kwargs):
                calls["agent_kwargs"] = kwargs

        class FakeRunConfig:
            def __init__(self, **kwargs):
                calls["run_config"] = kwargs

        class FakeRunner:
            @classmethod
            async def run(cls, agent, task, **kwargs):
                calls["run"] = (agent, task, kwargs)
                return types.SimpleNamespace(final_output="Verified answer")

        agents = types.ModuleType("agents")
        agents.Agent = FakeAgent
        agents.RunConfig = FakeRunConfig
        agents.Runner = FakeRunner
        agents_mcp = types.ModuleType("agents.mcp")
        agents_mcp.MCPServerSse = FakeServer
        agents_mcp.MCPServerStreamableHttp = FakeServer
        agents_mcp.create_static_tool_filter = lambda **kwargs: kwargs
        return calls, {"agents": agents, "agents.mcp": agents_mcp}

    async def test_runner_filters_tools_and_disables_tracing(self):
        calls, modules = self.fake_sdk()
        with patch.dict(sys.modules, modules):
            output = await run_agent(
                "research-briefing",
                "Research release notes",
                model="test-model",
                mcp_api_key="server-secret",
            )
        self.assertEqual(output, "Verified answer")
        self.assertTrue(calls["server"].closed)
        self.assertEqual(calls["server_kwargs"]["params"]["url"], "https://mcpsever.fly.dev/sse")
        self.assertEqual(calls["server_kwargs"]["params"]["headers"], {"X-API-Key": "server-secret"})
        self.assertEqual(
            set(calls["server_kwargs"]["tool_filter"]["allowed_tool_names"]),
            set(PROFILES["research-briefing"].tools),
        )
        self.assertEqual(calls["agent_kwargs"]["mcp_servers"], [calls["server"]])
        self.assertEqual(calls["run"][2]["max_turns"], 8)
        self.assertEqual(calls["run_config"], {"tracing_disabled": True})

    async def test_runner_can_use_streamable_http(self):
        calls, modules = self.fake_sdk()
        with patch.dict(sys.modules, modules):
            output = await run_agent("research-briefing", "Research release notes",
                                     model="test-model", mcp_api_key="server-secret",
                                     transport="streamable-http")
        self.assertEqual(output, "Verified answer")
        self.assertEqual(calls["server_kwargs"]["params"]["url"], "https://mcpsever.fly.dev/mcp")

    async def test_missing_deployed_tools_fail_before_model_call(self):
        calls, modules = self.fake_sdk(available={"tavily_search"})
        with patch.dict(sys.modules, modules), self.assertRaisesRegex(AgentClientError, "missing tools"):
            await run_agent("research-briefing", "Research a topic", model="test-model", mcp_api_key="key")
        self.assertTrue(calls["server"].closed)
        self.assertNotIn("run", calls)

    async def test_timeout_becomes_actionable_error(self):
        calls, modules = self.fake_sdk(list_error=TimeoutError())
        with patch.dict(sys.modules, modules), self.assertRaisesRegex(AgentClientError, "timed out"):
            await run_agent("research-briefing", "Research a topic", model="test-model", mcp_api_key="key")
        self.assertTrue(calls["server"].closed)

    async def test_validation_happens_without_sdk_or_network(self):
        with self.assertRaisesRegex(AgentClientError, "max_turns"):
            await run_agent("research-briefing", "task", model="test-model", mcp_api_key="key", max_turns=0)
        with self.assertRaisesRegex(AgentClientError, "MCP_API_KEY"):
            await run_agent("research-briefing", "task", model="test-model", mcp_api_key="")
        with self.assertRaisesRegex(AgentClientError, "HTTPS"):
            await run_agent(
                "research-briefing", "task", model="test-model", mcp_api_key="key",
                base_url="http://public.example.com",
            )


class AgentCliTests(unittest.TestCase):
    def test_list_does_not_need_secrets(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), contextlib.redirect_stdout(output):
            self.assertEqual(main(["--list"]), 0)
        self.assertIn("release-readiness", output.getvalue())
        self.assertIn("research-briefing", output.getvalue())

    def test_missing_openai_key_is_clear(self):
        error = io.StringIO()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), contextlib.redirect_stderr(error):
            self.assertEqual(main(["research-briefing", "--task", "Test"]), 1)
        self.assertIn("OPENAI_API_KEY", error.getvalue())

    def test_task_file_runs_with_environment_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            task_file = Path(directory) / "task.txt"
            task_file.write_text("Research the release", encoding="utf-8")
            output = io.StringIO()
            env = {"OPENAI_API_KEY": "openai-secret", "MCP_API_KEY": "mcp-secret", "OPENAI_MODEL": "test-model"}
            with patch.dict(os.environ, env), patch("agent_client.__main__.load_dotenv"), patch(
                "agent_client.__main__.run_agent", return_value="Mock brief"
            ) as mocked, contextlib.redirect_stdout(output):
                self.assertEqual(main(["research-briefing", "--task-file", str(task_file)]), 0)
            self.assertEqual(mocked.call_args.args, ("research-briefing", "Research the release"))
            self.assertEqual(mocked.call_args.kwargs["mcp_api_key"], "mcp-secret")
            self.assertEqual(output.getvalue().strip(), "Mock brief")
