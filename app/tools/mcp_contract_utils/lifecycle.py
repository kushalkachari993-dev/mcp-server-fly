from collections import Counter
from datetime import date

from app.tools.report_utils.service import _Summary

from . import catalog_parser, flows, observability, parser


_LEGACY_VERSION = "2025-11-25"
_MODERN_VERSION = "2026-07-28"
_SUBSCRIPTION_ID = "io.modelcontextprotocol/subscriptionId"
_TASK_EXTENSION = "io.modelcontextprotocol/tasks"


def _version(value):
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
        return parsed if parsed.isoformat() == value else None
    except ValueError:
        return None


def _implementation(value):
    return (isinstance(value, dict)
            and all(isinstance(value.get(key), str) and 0 < len(value[key]) <= 1000
                    for key in ("name", "version")))


def _uri(value):
    try:
        catalog_parser._text(value, "resource URI", 10000)
        return catalog_parser.scheme(value) is not None and not any(char.isspace() for char in value)
    except ValueError:
        return False


def _ack(request, raw, issues, label):
    kind, payload = flows._response(raw, issues)
    if isinstance(raw, dict) and (type(raw.get("id")) not in (str, int) or raw.get("id") != request["id"]):
        observability._issue(issues, label + "_response_id_mismatch")
    if kind != "result":
        observability._issue(issues, label + "_ack_missing")
        return False
    if (not isinstance(payload, dict) or set(payload) - {"_meta"}
            or "_meta" in payload and not isinstance(payload["_meta"], dict)):
        observability._issue(issues, label + "_ack_shape_invalid")
        return False
    return isinstance(raw, dict) and raw.get("id") == request["id"]


def validate_mcp_initialize_roundtrip(request, response, initialized, supported_versions, limit):
    summary = _Summary(request, limit)
    _Summary(response, limit)
    _Summary(initialized, limit)
    _Summary(supported_versions, limit)
    call = observability._request(parser.json_value(request, "MCP initialize request"),
                                 "MCP initialize request")
    raw = parser.json_value(response, "MCP initialize response")
    supported = None
    if supported_versions:
        supported = observability._array(supported_versions, "MCP client supported versions", 20, 1)
        if any(_version(value) is None for value in supported) or len(set(supported)) != len(supported):
            raise ValueError("supported_versions must contain unique protocol date strings")
    issues = []
    if call["method"] != "initialize":
        observability._issue(issues, "initialize_method_required")
    params = call["params"]
    requested_version = params.get("protocolVersion")
    if _version(requested_version) is None:
        observability._issue(issues, "requested_version_invalid")
    if not isinstance(params.get("capabilities"), dict):
        observability._issue(issues, "client_capabilities_invalid")
    if not _implementation(params.get("clientInfo")):
        observability._issue(issues, "client_info_invalid")
    if supported is not None and requested_version not in supported:
        observability._issue(issues, "requested_version_not_supported_by_client")
    kind, payload = flows._response(raw, issues)
    if isinstance(raw, dict) and (type(raw.get("id")) not in (str, int) or raw.get("id") != call["id"]):
        observability._issue(issues, "initialize_response_id_mismatch")
    negotiated = None
    if kind == "result":
        if not isinstance(payload, dict):
            observability._issue(issues, "initialize_result_invalid")
        else:
            negotiated = payload.get("protocolVersion")
            parsed = _version(negotiated)
            if parsed is None or parsed > date.fromisoformat(_LEGACY_VERSION):
                observability._issue(issues, "negotiated_legacy_version_invalid")
            if not isinstance(payload.get("capabilities"), dict):
                observability._issue(issues, "server_capabilities_invalid")
            if not _implementation(payload.get("serverInfo")):
                observability._issue(issues, "server_info_invalid")
            if supported is not None and negotiated not in supported:
                observability._issue(issues, "negotiated_version_not_supported_by_client")
    elif kind == "error":
        if (not isinstance(payload, dict) or type(payload.get("code")) is not int
                or not isinstance(payload.get("message"), str)):
            observability._issue(issues, "initialize_error_shape_invalid")
    if initialized:
        notice = parser.json_value(initialized, "MCP initialized notification")
        if (not isinstance(notice, dict) or notice.get("jsonrpc") != "2.0"
                or notice.get("method") != "notifications/initialized"
                or any(key in notice for key in ("id", "result", "error"))
                or not isinstance(notice.get("params", {}), dict)):
            observability._issue(issues, "initialized_notification_invalid")
        if kind != "result":
            observability._issue(issues, "initialized_without_success")
    elif kind == "result":
        observability._issue(issues, "initialized_notification_missing")
    return observability._output(summary, issues, protocol_version=_LEGACY_VERSION,
                                 outcome="success" if kind == "result" else "jsonrpc_error" if kind == "error" else None,
                                 initialized_seen=bool(initialized),
                                 version_changed=(negotiated != requested_version if negotiated is not None else None),
                                 client_support_known=supported is not None,
                                 compatible=(negotiated in supported if negotiated is not None and supported is not None else None),
                                 notes=["Checks selected 2025-era initialize request/response fields, ID and initialized notification offline.",
                                        "A different negotiated version is valid when the client supports it; provide supported_versions to check that.",
                                        "Capabilities are shape-checked, not feature-tested. Names, IDs, instructions and error text are omitted."])


def inspect_mcp_resource_subscription_flow(subscribe_request, subscribe_result, notifications,
                                           unsubscribe_request, unsubscribe_result, limit):
    summary = _Summary(subscribe_request, limit)
    for content in (subscribe_result, notifications, unsubscribe_request, unsubscribe_result):
        _Summary(content, limit)
    subscribe = observability._request(parser.json_value(subscribe_request, "MCP subscribe request"),
                                      "MCP subscribe request")
    ack = parser.json_value(subscribe_result, "MCP subscribe result")
    events = observability._array(notifications, "MCP resource update notifications", 100)
    if bool(unsubscribe_request) != bool(unsubscribe_result):
        raise ValueError("Supply both unsubscribe_request and unsubscribe_result, or neither")
    issues = []
    if subscribe["method"] != "resources/subscribe":
        observability._issue(issues, "subscribe_method_required")
    uri = subscribe["params"].get("uri")
    if not _uri(uri):
        observability._issue(issues, "subscribe_uri_invalid")
    subscribed = _ack(subscribe, ack, issues, "subscribe")
    matched = 0
    for index, event in enumerate(events):
        if (not isinstance(event, dict) or event.get("jsonrpc") != "2.0"
                or event.get("method") != "notifications/resources/updated"
                or any(key in event for key in ("id", "result", "error"))
                or not isinstance(event.get("params"), dict)):
            observability._issue(issues, "resource_update_notification_invalid", index)
            continue
        updated_uri = event["params"].get("uri")
        if not _uri(updated_uri):
            observability._issue(issues, "updated_uri_invalid", index)
        elif updated_uri != uri:
            observability._issue(issues, "updated_uri_mismatch", index)
        else:
            matched += 1
    unsubscribed = False
    if unsubscribe_request:
        unsubscribe = observability._request(parser.json_value(unsubscribe_request, "MCP unsubscribe request"),
                                            "MCP unsubscribe request")
        unack = parser.json_value(unsubscribe_result, "MCP unsubscribe result")
        if unsubscribe["method"] != "resources/unsubscribe":
            observability._issue(issues, "unsubscribe_method_required")
        if not _uri(unsubscribe["params"].get("uri")) or unsubscribe["params"]["uri"] != uri:
            observability._issue(issues, "unsubscribe_uri_mismatch")
        unsubscribed = _ack(unsubscribe, unack, issues, "unsubscribe")
    return observability._output(summary, issues, protocol_version=_LEGACY_VERSION,
                                 notification_count=len(events), matching_update_count=matched,
                                 subscribe_acknowledged=subscribed, unsubscribe_acknowledged=unsubscribed,
                                 notes=["Checks one supplied 2025 resource subscription, matching update notifications and optional unsubscribe exchange offline.",
                                        "Updates are assumed to be filtered for this subscription; capture order, delivery completeness and subscription capability are not proven.",
                                        "A notification racing with unsubscribe is not judged here. URIs, IDs and metadata are omitted."])


def inspect_mcp_cancellation_flow(request, cancellation, late_response, task_augmented, limit):
    summary = _Summary(request, limit)
    _Summary(cancellation, limit)
    _Summary(late_response, limit)
    if type(task_augmented) is not bool:
        raise ValueError("task_augmented must be a boolean")
    call = observability._request(parser.json_value(request, "MCP in-progress request"),
                                 "MCP in-progress request")
    notice = parser.json_value(cancellation, "MCP cancellation notification")
    issues = []
    if call["method"] == "initialize":
        observability._issue(issues, "initialize_cannot_be_cancelled")
    if task_augmented:
        observability._issue(issues, "task_cancel_required")
    if (not isinstance(notice, dict) or notice.get("jsonrpc") != "2.0"
            or notice.get("method") != "notifications/cancelled"
            or any(key in notice for key in ("id", "result", "error"))
            or not isinstance(notice.get("params"), dict)):
        observability._issue(issues, "cancellation_notification_invalid")
    else:
        params = notice["params"]
        if type(params.get("requestId")) not in (str, int) or params["requestId"] != call["id"]:
            observability._issue(issues, "cancelled_request_id_mismatch")
        if "reason" in params and not isinstance(params["reason"], str):
            observability._issue(issues, "cancellation_reason_invalid")
    if late_response:
        raw = parser.json_value(late_response, "MCP late response")
        kind, payload = flows._response(raw, issues)
        if isinstance(raw, dict) and (type(raw.get("id")) not in (str, int) or raw.get("id") != call["id"]):
            observability._issue(issues, "late_response_id_mismatch")
        if kind == "result" and not isinstance(payload, dict):
            observability._issue(issues, "late_result_invalid")
        if kind == "error" and (not isinstance(payload, dict) or type(payload.get("code")) is not int
                                or not isinstance(payload.get("message"), str)):
            observability._issue(issues, "late_error_invalid")
    return observability._output(summary, issues, protocol_version=_LEGACY_VERSION,
                                 late_response_seen=bool(late_response), race_possible=bool(late_response),
                                 task_augmented_declared=task_augmented,
                                 notes=["Checks selected 2025 cancellation notification shape and request ID offline.",
                                        "A late response can race with cancellation and is not itself a violation; the receiver may ignore cancellation.",
                                        "Request direction, in-progress state, task augmentation and transport timing cannot be independently verified. IDs, reasons and payloads are omitted."])


def inspect_mcp_task_notification_sequence(listen_request, notifications, limit):
    summary = _Summary(listen_request, limit)
    _Summary(notifications, limit)
    listen = observability._request(parser.json_value(listen_request, "MCP task listen request"),
                                   "MCP task listen request")
    events = observability._array(notifications, "MCP task notifications", 100)
    issues = []
    if listen["method"] != "subscriptions/listen":
        observability._issue(issues, "listen_method_required")
    filters = listen["params"].get("notifications")
    task_ids = filters.get("taskIds") if isinstance(filters, dict) else None
    if (not isinstance(task_ids, list) or not task_ids or len(task_ids) > 100
            or any(not isinstance(item, str) or not item or len(item) > 1000 for item in task_ids)):
        observability._issue(issues, "task_filter_invalid")
        subscribed = set()
    else:
        subscribed = set(task_ids)
        if len(subscribed) != len(task_ids):
            observability._issue(issues, "task_filter_duplicate")
    meta = listen["params"].get("_meta")
    capabilities = meta.get("io.modelcontextprotocol/clientCapabilities") if isinstance(meta, dict) else None
    extensions = capabilities.get("extensions") if isinstance(capabilities, dict) else None
    if not isinstance(extensions, dict) or not isinstance(extensions.get(_TASK_EXTENSION), dict):
        observability._issue(issues, "task_extension_not_declared")
    previous = {}
    for index, event in enumerate(events):
        if (not isinstance(event, dict) or event.get("jsonrpc") != "2.0"
                or event.get("method") != "notifications/tasks"
                or any(key in event for key in ("id", "result", "error"))
                or not isinstance(event.get("params"), dict)):
            observability._issue(issues, "task_notification_invalid", index)
            continue
        params = event["params"]
        event_meta = params.get("_meta")
        if not isinstance(event_meta, dict) or event_meta.get(_SUBSCRIPTION_ID) != listen["id"]:
            observability._issue(issues, "subscription_id_mismatch", index)
        task_id = params.get("taskId")
        if not isinstance(task_id, str) or task_id not in subscribed:
            observability._issue(issues, "task_not_subscribed", index)
        created, updated, status = observability._task_shape(params, issues, index)
        if not isinstance(task_id, str) or not task_id or len(task_id) > 1000:
            continue
        if task_id in previous:
            before_created, before_updated, before_status = previous[task_id]
            if before_created is not None and created is not None and before_created != created:
                observability._issue(issues, "task_created_at_changed", index)
            if before_updated is not None and updated is not None and updated < before_updated:
                observability._issue(issues, "task_last_updated_regressed", index)
            if isinstance(before_status, str) and before_status in observability._TERMINAL and status != before_status:
                observability._issue(issues, "task_left_terminal_state", index)
            previous[task_id] = (before_created or created, updated or before_updated, status)
        else:
            previous[task_id] = (created, updated, status)
    last_status_counts = Counter(status for _, _, status in previous.values()
                                 if isinstance(status, str) and status in observability._STATUSES)
    return observability._output(summary, issues, protocol_version=_MODERN_VERSION,
                                 notification_count=len(events), subscribed_task_count=len(subscribed),
                                 observed_task_count=len(previous), last_status_counts=dict(last_status_counts),
                                 notes=["Checks selected 2026 notifications/tasks shapes and per-task status progression on one listen stream offline.",
                                        "The supplied array contains task notifications only; use validate_mcp_subscription_stream to inspect acknowledgment and other frames.",
                                        "Missing delivery, polling consistency and authorization are not proven. Task IDs, input requests, results and status messages are omitted."])
