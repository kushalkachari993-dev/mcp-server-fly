import json

import anyio
import urllib3

from . import service


def register(mcp):

    @mcp.tool()
    async def get_pypi_package(name: str) -> str:
        """Summarize the latest version, Python requirement, dependencies,
        license, and project links for a public PyPI package. Returns at most
        30 dependencies and 10 links, with a truncation flag. No release
        history is returned; PyPI's response must fit the 1 MB fetch limit.
        """
        try:
            result = await anyio.to_thread.run_sync(service.get_package, name)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"
