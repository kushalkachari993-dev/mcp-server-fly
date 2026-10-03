import json

import anyio
import urllib3

from . import service


def register(mcp):

    @mcp.tool()
    async def inspect_lockfile(content: str, format: str, limit: int = 100) -> str:
        """Inspect supplied package-lock.json v2/v3 or pylock.toml text offline.
        Lists resolved package versions and bounded package metadata. It does not
        install packages, read local files, resolve dependencies, or validate the
        full lockfile. Input is limited to 2 MB and 1-500 returned packages.
        """
        try:
            result = await anyio.to_thread.run_sync(service.inspect_lockfile, content, format, limit)
            output = json.dumps(result, indent=2)
            if len(output) > 100000:
                raise ValueError("Lockfile output exceeds 100000 characters; reduce limit")
            return output
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"

    @mcp.tool()
    async def compare_lockfiles(before: str, after: str, format: str, limit: int = 100) -> str:
        """Compare supplied package-lock.json v2/v3 or pylock.toml versions offline.
        Reports added, removed, and changed packages with full change counts. npm
        packages are matched by path and name; normalized Python names group all
        recorded versions. Ignores sources, markers, hashes, and metadata. Each
        input: 2000000 characters. Returns 1-200 changes; output: 100000 characters.
        Unresolved records make complete false; equal refers to resolved versions.
        """
        try:
            result = await anyio.to_thread.run_sync(service.compare_lockfiles, before, after, format, limit)
            output = json.dumps(result, indent=2, allow_nan=False)
            if len(output) > 100000:
                raise ValueError("Lockfile comparison output exceeds 100000 characters; reduce limit")
            return output
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"
