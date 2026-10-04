import json
import re

from app.tools.report_utils.service import _Summary

from . import parser, transport


_VERSION_2025 = "2025-11-25"
_VERSION_2026 = "2026-07-28"


def _issue(issues, code, index=None):
    item = {"code": code}
    if index is not None:
        item["index"] = index
    issues.append(item)


def _output(summary, issues, **fields):
    return {"valid": not issues, "issue_count": len(issues),
            "issues": summary.take(issues), "truncated": summary.truncated, **fields}


def _array(content, label, maximum, minimum=0):
    value = parser.json_value(content, label)
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} must be a JSON array of {minimum}-{maximum} entries")
    return value


def _message_kind(value):
    if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
        return None
    has_id = type(value.get("id")) in (str, int)
    if "method" in value and isinstance(value["method"], str) and value["method"]:
        if not isinstance(value.get("params", {}), dict) or "result" in value or "error" in value:
            return None
        return "request" if has_id else "notification" if "id" not in value else None
    if not has_id or ("result" in value) == ("error" in value) or "method" in value:
        return None
    if "error" in value:
        error = value["error"]
        if not isinstance(error, dict) or type(error.get("code")) is not int or not isinstance(error.get("message"), str):
            return None
        return "error"
    return "response"


def inspect_mcp_sse_trace(content, mode, protocol_version, limit):
    summary = _Summary(content, limit)
    parser.protocol_version(protocol_version)
    if mode not in ("legacy-sse", "streamable-http"):
        raise ValueError("mode must be legacy-sse or streamable-http")
    if mode == "legacy-sse" and protocol_version != _VERSION_2025:
        raise ValueError("legacy-sse mode supports only the 2025-11-25 protocol era")
    lines = re.split(r"\r\n|\n|\r", content)
    if len(lines) > 3000 or any(len(line) > 200000 for line in lines):
        raise ValueError("SSE trace must contain at most 3000 lines")
    issues = []
    counts = {key: 0 for key in ("endpoint", "request", "notification", "response", "error", "empty", "comment")}
    event_ids = set()
    frame_count = 0
    retry_count = 0
    first_event = None
    saw_response = False
    fields = {"data": []}
    touched = False

    def dispatch():
        nonlocal frame_count, retry_count, first_event, saw_response, fields, touched
        if not touched:
            return
        frame_count += 1
        if frame_count > 100:
            raise ValueError("SSE trace must contain at most 100 frames")
        index = frame_count - 1
        kind = fields.get("event", "message")
        if first_event is None:
            first_event = kind
            if mode == "legacy-sse" and kind != "endpoint":
                _issue(issues, "legacy_endpoint_event_missing", index)
        if "retry" in fields:
            retry_count += 1
        event_id = fields.get("id")
        if event_id is not None:
            if protocol_version == _VERSION_2026:
                _issue(issues, "event_id_not_supported_2026", index)
            elif event_id in event_ids:
                _issue(issues, "event_id_reused", index)
            event_ids.add(event_id)
        data = "\n".join(fields["data"])
        if kind == "endpoint":
            counts["endpoint"] += 1
            if mode != "legacy-sse":
                _issue(issues, "endpoint_event_in_streamable_http", index)
            if not data or not data.startswith("/") or data.startswith("//"):
                _issue(issues, "legacy_endpoint_invalid", index)
            if counts["endpoint"] > 1:
                _issue(issues, "legacy_endpoint_repeated", index)
        elif kind != "message":
            _issue(issues, "unsupported_event_type", index)
        elif not data:
            counts["empty"] += 1
        else:
            try:
                message = parser.json_value(data, "SSE JSON-RPC message")
            except ValueError:
                message = None
            message_kind = _message_kind(message)
            if message_kind is None:
                _issue(issues, "jsonrpc_message_invalid", index)
            else:
                counts[message_kind] += 1
                if mode == "streamable-http" and protocol_version == _VERSION_2026 and message_kind == "request":
                    _issue(issues, "server_request_not_supported_2026", index)
                if mode == "streamable-http" and saw_response:
                    _issue(issues, "message_after_response", index)
                if mode == "streamable-http" and message_kind in ("response", "error"):
                    saw_response = True
        fields = {"data": []}
        touched = False

    for line in lines:
        if not line:
            dispatch()
            continue
        if line.startswith(":"):
            counts["comment"] += 1
            continue
        name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if name not in ("data", "event", "id", "retry"):
            continue
        touched = True
        if name == "data":
            fields["data"].append(value)
        elif name == "id":
            if "\x00" in value or len(value) > 1000:
                _issue(issues, "event_id_invalid", frame_count)
            else:
                fields["id"] = value
        elif name == "retry":
            if not value.isascii() or not value.isdecimal() or len(value) > 12:
                _issue(issues, "retry_invalid", frame_count)
            else:
                fields["retry"] = int(value)
        else:
            fields["event"] = value
    partial_frame = touched
    if mode == "legacy-sse" and first_event is None:
        _issue(issues, "legacy_endpoint_event_missing")
    return _output(summary, issues, mode=mode, protocol_version=protocol_version,
                   frame_count=frame_count, counts=counts, event_id_count=len(event_ids),
                   retry_count=retry_count, partial_frame=partial_frame,
                   notes=["Analyzes supplied SSE text only; a partial final frame is reported but not dispatched.",
                          "Comments are keepalives, not malformed events. Message bodies, endpoint URLs and event IDs are omitted.",
                          "Does not prove delivery, ordering across connections or stream completeness."])


def _headers(raw, label):
    if not isinstance(raw, dict) or len(raw) > 100:
        raise ValueError(f"{label} must be an object of at most 100 headers")
    headers = {}
    for name, value in raw.items():
        if (not isinstance(name, str) or not transport._HEADER_NAME.fullmatch(name)
                or not isinstance(value, str) or len(value) > 16000
                or any(ord(char) < 32 and char != "\t" or ord(char) == 127 for char in value)):
            raise ValueError(f"{label} contains an invalid name or value")
        key = name.lower()
        if key in headers:
            raise ValueError(f"{label} contains duplicate case-insensitive names")
        headers[key] = value
    return headers


def inspect_mcp_session_recovery(exchanges, limit):
    summary = _Summary(exchanges, limit)
    rows = _array(exchanges, "MCP HTTP exchanges", 100, 1)
    issues = []
    session_id = None
    awaiting_initialize = False
    initialized = False
    known_ids = {}
    counts = {"initialize": 0, "resumption": 0, "session_expired": 0, "event_ids": 0}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("method") not in ("POST", "GET", "DELETE"):
            raise ValueError("Each exchange needs a POST, GET or DELETE method")
        method = row["method"]
        is_initialize = row.get("initialize", False)
        if type(is_initialize) is not bool:
            raise ValueError("initialize must be a boolean")
        status = row.get("response_status")
        if type(status) is not int or not 100 <= status <= 599:
            raise ValueError("response_status must be an HTTP status code")
        incoming = _headers(row.get("request_headers", {}), "MCP request headers")
        outgoing = _headers(row.get("response_headers", {}), "MCP response headers")
        ids = row.get("event_ids", [])
        if not isinstance(ids, list) or len(ids) > 100 or any(
                not isinstance(item, str) or not item or len(item) > 1000 or "\x00" in item for item in ids):
            raise ValueError("event_ids must contain at most 100 nonempty SSE IDs")
        stream = row.get("stream")
        if stream is not None and (not isinstance(stream, str) or not stream or len(stream) > 1000):
            raise ValueError("stream must be a nonempty local label when supplied")
        if is_initialize:
            counts["initialize"] += 1
            if method != "POST" or "mcp-session-id" in incoming:
                _issue(issues, "initialize_request_invalid", index)
            if 200 <= status < 300:
                session_id = outgoing.get("mcp-session-id")
                if session_id is not None and (not session_id or any(not 33 <= ord(char) <= 126 for char in session_id)):
                    _issue(issues, "session_id_invalid", index)
                    session_id = None
                known_ids.clear()
                initialized = True
                awaiting_initialize = False
            else:
                initialized = False
        else:
            if not initialized or awaiting_initialize:
                _issue(issues, "reinitialize_required", index)
            if incoming.get("mcp-protocol-version") != _VERSION_2025:
                _issue(issues, "protocol_version_header_mismatch", index)
            provided_session = incoming.get("mcp-session-id")
            if session_id is not None and provided_session != session_id:
                _issue(issues, "session_id_missing_or_mismatch", index)
            if method == "DELETE" and session_id is None:
                _issue(issues, "delete_without_session", index)
            last_id = incoming.get("last-event-id")
            if last_id is not None:
                counts["resumption"] += 1
                if method != "GET":
                    _issue(issues, "resume_requires_get", index)
                if last_id not in known_ids:
                    _issue(issues, "resume_event_id_unknown", index)
                elif stream is not None and known_ids[last_id] is not None and stream != known_ids[last_id]:
                    _issue(issues, "resume_stream_mismatch", index)
        for event_id in ids:
            counts["event_ids"] += 1
            if event_id in known_ids:
                _issue(issues, "event_id_reused", index)
            else:
                known_ids[event_id] = stream
        if not is_initialize:
            if status == 404 and provided_session is not None and provided_session == session_id:
                counts["session_expired"] += 1
                awaiting_initialize = True
            if method == "DELETE" and 200 <= status < 300:
                awaiting_initialize = True
    return _output(summary, issues, protocol_version=_VERSION_2025,
                   exchange_count=len(rows), counts=counts,
                   session_assigned=session_id is not None,
                   reinitialize_required=awaiting_initialize,
                   notes=["Checks ordered, caller-supplied 2025 Streamable HTTP exchanges only.",
                          "A 404 with a session ID requires a new initialization without that ID. Resumption uses GET and a previously seen event ID.",
                          "Stream labels are caller-supplied; cross-stream delivery and server-side replay cannot be proven. Header and ID values are omitted."])


def inspect_mcp_tool_retry_risk(manifest, attempts, protocol_version, limit):
    summary = _Summary(manifest, limit)
    _Summary(attempts, limit)
    tools, partial = parser.manifest(manifest, protocol_version)
    if partial:
        raise ValueError("Supply a complete tools/list snapshot to assess retry hints")
    rows = _array(attempts, "MCP tool call attempts", 100, 1)
    issues = []
    seen_calls = {}
    seen_ids = {}
    repeats = []
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or row.get("jsonrpc") != "2.0"
                or row.get("method") != "tools/call" or type(row.get("id")) not in (str, int)
                or not isinstance(row.get("params"), dict)):
            raise ValueError("Each attempt must be a tools/call JSON-RPC request with ID and object params")
        params = row["params"]
        name = parser.name(params.get("name"))
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("Tool call arguments must be an object when present")
        if name not in tools:
            _issue(issues, "tool_not_in_manifest", index)
        call_key = (name, json.dumps(arguments, sort_keys=True, separators=(",", ":"), allow_nan=False))
        request_id = (type(row["id"]), row["id"])
        if request_id in seen_ids:
            _issue(issues, "jsonrpc_id_reused", index)
        else:
            seen_ids[request_id] = index
        if call_key in seen_calls:
            hints = tools.get(name, {}).get("annotations", {})
            read_only = hints.get("readOnlyHint") is True
            idempotent = hints.get("idempotentHint") is True
            repeats.append({"index": index, "repeat_of_index": seen_calls[call_key],
                            "read_only_hint": read_only, "idempotent_hint": idempotent,
                            "risk": "hinted_lower_risk" if read_only or idempotent else "possible_duplicate_effect"})
        else:
            seen_calls[call_key] = index
    selected_repeats = summary.take(repeats)
    return _output(summary, issues, protocol_version=protocol_version,
                   attempt_count=len(rows), repeat_count=len(repeats),
                   repeats=selected_repeats,
                   notes=["Exact repeated tool name and JSON arguments are retry candidates, not proof of a retry or duplicate execution.",
                          "Read-only and idempotent annotations are untrusted hints, never a safety guarantee.",
                          "Tool names, arguments, request IDs and result values are omitted."])
