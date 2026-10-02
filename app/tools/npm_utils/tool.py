import json

import anyio
import urllib3

from . import service


def register(mcp):

    @mcp.tool()
    async def get_npm_package(name: str) -> str:
        """Read public npm latest-tag metadata, including scoped packages.
        Returns version, Node requirement, license, repository, deprecation text,
        and up to 30 dependencies and 30 peer dependencies. Does not install code,
        execute scripts, or fetch release history. Download limit: 1 MB.
        """
        try:
            result = await anyio.to_thread.run_sync(service.get_package, name)
            return json.dumps(result, indent=2)
        except (ValueError, RecursionError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"
