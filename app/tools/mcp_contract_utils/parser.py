import json
import re

from app.tools.json_query.service import _check_tree
from app.tools.manifest_utils.service import _unique_object


VERSIONS = {"2025-11-25", "2026-07-28"}
NAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
MAX_TOOLS = 500


def protocol_version(value):
    if not isinstance(value, str) or value not in VERSIONS:
        raise ValueError("protocol_version must be 2025-11-25 or 2026-07-28")
    return value


def json_value(content, label):
    if not isinstance(content, str) or not content.strip() or len(content) > 200000:
        raise ValueError(f"{label} must be nonempty JSON text of at most 200000 characters")
    try:
        value = json.loads(content, object_pairs_hook=_unique_object)
        _check_tree(value, max_nodes=20000, max_depth=50)
        return value
    except (ValueError, RecursionError) as error:
        raise ValueError(f"Invalid or oversized {label}; duplicate keys and non-finite numbers are rejected") from error


def name(value):
    if (not isinstance(value, str) or not value or len(value) > 1000
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("MCP tool names must be nonempty text of at most 1000 characters without controls")
    return value


def _schema_shape(schema, label):
    if not isinstance(schema, dict):
        raise ValueError(f"{label} must be a JSON Schema object")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or len(properties) > 500:
        raise ValueError(f"{label} properties must be an object with at most 500 entries")
    if (not isinstance(required, list) or len(required) > 500
            or any(not isinstance(item, str) for item in required)):
        raise ValueError(f"{label} required must be an array of at most 500 names")
    return properties, required


def manifest(content, version):
    protocol_version(version)
    value = json_value(content, "MCP tools/list snapshot")
    if not isinstance(value, dict):
        raise ValueError("MCP tools/list snapshot must be an object")
    if value.get("jsonrpc") == "2.0" and "error" in value:
        raise ValueError("Supply a successful MCP tools/list response")
    if value.get("jsonrpc") == "2.0" and "result" in value:
        value = value["result"]
    if not isinstance(value, dict):
        raise ValueError("MCP tools/list result must be an object")
    if "resultType" in value and value["resultType"] != "complete":
        raise ValueError("MCP tools/list result is not complete")
    tools = value.get("tools")
    if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
        raise ValueError("MCP tools/list must contain an array of at most 500 tools")
    cursor = value.get("nextCursor")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 1000):
        raise ValueError("MCP nextCursor must be a string of at most 1000 characters when present")
    rows = {}
    for raw in tools:
        if not isinstance(raw, dict):
            raise ValueError("MCP tool entries must be objects")
        tool_name = name(raw.get("name"))
        if tool_name in rows:
            raise ValueError("Duplicate MCP tool names are not supported")
        _schema_shape(raw.get("inputSchema"), "MCP inputSchema")
        if "outputSchema" in raw:
            _schema_shape(raw["outputSchema"], "MCP outputSchema")
        for key in ("description", "title"):
            if key in raw and not isinstance(raw[key], str):
                raise ValueError(f"MCP {key} must be text when present")
        if "annotations" in raw and not isinstance(raw["annotations"], dict):
            raise ValueError("MCP annotations must be an object")
        if "execution" in raw and not isinstance(raw["execution"], dict):
            raise ValueError("MCP execution must be an object")
        rows[tool_name] = raw
    return rows, cursor is not None


def result(content):
    value = json_value(content, "MCP tool result")
    if not isinstance(value, dict):
        raise ValueError("MCP tool result must be an object")
    if value.get("jsonrpc") == "2.0" and "error" in value:
        raise ValueError("Supply a successful MCP tool result")
    if value.get("jsonrpc") == "2.0" and "result" in value:
        value = value["result"]
    if not isinstance(value, dict):
        raise ValueError("MCP tool result must contain an object")
    if "isError" in value and type(value["isError"]) is not bool:
        raise ValueError("MCP result isError must be a boolean")
    return value
