import json


def _load_json(value: str):
    return json.loads(value)


def register(mcp):

    @mcp.tool()
    def validate_json(value: str) -> str:
        """
        Validate JSON and report whether it is valid.
        """

        try:
            parsed = _load_json(value)
            return f"Valid JSON. Type: {type(parsed).__name__}"
        except json.JSONDecodeError as e:
            return f"Invalid JSON: line {e.lineno}, column {e.colno}: {e.msg}"

    @mcp.tool()
    def format_json(value: str, indent: int = 2, sort_keys: bool = False) -> str:
        """
        Pretty-print JSON with configurable indentation.
        Use indent=0 to minify.
        """

        if indent < 0 or indent > 8:
            return "Error: indent must be between 0 and 8"

        try:
            parsed = _load_json(value)
            if indent == 0:
                return json.dumps(parsed, separators=(",", ":"), sort_keys=sort_keys)

            return json.dumps(parsed, indent=indent, sort_keys=sort_keys)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: line {e.lineno}, column {e.colno}: {e.msg}"
