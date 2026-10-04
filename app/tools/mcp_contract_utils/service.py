from app.tools.report_utils.service import _Summary
from app.tools.schema_utils.service import validate_schema

from . import parser


_DIALECTS = {
    "https://json-schema.org/draft/2020-12/schema",
    "https://json-schema.org/draft/2020-12/schema#",
    "http://json-schema.org/draft-07/schema#",
    "https://json-schema.org/draft-07/schema#",
}
_ANNOTATION_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def _type(value):
    known = {"array", "boolean", "integer", "null", "number", "object", "string"}
    if value is None:
        return None
    if isinstance(value, str) and value in known:
        return value
    if isinstance(value, list) and value and all(isinstance(item, str) and item in known for item in value):
        return sorted(set(value))
    return "unknown"


def _property_type(value):
    return isinstance(value, dict), _type(value.get("type")) if isinstance(value, dict) else None


def _shown_tool(tool_name, raw, summary):
    input_schema = raw["inputSchema"]
    input_properties, required = parser._schema_shape(input_schema, "MCP inputSchema")
    output_schema = raw.get("outputSchema")
    annotations = raw.get("annotations", {})
    task_support = raw.get("execution", {}).get("taskSupport")
    return {"name": summary.text(tool_name, 200),
            "name_follows_recommendation": bool(parser.NAME_PATTERN.fullmatch(tool_name)),
            "description_present": "description" in raw,
            "input_root_type": _type(input_schema.get("type")),
            "input_property_count": len(input_properties),
            "required_argument_count": len(set(required)),
            "required_arguments": summary.take([summary.text(item, 200) for item in sorted(set(required))]),
            "output_schema_present": output_schema is not None,
            "output_root_type": _type(output_schema.get("type")) if output_schema is not None else None,
            "annotation_hints": {key: annotations[key] for key in _ANNOTATION_HINTS
                                 if type(annotations.get(key)) is bool},
            "task_support": task_support if isinstance(task_support, str)
            and task_support in {"forbidden", "optional", "required"} else None}


def inspect_mcp_tool_manifest(manifest, protocol_version, limit):
    summary = _Summary(manifest, limit)
    rows, partial = parser.manifest(manifest, protocol_version)
    return {"protocol_version": protocol_version, "tool_count": len(rows),
            "partial_list": partial,
            "nonconforming_name_count": sum(not parser.NAME_PATTERN.fullmatch(name) for name in rows),
            "tools": summary.take([_shown_tool(name, rows[name], summary) for name in sorted(rows)]),
            "truncated": summary.truncated,
            "notes": ["Inspects one supplied tools/list page or complete snapshot, not a live server or full MCP conformance.",
                      "A nextCursor marks an incomplete page; absence of a tool on that page does not prove removal.",
                      "Descriptions, defaults, examples, schemas and result values are omitted. Tool and argument names may still be sensitive.",
                      "Annotations are untrusted hints. Schema syntax and tool behavior are not validated by inspection."]}


def _shape_delta(before, after, summary):
    old_props, old_required = parser._schema_shape(before, "MCP schema")
    new_props, new_required = parser._schema_shape(after, "MCP schema")
    common = old_props.keys() & new_props.keys()
    return {"root_type_before": _type(before.get("type")),
            "root_type_after": _type(after.get("type")),
            "required_added": summary.take([summary.text(name, 200) for name in sorted(set(new_required) - set(old_required))]),
            "required_removed": summary.take([summary.text(name, 200) for name in sorted(set(old_required) - set(new_required))]),
            "properties_added": summary.take([summary.text(name, 200) for name in sorted(new_props.keys() - old_props.keys())]),
            "properties_removed": summary.take([summary.text(name, 200) for name in sorted(old_props.keys() - new_props.keys())]),
            "property_type_changes": summary.take([
                {"name": summary.text(name, 200), "before": _property_type(old_props[name])[1],
                 "after": _property_type(new_props[name])[1]}
                for name in sorted(common) if _property_type(old_props[name]) != _property_type(new_props[name])]),
            "additional_properties_changed": before.get("additionalProperties") != after.get("additionalProperties")}


def compare_mcp_tool_manifests(before, after, protocol_version, limit):
    summary = _Summary(before, limit)
    _Summary(after, limit)
    old_rows, old_partial = parser.manifest(before, protocol_version)
    new_rows, new_partial = parser.manifest(after, protocol_version)
    if old_partial or new_partial:
        raise ValueError("Compare complete tools/list snapshots; follow nextCursor on every page first")
    changes = []
    for tool_name in sorted(old_rows.keys() | new_rows.keys()):
        old, new = old_rows.get(tool_name), new_rows.get(tool_name)
        identity = summary.text(tool_name, 200)
        if old is None or new is None:
            changes.append({"name": identity, "field": "tool_presence", "before": old is not None, "after": new is not None})
            continue
        for field, key in (("input_schema", "inputSchema"), ("output_schema", "outputSchema")):
            if old.get(key) != new.get(key):
                change = {"name": identity, "field": field, "before_present": key in old, "after_present": key in new}
                if key in old and key in new:
                    change["selected_shape"] = _shape_delta(old[key], new[key], summary)
                changes.append(change)
        for field, key in (("title", "title"), ("description", "description"),
                           ("annotations", "annotations"), ("execution", "execution")):
            if old.get(key) != new.get(key):
                changes.append({"name": identity, "field": field, "changed": True})
    return {"protocol_version": protocol_version, "before_tool_count": len(old_rows),
            "after_tool_count": len(new_rows), "selected_change_count": len(changes),
            "changes": summary.take(changes), "truncated": summary.truncated,
            "notes": ["Exact full case-sensitive tool names are matched before display shortening; no rename inference.",
                      "Schema changes include exact supplied JSON differences; selected shape details are not a compatibility verdict.",
                      "Description, annotation and execution changes are flags only; their values are omitted. Annotations are untrusted.",
                      "Complete snapshots are required; paginated pages with nextCursor are rejected."]}


def _check_schema_for_validation(schema):
    dialect = schema.get("$schema")
    if dialect is not None and (not isinstance(dialect, str) or dialect not in _DIALECTS):
        raise ValueError("Only JSON Schema 2020-12 and Draft 7 are supported")
    stack = [(schema, True)]
    while stack:
        node, root = stack.pop()
        if isinstance(node, dict):
            if not root and ("$schema" in node or "$id" in node):
                raise ValueError("Nested JSON Schema dialects and resource IDs are not supported")
            if "$dynamicRef" in node or "$recursiveRef" in node:
                raise ValueError("Dynamic JSON Schema references are not supported")
            if "$ref" in node and (not isinstance(node["$ref"], str) or not node["$ref"].startswith("#")):
                raise ValueError("Only local JSON Schema references are supported")
            stack.extend((child, False) for child in node.values())
        elif isinstance(node, list):
            stack.extend((child, False) for child in node)


def _validation_errors(instance, schema, summary):
    _check_schema_for_validation(schema)
    try:
        result = validate_schema(instance, schema)
    except ValueError as error:
        raise ValueError("MCP JSON Schema validation failed or exceeded its time limit") from error
    errors = [{"path": item["path"], "schema_path": item["schema_path"]} for item in result["errors"]]
    return result["valid"], summary.take(errors), result["truncated"] or summary.truncated


def validate_mcp_tool_arguments(manifest, tool_name, arguments, protocol_version, limit):
    summary = _Summary(manifest, limit)
    _Summary(arguments, limit)
    rows, _ = parser.manifest(manifest, protocol_version)
    selected = rows.get(parser.name(tool_name))
    if selected is None:
        raise ValueError("Selected MCP tool is absent from the supplied snapshot")
    instance = parser.json_value(arguments, "MCP tool arguments")
    if not isinstance(instance, dict):
        raise ValueError("MCP tool arguments must be a JSON object")
    valid, errors, truncated = _validation_errors(instance, selected["inputSchema"], summary)
    return {"protocol_version": protocol_version, "tool_name": summary.text(tool_name, 200),
            "valid": valid, "error_count_returned": len(errors), "errors": errors, "truncated": truncated,
            "notes": ["Checks supplied arguments only; the tool is never called and authorization or runtime behavior is not tested.",
                      "JSON Schema 2020-12 (default) and explicit Draft 7 are supported with local references only.",
                      "Argument values and validator messages are omitted; JSON pointer paths can contain supplied property names."]}


def validate_mcp_tool_result(manifest, tool_name, result, protocol_version, limit):
    summary = _Summary(manifest, limit)
    _Summary(result, limit)
    rows, _ = parser.manifest(manifest, protocol_version)
    selected = rows.get(parser.name(tool_name))
    if selected is None:
        raise ValueError("Selected MCP tool is absent from the supplied snapshot")
    value = parser.result(result)
    result_type = value.get("resultType")
    if result_type is not None and not isinstance(result_type, str):
        raise ValueError("MCP resultType must be text when present")
    if protocol_version == "2026-07-28" and result_type not in {"complete", "input_required"}:
        raise ValueError("2026-07-28 tool results need a supported resultType")
    if result_type not in (None, "complete", "input_required"):
        raise ValueError("Unsupported MCP tool resultType")
    reason = None
    if result_type == "input_required":
        reason = "input_required"
    elif value.get("isError", False):
        reason = "tool_error"
    elif "outputSchema" not in selected:
        reason = "output_schema_absent"
    if reason is not None:
        return {"protocol_version": protocol_version, "tool_name": summary.text(tool_name, 200),
                "checked": False, "schema_valid": None, "reason": reason,
                "error_count_returned": 0, "errors": [], "truncated": summary.truncated,
                "notes": ["Structured content was not checked; no full result-envelope or content-block validation is claimed.",
                          "Tool output values and validator messages are omitted."]}
    if "structuredContent" not in value or protocol_version == "2025-11-25" and not isinstance(value["structuredContent"], dict):
        reason = "structured_content_missing" if "structuredContent" not in value else "structured_content_must_be_object"
        return {"protocol_version": protocol_version, "tool_name": summary.text(tool_name, 200),
                "checked": True, "schema_valid": False, "reason": reason,
                "error_count_returned": 0, "errors": [], "truncated": summary.truncated,
                "notes": ["The selected tool declares outputSchema, but structuredContent is missing or violates the selected protocol shape.",
                          "Tool output values are omitted; no full result-envelope or content-block validation is claimed."]}
    valid, errors, truncated = _validation_errors(value["structuredContent"], selected["outputSchema"], summary)
    return {"protocol_version": protocol_version, "tool_name": summary.text(tool_name, 200),
            "checked": True, "schema_valid": valid, "reason": None,
            "error_count_returned": len(errors), "errors": errors, "truncated": truncated,
            "notes": ["Checks only structuredContent against the selected outputSchema; no full result-envelope, content-block or runtime validation.",
                      "2025-11-25 requires structuredContent to be an object; 2026-07-28 permits any JSON value.",
                      "Result values and validator messages are omitted; JSON pointer paths can contain supplied property names."]}
