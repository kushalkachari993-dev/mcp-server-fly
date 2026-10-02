import anyio

from . import service


def register(mcp):

    @mcp.tool()
    async def query_json_advanced(value: str, expression: str) -> str:
        """Filter, sort, and reshape JSON with JMESPath, e.g. users[?active].name.
        Returns the selected value as JSON (missing fields yield null). No Python,
        shell, file, or network execution. Input: 200000 characters; expression:
        1000 characters; output: 100000 characters. Uses one isolated worker at a
        time with a 3-second timeout; oversized results return an error, not partial JSON.
        """
        try:
            return await anyio.to_thread.run_sync(service.query_json, value, expression)
        except (ValueError, RecursionError, OSError) as error:
            return f"Error: {error}"
