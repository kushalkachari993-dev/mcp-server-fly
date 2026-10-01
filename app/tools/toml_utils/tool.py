import json
import math
import tomllib
from datetime import date, datetime, time


_MAX_INPUT = 200000
_MAX_OUTPUT = 200000
_MAX_NODES = 10000
_MAX_DEPTH = 100


def _json_compatible(value):
    count = 0

    def convert(item, depth):
        nonlocal count
        count += 1
        if count > _MAX_NODES or depth > _MAX_DEPTH:
            raise ValueError("TOML exceeds the supported size or nesting depth")
        if isinstance(item, dict):
            return {key: convert(child, depth + 1) for key, child in item.items()}
        if isinstance(item, list):
            return [convert(child, depth + 1) for child in item]
        if isinstance(item, (datetime, date, time)):
            return item.isoformat()
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("TOML non-finite numbers cannot be represented in JSON")
        return item

    return convert(value, 0)


def register(mcp):

    @mcp.tool()
    def toml_to_json(value: str) -> str:
        """Parse a TOML document into JSON. Dates and times become ISO strings;
        non-finite numbers are rejected. Input and output are capped at 200000
        characters, with at most 10000 values and 100 nesting levels.
        """
        try:
            if len(value) > _MAX_INPUT:
                raise ValueError("TOML input must not exceed 200000 characters")
            parsed = _json_compatible(tomllib.loads(value))
            output = json.dumps(parsed, indent=2, allow_nan=False)
            if len(output) > _MAX_OUTPUT:
                raise ValueError("JSON output exceeds 200000 characters")
            return output
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"
