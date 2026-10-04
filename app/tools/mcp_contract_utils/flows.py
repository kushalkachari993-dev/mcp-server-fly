from collections import Counter

from app.tools.report_utils.service import _Summary

from . import observability, parser, runtime


_VERSION = "2026-07-28"
_INVALIDATIONS = {
    "tools/list": "notifications/tools/list_changed",
    "prompts/list": "notifications/prompts/list_changed",
    "resources/list": "notifications/resources/list_changed",
    "resources/templates/list": "notifications/resources/list_changed",
    "resources/read": "notifications/resources/updated",
}


def _response(raw, issues):
    if not isinstance(raw, dict) or raw.get("jsonrpc") != "2.0":
        observability._issue(issues, "response_envelope_invalid")
        return None, None
    has_result, has_error = "result" in raw, "error" in raw
    if has_result == has_error:
        observability._issue(issues, "response_result_or_error_required")
        return None, None
    return ("result" if has_result else "error"), raw["result" if has_result else "error"]


def validate_mcp_tool_content_blocks(result, protocol_version, limit):
    summary = _Summary(result, limit)
    parser.protocol_version(protocol_version)
    value = observability._result(parser.json_value(result, "MCP tool result"), "MCP tool result")
    result_type = value.get("resultType")
    if protocol_version == "2025-11-25" and result_type not in (None, "complete"):
        raise ValueError("2025 MCP tool resultType must be absent or complete")
    if protocol_version == _VERSION and result_type in ("input_required", "task"):
        return {"protocol_version": protocol_version, "checked": False, "valid": None,
                "reason": result_type,
                "notes": ["No completed tool content is available in this result; IDs and payloads are omitted."]}
    errors = []
    if protocol_version == _VERSION and result_type != "complete":
        runtime._issue(errors, "/resultType", "complete_result_type_required")
    if "isError" in value and type(value["isError"]) is not bool:
        runtime._issue(errors, "/isError", "boolean_required")
    blocks = value.get("content")
    if not isinstance(blocks, list) or len(blocks) > 500:
        runtime._issue(errors, "/content", "array_of_at_most_500_required")
        blocks = []
    counts = Counter()
    for index, block in enumerate(blocks):
        path = f"/content/{index}"
        kind = runtime._prompt_content(block, path, errors)
        if kind:
            counts[kind] += 1
        if isinstance(block, dict) and "annotations" in block and not isinstance(block["annotations"], dict):
            runtime._issue(errors, f"{path}/annotations", "object_required")
    return runtime._validation_output(protocol_version, summary, errors, content_count=len(blocks),
                                      content_kinds=dict(counts),
                                      notes=["Checks selected completed tools/call content-block shapes, base64 syntax and resource identities offline.",
                                             "Does not decode media semantics, dereference links, verify MIME types or validate structuredContent.",
                                             "Text, binary data, URIs and annotations are omitted; error paths use numeric indices only."])


def validate_mcp_call_roundtrip(request, response, protocol_version, limit):
    summary = _Summary(request, limit)
    _Summary(response, limit)
    parser.protocol_version(protocol_version)
    call = observability._request(parser.json_value(request, "MCP tool call request"), "MCP tool call request")
    raw = parser.json_value(response, "MCP tool call response")
    issues = []
    if call["method"] != "tools/call":
        observability._issue(issues, "tools_call_method_required")
    params = call["params"]
    try:
        parser.name(params.get("name"))
    except ValueError:
        observability._issue(issues, "tool_name_invalid")
    if "arguments" in params and not isinstance(params["arguments"], dict):
        observability._issue(issues, "arguments_object_required")
    kind, payload = _response(raw, issues)
    if isinstance(raw, dict) and (type(raw.get("id")) not in (str, int) or raw.get("id") != call["id"]):
        observability._issue(issues, "response_id_mismatch")
    outcome = None
    if kind == "error":
        outcome = "jsonrpc_error"
        if (not isinstance(payload, dict) or type(payload.get("code")) is not int
                or not isinstance(payload.get("message"), str)):
            observability._issue(issues, "jsonrpc_error_shape_invalid")
    elif kind == "result":
        if not isinstance(payload, dict):
            observability._issue(issues, "tool_result_object_required")
        else:
            result_type = payload.get("resultType")
            if protocol_version == "2025-11-25" and result_type not in (None, "complete"):
                observability._issue(issues, "result_type_invalid")
            if protocol_version == _VERSION and result_type not in ("complete", "input_required", "task"):
                observability._issue(issues, "result_type_invalid")
            if "isError" in payload and type(payload["isError"]) is not bool:
                observability._issue(issues, "is_error_boolean_required")
            if result_type == "task":
                meta = params.get("_meta", {})
                capabilities = meta.get("io.modelcontextprotocol/clientCapabilities", {}) if isinstance(meta, dict) else {}
                extensions = capabilities.get("extensions", {}) if isinstance(capabilities, dict) else {}
                if not isinstance(extensions, dict) or not isinstance(extensions.get("io.modelcontextprotocol/tasks"), dict):
                    observability._issue(issues, "task_extension_not_declared")
            outcome = (result_type if result_type in ("input_required", "task")
                       else "tool_error" if payload.get("isError") is True else "success")
    return observability._output(summary, issues, protocol_version=protocol_version, outcome=outcome,
                                 notes=["Separates JSON-RPC errors from successful tools/call envelopes with tool-level isError.",
                                        "Checks request/response identity and selected shapes, not content blocks, outputSchema or execution.",
                                        "Tool names, arguments, IDs, error messages and result content are omitted."])


def inspect_mcp_task_update_roundtrip(snapshot, update_request, update_result, limit):
    summary = _Summary(snapshot, limit)
    _Summary(update_request, limit)
    _Summary(update_result, limit)
    state = observability._result(parser.json_value(snapshot, "MCP task snapshot"), "MCP task snapshot")
    request = observability._request(parser.json_value(update_request, "MCP task update request"),
                                    "MCP task update request")
    raw_ack = parser.json_value(update_result, "MCP task update result")
    issues = []
    if state.get("resultType") != "complete" or state.get("status") != "input_required":
        observability._issue(issues, "input_required_snapshot_required")
    observability._task_shape(state, issues, 0)
    pending = state.get("inputRequests")
    if not isinstance(pending, dict) or not pending or len(pending) > 20:
        pending = {}
    for key, value in pending.items():
        if not isinstance(key, str) or not key or len(key) > 200:
            observability._issue(issues, "input_request_key_invalid")
        if (not isinstance(value, dict) or value.get("method") not in
                ("elicitation/create", "sampling/createMessage", "roots/list")
                or not isinstance(value.get("params"), dict)):
            observability._issue(issues, "input_request_shape_invalid")
    params = request["params"]
    if request["method"] != "tasks/update":
        observability._issue(issues, "tasks_update_method_required")
    if not isinstance(params.get("taskId"), str) or params["taskId"] != state.get("taskId"):
        observability._issue(issues, "task_id_mismatch")
    responses = params.get("inputResponses")
    if not isinstance(responses, dict) or len(responses) > 20:
        observability._issue(issues, "input_responses_invalid")
        responses = {}
    for key, value in responses.items():
        if not isinstance(key, str) or not key or len(key) > 200:
            observability._issue(issues, "input_response_key_invalid")
        if not isinstance(value, dict):
            observability._issue(issues, "input_response_shape_invalid")
    kind, ack = _response(raw_ack, issues)
    if isinstance(raw_ack, dict) and (type(raw_ack.get("id")) not in (str, int)
                                      or raw_ack.get("id") != request["id"]):
        observability._issue(issues, "ack_id_mismatch")
    acknowledged = (kind == "result" and isinstance(ack, dict)
                    and ack.get("resultType") == "complete"
                    and isinstance(raw_ack, dict) and raw_ack.get("id") == request["id"])
    if kind == "error":
        observability._issue(issues, "update_not_acknowledged")
    elif kind == "result" and not acknowledged:
        observability._issue(issues, "complete_ack_required")
    return observability._output(summary, issues, protocol_version=_VERSION,
                                 outstanding_count=len(pending), response_count=len(responses),
                                 matched_response_count=len(set(pending) & set(responses)),
                                 unexpected_response_count=len(set(responses) - set(pending)),
                                 remaining_count=len(set(pending) - set(responses)),
                                 acknowledged=acknowledged,
                                 notes=["Checks one supplied input_required task snapshot, tasks/update request and acknowledgment offline.",
                                        "Partial responses are allowed; unknown or superseded keys are counted, not rejected.",
                                        "An acknowledgment does not imply that task status has changed. IDs, keys and payloads are omitted."])


def inspect_mcp_cache_invalidation(request, response, notification, limit):
    summary = _Summary(request, limit)
    _Summary(response, limit)
    _Summary(notification, limit)
    call = observability._request(parser.json_value(request, "MCP cache request"), "MCP cache request")
    raw_result = parser.json_value(response, "MCP cache response")
    result = observability._result(raw_result, "MCP cache response")
    event = parser.json_value(notification, "MCP change notification")
    if call["method"] not in observability._CACHE_METHODS:
        raise ValueError("MCP cache request method must be cacheable in 2026")
    issues = []
    if isinstance(raw_result, dict) and "jsonrpc" in raw_result and raw_result.get("id") != call["id"]:
        observability._issue(issues, "response_id_mismatch")
    if (not isinstance(event, dict) or event.get("jsonrpc") != "2.0" or "id" in event
            or not isinstance(event.get("method"), str)
            or not isinstance(event.get("params", {}), dict)):
        observability._issue(issues, "notification_shape_invalid")
        event = {}
    method = event.get("method")
    if method not in set(_INVALIDATIONS.values()):
        observability._issue(issues, "unsupported_change_notification")
    params = call["params"]
    uri = params.get("uri")
    if call["method"] == "resources/read" and (not isinstance(uri, str) or not uri):
        observability._issue(issues, "read_uri_invalid")
    event_uri = event.get("params", {}).get("uri")
    if method == "notifications/resources/updated" and (not isinstance(event_uri, str) or not event_uri):
        observability._issue(issues, "updated_uri_invalid")
    if result.get("resultType") != "complete":
        observability._issue(issues, "complete_result_type_required")
    ttl = result.get("ttlMs")
    if type(ttl) is not int or ttl < 0:
        observability._issue(issues, "ttl_ms_invalid")
    if result.get("cacheScope") not in ("public", "private"):
        observability._issue(issues, "cache_scope_invalid")
    retry = "inputResponses" in params or "requestState" in params
    eligible = (not retry and result.get("resultType") == "complete"
                and type(ttl) is int and ttl >= 0
                and result.get("cacheScope") in ("public", "private")
                and ("jsonrpc" not in raw_result or raw_result.get("id") == call["id"])
                and (call["method"] != "resources/read" or isinstance(uri, str) and bool(uri)))
    relevant = (method == _INVALIDATIONS.get(call["method"])
                and (call["method"] != "resources/read" or uri == event_uri))
    return observability._output(summary, issues, protocol_version=_VERSION,
                                 cache_eligible=eligible, retry_request=retry,
                                 matching_notification=relevant,
                                 invalidates=eligible and relevant and not issues,
                                 notes=["Matches one supplied change notification to a 2026 cacheable request/result offline.",
                                        "List changes invalidate matching list pages; resource updates match an exact read URI. No notification is defined here for server/discover.",
                                        "MRTR retries are not cacheable; TTL freshness, delivery/subscription and authorization are not verified. URIs and values are omitted."])
