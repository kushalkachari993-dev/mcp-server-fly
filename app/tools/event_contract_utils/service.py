import base64
import re
from datetime import datetime
from urllib.parse import urlsplit

from app.tools.report_utils.service import _Summary
from app.tools.schema_utils.service import validate_schema

from . import parser


_DRAFT7 = "http://json-schema.org/draft-07/schema#"
_CE_REQUIRED = ("id", "source", "specversion", "type")
_CE_OPTIONAL = ("datacontenttype", "dataschema", "subject", "time")
_CE_KNOWN = set(_CE_REQUIRED) | set(_CE_OPTIONAL) | {"data", "data_base64"}
_MEDIA_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+(?:\s*;\s*[A-Za-z0-9!#$&^_.+-]+\s*=\s*(?:[A-Za-z0-9!#$&^_.+-]+|\"[^\"\r\n]*\"))*\Z")


def _uri(value, absolute=False):
    if not value.isascii() or re.search(r"[^A-Za-z0-9:/?#\[\]@!$&'()*+,;=._~%-]|%(?![0-9A-Fa-f]{2})", value):
        return False
    try:
        parsed = urlsplit(value)
        return not absolute or bool(parsed.scheme and re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", parsed.scheme))
    except ValueError:
        return False


def _timestamp(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)", value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def inspect_asyncapi_document(content, limit):
    summary = _Summary(content, limit)
    value = parser.document(content)
    channels, operations = parser.selected(value)
    refs = parser.ref_status(value)
    return {"asyncapi": "3.0.0", "title": summary.text(value["info"].get("title")),
            "version": summary.text(value["info"].get("version")),
            "channel_count": len(channels), "operation_count": len(operations),
            "message_count": sum(len(row["messages"]) for row in channels.values()),
            "unresolved_channel_count": sum(row["status"] != "known" for row in channels.values()),
            "unresolved_operation_count": sum(row["status"] != "known" for row in operations.values()),
            "reference_status": refs,
            "channels": summary.take([parser.show_channel(row, summary) for row in channels.values()]),
            "operations": summary.take([parser.show_operation(row, summary) for row in operations.values()]),
            "truncated": summary.truncated,
            "notes": ["Selected AsyncAPI 3.0.0 declarations only, not complete specification, bindings, trait or security validation.",
                      "Local references are resolved for selected fields; external, missing and cyclic references remain unknown and are never fetched.",
                      "Payload summaries cover only shallow JSON-schema shape. Examples, payload values and descriptions are omitted; IDs and addresses may be sensitive."]}


def _change(rows, kind, identity, field, before, after, certainty="declared", details=None):
    item = {"kind": kind, "identity": identity, "field": field, "before": before, "after": after,
            "certainty": certainty}
    if details is not None:
        item["details"] = details
    rows.append(item)


def _shape_details(before, after, summary):
    if before["status"] != "known" or after["status"] != "known" or "boolean" in before or "boolean" in after:
        return {}
    old_types, new_types = dict(before["property_types"]), dict(after["property_types"])
    changed = [{"name": summary.text(name), "before_type": old_types.get(name), "after_type": new_types.get(name)}
               for name in sorted(old_types.keys() | new_types.keys()) if old_types.get(name) != new_types.get(name)
               or (name in old_types) != (name in new_types)]
    return {"required_added": summary.take([summary.text(name) for name in sorted(set(after["required"]) - set(before["required"]))]),
            "required_removed": summary.take([summary.text(name) for name in sorted(set(before["required"]) - set(after["required"]))]),
            "property_type_changes": summary.take(changed)}


def _unknown_selected(channels, operations):
    count = 0
    for channel in channels.values():
        count += channel["status"] != "known"
        for message in channel["messages"].values():
            count += message["status"] != "known" or message["payload"]["status"] not in {"known", "missing"}
    count += sum(operation["status"] != "known" for operation in operations.values())
    return count


def compare_asyncapi_contracts(before, after, limit):
    summary = _Summary(before, limit)
    _Summary(after, limit)
    old_doc, new_doc = parser.document(before), parser.document(after)
    old_channels, old_operations = parser.selected(old_doc)
    new_channels, new_operations = parser.selected(new_doc)
    changes = []
    uncertainty = _unknown_selected(old_channels, old_operations) + _unknown_selected(new_channels, new_operations)
    for channel_id in sorted(old_channels.keys() | new_channels.keys()):
        old, new = old_channels.get(channel_id), new_channels.get(channel_id)
        identity = {"channel_id": summary.text(channel_id)}
        if old is None or new is None:
            _change(changes, "channel", identity, "presence", old is not None, new is not None)
            continue
        if old["status"] != "known" or new["status"] != "known":
            continue
        if old["address"] != new["address"]:
            _change(changes, "channel", identity, "address", summary.text(old["address"]), summary.text(new["address"]))
        for message_id in sorted(old["messages"].keys() | new["messages"].keys()):
            previous, current = old["messages"].get(message_id), new["messages"].get(message_id)
            message_identity = {**identity, "message_id": summary.text(message_id)}
            if previous is None or current is None:
                _change(changes, "message", message_identity, "presence", previous is not None, current is not None)
                continue
            if previous["status"] != "known" or current["status"] != "known":
                continue
            if previous["content_type"] != current["content_type"]:
                _change(changes, "message", message_identity, "content_type",
                        summary.text(previous["content_type"]), summary.text(current["content_type"]))
            if previous["payload"] != current["payload"]:
                certainty = ("selected_schema_only" if previous["payload"]["status"] == current["payload"]["status"] == "known"
                             else "uncertain")
                _change(changes, "message", message_identity, "payload_shape",
                        parser.show_shape(previous["payload"]), parser.show_shape(current["payload"]),
                        certainty, _shape_details(previous["payload"], current["payload"], summary))
    for operation_id in sorted(old_operations.keys() | new_operations.keys()):
        old, new = old_operations.get(operation_id), new_operations.get(operation_id)
        identity = {"operation_id": summary.text(operation_id)}
        if old is None or new is None:
            _change(changes, "operation", identity, "presence", old is not None, new is not None)
            continue
        if old["status"] != "known" or new["status"] != "known":
            continue
        for field in ("action", "channel_id", "message_ids"):
            if old[field] != new[field]:
                left = old[field]
                right = new[field]
                if field == "channel_id":
                    left, right = summary.text(left), summary.text(right)
                elif field == "message_ids":
                    left = None if left is None else summary.take([summary.text(name) for name in left])
                    right = None if right is None else summary.take([summary.text(name) for name in right])
                _change(changes, "operation", identity, field, left, right,
                        "uncertain" if field == "message_ids" and (None in (old[field] or []) or None in (new[field] or [])) else "declared")
    refs = {"before": parser.ref_status(old_doc), "after": parser.ref_status(new_doc)}
    complete = not uncertainty and not any(row["unresolved_local"] or row["external_or_invalid"] for row in refs.values())
    return {"before_channel_count": len(old_channels), "after_channel_count": len(new_channels),
            "before_operation_count": len(old_operations), "after_operation_count": len(new_operations),
            "reference_status": refs, "uncertain_selected_record_count": uncertainty,
            "selected_reference_coverage_complete": complete,
            "selected_change_count": len(changes), "changes": summary.take(changes), "truncated": summary.truncated,
            "notes": ["Matches use exact full channel, message and operation IDs; no rename inference or full compatibility verdict.",
                      "Only addresses, operation actions/channel/message references, content types and shallow payload shapes are compared. Other schema constraints, traits, bindings and runtime behavior are outside scope.",
                      "Unknown/external references and unsupported payload schema formats remain uncertain. IDs and addresses may be sensitive."]}


def _validation_schema(schema, kind, document_value):
    if not isinstance(schema, (dict, bool)):
        raise ValueError("Selected payload schema must be an object or boolean")
    if isinstance(schema, bool):
        return schema
    components = document_value.get("components", {})
    schemas = components.get("schemas", {}) if isinstance(components, dict) else {}
    if not isinstance(schemas, dict):
        raise ValueError("AsyncAPI components.schemas must be an object")
    definitions = schema.get("definitions", {})
    if not isinstance(definitions, dict):
        raise ValueError("Payload schema definitions must be an object")
    reserved = "_asyncapi_components"
    while reserved in definitions:
        reserved += "_"
    selected = {}
    map_keywords = {"properties", "patternProperties", "definitions"}
    list_keywords = {"allOf", "anyOf", "oneOf"}
    schema_keywords = {"additionalProperties", "additionalItems", "propertyNames", "not", "contains", "if", "then", "else"}

    def transform(node):
        if isinstance(node, bool):
            return node
        if not isinstance(node, dict):
            return node
        if any(key in node for key in ("$id", "$schema", "$anchor", "$dynamicRef", "$dynamicAnchor", "$vocabulary",
                                       "$defs", "prefixItems", "unevaluatedProperties", "unevaluatedItems",
                                       "dependentSchemas", "dependentRequired", "minContains", "maxContains",
                                       "discriminator", "readOnly", "writeOnly", "nullable")):
            raise ValueError("Selected payload uses unsupported dialect or AsyncAPI-specific schema features")
        result = {}
        for key, value in node.items():
            if key == "$ref":
                prefix = "#/components/schemas/"
                if not isinstance(value, str) or not value.startswith(prefix) or parser.pointer(document_value, value) is None:
                    raise ValueError("Only resolvable local #/components/schemas references are supported")
                encoded_name = value[len(prefix):].split("/", 1)[0]
                name = encoded_name.replace("~1", "/").replace("~0", "~")
                if name not in schemas:
                    raise ValueError("Referenced AsyncAPI component schema is missing")
                selected[name] = None
                result[key] = "#/definitions/" + reserved + "/" + value[len(prefix):]
            elif key in map_keywords and isinstance(value, dict):
                result[key] = {name: transform(child) for name, child in value.items()}
            elif key == "dependencies" and isinstance(value, dict):
                result[key] = {name: transform(child) if isinstance(child, dict) else child for name, child in value.items()}
            elif key in list_keywords and isinstance(value, list):
                result[key] = [transform(child) for child in value]
            elif key == "items" and isinstance(value, list):
                result[key] = [transform(child) for child in value]
            elif key in schema_keywords or key == "items":
                result[key] = transform(value)
            else:
                result[key] = value
        return result

    root = transform(schema)
    expanded = {}
    while len(expanded) < len(selected):
        for name in list(selected):
            if name in expanded:
                continue
            component_schema, component_kind = parser.payload_schema(schemas[name], document_value)
            if component_schema is None and component_kind == "unresolved":
                raise ValueError("Only resolvable local #/components/schemas references are supported")
            if component_kind != kind or not isinstance(component_schema, (dict, bool)):
                raise ValueError("Referenced component uses an incompatible or unsupported schema format")
            expanded[name] = transform(component_schema)
    if expanded:
        root["definitions"] = {**definitions, reserved: expanded}
    root["$schema"] = _DRAFT7
    return root


def validate_asyncapi_json_message(spec, channel_id, message_id, payload, limit):
    summary = _Summary(spec, limit)
    _Summary(payload, limit)
    document_value = parser.document(spec)
    channel_id = parser.text(channel_id, "channel ID", True)
    message_id = parser.text(message_id, "message ID", True)
    channel, resolved = parser.resolve(document_value.get("channels", {}).get(channel_id), document_value)
    if not resolved or not isinstance(channel, dict):
        raise ValueError("Selected AsyncAPI channel is missing or unresolved")
    messages = channel.get("messages", {})
    if not isinstance(messages, dict):
        raise ValueError("AsyncAPI channel messages must be an object")
    message, resolved = parser.resolve(messages.get(message_id), document_value)
    if not resolved or not isinstance(message, dict):
        raise ValueError("Selected AsyncAPI message is missing or unresolved")
    content_type = message.get("contentType", document_value.get("defaultContentType"))
    if not isinstance(content_type, str):
        raise ValueError("Selected message must declare JSON contentType or defaultContentType")
    base_type = content_type.split(";", 1)[0].strip().lower()
    if not re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", base_type) or (base_type != "application/json" and not base_type.endswith("+json")):
        raise ValueError("Selected message must declare JSON contentType or defaultContentType")
    schema, kind = parser.payload_schema(message.get("payload"), document_value)
    if kind not in {"asyncapi_schema", "json_schema_draft7"} or schema is None:
        raise ValueError("Selected message needs a supported inline or local JSON Schema payload")
    validator_schema = _validation_schema(schema, kind, document_value)
    instance = parser.json_value(payload)
    try:
        result = validate_schema(instance, validator_schema)
    except ValueError as error:
        raise ValueError("JSON payload validation failed or exceeded its time limit") from error
    errors = [{"path": item["path"], "schema_path": item["schema_path"]} for item in result["errors"]]
    return {"valid": result["valid"], "channel_id": summary.text(channel_id),
            "message_id": summary.text(message_id), "schema_format": kind,
            "error_count_returned": len(errors), "errors": summary.take(errors),
            "truncated": result["truncated"] or summary.truncated,
            "notes": ["Selected JSON payload only, using Draft 7 checks for the supported AsyncAPI schema subset or explicit JSON Schema Draft 7. No broker access or message execution.",
                      "Only local component-schema references are resolved. Avro, Protobuf, external refs, custom dialects, traits, discriminator and readOnly/writeOnly semantics are unsupported.",
                      "Body values and validator messages are omitted; JSON pointer paths can contain caller-supplied property names. Unknown formats may not be checked."]}


def _ce_string(value, required=False):
    if not isinstance(value, str) or required and not value:
        return False
    return not any(ord(char) < 32 or 127 <= ord(char) <= 159 or 0xD800 <= ord(char) <= 0xDFFF
                   or 0xFDD0 <= ord(char) <= 0xFDEF or ord(char) & 0xFFFF in (0xFFFE, 0xFFFF) for char in value)


def validate_cloudevents_json(content, limit):
    summary = _Summary(content, limit)
    event = parser.json_value(content)
    if not isinstance(event, dict):
        raise ValueError("Supply one structured CloudEvents JSON object; batch arrays are not supported")
    issues = []

    def issue(field, code):
        issues.append({"field": field, "code": code})

    for name in _CE_REQUIRED:
        if name not in event or not _ce_string(event[name], required=True):
            issue(name, "missing_or_invalid_required_attribute")
    if _ce_string(event.get("specversion")) and event["specversion"] != "1.0":
        issue("specversion", "unsupported_version")
    if _ce_string(event.get("source"), required=True) and not _uri(event["source"]):
        issue("source", "invalid_uri_reference")
    for name in _CE_OPTIONAL:
        if name not in event or event[name] is None:
            continue
        if not _ce_string(event[name], required=True):
            issue(name, "invalid_optional_attribute")
        elif name == "dataschema" and not _uri(event[name], absolute=True):
            issue(name, "invalid_uri")
        elif name == "time" and not _timestamp(event[name]):
            issue(name, "invalid_timestamp")
        elif name == "datacontenttype" and not _MEDIA_TYPE.fullmatch(event[name]):
            issue(name, "invalid_media_type")
    for name, value in event.items():
        if name in {"data", "data_base64"}:
            continue
        if not re.fullmatch(r"[a-z0-9]+", name):
            issue("extension", "invalid_attribute_name")
        if name not in _CE_KNOWN and value is not None:
            if type(value) is int and not -2147483648 <= value <= 2147483647:
                issue("extension", "integer_out_of_range")
            elif type(value) not in (bool, int, str) or isinstance(value, str) and not _ce_string(value):
                issue("extension", "invalid_attribute_type")
    if "data" in event and "data_base64" in event:
        issue("payload", "data_and_data_base64_conflict")
    if "data_base64" in event:
        encoded = event["data_base64"]
        try:
            if not isinstance(encoded, str) or not encoded.isascii():
                raise ValueError
            base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            issue("data_base64", "invalid_base64")
    content_type = event.get("datacontenttype")
    if "data" in event and isinstance(content_type, str) and _MEDIA_TYPE.fullmatch(content_type):
        subtype = content_type.split(";", 1)[0].split("/", 1)[1].lower()
        if subtype != "json" and not subtype.endswith("+json") and not isinstance(event["data"], str):
            issue("data", "non_json_content_requires_string")
    return {"valid": not issues, "issue_count": len(issues), "issues": summary.take(issues),
            "truncated": summary.truncated, "attribute_count": len(event) - int("data" in event) - int("data_base64" in event),
            "extension_attribute_count": sum(name not in _CE_KNOWN for name in event),
            "payload_kind": "base64" if "data_base64" in event else "json" if "data" in event else "absent",
            "notes": ["Selected CloudEvents 1.0 structured JSON envelope checks only, not complete protocol binding or extension-specific validation. Single events only.",
                      "Required/optional attribute types, basic URI/media/time syntax, extension value types, and data/data_base64 representation are checked. Producer uniqueness and payload schema are not checked.",
                      "Attribute and payload values are never returned. No network, file or message-broker access."]}
