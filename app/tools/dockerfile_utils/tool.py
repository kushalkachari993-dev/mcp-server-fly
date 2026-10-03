import json

import anyio

from . import service


def register(mcp):
    @mcp.tool()
    async def inspect_dockerfile(content: str) -> str:
        """Summarize supplied Dockerfile stages, base images, declared users/ports,
        working directories, and startup commands offline using dockerfile-parse.
        Reads text only; never builds, runs, or fetches images. No variable expansion
        or inference of inherited settings. Limits: 200000 input characters, 5000
        physical lines, 1000 instructions, 20 stages, 100 ports/command arguments per stage, 2000 chars
        per value, 100000 output characters. BuildKit heredoc/<< syntax is rejected.
        """
        try:
            result = await anyio.to_thread.run_sync(service.inspect_content, content)
            output = json.dumps(result, indent=2, allow_nan=False)
            if len(output) > 100000:
                raise ValueError("Dockerfile output exceeds 100000 characters; reduce supplied content")
            return output
        except (ValueError, RecursionError, UnicodeError) as error:
            return f"Error: {error}"
