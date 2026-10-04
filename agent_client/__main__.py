"""Command-line entry point for the client-side agents."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .profiles import PROFILES
from .runner import AgentClientError, DEFAULT_BASE_URL, MAX_TASK_CHARS, run_agent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an agent using the deployed MCP server")
    parser.add_argument("agent", nargs="?", choices=sorted(PROFILES))
    parser.add_argument("--list", action="store_true", help="list the available agents")
    task_input = parser.add_mutually_exclusive_group()
    task_input.add_argument("--task", help="task text (avoid credentials and private data)")
    task_input.add_argument("--task-file", type=Path, help="UTF-8 task file")
    parser.add_argument("--model", help="OpenAI model name (or set OPENAI_MODEL)")
    parser.add_argument("--base-url", help="MCP server origin (or set MCP_BASE_URL)")
    parser.add_argument("--transport", choices=("sse", "streamable-http"), default="sse",
                        help="Use streamable-http after deploying the /mcp endpoint.")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser


def read_task(args: argparse.Namespace) -> str:
    if args.task is not None:
        return args.task
    if args.task_file is None:
        raise AgentClientError("Provide --task or --task-file.")
    if args.task_file.stat().st_size > MAX_TASK_CHARS * 4:
        raise AgentClientError(f"Task file is too large (max {MAX_TASK_CHARS:,} characters).")
    return args.task_file.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list:
        for profile in PROFILES.values():
            print(f"{profile.slug}: {profile.description} ({len(profile.tools)} tools)")
        return 0
    if args.agent is None:
        parser.error("choose an agent or use --list")

    load_dotenv()
    try:
        if not os.getenv("OPENAI_API_KEY"):
            raise AgentClientError("Set OPENAI_API_KEY in the environment or .env file.")
        task = read_task(args)
        output = asyncio.run(
            run_agent(
                args.agent,
                task,
                model=args.model or os.getenv("OPENAI_MODEL", ""),
                mcp_api_key=os.getenv("MCP_API_KEY", ""),
                base_url=args.base_url or os.getenv("MCP_BASE_URL", DEFAULT_BASE_URL),
                transport=args.transport,
                max_turns=args.max_turns,
                timeout_seconds=args.timeout_seconds,
            )
        )
    except AgentClientError as exc:
        print(f"Agent error: {exc}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError) as exc:
        print(f"Agent error: could not read task file ({type(exc).__name__}).", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"Agent run failed ({type(exc).__name__}). Check MCP connectivity, OpenAI credentials, "
            "model access, and deployed tool versions.",
            file=sys.stderr,
        )
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
