import base64
import binascii
import math
from collections import Counter

from app.tools.report_utils.service import _Summary

from . import catalog_parser, parser


_KNOWN_CAPABILITIES = ("tools", "prompts", "resources", "logging", "completions")
_FLAGS = {"tools": ("listChanged",), "prompts": ("listChanged",),
          "resources": ("listChanged", "subscribe")}
_MAX_ITEMS = 500


def _response(content, label, protocol_version):
    parser.protocol_version(protocol_version)
    value = parser.json_value(content, label)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if "jsonrpc" in value:
        if value["jsonrpc"] != "2.0" or "error" in value or "result" not in value:
            raise ValueError(f"Supply a successful {label} response")
        value = value["result"]
    if not isinstance(value, dict):
        raise ValueError(f"{label} result must be an object")
    return value


def _text(value, label, maximum=1000):
    return catalog_parser._text(value, label, maximum)


def _cache(value):
    ttl = value.get("ttlMs")
    if type(ttl) not in (int, float) or (type(ttl) is float and not math.isfinite(ttl)) or ttl < 0:
        raise ValueError("2026 MCP cache ttlMs must be a nonnegative finite number")
    if value.get("cacheScope") not in ("public", "private"):
        raise ValueError("2026 MCP cacheScope must be public or private")
    return ttl, value["cacheScope"]


def _capabilities(value):
    if not isinstance(value, dict) or len(value) > 100:
        raise ValueError("MCP capabilities must be an object with at most 100 entries")
    selected = {}
    for name in _KNOWN_CAPABILITIES:
        if name not in value:
            selected[name] = {"present": False}
            continue
        raw = value[name]
        if not isinstance(raw, dict):
            raise ValueError(f"MCP {name} capability must be an object")
        flags = {}
        for key in _FLAGS.get(name, ()):
            if key in raw and type(raw[key]) is not bool:
                raise ValueError(f"MCP {name}.{key} must be a boolean")
            flags[key] = raw.get(key, False)
        selected[name] = {"present": True, **flags}
    for name in ("experimental", "extensions"):
        if name in value:
            raw = value[name]
            if (not isinstance(raw, dict) or len(raw) > 100
                    or any(not isinstance(key, str) or not isinstance(item, dict)
                           for key, item in raw.items())):
                raise ValueError(f"MCP {name} capability must be a map of at most 100 objects")
    return selected


def _profile(content, protocol_version):
    label = "MCP initialize result" if protocol_version == "2025-11-25" else "MCP server/discover result"
    value = _response(content, label, protocol_version)
    if protocol_version == "2025-11-25":
        if "resultType" in value:
            raise ValueError("2025 MCP initialize result must not have resultType")
        declared_version = _text(value.get("protocolVersion"), "protocolVersion", 100)
        supported_versions = None
        server_info = value.get("serverInfo")
        ttl = scope = None
    else:
        if value.get("resultType") != "complete":
            raise ValueError("2026 MCP server/discover resultType must be complete")
        versions = value.get("supportedVersions")
        if (not isinstance(versions, list) or not 1 <= len(versions) <= 20
                or len(set(item for item in versions if isinstance(item, str))) != len(versions)):
            raise ValueError("MCP supportedVersions must contain 1-20 distinct versions")
        supported_versions = [_text(item, "supported version", 100) for item in versions]
        if protocol_version not in supported_versions:
            raise ValueError("MCP server/discover must advertise the selected protocol version")
        declared_version = None
        meta = value.get("_meta", {})
        if not isinstance(meta, dict):
            raise ValueError("MCP result _meta must be an object")
        server_info = meta.get("io.modelcontextprotocol/serverInfo")
        ttl, scope = _cache(value)
    if server_info is not None:
        if not isinstance(server_info, dict):
            raise ValueError("MCP serverInfo must be an object")
        _text(server_info.get("name"), "server name")
        _text(server_info.get("version"), "server version")
    elif protocol_version == "2025-11-25":
        raise ValueError("MCP initialize result must include serverInfo")
    if "instructions" in value and not isinstance(value["instructions"], str):
        raise ValueError("MCP instructions must be text")
    caps = value.get("capabilities")
    selected = _capabilities(caps)
    return {"declared_version": declared_version, "supported_versions": supported_versions,
            "server_info": server_info, "instructions_present": "instructions" in value,
            "instructions": value.get("instructions"), "capabilities": selected,
            "raw_capabilities": caps, "ttl_ms": ttl, "cache_scope": scope}


def inspect_mcp_server_capabilities(response, protocol_version, limit):
    summary = _Summary(response, limit)
    profile = _profile(response, protocol_version)
    info = profile["server_info"]
    return {"protocol_version": protocol_version, "declared_protocol_version": profile["declared_version"],
            "supported_versions": profile["supported_versions"],
            "server_name": summary.text(info["name"], 200) if info else None,
            "server_version": summary.text(info["version"], 200) if info else None,
            "capabilities": profile["capabilities"],
            "experimental_count": len(profile["raw_capabilities"].get("experimental", {})),
            "extension_count": len(profile["raw_capabilities"].get("extensions", {})),
            "instructions_present": profile["instructions_present"],
            "ttl_ms": profile["ttl_ms"], "cache_scope": profile["cache_scope"],
            "truncated": summary.truncated,
            "notes": ["Inspects one supplied successful initialize (2025) or server/discover (2026) result; no live connection or capability probe.",
                      "Server identity is self-reported and not an authorization or trust signal.",
                      "Instructions, experimental and extension settings are omitted; known capability flags are selected, not full protocol conformance."]}


def compare_mcp_server_capabilities(before, after, protocol_version, limit):
    summary = _Summary(before, limit)
    _Summary(after, limit)
    old, new = _profile(before, protocol_version), _profile(after, protocol_version)
    changes = []
    if protocol_version == "2025-11-25" and old["declared_version"] != new["declared_version"]:
        changes.append({"field": "protocolVersion", "before": old["declared_version"],
                        "after": new["declared_version"]})
    if protocol_version == "2026-07-28":
        previous, current = set(old["supported_versions"]), set(new["supported_versions"])
        if previous != current:
            changes.append({"field": "supportedVersions", "added": sorted(current - previous),
                            "removed": sorted(previous - current)})
        for key in ("ttl_ms", "cache_scope"):
            if old[key] != new[key]:
                changes.append({"field": key, "before": old[key], "after": new[key]})
    for name in _KNOWN_CAPABILITIES:
        for key in old["capabilities"][name].keys() | new["capabilities"][name].keys():
            previous = old["capabilities"][name].get(key, False)
            current = new["capabilities"][name].get(key, False)
            if previous != current:
                changes.append({"field": f"{name}.{key}", "before": previous, "after": current})
    for name in ("experimental", "extensions"):
        previous, current = old["raw_capabilities"].get(name), new["raw_capabilities"].get(name)
        if previous != current:
            changes.append({"field": name, "changed": True,
                            "before_count": len(previous or {}), "after_count": len(current or {})})
    for key in ("server_info", "instructions"):
        if old[key] != new[key]:
            changes.append({"field": key, "changed": True})
    return {"protocol_version": protocol_version, "selected_change_count": len(changes),
            "changes": summary.take(changes), "truncated": summary.truncated,
            "notes": ["Compares selected declarations in two supplied results of the same protocol era; no live or compatibility verdict.",
                      "Instructions, server identity changes and extension/experimental details are flags only.",
                      "Unknown capability fields are not compared; server identity is self-reported."]}


def validate_mcp_prompt_arguments(manifest, prompt_name, arguments, protocol_version, limit):
    summary = _Summary(manifest, limit)
    _Summary(arguments, limit)
    rows, partial = catalog_parser.prompt_catalog(manifest, protocol_version)
    selected = rows.get(_text(prompt_name, "prompt name"))
    if selected is None:
        raise ValueError("Selected MCP prompt is absent from the supplied page; follow nextCursor if present")
    supplied = parser.json_value(arguments, "MCP prompt arguments")
    if not isinstance(supplied, dict) or len(supplied) > _MAX_ITEMS:
        raise ValueError("MCP prompt arguments must be an object with at most 500 entries")
    for key in supplied:
        _text(key, "prompt argument name")
    declared = selected[1]
    missing = sorted(name for name, arg in declared.items() if arg.get("required", False) and name not in supplied)
    non_string = sorted(name for name, value in supplied.items() if not isinstance(value, str))
    undeclared = sorted(supplied.keys() - declared.keys())
    return {"protocol_version": protocol_version, "prompt_name": summary.text(prompt_name, 200),
            "catalog_partial": partial, "valid": not missing and not non_string,
            "missing_required": summary.take([summary.text(name, 200) for name in missing]),
            "non_string_arguments": summary.take([summary.text(name, 200) for name in non_string]),
            "undeclared_arguments": summary.take([summary.text(name, 200) for name in undeclared]),
            "truncated": summary.truncated,
            "notes": ["Checks supplied argument names, required declarations and string values only; no prompt is rendered or fetched.",
                      "Undeclared arguments are reported but do not invalidate; the server may accept them.",
                      "Argument values are omitted. Names may be sensitive. A partial catalog can validate a present prompt but not prove an absent prompt does not exist."]}


def _result(response, label, protocol_version):
    value = _response(response, label, protocol_version)
    result_type = value.get("resultType")
    if protocol_version == "2026-07-28":
        if result_type not in ("complete", "input_required"):
            raise ValueError("2026 MCP resultType must be complete or input_required")
    elif result_type not in (None, "complete"):
        raise ValueError("2025 MCP resultType must be absent or complete")
    if result_type == "input_required":
        requests = value.get("inputRequests")
        state = value.get("requestState")
        if (requests is None and state is None or requests is not None and not isinstance(requests, dict)
                or state is not None and not isinstance(state, str)):
            raise ValueError("MCP input_required needs inputRequests or requestState in the supported shape")
    return value, result_type == "input_required"


def _issue(errors, path, code):
    errors.append({"path": path, "code": code})


def _binary(value):
    if not isinstance(value, str):
        return False
    try:
        base64.b64decode(value, validate=True)
        return True
    except (ValueError, binascii.Error):
        return False


def _resource_content(raw, path, errors):
    if not isinstance(raw, dict):
        _issue(errors, path, "object_required")
        return None
    try:
        uri = _text(raw.get("uri"), "resource URI", 10000)
        if catalog_parser.scheme(uri) is None or any(char.isspace() for char in uri):
            raise ValueError("Resource URI must be absolute")
    except ValueError:
        _issue(errors, f"{path}/uri", "uri_required")
    if "mimeType" in raw and (not isinstance(raw["mimeType"], str) or not raw["mimeType"]):
        _issue(errors, f"{path}/mimeType", "mime_type_invalid")
    has_text, has_blob = "text" in raw, "blob" in raw
    if has_text == has_blob:
        _issue(errors, path, "exactly_one_text_or_blob_required")
        return None
    if has_text:
        if not isinstance(raw["text"], str):
            _issue(errors, f"{path}/text", "text_must_be_string")
        return "text"
    if not _binary(raw["blob"]):
        _issue(errors, f"{path}/blob", "blob_must_be_base64")
    return "blob"


def _validation_output(protocol_version, summary, errors, **fields):
    shown = summary.take(errors)
    return {"protocol_version": protocol_version, "checked": True, "valid": not errors,
            "error_count": len(errors), "errors": shown, "truncated": summary.truncated, **fields}


def _pending(protocol_version, value):
    return {"protocol_version": protocol_version, "checked": False, "valid": None,
            "reason": "input_required", "input_request_count": len(value.get("inputRequests") or {}),
            "request_state_present": "requestState" in value,
            "notes": ["The server requested another round trip; no completed content was validated or returned.",
                      "Input request and request-state values are omitted; this is not full MRTR validation."]}


def validate_mcp_resource_read_result(response, protocol_version, limit):
    summary = _Summary(response, limit)
    value, pending = _result(response, "MCP resources/read result", protocol_version)
    if pending:
        return _pending(protocol_version, value)
    errors = []
    if protocol_version == "2026-07-28":
        try:
            _cache(value)
        except ValueError:
            _issue(errors, "/", "cache_hints_invalid")
    contents = value.get("contents")
    if not isinstance(contents, list) or len(contents) > _MAX_ITEMS:
        _issue(errors, "/contents", "array_of_at_most_500_required")
        contents = []
    kinds = Counter()
    for index, raw in enumerate(contents):
        kind = _resource_content(raw, f"/contents/{index}", errors)
        if kind:
            kinds[kind] += 1
    return _validation_output(protocol_version, summary, errors, content_count=len(contents),
                              content_kinds=dict(kinds),
                              notes=["Checks selected resources/read result structure, text/blob types and base64 syntax only; no URI dereference or MIME/content verification.",
                                     "Multiple content entries and an empty array are allowed; neither proves a resource exists.",
                                     "Content, URIs, MIME values and metadata are omitted; error paths use numeric indices only."])


def _prompt_content(raw, path, errors):
    if not isinstance(raw, dict):
        _issue(errors, path, "object_required")
        return None
    kind = raw.get("type")
    if kind == "text":
        if not isinstance(raw.get("text"), str):
            _issue(errors, f"{path}/text", "text_must_be_string")
    elif kind in ("image", "audio"):
        if not _binary(raw.get("data")):
            _issue(errors, f"{path}/data", "data_must_be_base64")
        if not isinstance(raw.get("mimeType"), str) or not raw["mimeType"]:
            _issue(errors, f"{path}/mimeType", "mime_type_required")
    elif kind == "resource":
        _resource_content(raw.get("resource"), f"{path}/resource", errors)
    elif kind == "resource_link":
        try:
            uri = _text(raw.get("uri"), "resource URI", 10000)
            if catalog_parser.scheme(uri) is None or any(char.isspace() for char in uri):
                raise ValueError("Resource URI must be absolute")
            _text(raw.get("name"), "resource name")
        except ValueError:
            _issue(errors, path, "resource_link_identity_invalid")
        if "mimeType" in raw and (not isinstance(raw["mimeType"], str) or not raw["mimeType"]):
            _issue(errors, f"{path}/mimeType", "mime_type_invalid")
        if "size" in raw and (type(raw["size"]) is not int or raw["size"] < 0):
            _issue(errors, f"{path}/size", "size_invalid")
    else:
        _issue(errors, f"{path}/type", "unsupported_content_type")
        return None
    return kind


def validate_mcp_prompt_get_result(response, protocol_version, limit):
    summary = _Summary(response, limit)
    value, pending = _result(response, "MCP prompts/get result", protocol_version)
    if pending:
        return _pending(protocol_version, value)
    errors = []
    if "description" in value and not isinstance(value["description"], str):
        _issue(errors, "/description", "description_must_be_string")
    messages = value.get("messages")
    if not isinstance(messages, list) or len(messages) > _MAX_ITEMS:
        _issue(errors, "/messages", "array_of_at_most_500_required")
        messages = []
    roles, kinds = Counter(), Counter()
    for index, raw in enumerate(messages):
        path = f"/messages/{index}"
        if not isinstance(raw, dict):
            _issue(errors, path, "object_required")
            continue
        role = raw.get("role")
        if role not in ("user", "assistant"):
            _issue(errors, f"{path}/role", "unsupported_role")
        else:
            roles[role] += 1
        kind = _prompt_content(raw.get("content"), f"{path}/content", errors)
        if kind:
            kinds[kind] += 1
    return _validation_output(protocol_version, summary, errors, message_count=len(messages),
                              role_counts=dict(roles), content_kinds=dict(kinds),
                              notes=["Checks selected prompts/get message roles and content-block shapes only; no prompt rendering or execution.",
                                     "Text, binary content, embedded resources, descriptions and metadata are omitted.",
                                     "Base64 syntax is checked, not media decoding, URI reachability or injection safety."])
