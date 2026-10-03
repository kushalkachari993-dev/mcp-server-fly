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
