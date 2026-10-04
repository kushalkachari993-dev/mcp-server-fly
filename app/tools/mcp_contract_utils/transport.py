import base64
import binascii
import re
from urllib.parse import urlsplit
from urllib.request import parse_http_list, parse_keqv_list

from app.tools.report_utils.service import _Summary

from . import parser


_VERSION = "2026-07-28"
_META_VERSION = "io.modelcontextprotocol/protocolVersion"
_META_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
_META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
_META_LOG_LEVEL = "io.modelcontextprotocol/logLevel"
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}\Z")
_SENTINEL = re.compile(r"=\?base64\?([A-Za-z0-9+/]*={0,2})\?=\Z")
_NAMED_METHODS = {"tools/call": "name", "prompts/get": "name", "resources/read": "uri"}
_INPUT_METHODS = {"elicitation/create", "sampling/createMessage", "roots/list"}
_LOG_LEVELS = {"debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"}


def _request(content, label):
    value = parser.json_value(content, label)
    if (not isinstance(value, dict) or value.get("jsonrpc") != "2.0"
            or not isinstance(value.get("method"), str) or not value["method"]
            or "id" not in value or type(value["id"]) not in (str, int)):
        raise ValueError(f"{label} must be a JSON-RPC 2.0 request with a method and ID")
    if not isinstance(value.get("params"), dict):
        raise ValueError(f"{label} params must be an object")
    return value


def _meta_issues(request):
    issues = []
    meta = request["params"].get("_meta")
    if not isinstance(meta, dict) or len(meta) > 100:
        return ["request_meta_object_required"], None
    if meta.get(_META_VERSION) != _VERSION:
        issues.append("protocol_version_missing_or_wrong")
    capabilities = meta.get(_META_CAPABILITIES)
    if not isinstance(capabilities, dict) or len(capabilities) > 100:
        issues.append("client_capabilities_object_required")
        capability_count = None
    else:
        capability_count = len(capabilities)
        for key in ("elicitation", "sampling", "roots", "experimental", "extensions"):
            if key in capabilities and not isinstance(capabilities[key], dict):
                issues.append("known_capability_must_be_object")
                break
    if _META_CLIENT_INFO in meta:
        info = meta[_META_CLIENT_INFO]
        if (not isinstance(info, dict)
                or any(not isinstance(info.get(key), str) or not info[key]
                       for key in ("name", "version"))):
            issues.append("client_info_shape_invalid")
    if (_META_LOG_LEVEL in meta and
            (not isinstance(meta[_META_LOG_LEVEL], str) or meta[_META_LOG_LEVEL] not in _LOG_LEVELS)):
        issues.append("log_level_invalid")
    return issues, capability_count


def validate_mcp_request_metadata(request, limit):
    summary = _Summary(request, limit)
    value = _request(request, "MCP request")
    issues, capability_count = _meta_issues(value)
    meta = value["params"].get("_meta")
    return {"protocol_version": _VERSION, "valid": not issues,
            "client_info_present": isinstance(meta, dict) and _META_CLIENT_INFO in meta,
            "capability_count": capability_count, "issue_count": len(issues),
            "issues": summary.take(issues), "truncated": summary.truncated,
            "notes": ["Checks selected 2026 per-request metadata, not the full method-specific request schema.",
                      "Client identity and capabilities are self-reported; no values are returned or trusted."]}


def _headers(content, label):
    raw = parser.json_value(content, label)
    if not isinstance(raw, dict) or len(raw) > 100:
        raise ValueError(f"{label} must be an object of at most 100 headers")
    headers = {}
    for name, value in raw.items():
        if (not isinstance(name, str) or not _HEADER_NAME.fullmatch(name)
                or not isinstance(value, str) or len(value) > 16000
                or any(ord(char) < 32 and char != "\t" or ord(char) == 127 for char in value)):
            raise ValueError(f"{label} contains an invalid name or value")
        normalized = name.lower()
        if normalized in headers:
            raise ValueError(f"{label} contains duplicate case-insensitive names")
        headers[normalized] = value
    return headers


def _mirrored_name(value):
    match = _SENTINEL.fullmatch(value)
    if match:
        try:
            decoded = base64.b64decode(match.group(1), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None
        return decoded
    if value.startswith("=?base64?") or value.endswith("?="):
        return None
    if value != value.strip() or any(ord(char) < 32 or ord(char) > 126 for char in value):
        return None
    return value


def validate_mcp_http_exchange(request, request_headers, response_status, response_headers, limit):
    summary = _Summary(request, limit)
    _Summary(request_headers, limit)
    _Summary(response_headers, limit)
    value = _request(request, "MCP HTTP request")
    incoming = _headers(request_headers, "MCP request headers")
    outgoing = _headers(response_headers, "MCP response headers")
    if type(response_status) is not int or not 100 <= response_status <= 599:
        raise ValueError("response_status must be an HTTP status code")
    issues, _ = _meta_issues(value)
    if incoming.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        issues.append("request_content_type_invalid")
    accepted = {part.split(";", 1)[0].strip().lower() for part in incoming.get("accept", "").split(",")}
    if not {"application/json", "text/event-stream"}.issubset(accepted):
        issues.append("request_accept_missing_types")
    meta = value["params"].get("_meta")
    if incoming.get("mcp-protocol-version") != (meta.get(_META_VERSION) if isinstance(meta, dict) else None):
        issues.append("protocol_version_header_mismatch")
    if incoming.get("mcp-method") != value["method"]:
        issues.append("method_header_mismatch")
    name_key = _NAMED_METHODS.get(value["method"])
    if name_key is not None:
        name = value["params"].get(name_key)
        if not isinstance(name, str) or not name:
            issues.append("named_request_parameter_missing")
        elif _mirrored_name(incoming.get("mcp-name", "")) != name:
            issues.append("name_header_mismatch")
    if response_status == 200:
        media_type = outgoing.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type not in ("application/json", "text/event-stream"):
            issues.append("response_content_type_invalid")
    return {"protocol_version": _VERSION, "valid": not issues,
            "response_status": response_status, "response_is_error": response_status >= 400,
            "named_method": name_key is not None, "issue_count": len(issues),
            "issues": summary.take(issues), "truncated": summary.truncated,
            "notes": ["Checks selected 2026 Streamable HTTP request headers and a response status/content type; no network call.",
                      "Does not inspect response bodies, SSE framing, authorization or custom Mcp-Param headers.",
                      "HTTP error statuses are reported, not automatically treated as protocol violations. Header values are omitted."]}


def _result(content):
    value = parser.json_value(content, "MCP input-required result")
    if not isinstance(value, dict):
        raise ValueError("MCP input-required result must be an object")
    if "jsonrpc" in value:
        if value.get("jsonrpc") != "2.0" or "result" not in value or "error" in value:
            raise ValueError("Supply a successful JSON-RPC result")
        value = value["result"]
    if not isinstance(value, dict):
        raise ValueError("MCP input-required result must contain an object")
    return value


def inspect_mcp_input_required_roundtrip(initial_request, result, retry_request, limit):
    summary = _Summary(initial_request, limit)
    _Summary(result, limit)
    _Summary(retry_request, limit)
    initial = _request(initial_request, "Initial MCP request")
    retry = _request(retry_request, "Retry MCP request")
    supplied = _result(result)
    issues = []
    for request in (initial, retry):
        issues.extend(_meta_issues(request)[0])
    if initial["method"] not in _NAMED_METHODS:
        issues.append("method_does_not_support_input_required")
    if supplied.get("resultType") != "input_required":
        issues.append("input_required_result_type_missing")
    requested = supplied.get("inputRequests")
    if "inputRequests" in supplied:
        if not isinstance(requested, dict) or len(requested) > 20:
            raise ValueError("inputRequests must be an object of at most 20 entries")
        for key, item in requested.items():
            if not isinstance(key, str) or not key or len(key) > 200:
                issues.append("input_request_id_invalid")
            if (not isinstance(item, dict) or not isinstance(item.get("method"), str)
                    or item["method"] not in _INPUT_METHODS
                    or not isinstance(item.get("params"), dict)):
                issues.append("input_request_shape_invalid")
    else:
        requested = {}
    if "requestState" in supplied and not isinstance(supplied["requestState"], str):
        issues.append("request_state_must_be_text")
    if "inputRequests" not in supplied and "requestState" not in supplied:
        issues.append("input_requests_or_state_required")
    if retry["method"] != initial["method"]:
        issues.append("retry_method_changed")
    if retry["id"] == initial["id"]:
        issues.append("retry_id_not_new")
    previous = {key: item for key, item in initial["params"].items()
                if key not in ("_meta", "inputResponses", "requestState")}
    current = {key: item for key, item in retry["params"].items()
               if key not in ("_meta", "inputResponses", "requestState")}
    if previous != current:
        issues.append("retry_parameters_changed")
    if (("requestState" in supplied) != ("requestState" in retry["params"])
            or ("requestState" in supplied and supplied["requestState"] != retry["params"].get("requestState"))):
        issues.append("request_state_not_echoed")
    responses = retry["params"].get("inputResponses", {})
    if not isinstance(responses, dict) or len(responses) > 20:
        raise ValueError("inputResponses must be an object of at most 20 entries")
    if set(requested) - set(responses):
        issues.append("input_responses_missing")
    if any(not isinstance(item, dict) for item in responses.values()):
        issues.append("input_response_shape_invalid")
    return {"protocol_version": _VERSION, "valid": not issues,
            "input_request_count": len(requested), "input_response_count": len(responses),
            "unexpected_response_count": len(set(responses) - set(requested)),
            "request_state_present": "requestState" in supplied,
            "issue_count": len(issues), "issues": summary.take(issues), "truncated": summary.truncated,
            "notes": ["Checks selected 2026 multi-round-trip structure and byte-exact state echo, not state authenticity.",
                      "Request and response identifiers, input payloads and requestState are never returned.",
                      "Unexpected inputResponses are counted but not rejected because servers may ignore them."]}


def _https_url(value):
    if (not isinstance(value, str) or len(value) > 2000 or not value
            or any(char.isspace() or ord(char) < 32 for char in value)):
        return False
    try:
        parts = urlsplit(value)
        return (parts.scheme == "https" and bool(parts.hostname) and parts.username is None
                and parts.password is None and not parts.fragment and parts.port != 0)
    except ValueError:
        return False


def _bearer_challenge(content):
    if (not isinstance(content, str) or not content.lower().startswith("bearer ") or len(content) > 8000
            or any(ord(char) < 32 or ord(char) == 127 for char in content)):
        raise ValueError("challenge must be one Bearer WWW-Authenticate header of at most 8000 characters")
    parts = parse_http_list(content[7:])
    if not parts or len(parts) > 20:
        raise ValueError("Bearer challenge must contain 1-20 parameters")
    names = []
    for part in parts:
        if "=" not in part:
            raise ValueError("Bearer challenge parameters must be key=value pairs")
        key = part.split("=", 1)[0].strip().lower()
        if not _HEADER_NAME.fullmatch(key) or key in names:
            raise ValueError("Bearer challenge parameter names must be distinct tokens")
        names.append(key)
    return {key.lower(): value for key, value in parse_keqv_list(parts).items()}


def inspect_mcp_auth_discovery(challenge, resource_metadata, authorization_metadata, resource_url, limit):
    summary = _Summary(challenge, limit)
    for content in (resource_metadata, authorization_metadata, resource_url):
        _Summary(content, limit)
    params = _bearer_challenge(challenge)
    resource = parser.json_value(resource_metadata, "MCP protected resource metadata")
    authorization = parser.json_value(authorization_metadata, "MCP authorization server metadata")
    if not isinstance(resource, dict) or not isinstance(authorization, dict):
        raise ValueError("MCP authorization metadata must be JSON objects")
    issues = []
    if not _https_url(resource_url):
        issues.append("resource_url_invalid")
    if not _https_url(params.get("resource_metadata")):
        issues.append("resource_metadata_challenge_missing_or_invalid")
    if not _https_url(resource.get("resource")) or resource.get("resource") != resource_url:
        issues.append("resource_identifier_mismatch")
    servers = resource.get("authorization_servers")
    if (not isinstance(servers, list) or not 1 <= len(servers) <= 20
            or any(not _https_url(item) for item in servers)):
        issues.append("authorization_servers_invalid")
        servers = []
    issuer = authorization.get("issuer")
    if not _https_url(issuer) or issuer not in servers:
        issues.append("issuer_not_advertised")
    for key in ("authorization_endpoint", "token_endpoint"):
        if not _https_url(authorization.get(key)):
            issues.append(key + "_invalid")
    if "registration_endpoint" in authorization and not _https_url(authorization["registration_endpoint"]):
        issues.append("registration_endpoint_invalid")
    return {"valid": not issues, "authorization_server_count": len(servers),
            "scope_challenge_present": "scope" in params,
            "registration_endpoint_present": "registration_endpoint" in authorization,
            "issue_count": len(issues), "issues": summary.take(issues), "truncated": summary.truncated,
            "notes": ["Checks one supplied Bearer challenge and selected OAuth discovery metadata offline.",
                      "Does not fetch metadata, verify issuer ownership, validate tokens or perform an OAuth flow.",
                      "URLs, scopes and challenge values are omitted; this checker requires HTTPS resource and issuer URLs."]}
