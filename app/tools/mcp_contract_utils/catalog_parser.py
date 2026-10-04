import re

from . import parser


_MAX_ENTRIES = 500
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*\Z")


def _text(value, label, maximum=1000):
    if (not isinstance(value, str) or not value or len(value) > maximum
            or any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF
                   for char in value)):
        raise ValueError(f"MCP {label} must be nonempty text of at most {maximum} characters without controls")
    return value


def _optional_text(raw, key, label, maximum=1000):
    if key in raw:
        value = raw[key]
        if (not isinstance(value, str) or len(value) > maximum
                or any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF
                       for char in value)):
            raise ValueError(f"MCP {label} must be text of at most {maximum} characters without controls")


def _list_result(content, field, label, protocol_version):
    parser.protocol_version(protocol_version)
    value = parser.json_value(content, label)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if value.get("jsonrpc") == "2.0" and "error" in value:
        raise ValueError(f"Supply a successful {label} response")
    if value.get("jsonrpc") == "2.0" and "result" in value:
        value = value["result"]
    if not isinstance(value, dict) or value.get("resultType", "complete") != "complete":
        raise ValueError(f"{label} result must be a complete list response")
    entries = value.get(field)
    if not isinstance(entries, list) or len(entries) > _MAX_ENTRIES:
        raise ValueError(f"{label} must contain an array of at most 500 entries")
    cursor = value.get("nextCursor")
    if cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 1000):
        raise ValueError("MCP nextCursor must be a nonempty string when present")
    return entries, cursor is not None


def _resource_rows(content, field, identity_key, label, protocol_version):
    entries, partial = _list_result(content, field, label, protocol_version)
    rows = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError(f"{label} entries must be objects")
        identity = _text(raw.get(identity_key), identity_key, 10000)
        _text(raw.get("name"), "resource name")
        for key in ("title", "description"):
            _optional_text(raw, key, key, 10000)
        _optional_text(raw, "mimeType", "mimeType", 1000)
        if "size" in raw and (type(raw["size"]) is not int or raw["size"] < 0):
            raise ValueError("MCP resource size must be a nonnegative integer")
        if "annotations" in raw and not isinstance(raw["annotations"], dict):
            raise ValueError("MCP resource annotations must be an object")
        if "icons" in raw and (not isinstance(raw["icons"], list) or len(raw["icons"]) > 20):
            raise ValueError("MCP resource icons must be an array of at most 20 items")
        if identity in rows:
            raise ValueError(f"Duplicate MCP {identity_key} values are not supported")
        rows[identity] = raw
    return rows, partial


def resource_catalog(resources, templates, protocol_version):
    if not isinstance(templates, str):
        raise ValueError("templates must be JSON text or an empty string")
    resource_rows, resource_partial = _resource_rows(
        resources, "resources", "uri", "MCP resources/list", protocol_version)
    if templates:
        template_rows, template_partial = _resource_rows(
            templates, "resourceTemplates", "uriTemplate", "MCP resources/templates/list", protocol_version)
    else:
        template_rows, template_partial = {}, False
    return resource_rows, resource_partial, template_rows, template_partial


def prompt_catalog(manifest, protocol_version):
    entries, partial = _list_result(manifest, "prompts", "MCP prompts/list", protocol_version)
    rows = {}
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError("MCP prompt entries must be objects")
        prompt_name = _text(raw.get("name"), "prompt name")
        for key in ("title", "description"):
            _optional_text(raw, key, key, 10000)
        if "icons" in raw and (not isinstance(raw["icons"], list) or len(raw["icons"]) > 20):
            raise ValueError("MCP prompt icons must be an array of at most 20 items")
        arguments = raw.get("arguments", [])
        if not isinstance(arguments, list) or len(arguments) > _MAX_ENTRIES:
            raise ValueError("MCP prompt arguments must be an array of at most 500 entries")
        argument_rows = {}
        for argument in arguments:
            if not isinstance(argument, dict):
                raise ValueError("MCP prompt arguments must be objects")
            argument_name = _text(argument.get("name"), "prompt argument name")
            _optional_text(argument, "description", "argument description", 10000)
            if "required" in argument and type(argument["required"]) is not bool:
                raise ValueError("MCP prompt argument required must be a boolean")
            if argument_name in argument_rows:
                raise ValueError("Duplicate MCP prompt argument names are not supported")
            argument_rows[argument_name] = argument
        if prompt_name in rows:
            raise ValueError("Duplicate MCP prompt names are not supported")
        rows[prompt_name] = (raw, argument_rows)
    return rows, partial


def scheme(value):
    prefix = value.split(":", 1)[0] if ":" in value else ""
    return prefix.lower() if _SCHEME.fullmatch(prefix) else None
