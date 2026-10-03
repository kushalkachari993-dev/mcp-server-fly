import json

import anyio
import urllib3

from . import service


def register(mcp):

    @mcp.tool()
    async def check_dependencies_batch(packages_json: str, limit: int = 10) -> str:
        """Check up to 50 exact package versions against OSV in one bounded request.
        packages_json must be a JSON array of objects with ecosystem, name, and
        version fields. Returns advisory IDs and summaries per package. No matches
        do not prove safety, and this does not scan source code or dependency ranges.
        """
        try:
            if not isinstance(packages_json, str) or len(packages_json) > 50000:
                raise ValueError("packages_json must not exceed 50000 characters")
            packages = json.loads(packages_json)
            result = await anyio.to_thread.run_sync(service.check_packages, packages, limit)
            output = json.dumps(result, indent=2)
            if len(output) > 100000:
                raise ValueError("Dependency audit output exceeds 100000 characters; reduce limit")
            return output
        except (ValueError, RecursionError, json.JSONDecodeError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"
