import json

import anyio

from app.tools.json_utils.tool import _load_bounded_json

from .service import validate_schema


def register(mcp):

    @mcp.tool()
    async def validate_json_schema(value: str, schema: str) -> str:
        """Validate JSON against a JSON Schema, returning valid, errors, and truncated.
        Supports known schema drafts (default: 2020-12), local $ref definitions,
        and format checks. Remote $ref retrieval is disabled. Each input is limited
        to 200000 characters; validation has a 3-second timeout and reports at most
        50 errors. Unknown formats are not checked.
        """
        try:
            instance = _load_bounded_json(value)
            parsed_schema = _load_bounded_json(schema)
            if not isinstance(parsed_schema, (dict, bool)):
                raise ValueError("Schema must be a JSON object or boolean")
            result = await anyio.to_thread.run_sync(validate_schema, instance, parsed_schema)
            return json.dumps(result, indent=2)
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"
