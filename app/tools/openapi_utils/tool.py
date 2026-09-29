import json
from functools import partial

import anyio
import urllib3

from app.tools.webpage.service import fetch_page

from .service import _SPEC_TYPES, inspect_spec


def register(mcp):

    @mcp.tool()
    async def inspect_openapi(url: str, max_operations: int = 100) -> str:
        """Inspect an OpenAPI 3.x JSON/YAML description at a public URL.
        Lists title, version, servers, methods, paths, tags, and declared security
        schemes. Supports up to 200 operations; external/local $refs are not
        dereferenced. Download capped at 1 MB and parsed input at 200000 chars.
        """
        try:
            if not 1 <= max_operations <= 200:
                raise ValueError("max_operations must be between 1 and 200")
            body, _, final_url = await anyio.to_thread.run_sync(partial(fetch_page, url, media_types=_SPEC_TYPES))
            result = await anyio.to_thread.run_sync(inspect_spec, body, final_url, max_operations)
            return json.dumps(result, indent=2)
        except (ValueError, urllib3.exceptions.HTTPError, OSError) as error:
            return f"Error: {error}"
