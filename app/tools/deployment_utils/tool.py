import json

import anyio

from . import service


async def _run(function, *arguments):
    try:
        result = await anyio.to_thread.run_sync(function, *arguments)
        output = json.dumps(result, indent=2, allow_nan=False)
        if len(output) > 100000:
            raise ValueError("Deployment summary exceeds 100000 characters; reduce input/limit")
        return output
    except (ValueError, RecursionError) as error:
        return f"Error: {error}"


def register(mcp):
    @mcp.tool()
    async def inspect_fly_config(content: str) -> str:
        """Inspect supplied fly.toml services, ports, checks, VM declarations and
        autostart/autostop settings offline. Omits environment/header/build-arg
        values and commands. No file/network access, deployment, live-state or
        cost lookup. Not full Fly validation; defaults/CLI overrides not applied.
        Bounds: 200000 chars, 10000 nodes, 50 nesting levels, 100 entries per
        collection, selected strings 2000 chars; output 100000 chars.
        """
        return await _run(service.inspect_fly, content)

    @mcp.tool()
    async def compare_env_keys(template: str, available_keys_json: str) -> str:
        """Compare dotenv template key names against a JSON array of available
        names, never actual deployed values. Reports missing/unexpected/matched
        keys and duplicates, case-sensitively. No interpolation, value validation,
        required/optional inference, file access or server environment access.
        Values are omitted. Bounds: 200000 chars per input, 1000 declarations/
        available entries, ASCII key names 200 chars, output 100000 chars.
        """
        return await _run(service.compare_environment, template, available_keys_json)

    @mcp.tool()
    async def inspect_kubernetes_manifest(content: str, limit: int = 20) -> str:
        """Inspect supplied Kubernetes YAML/JSON, multi-documents or one-level
        Lists. Summarize common workloads, images, replicas, Services, declared
        resource quantities, probes and Secret/ConfigMap references. Secret,
        environment and command values are omitted. Other kinds: metadata only.
        No cluster/file/network access, rendering or execution; not full validation.
        Bounds: 200000 chars, 100 documents/objects, 10000 expanded nodes, 50
        nesting levels, 200 containers, limit 1-50 objects, output 100000 chars.
        """
        return await _run(service.inspect_kubernetes, content, limit)
