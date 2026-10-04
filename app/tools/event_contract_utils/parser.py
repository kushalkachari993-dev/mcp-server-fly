import json
import re

import yaml

from app.tools.config_utils.service import _ConfigLoader
from app.tools.json_query.service import _check_tree
from app.tools.manifest_utils.service import _unique_object
from app.tools.yaml_utils.tool import _json_compatible


_MAX_CHARS = 200000
_MAX_ITEMS = 500
_SCHEMA_TYPES = {"array", "boolean", "integer", "null", "number", "object", "string"}
_ASYNCAPI_FORMATS = {
    "application/vnd.aai.asyncapi;version=3.0.0",
    "application/vnd.aai.asyncapi+json;version=3.0.0",
    "application/vnd.aai.asyncapi+yaml;version=3.0.0",
}
_DRAFT7_FORMATS = {"application/schema+json;version=draft-07", "application/schema+yaml;version=draft-07"}


def json_value(content):
    if not isinstance(content, str) or not content.strip() or len(content) > _MAX_CHARS:
        raise ValueError("JSON input must be nonempty text of at most 200000 characters")
    try:
        value = json.loads(content, object_pairs_hook=_unique_object)
        _check_tree(value, max_nodes=20000, max_depth=50)
        return value
    except (ValueError, RecursionError) as error:
        raise ValueError("Invalid or oversized JSON; duplicate keys and non-finite numbers are rejected") from error


def document(content):
    if not isinstance(content, str) or not content.strip() or len(content) > _MAX_CHARS:
        raise ValueError("AsyncAPI document must be nonempty text of at most 200000 characters")
    if content.lstrip().startswith(("{", "[")):
        value = json_value(content)
    else:
        try:
            value = _json_compatible(yaml.load(content, Loader=_ConfigLoader))
        except (yaml.YAMLError, ValueError, RecursionError) as error:
            raise ValueError("Invalid or oversized AsyncAPI YAML; duplicate keys and unsafe values are rejected") from error
    if not isinstance(value, dict) or value.get("asyncapi") != "3.0.0" or not isinstance(value.get("info"), dict):
        raise ValueError("Supply an AsyncAPI 3.0.0 document with an info object")
    for key in ("channels", "operations"):
        if not isinstance(value.get(key, {}), dict) or len(value.get(key, {})) > _MAX_ITEMS:
            raise ValueError(f"AsyncAPI {key} must be an object with at most 500 entries")
    return value


def text(value, label, required=False):
    if value is None and not required:
        return None
    if (not isinstance(value, str) or (required and not value) or len(value) > 10000
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"AsyncAPI {label} must be text of at most 10000 characters without controls")
    return value


def pointer(document_value, ref):
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    node = document_value
    for token in ref[2:].split("/"):
        if re.search(r"~(?![01])", token):
            return None
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and len(token) <= 10 and token.isdecimal() and str(int(token)) == token and int(token) < len(node):
            node = node[int(token)]
        else:
            return None
    return node


def resolve(value, document_value):
    seen = set()
    for _ in range(20):
        if not isinstance(value, dict) or "$ref" not in value:
            return value, True
        ref = value["$ref"]
        if not isinstance(ref, str) or ref in seen:
            return None, False
        seen.add(ref)
        value = pointer(document_value, ref)
        if value is None:
            return None, False
    return None, False


def ref_status(document_value):
    counts = {"total": 0, "resolved_local": 0, "unresolved_local": 0, "external_or_invalid": 0}
    stack = [document_value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "$ref" in node:
                counts["total"] += 1
                ref = node["$ref"]
                if isinstance(ref, str) and ref.startswith("#/"):
                    counts["resolved_local" if pointer(document_value, ref) is not None else "unresolved_local"] += 1
                else:
                    counts["external_or_invalid"] += 1
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return counts


def format_kind(value):
    if value is not None and not isinstance(value, str):
        return "unsupported"
    if value in _ASYNCAPI_FORMATS or value is None:
        return "asyncapi_schema"
    if value in _DRAFT7_FORMATS:
        return "json_schema_draft7"
    return "unsupported"


def payload_schema(raw, document_value):
    if raw is None:
        return None, "missing"
    value, resolved = resolve(raw, document_value)
    if not resolved or not isinstance(value, (dict, bool)):
        return None, "unresolved"
    if isinstance(value, dict) and ("schemaFormat" in value or "schema" in value):
        kind = format_kind(value.get("schemaFormat"))
        if kind == "unsupported":
            return None, kind
        schema = value.get("schema")
        return (schema, kind) if isinstance(schema, (dict, bool)) else (None, "unresolved")
    return value, "asyncapi_schema"


def schema_type(value):
    if value is None:
        return None
    if isinstance(value, str) and value in _SCHEMA_TYPES:
        return value
    if isinstance(value, list) and value and len(value) <= 7 and all(isinstance(item, str) and item in _SCHEMA_TYPES for item in value):
        return sorted(set(value))
    return "unknown"


def schema_shape(raw, document_value):
    schema, kind = payload_schema(raw, document_value)
    if schema is None:
        return {"status": kind}
    if isinstance(schema, bool):
        return {"status": "known", "format": kind, "boolean": schema}
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    if not isinstance(required, list) or any(not isinstance(name, str) for name in required):
        required = []
    if not isinstance(properties, dict):
        properties = {}
    property_types = []
    for name, child in properties.items():
        child_schema, _ = payload_schema(child, document_value)
        property_types.append((name, schema_type(child_schema.get("type")) if isinstance(child_schema, dict) else None))
    return {"status": "known", "format": kind, "type": schema_type(schema.get("type")),
            "required": sorted(set(required)), "property_types": sorted(property_types)}


def selected(document_value):
    channels, operations = {}, {}
    default_content_type = text(document_value.get("defaultContentType"), "defaultContentType")
    for channel_id, raw in document_value.get("channels", {}).items():
        text(channel_id, "channel ID", True)
        channel, resolved = resolve(raw, document_value)
        if not resolved or not isinstance(channel, dict):
            channels[channel_id] = {"id": channel_id, "status": "unresolved", "address": None, "messages": {}}
            continue
        address = text(channel.get("address"), "channel address")
        messages = channel.get("messages", {})
        if not isinstance(messages, dict) or len(messages) > _MAX_ITEMS:
            raise ValueError("AsyncAPI channel messages must be an object with at most 500 entries")
        rows = {}
        for message_id, message_raw in messages.items():
            text(message_id, "message ID", True)
            message, resolved = resolve(message_raw, document_value)
            if not resolved or not isinstance(message, dict):
                rows[message_id] = {"id": message_id, "status": "unresolved", "content_type": None,
                                    "payload": {"status": "unresolved"}}
                continue
            rows[message_id] = {"id": message_id, "status": "known",
                                "content_type": text(message.get("contentType", default_content_type), "message contentType"),
                                "payload": schema_shape(message.get("payload"), document_value)}
        channels[channel_id] = {"id": channel_id, "status": "known", "address": address, "messages": rows}
    for operation_id, raw in document_value.get("operations", {}).items():
        text(operation_id, "operation ID", True)
        operation, resolved = resolve(raw, document_value)
        if not resolved or not isinstance(operation, dict):
            operations[operation_id] = {"id": operation_id, "status": "unresolved", "action": None,
                                        "channel_id": None, "message_ids": None}
            continue
        action = operation.get("action")
        if action not in {"send", "receive"}:
            raise ValueError("AsyncAPI operation action must be send or receive")
        channel_ref = operation.get("channel")
        channel_id = channel_ref.get("$ref") if isinstance(channel_ref, dict) else None
        channel_id = _root_channel_id(channel_id, channels)
        message_refs = operation.get("messages")
        message_ids = None
        if message_refs is not None:
            if not isinstance(message_refs, list) or len(message_refs) > _MAX_ITEMS:
                raise ValueError("AsyncAPI operation messages must be an array of at most 500 references")
            message_ids = []
            for entry in message_refs:
                ref = entry.get("$ref") if isinstance(entry, dict) else None
                message_ids.append(_channel_message_id(ref, channel_id, channels))
            message_ids.sort(key=lambda value: "" if value is None else value)
        channel_known = channel_id is not None and channels[channel_id]["status"] == "known"
        operations[operation_id] = {"id": operation_id, "status": "known" if channel_known and (message_ids is None or None not in message_ids) else "unresolved",
                                    "action": action, "channel_id": channel_id, "message_ids": message_ids}
    return channels, operations


def _pointer_token(value):
    return value.replace("~", "~0").replace("/", "~1")


def _root_channel_id(ref, channels):
    for channel_id in channels:
        if ref == "#/channels/" + _pointer_token(channel_id):
            return channel_id
    return None


def _channel_message_id(ref, channel_id, channels):
    if channel_id is None or channels[channel_id]["status"] != "known":
        return None
    for message_id in channels[channel_id]["messages"]:
        if ref == "#/channels/" + _pointer_token(channel_id) + "/messages/" + _pointer_token(message_id):
            return message_id
    return None


def show_shape(shape):
    if shape["status"] != "known":
        return {"status": shape["status"]}
    if "boolean" in shape:
        return {"status": "known", "format": shape["format"], "boolean": shape["boolean"]}
    return {"status": "known", "format": shape["format"], "type": shape["type"],
            "required_property_count": len(shape["required"]), "property_count": len(shape["property_types"])}


def show_channel(row, summary):
    return {"id": summary.text(row["id"]), "status": row["status"],
            "address": summary.text(row["address"]),
            "message_count": len(row["messages"]),
            "messages": summary.take([{"id": summary.text(message["id"]), "status": message["status"],
                                       "content_type": summary.text(message["content_type"]),
                                       "payload": show_shape(message["payload"])}
                                      for message in row["messages"].values()])}


def show_operation(row, summary):
    return {"id": summary.text(row["id"]), "status": row["status"], "action": row["action"],
            "channel_id": summary.text(row["channel_id"]),
            "message_ids_declared": row["message_ids"] is not None,
            "message_ids": None if row["message_ids"] is None else summary.take([summary.text(name) for name in row["message_ids"]])}
