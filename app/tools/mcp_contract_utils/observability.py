import math
from datetime import datetime

from app.tools.report_utils.service import _Summary

from . import parser, transport


_VERSION = "2026-07-28"
_SUBSCRIPTION_ID = "io.modelcontextprotocol/subscriptionId"
_TASK_EXTENSION = "io.modelcontextprotocol/tasks"
_CACHE_METHODS = {"server/discover", "tools/list", "prompts/list", "resources/list",
                  "resources/templates/list", "resources/read"}
_LIST_METHODS = {"tools/list", "prompts/list", "resources/list", "resources/templates/list"}
_CHANGE_METHODS = {"notifications/tools/list_changed": "toolsListChanged",
                   "notifications/prompts/list_changed": "promptsListChanged",
                   "notifications/resources/list_changed": "resourcesListChanged"}
_FILTER_FLAGS = ("toolsListChanged", "promptsListChanged", "resourcesListChanged")
_TERMINAL = {"completed", "failed", "cancelled"}
_STATUSES = _TERMINAL | {"working", "input_required"}


def _issue(issues, code, index=None):
    item = {"code": code}
    if index is not None:
        item["index"] = index
    issues.append(item)


def _output(summary, issues, **fields):
    return {"valid": not issues, "issue_count": len(issues), "issues": summary.take(issues),
            "truncated": summary.truncated, **fields}


def _array(content, label, maximum, minimum=0):
    value = parser.json_value(content, label)
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} must be a JSON array of {minimum}-{maximum} entries")
    return value


def _request(value, label):
    if (not isinstance(value, dict) or value.get("jsonrpc") != "2.0"
            or type(value.get("id")) not in (str, int)
            or not isinstance(value.get("method"), str) or not value["method"]
            or not isinstance(value.get("params", {}), dict)):
        raise ValueError(f"{label} must be a JSON-RPC request with object params")
    return value


def _result(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if "jsonrpc" in value:
        if (value.get("jsonrpc") != "2.0" or "result" not in value
                or "error" in value or type(value.get("id")) not in (str, int)):
            raise ValueError(f"{label} must be a successful JSON-RPC result")
        value = value["result"]
    if not isinstance(value, dict):
        raise ValueError(f"{label} result must be an object")
    return value


def _number(value):
    if type(value) not in (int, float) or value < 0:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def inspect_mcp_progress_sequence(request, notifications, protocol_version, limit):
    summary = _Summary(request, limit)
    _Summary(notifications, limit)
    parser.protocol_version(protocol_version)
    call = _request(parser.json_value(request, "MCP progress request"), "MCP progress request")
    events = _array(notifications, "MCP progress notifications", 100)
    meta = call.get("params", {}).get("_meta", {})
    token = meta.get("progressToken") if isinstance(meta, dict) else None
    token_valid = type(token) in (str, int)
    issues = []
    if token is not None and not token_valid:
        _issue(issues, "request_progress_token_invalid")
    if events and not token_valid:
        _issue(issues, "progress_unrequested")
    previous = None
    total_count = 0
    for index, event in enumerate(events):
        if (not isinstance(event, dict) or event.get("jsonrpc") != "2.0"
                or event.get("method") != "notifications/progress" or "id" in event
                or not isinstance(event.get("params"), dict)):
            _issue(issues, "progress_notification_shape_invalid", index)
            continue
        params = event["params"]
        if type(params.get("progressToken")) not in (str, int) or params["progressToken"] != token:
            _issue(issues, "progress_token_mismatch", index)
        progress = params.get("progress")
        if not _number(progress):
            _issue(issues, "progress_value_invalid", index)
        elif (previous is not None and token_valid and params.get("progressToken") == token
              and progress <= previous):
            _issue(issues, "progress_not_increasing", index)
        if _number(progress) and params.get("progressToken") == token and token_valid:
            previous = progress
        if "total" in params:
            total_count += 1
            if not _number(params["total"]):
                _issue(issues, "total_value_invalid", index)
        if "message" in params and not isinstance(params["message"], str):
            _issue(issues, "message_must_be_text", index)
    return _output(summary, issues, protocol_version=protocol_version,
                   progress_requested=token_valid, notification_count=len(events),
                   notifications_with_total=total_count,
                   notes=["Checks selected progress notification shape, token matching and increasing values offline.",
                          "Assumes supplied notifications belong to an active request and are in arrival order; completion timing and direction are not verified.",
                          "Tokens, progress messages, request IDs and request content are omitted."])


def _filter(value, issues, label):
    if not isinstance(value, dict) or len(value) > 20:
        _issue(issues, label + "_filter_invalid")
        return {}, 0
    selected = {}
    for flag in _FILTER_FLAGS:
        if flag in value and type(value[flag]) is not bool:
            _issue(issues, label + "_flag_invalid")
        selected[flag] = value.get(flag) is True
    for key in ("resourceSubscriptions", "taskIds"):
        raw = value.get(key, [])
        if (not isinstance(raw, list) or len(raw) > 100
                or any(not isinstance(item, str) or not item or len(item) > 10000
                       or any(ord(char) < 32 for char in item) for item in raw)):
            _issue(issues, label + "_list_invalid")
            selected[key] = set()
        else:
            if len(set(raw)) != len(raw):
                _issue(issues, label + "_list_duplicate")
            selected[key] = set(raw)
    unknown = len(value.keys() - set(_FILTER_FLAGS) - {"resourceSubscriptions", "taskIds"})
    return selected, unknown


def _subscribed_resource(uri, subscriptions):
    return isinstance(uri, str) and any(uri == item or uri.startswith(item.rstrip("/") + "/")
                                             for item in subscriptions)


def validate_mcp_subscription_stream(request, events, limit):
    summary = _Summary(request, limit)
    _Summary(events, limit)
    call = _request(parser.json_value(request, "MCP listen request"), "MCP listen request")
    frames = _array(events, "MCP subscription frames", 100, 1)
    issues = []
    if call["method"] != "subscriptions/listen":
        _issue(issues, "listen_method_required")
    for code in transport._meta_issues({"params": call.get("params", {})})[0]:
        _issue(issues, code)
    requested, unknown_request_fields = _filter(call.get("params", {}).get("notifications"), issues, "request")
    capabilities = call.get("params", {}).get("_meta", {})
    capabilities = capabilities.get("io.modelcontextprotocol/clientCapabilities", {}) if isinstance(capabilities, dict) else {}
    extensions = capabilities.get("extensions", {}) if isinstance(capabilities, dict) else {}
    if requested.get("taskIds") and (not isinstance(extensions, dict)
                                      or not isinstance(extensions.get(_TASK_EXTENSION), dict)):
        _issue(issues, "task_extension_not_declared")
    first = frames[0]
    acknowledged = (isinstance(first, dict)
                    and first.get("method") == "notifications/subscriptions/acknowledged")
    if not acknowledged:
        _issue(issues, "ack_missing_or_not_first")
    honored = {}
    unknown_ack_fields = 0
    closed = False
    notification_count = 0
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict) or frame.get("jsonrpc") != "2.0":
            _issue(issues, "frame_shape_invalid", index)
            continue
        if "result" in frame or "error" in frame:
            if (closed or not acknowledged or index != len(frames) - 1 or frame.get("id") != call["id"]
                    or "error" in frame or not isinstance(frame.get("result"), dict)
                    or frame["result"].get("resultType") != "complete"):
                _issue(issues, "close_result_invalid", index)
            closed = True
            continue
        if closed:
            _issue(issues, "notification_after_close", index)
        if "id" in frame or not isinstance(frame.get("params"), dict):
            _issue(issues, "notification_shape_invalid", index)
            continue
        params = frame["params"]
        meta = params.get("_meta")
        if not isinstance(meta, dict) or meta.get(_SUBSCRIPTION_ID) != call["id"]:
            _issue(issues, "subscription_id_mismatch", index)
        method = frame.get("method")
        if method == "notifications/subscriptions/acknowledged":
            if index != 0:
                _issue(issues, "ack_not_first_or_duplicate", index)
            honored, unknown_ack_fields = _filter(params.get("notifications"), issues, "ack")
            for flag in _FILTER_FLAGS:
                if honored.get(flag) and not requested.get(flag):
                    _issue(issues, "ack_exceeds_requested_filter", index)
            for key in ("resourceSubscriptions", "taskIds"):
                if honored.get(key, set()) - requested.get(key, set()):
                    _issue(issues, "ack_exceeds_requested_filter", index)
            continue
        notification_count += 1
        if isinstance(method, str) and method in _CHANGE_METHODS:
            if not honored.get(_CHANGE_METHODS[method]):
                _issue(issues, "notification_not_subscribed", index)
        elif method == "notifications/resources/updated":
            if not _subscribed_resource(params.get("uri"), honored.get("resourceSubscriptions", set())):
                _issue(issues, "resource_update_not_subscribed", index)
        elif method == "notifications/tasks":
            task_id = params.get("taskId")
            if not isinstance(task_id, str) or task_id not in honored.get("taskIds", set()):
                _issue(issues, "task_update_not_subscribed", index)
        else:
            _issue(issues, "unsupported_stream_notification", index)
    return _output(summary, issues, protocol_version=_VERSION, acknowledged=acknowledged,
                   notification_count=notification_count, graceful_close_seen=closed,
                   unverified_filter_field_count=unknown_request_fields + unknown_ack_fields,
                   notes=["Checks selected 2026 subscriptions/listen acknowledgments, filters, stream IDs and change notifications offline.",
                          "Resource child-URI matching is a conservative string-prefix check; authorization and event delivery completeness cannot be established.",
                          "IDs, resource URIs, task IDs, notification payloads and request metadata are omitted."])


def validate_mcp_cache_hints(method, responses, user_scoped, limit):
    summary = _Summary(responses, limit)
    if not isinstance(method, str) or method not in _CACHE_METHODS:
        raise ValueError("method must be a 2026 cacheable MCP method")
    if type(user_scoped) is not bool:
        raise ValueError("user_scoped must be a boolean")
    pages = _array(responses, "MCP cache responses", 20, 1)
    if method not in _LIST_METHODS and len(pages) != 1:
        raise ValueError("Only list methods accept multiple response pages")
    issues = []
    scope_first = None
    complete_count = input_required_count = public_count = private_count = 0
    for index, page in enumerate(pages):
        value = _result(page, "MCP cache response")
        result_type = value.get("resultType")
        if result_type == "input_required":
            input_required_count += 1
            if "ttlMs" in value or "cacheScope" in value:
                _issue(issues, "input_required_has_cache_hints", index)
            continue
        if result_type != "complete":
            _issue(issues, "complete_result_type_required", index)
            continue
        complete_count += 1
        ttl = value.get("ttlMs")
        if type(ttl) is not int or ttl < 0:
            _issue(issues, "ttl_ms_invalid", index)
        scope = value.get("cacheScope")
        if scope not in ("public", "private"):
            _issue(issues, "cache_scope_invalid", index)
            continue
        if scope == "public":
            public_count += 1
            if user_scoped:
                _issue(issues, "user_scoped_result_declared_public", index)
        else:
            private_count += 1
        if scope_first is None:
            scope_first = scope
        elif scope != scope_first:
            _issue(issues, "page_cache_scope_changed", index)
    return _output(summary, issues, protocol_version=_VERSION, response_count=len(pages),
                   complete_count=complete_count, input_required_count=input_required_count,
                   public_count=public_count, private_count=private_count,
                   notes=["Checks selected 2026 cache hints on supplied complete results; array entries are pages of one list request.",
                          "user_scoped is caller-declared; this tool cannot infer whether content is actually safe to share.",
                          "Input-required results and retries carrying inputResponses or requestState must not be cached. Response content is omitted."])


def _timestamp(value):
    if not isinstance(value, str) or not value or len(value) > 100:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _task_shape(value, issues, index):
    if not isinstance(value.get("taskId"), str) or not value["taskId"] or len(value["taskId"]) > 1000:
        _issue(issues, "task_id_invalid", index)
    status = value.get("status")
    if not isinstance(status, str) or status not in _STATUSES:
        _issue(issues, "task_status_invalid", index)
    if "statusMessage" in value and not isinstance(value["statusMessage"], str):
        _issue(issues, "task_status_message_invalid", index)
    created, updated = _timestamp(value.get("createdAt")), _timestamp(value.get("lastUpdatedAt"))
    if created is None or updated is None or updated < created:
        _issue(issues, "task_timestamps_invalid", index)
    ttl = value.get("ttlMs", object())
    if ttl is not None and (type(ttl) is not int or ttl < 0):
        _issue(issues, "task_ttl_invalid", index)
    if "pollIntervalMs" in value and (type(value["pollIntervalMs"]) is not int or value["pollIntervalMs"] < 0):
        _issue(issues, "task_poll_interval_invalid", index)
    if status == "input_required" and (not isinstance(value.get("inputRequests"), dict)
                                        or not value["inputRequests"] or len(value["inputRequests"]) > 20):
        _issue(issues, "input_requests_invalid", index)
    if status == "completed" and not isinstance(value.get("result"), dict):
        _issue(issues, "completed_result_missing", index)
    if status == "failed":
        error = value.get("error")
        if (not isinstance(error, dict) or type(error.get("code")) is not int
                or not isinstance(error.get("message"), str)):
            _issue(issues, "failed_error_invalid", index)
    return created, updated, status


def inspect_mcp_task_lifecycle(create_result, snapshots, cancel_request, cancel_result, limit):
    summary = _Summary(create_result, limit)
    _Summary(snapshots, limit)
    _Summary(cancel_request, limit)
    _Summary(cancel_result, limit)
    creation = _result(parser.json_value(create_result, "MCP task creation result"), "MCP task creation result")
    polls = _array(snapshots, "MCP task snapshots", 100)
    if bool(cancel_request) != bool(cancel_result):
        raise ValueError("Supply both cancel_request and cancel_result, or neither")
    issues = []
    if creation.get("resultType") != "task":
        _issue(issues, "task_creation_result_type_required")
    created, previous_update, previous_status = _task_shape(creation, issues, -1)
    task_id = creation.get("taskId")
    for index, raw in enumerate(polls):
        value = _result(raw, "MCP task snapshot")
        if value.get("resultType") != "complete":
            _issue(issues, "task_snapshot_result_type_required", index)
        if value.get("taskId") != task_id:
            _issue(issues, "task_id_changed", index)
        current_created, updated, status = _task_shape(value, issues, index)
        if created is not None and current_created is not None and current_created != created:
            _issue(issues, "task_created_at_changed", index)
        if previous_update is not None and updated is not None and updated < previous_update:
            _issue(issues, "task_last_updated_regressed", index)
        if isinstance(previous_status, str) and previous_status in _TERMINAL and status != previous_status:
            _issue(issues, "task_left_terminal_state", index)
        previous_update, previous_status = updated, status
    cancelled = False
    if cancel_request:
        request = _request(parser.json_value(cancel_request, "MCP task cancel request"), "MCP task cancel request")
        response = parser.json_value(cancel_result, "MCP task cancel result")
        value = _result(response, "MCP task cancel result")
        if request["method"] != "tasks/cancel" or request.get("params", {}).get("taskId") != task_id:
            _issue(issues, "cancel_request_task_mismatch")
        if not isinstance(response, dict) or response.get("id") != request["id"]:
            _issue(issues, "cancel_response_id_mismatch")
        if value.get("resultType") != "complete":
            _issue(issues, "cancel_ack_result_type_required")
        cancelled = True
    return _output(summary, issues, protocol_version=_VERSION, snapshot_count=len(polls),
                   last_observed_status=(previous_status if isinstance(previous_status, str)
                                         and previous_status in _STATUSES else None),
                   cancel_ack_supplied=cancelled,
                   notes=["Checks selected 2026 Tasks extension creation, tasks/get snapshots and optional tasks/cancel acknowledgement offline.",
                          "A cancel acknowledgement does not guarantee a cancelled terminal state; task update requests, polling intervals and authorization are not verified.",
                          "Task IDs, request IDs, input requests, status messages, results and errors are omitted."])
