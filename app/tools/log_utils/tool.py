import json

import anyio

from . import service


def register(mcp):

    @mcp.tool()
    async def analyze_jsonl_logs(content: str, limit: int = 10, level_field: str = "level",
                                 message_field: str = "message", timestamp_field: str = "timestamp") -> str:
        """Summarize supplied JSON Lines logs offline, using configurable top-level keys.
        Returns level/error counts, frequent exact messages, UTC timestamp range,
        and invalid-line/error samples. Numeric levels and naive/numeric times are
        not inferred. Input: 1000000 characters, 5000 lines; each entry: 200000
        characters, 1000 nodes, 20 nested levels. limit 1-50 bounds samples/message
        groups; totals cover all supplied lines. Output: 100000 characters.
        """
        try:
            result = await anyio.to_thread.run_sync(service.analyze, content, limit, level_field,
                                                   message_field, timestamp_field)
            output = json.dumps(result, indent=2, allow_nan=False)
            if len(output) > 100000:
                raise ValueError("Log analysis output exceeds 100000 characters; reduce limit")
            return output
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"
