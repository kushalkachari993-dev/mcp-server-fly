import json
import math

import yaml

from app.tools.json_utils.tool import _load_bounded_json


_MAX_CHARS = 200000
_MAX_NODES = 10000
_MAX_DEPTH = 100


class _JsonSafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        keys = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError("YAML mapping keys must be strings")
            if key in keys:
                raise ValueError(f"Duplicate YAML key: {key}")
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


_JsonSafeLoader.add_constructor(
    "tag:yaml.org,2002:timestamp", lambda loader, node: loader.construct_scalar(node)
)


def _json_compatible(value):
    active = set()
    nodes = 0

    def visit(item, depth):
        nonlocal nodes
        nodes += 1
        if nodes > _MAX_NODES or depth > _MAX_DEPTH:
            raise ValueError("Data exceeds the 10000-node or 100-level nesting limit")
        if isinstance(item, (list, dict)):
            identity = id(item)
            if identity in active:
                raise ValueError("Recursive YAML aliases cannot be converted to JSON")
            active.add(identity)
            try:
                if isinstance(item, list):
                    return [visit(child, depth + 1) for child in item]
                if any(not isinstance(key, str) for key in item):
                    raise ValueError("Mapping keys must be strings")
                return {key: visit(child, depth + 1) for key, child in item.items()}
            finally:
                active.remove(identity)
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Non-finite numbers cannot be converted")
        if item is None or isinstance(item, (str, bool, int, float)):
            return item
        raise ValueError("Only JSON-compatible YAML values are supported")

    return visit(value, 0)


def _bounded_output(value: str) -> str:
    if len(value) > _MAX_CHARS:
        raise ValueError("Converted output exceeds 200000 characters")
    return value


def register(mcp):

    @mcp.tool()
    def yaml_to_json(value: str) -> str:
        """Convert one YAML document to JSON using safe loading.
        Preserves dates as strings. Rejects duplicate/non-string keys, recursive
        aliases, and non-JSON types. Uses YAML 1.1 boolean rules (e.g. yes is true).
        Input and output are limited to 200000 characters.
        """
        try:
            if len(value) > _MAX_CHARS:
                raise ValueError("Input must not exceed 200000 characters")
            parsed = yaml.load(value, Loader=_JsonSafeLoader)
            return _bounded_output(json.dumps(_json_compatible(parsed), indent=2))
        except (ValueError, yaml.YAMLError, RecursionError) as error:
            return f"Error: {error}"

    @mcp.tool()
    def json_to_yaml(value: str) -> str:
        """Convert JSON to YAML, preserving object key order.
        Input and output are limited to 200000 characters, 10000 nodes, and
        100 nested levels. Output uses safe YAML tags only.
        """
        try:
            parsed = _json_compatible(_load_bounded_json(value))
            return _bounded_output(yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True))
        except (ValueError, yaml.YAMLError, RecursionError) as error:
            return f"Error: {error}"
