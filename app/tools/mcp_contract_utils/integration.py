import math

from app.tools.report_utils.service import _Summary

from . import catalog_parser, parser, runtime


_CATALOGS = {
    "tools": ("tools", "name"),
    "resources": ("resources", "uri"),
    "resource_templates": ("resourceTemplates", "uriTemplate"),
    "prompts": ("prompts", "name"),
}
_ERROR_CODES = {
    -32700: "parse_error",
    -32600: "invalid_request",
    -32601: "method_not_found",
    -32602: "invalid_params",
    -32603: "internal_error",
}
_MODERN_ERROR_CODES = {
    -32020: "header_mismatch",
    -32021: "missing_required_client_capability",
    -32022: "unsupported_protocol_version",
}


def _result_object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if "jsonrpc" in value:
        if value["jsonrpc"] != "2.0" or "error" in value or "result" not in value:
            raise ValueError(f"Supply a successful {label} response")
        value = value["result"]
    if not isinstance(value, dict):
        raise ValueError(f"{label} result must be an object")
    return value


def _catalog_page(raw, kind, protocol_version):
    value = _result_object(raw, "MCP catalog page")
    if protocol_version == "2026-07-28":
        if value.get("resultType") != "complete":
            raise ValueError("2026 MCP catalog pages need resultType complete")
        if type(value.get("ttlMs")) is not int:
            raise ValueError("2026 MCP catalog ttlMs must be a nonnegative integer")
        runtime._cache(value)
    elif value.get("resultType") not in (None, "complete"):
        raise ValueError("MCP catalog page resultType is unsupported")
    field, key = _CATALOGS[kind]
    entries = value.get(field)
    if not isinstance(entries, list) or len(entries) > 500:
        raise ValueError(f"MCP {field} must be an array of at most 500 entries per page")
    identities = []
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            raise ValueError("MCP catalog entries must be objects")
        identities.append(catalog_parser._text(raw_entry.get(key), key, 10000 if key != "name" else 1000))
    cursor = value.get("nextCursor")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 1000):
        raise ValueError("MCP nextCursor must be a string of at most 1000 characters when present")
    return identities, cursor


def inspect_mcp_paginated_catalog(pages, kind, request_cursors, protocol_version, limit):
    summary = _Summary(pages, limit)
    parser.protocol_version(protocol_version)
    if kind not in _CATALOGS:
        raise ValueError("kind must be tools, resources, resource_templates or prompts")
    if not isinstance(request_cursors, str):
        raise ValueError("request_cursors must be JSON text or an empty string")
    if request_cursors:
        _Summary(request_cursors, limit)
    supplied = parser.json_value(pages, "MCP catalog pages")
    if not isinstance(supplied, list) or not 1 <= len(supplied) <= 20:
        raise ValueError("MCP catalog pages must be an array of 1-20 results")
    requested = parser.json_value(request_cursors, "MCP request cursors") if request_cursors else None
    if requested is not None:
        if (not isinstance(requested, list) or len(requested) != len(supplied)
                or any(item is not None and (not isinstance(item, str) or len(item) > 1000)
                       for item in requested)):
            raise ValueError("request_cursors must have one null or string entry per page")
    rows, issues, seen_identities, seen_cursors = [], [], set(), set()
    duplicate_count = cursor_reuse_count = 0
    previous_cursor = None
    for index, raw in enumerate(supplied):
        identities, cursor = _catalog_page(raw, kind, protocol_version)
        page_seen = set()
        duplicates = 0
        for identity in identities:
            duplicates += identity in seen_identities or identity in page_seen
            page_seen.add(identity)
        duplicate_count += duplicates
        seen_identities.update(page_seen)
        if duplicates:
            issues.append({"page": index, "code": "duplicate_identity", "count": duplicates})
        if cursor is not None:
            cursor_reuse_count += cursor in seen_cursors
            if cursor in seen_cursors:
                issues.append({"page": index, "code": "cursor_reused"})
            seen_cursors.add(cursor)
        if index and previous_cursor is None:
            issues.append({"page": index, "code": "page_after_terminal"})
        if requested is not None and requested[index] != previous_cursor:
            issues.append({"page": index, "code": "request_cursor_mismatch"})
        previous_cursor = cursor
        rows.append({"page": index, "entry_count": len(identities), "has_next_cursor": cursor is not None})
    terminal = previous_cursor is None
    return {"protocol_version": protocol_version, "kind": kind,
            "page_count": len(rows), "entry_count": sum(row["entry_count"] for row in rows),
            "duplicate_identity_count": duplicate_count, "cursor_reuse_count": cursor_reuse_count,
            "request_cursor_chain_checked": requested is not None,
            "request_cursor_chain_valid": not any(item["code"] in ("request_cursor_mismatch", "page_after_terminal") for item in issues)
            if requested is not None else None,
            "terminal_page_present": terminal,
            "complete_chain": terminal and not issues if requested is not None else None,
            "pages": summary.take(rows), "issue_count": len(issues), "issues": summary.take(issues),
            "truncated": summary.truncated,
            "notes": ["Inspects supplied list-result pages only; it never requests another page or interprets opaque cursor values.",
                      "Without request_cursors, page ordering and completeness from the first page cannot be verified.",
                      "An empty string is a present nextCursor. Identities and cursor values are never returned.",
                      "Selected structure and cross-page duplicates are checked, not full catalog schemas or snapshot stability."]}


def _completion_params(request, protocol_version):
    parser.protocol_version(protocol_version)
    value = parser.json_value(request, "MCP completion request")
    if not isinstance(value, dict):
        raise ValueError("MCP completion request must be an object")
    if "jsonrpc" in value:
        if value["jsonrpc"] != "2.0" or value.get("method") != "completion/complete":
            raise ValueError("Supply a completion/complete request or its params object")
        value = value.get("params")
    if not isinstance(value, dict):
        raise ValueError("MCP completion params must be an object")
    reference = value.get("ref")
    argument = value.get("argument")
    if not isinstance(reference, dict) or not isinstance(argument, dict):
        raise ValueError("MCP completion ref and argument must be objects")
    kind = reference.get("type")
    if kind == "ref/prompt":
        identity = catalog_parser._text(reference.get("name"), "prompt name")
    elif kind == "ref/resource":
        identity = catalog_parser._text(reference.get("uri"), "resource URI", 10000)
    else:
        raise ValueError("MCP completion ref type must be ref/prompt or ref/resource")
    argument_name = catalog_parser._text(argument.get("name"), "completion argument name")
    if not isinstance(argument.get("value"), str):
        raise ValueError("MCP completion argument value must be text")
    context = value.get("context", {})
    if not isinstance(context, dict):
        raise ValueError("MCP completion context must be an object")
    context_arguments = context.get("arguments", {})
    if not isinstance(context_arguments, dict) or len(context_arguments) > 100:
        raise ValueError("MCP completion context arguments must be an object of at most 100 entries")
    for name, supplied_value in context_arguments.items():
        catalog_parser._text(name, "context argument name")
        if not isinstance(supplied_value, str):
            raise ValueError("MCP completion context argument values must be text")
    return kind, identity, argument_name, len(context_arguments)


def _resource_catalog_for_completion(catalog, protocol_version):
    value = parser.json_value(catalog, "MCP completion catalog")
    value = _result_object(value, "MCP completion catalog")
    if "resourceTemplates" in value:
        rows, partial = catalog_parser._resource_rows(
            catalog, "resourceTemplates", "uriTemplate", "MCP resources/templates/list", protocol_version)
        return rows, partial, "resource_templates"
    if "resources" in value:
        rows, partial = catalog_parser._resource_rows(
            catalog, "resources", "uri", "MCP resources/list", protocol_version)
        return rows, partial, "resources"
    raise ValueError("Supply a resources/list or resources/templates/list catalog for ref/resource")


def validate_mcp_completion_request(request, catalog, protocol_version, limit):
    summary = _Summary(request, limit)
    _Summary(catalog, limit)
    kind, identity, argument_name, context_count = _completion_params(request, protocol_version)
    if kind == "ref/prompt":
        rows, partial = catalog_parser.prompt_catalog(catalog, protocol_version)
        selected = rows.get(identity)
        catalog_kind = "prompts"
        argument_declared = argument_name in selected[1] if selected is not None else None
    else:
        rows, partial, catalog_kind = _resource_catalog_for_completion(catalog, protocol_version)
        selected = rows.get(identity)
        argument_declared = None
    found = selected is not None
    checked = found or not partial
    valid = (found and argument_declared is not False) if checked else None
    return {"protocol_version": protocol_version, "reference_type": kind,
            "catalog_kind": catalog_kind, "catalog_partial": partial,
            "checked": checked, "valid": valid, "reference_found": found,
            "argument_declared": argument_declared, "context_argument_count": context_count,
            "truncated": summary.truncated,
            "notes": ["Checks selected completion request fields and exact reference identity against one supplied catalog page; no server call or suggestions.",
                      "A missing reference in a partial catalog is indeterminate, not invalid.",
                      "Prompt argument names are checked against declarations; resource template variables are not parsed or validated.",
                      "Argument and context values, reference names and URIs are omitted; no full JSON-RPC or 2026 _meta validation is claimed."]}


def validate_mcp_completion_result(response, protocol_version, limit):
    summary = _Summary(response, limit)
    value = runtime._response(response, "MCP completion result", protocol_version)
    if protocol_version == "2026-07-28":
        if value.get("resultType") != "complete":
            raise ValueError("2026 MCP completion resultType must be complete")
    elif value.get("resultType") not in (None, "complete"):
        raise ValueError("MCP completion resultType is unsupported")
    completion = value.get("completion")
    if not isinstance(completion, dict):
        raise ValueError("MCP completion must be an object")
    issues = []
    values = completion.get("values")
    if not isinstance(values, list) or len(values) > 100:
        issues.append({"field": "values", "code": "array_of_at_most_100_required"})
        count = None
    else:
        count = len(values)
        if any(not isinstance(item, str) for item in values):
            issues.append({"field": "values", "code": "all_values_must_be_strings"})
    total = completion.get("total")
    if "total" in completion and (type(total) not in (int, float)
                                   or (type(total) is float and not math.isfinite(total))
                                   or total < 0 or int(total) != total):
        issues.append({"field": "total", "code": "nonnegative_integer_required"})
        total = None
    if total is not None and count is not None and total < count:
        issues.append({"field": "total", "code": "total_less_than_returned"})
    has_more = completion.get("hasMore")
    if "hasMore" in completion and type(has_more) is not bool:
        issues.append({"field": "hasMore", "code": "boolean_required"})
        has_more = None
    if total is not None and count is not None and has_more is not None and has_more != (total > count):
        issues.append({"field": "hasMore", "code": "conflicts_with_total"})
    return {"protocol_version": protocol_version, "valid": not issues,
            "value_count": count, "total": total, "has_more": has_more,
            "issue_count": len(issues), "issues": summary.take(issues), "truncated": summary.truncated,
            "notes": ["Checks selected completion result fields and consistency when total is supplied; no request, ranking or runtime behavior is checked.",
                      "Suggestion values and metadata are omitted. Total and hasMore are optional in the MCP schema."]}


def inspect_mcp_jsonrpc_error(response, protocol_version, limit):
    summary = _Summary(response, limit)
    parser.protocol_version(protocol_version)
    value = parser.json_value(response, "MCP JSON-RPC error response")
    if not isinstance(value, dict) or value.get("jsonrpc") != "2.0" or not isinstance(value.get("error"), dict):
        raise ValueError("Supply a JSON-RPC 2.0 error response")
    error = value["error"]
    code = error.get("code")
    if type(code) is not int or not isinstance(error.get("message"), str):
        raise ValueError("MCP JSON-RPC error needs an integer code and text message")
    if "id" in value and value["id"] is not None and (type(value["id"]) not in (str, int, float)
                                                     or type(value["id"]) is float and not math.isfinite(value["id"])):
        raise ValueError("MCP JSON-RPC error id must be text, number or null")
    kind = _ERROR_CODES.get(code)
    if kind is None and protocol_version == "2026-07-28":
        kind = _MODERN_ERROR_CODES.get(code)
    if kind is None and protocol_version == "2025-11-25" and code == -32002:
        kind = "legacy_resource_not_found"
    data = error.get("data")
    version_hint_shape_valid = None
    supported_count = None
    if code == -32022 and protocol_version == "2026-07-28":
        supported = data.get("supported") if isinstance(data, dict) else None
        requested = data.get("requested") if isinstance(data, dict) else None
        version_hint_shape_valid = (isinstance(supported, list) and len(supported) <= 20
                                    and all(isinstance(item, str) for item in supported)
                                    and isinstance(requested, str))
        supported_count = len(supported) if isinstance(supported, list) and len(supported) <= 20 else None
    return {"protocol_version": protocol_version, "code": code,
            "classification": kind or "other", "known_for_version": kind is not None,
            "id_present": "id" in value, "id_is_null": value.get("id") is None if "id" in value else None,
            "data_present": "data" in error,
            "version_hint_shape_valid": version_hint_shape_valid,
            "supported_version_count": supported_count,
            "truncated": summary.truncated,
            "notes": ["Classifies selected JSON-RPC and MCP error codes for the supplied protocol version; unknown codes remain other.",
                      "Error message, data values and request ID are omitted. This does not establish failure cause or server trust."]}
