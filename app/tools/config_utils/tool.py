import json

import anyio

from . import service


def register(mcp):
    @mcp.tool()
    async def inspect_docker_compose(content: str, limit: int = 20) -> str:
        """Summarize supplied Compose YAML services, images/build paths, ports,
        dependencies, environment names, and health-check declarations offline.
        No variable/include/extends resolution, image access, or execution.
        Environment values and command bodies are omitted. Limits: 200000 input
        characters, 10000 expanded YAML nodes, 50 nesting levels, 100 services,
        limit 1-50 returned services, 100000 output characters. Not full validation.
        """
        try:
            result = await anyio.to_thread.run_sync(service.inspect_compose, content, limit)
            output = json.dumps(result, indent=2, allow_nan=False)
            if len(output) > 100000:
                raise ValueError("Compose output exceeds 100000 characters; reduce limit/content")
            return output
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def inspect_github_actions(content: str, limit: int = 20, max_steps: int = 20) -> str:
        """Summarize supplied GitHub Actions YAML events, declared permissions,
        runners, job dependencies, matrix axis names, and action references offline.
        Preserves on/yes/no as text; only true/false are implicit booleans. No
        execution, expression expansion, or reusable-workflow access. Environment
        values, run bodies, with arguments, and secret values are omitted.
        Bounds: 200000 chars, 10000 expanded YAML nodes, 50 nesting levels, 100 jobs,
        1000 steps; limit/max_steps 1-50; output 100000 chars. Not full validation.
        """
        try:
            result = await anyio.to_thread.run_sync(service.inspect_actions, content, limit, max_steps)
            output = json.dumps(result, indent=2, allow_nan=False)
            if len(output) > 100000:
                raise ValueError("Workflow output exceeds 100000 characters; reduce limit/max_steps/content")
            return output
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"
