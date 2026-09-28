import json
import math
import re


_MAX_INPUT_CHARS = 200000
_MAX_DIFFS = 100
_MAX_DEPTH = 100


def _load_json(value: str):
    return json.loads(value)


def _reject_constant(value: str):
    raise ValueError(f"Invalid JSON number: {value}")


def _parse_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number is outside the supported range")
    return number


def _load_bounded_json(value: str):
    if len(value) > _MAX_INPUT_CHARS:
        raise ValueError(f"Input must not exceed {_MAX_INPUT_CHARS} characters")
    return json.loads(value, parse_constant=_reject_constant, parse_float=_parse_float)


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _compare_json(before, after) -> dict:
    differences = []
    truncated = False

    def add_difference(path: str, kind: str, **values):
        nonlocal truncated
        if len(differences) == _MAX_DIFFS:
            truncated = True
        else:
            differences.append({"path": path, "type": kind, **values})

    def walk(left, right, path: str, depth: int):
        if truncated:
            return
        if depth > _MAX_DEPTH:
            raise ValueError(f"JSON comparison must not exceed {_MAX_DEPTH} nested levels")
        if isinstance(left, dict) and isinstance(right, dict):
            for key in left:
                child_path = path + "/" + _pointer_token(key)
                if key not in right:
                    add_difference(child_path, "removed", before=left[key])
                else:
                    walk(left[key], right[key], child_path, depth + 1)
            for key in right:
                if key not in left:
                    add_difference(path + "/" + _pointer_token(key), "added", after=right[key])
        elif isinstance(left, list) and isinstance(right, list):
            for index in range(max(len(left), len(right))):
                child_path = path + "/" + str(index)
                if index >= len(left):
                    add_difference(child_path, "added", after=right[index])
                elif index >= len(right):
                    add_difference(child_path, "removed", before=left[index])
                else:
                    walk(left[index], right[index], child_path, depth + 1)
        else:
            numbers = type(left) in (int, float) and type(right) in (int, float)
            if left != right or (type(left) is not type(right) and not numbers):
                add_difference(path, "changed", before=left, after=right)

    walk(before, after, "", 0)
    return {"equal": not differences, "differences": differences, "truncated": truncated}


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
    def query_json(value: str, pointer: str = "") -> str:
        """Extract a JSON value using an RFC 6901 JSON Pointer, e.g. /users/0/name.
        An empty pointer returns the entire document. Use ~1 for / and ~0 for ~ in
        object keys. Array indices start at zero. Returns the selected value as JSON.
        """
        try:
            selected = _load_bounded_json(value)
            if pointer and not pointer.startswith("/"):
                raise ValueError("Pointer must be empty or start with /")
            for token in pointer.split("/")[1:] if pointer else []:
                if re.search(r"~(?:[^01]|$)", token):
                    raise ValueError("Pointer escapes must be ~0 or ~1")
                token = token.replace("~1", "/").replace("~0", "~")
                if isinstance(selected, dict):
                    if token not in selected:
                        raise ValueError("Pointer refers to a missing object key")
                    selected = selected[token]
                elif isinstance(selected, list):
                    if not re.fullmatch(r"0|[1-9][0-9]*", token):
                        raise ValueError("Array index must be a nonnegative integer without leading zeros")
                    if len(token) > 10 or int(token) >= len(selected):
                        raise ValueError("Array index is out of range")
                    selected = selected[int(token)]
                else:
                    raise ValueError("Pointer cannot traverse a scalar value")
            return json.dumps(selected, indent=2)
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"

    @mcp.tool()
    def compare_json(before: str, after: str) -> str:
        """Compare two JSON documents and return added, removed, and changed values.
        Paths use JSON Pointer syntax. Object key order is ignored, but array order
        matters. Reports at most 100 differences with a truncated flag.
        """
        try:
            result = _compare_json(_load_bounded_json(before), _load_bounded_json(after))
            return json.dumps(result, indent=2)
        except (ValueError, RecursionError) as error:
            return f"Error: {error}"

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
