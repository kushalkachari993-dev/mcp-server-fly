import json
import re
import statistics
from collections import Counter

from app.tools.json_query.service import _check_tree
from app.tools.manifest_utils.service import _unique_object
from app.tools.report_comparison.service import _change, _inputs, _match, _matching
from app.tools.report_utils.service import _Summary, _array, _mapping


_SPAN_KINDS = {0: "unspecified", 1: "internal", 2: "server", 3: "client",
               4: "producer", 5: "consumer"}
_STATUS_CODES = {0: "unset", 1: "ok", 2: "error"}
_UINT64_MAX = 2**64 - 1


def _text(value, label, maximum=500, required=False):
    if value is None and not required:
        return None
    if (not isinstance(value, str) or (required and not value.strip()) or len(value) > maximum
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"Invalid {label}; source text is omitted")
    return value


def _hex_id(value, length, optional=False):
    if optional and (value is None or value == ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", value) or int(value, 16) == 0:
        raise ValueError("Trace/span IDs must be nonzero OTLP hex strings; source text is omitted")
    return value.lower()


def _uint64(value, label):
    if value is None:
        return None
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r"(?:0|[1-9][0-9]{0,19})", value):
        number = int(value)
    else:
        raise ValueError(f"Invalid {label}; source text is omitted")
    if not 0 <= number <= _UINT64_MAX:
        raise ValueError(f"Invalid {label}; source text is omitted")
    return number


def _resource_fields(resource):
    selected, duplicate = {}, set()
    for attribute in _array(_mapping(resource).get("attributes", []), 200):
        attribute = _mapping(attribute)
        key = attribute.get("key")
        if not isinstance(key, str) or key not in {"service.namespace", "service.name"}:
            continue
        if key in selected:
            duplicate.add(key)
        value = _mapping(attribute.get("value", {})).get("stringValue")
        selected[key] = _text(value, "service resource attribute")
    namespace = None if "service.namespace" in duplicate else selected.get("service.namespace", "")
    return {"service_namespace": namespace,
            "service_name": None if "service.name" in duplicate else selected.get("service.name") or None}


def _stats(values):
    return {"count": len(values), "min": min(values) if values else None,
            "max": max(values) if values else None,
            "mean": statistics.fmean(values) if values else None,
            "median": statistics.median(values) if values else None}


def _operation_identity(row, summary):
    namespace, service, name, kind = row["key"]
    return {"service_namespace": summary.text(namespace), "service_name": summary.text(service),
            "span_name": summary.text(name), "span_kind": kind}


def _operation_view(row, summary):
    return {"identity": _operation_identity(row, summary), "span_count": row["span_count"],
            "status_counts": row["status_counts"], "explicit_status_count": row["explicit_status_count"],
            "error_fraction_of_explicit_statuses": row["error_fraction"],
            "duration_ms": row["duration_ms"], "missing_duration_count": row["missing_duration_count"]}


def _parse(content, limit):
    summary = _Summary(content, limit)
    try:
        data = json.loads(content, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ValueError("Invalid OTLP/JSON; duplicate keys are rejected and source text is omitted") from error
    _mapping(data)
    _check_tree(data, max_nodes=20000, max_depth=50)
    resources = _array(data.get("resourceSpans"), 100)
    spans, scope_count = [], 0
    for resource in resources:
        resource = _mapping(resource)
        identity = _resource_fields(resource.get("resource", {}))
        scopes = _array(resource.get("scopeSpans", []), 200)
        scope_count += len(scopes)
        if scope_count > 500:
            raise ValueError("OTLP/JSON exceeds 500 scopeSpans")
        for scope in scopes:
            scope = _mapping(scope)
            for raw in _array(scope.get("spans", []), 2000):
                if len(spans) >= 2000:
                    raise ValueError("OTLP/JSON exceeds 2000 spans")
                raw = _mapping(raw)
                trace_id = _hex_id(raw.get("traceId"), 32)
                span_id = _hex_id(raw.get("spanId"), 16)
                parent_id = _hex_id(raw.get("parentSpanId"), 16, optional=True)
                name = _text(raw.get("name"), "span name", required=True)
                kind = raw.get("kind", 0)
                if type(kind) is not int or kind not in _SPAN_KINDS:
                    raise ValueError("Unsupported OTLP span kind; source text is omitted")
                status = _mapping(raw.get("status", {})).get("code", 0)
                if type(status) is not int or status not in _STATUS_CODES:
                    raise ValueError("Unsupported OTLP span status; source text is omitted")
                start = _uint64(raw.get("startTimeUnixNano"), "startTimeUnixNano")
                end = _uint64(raw.get("endTimeUnixNano"), "endTimeUnixNano")
                if start is not None and end is not None and end < start:
                    raise ValueError("OTLP span end precedes start; source text is omitted")
                events = _array(raw.get("events", []), 1000)
                links = _array(raw.get("links", []), 1000)
                duration = (end - start) / 1000000 if start and end else None
                spans.append({**identity, "trace_id": trace_id, "span_id": span_id,
                              "parent_id": parent_id, "name": name, "kind": _SPAN_KINDS[kind],
                              "status": _STATUS_CODES[status], "duration_ms": duration,
                              "event_count": len(events), "link_count": len(links)})
    span_ids = Counter((span["trace_id"], span["span_id"]) for span in spans)
    parent_counts = Counter()
    for span in spans:
        parent = span["parent_id"]
        if parent is None:
            parent_counts["root"] += 1
        elif parent == span["span_id"]:
            parent_counts["self"] += 1
        else:
            parent_counts["linked" if span_ids[(span["trace_id"], parent)] == 1 else
                          "missing" if span_ids[(span["trace_id"], parent)] == 0 else "ambiguous"] += 1
    grouped = {}
    for span in spans:
        if span["service_name"] is None or span["service_namespace"] is None:
            continue
        key = (span["service_namespace"], span["service_name"], span["name"], span["kind"])
        group = grouped.setdefault(key, {"key": key, "span_count": 0, "statuses": Counter(), "durations": []})
        group["span_count"] += 1
        group["statuses"][span["status"]] += 1
        if span["duration_ms"] is not None:
            group["durations"].append(span["duration_ms"])
    operations = []
    for group in grouped.values():
        statuses = group["statuses"]
        explicit = statuses["ok"] + statuses["error"]
        operations.append({"key": group["key"], "span_count": group["span_count"],
                           "status_counts": {name: statuses[name] for name in _STATUS_CODES.values()},
                           "explicit_status_count": explicit,
                           "error_fraction": statuses["error"] / explicit if explicit else None,
                           "duration_ms": _stats(group["durations"]),
                           "missing_duration_count": group["span_count"] - len(group["durations"])})
    operations.sort(key=lambda row: (-row["span_count"], row["key"]))
    statuses = Counter(span["status"] for span in spans)
    view = {"format": "OTLP/JSON traces", "resource_span_count": len(resources),
            "scope_span_count": scope_count, "span_count": len(spans),
            "trace_count": len({span["trace_id"] for span in spans}),
            "operation_count": len(operations),
            "unmatchable_service_span_count": sum(span["service_name"] is None or span["service_namespace"] is None
                                                   for span in spans),
            "status_counts": {name: statuses[name] for name in _STATUS_CODES.values()},
            "missing_duration_count": sum(span["duration_ms"] is None for span in spans),
            "event_count": sum(span["event_count"] for span in spans),
            "link_count": sum(span["link_count"] for span in spans),
            "root_span_count": parent_counts["root"], "linked_parent_count": parent_counts["linked"],
            "self_parent_count": parent_counts["self"],
            "missing_parent_count": parent_counts["missing"],
            "ambiguous_parent_count": parent_counts["ambiguous"],
            "duplicate_span_identity_count": sum(count - 1 for count in span_ids.values() if count > 1)}
    return summary, view, operations


def inspect_otlp_traces(content, limit):
    summary, view, operations = _parse(content, limit)
    return {**view, "operations": summary.take([_operation_view(row, summary) for row in operations]),
            "truncated": summary.truncated,
            "notes": ["Supplied OTLP/JSON ExportTraceServiceRequest only; binary protobuf and vendor trace exports are not supported. Selected fields are inspected, not full protocol validation.",
                      "Durations use end-start nanoseconds. Zero/missing timestamps are unknown; span status unset is not counted as success. Missing parent spans can reflect partial exports; self-parent spans are counted separately.",
                      "Only service.namespace, service.name, and span names/kinds are returned. Trace/span IDs, events, links, attributes and status messages are omitted; selected names may still be sensitive.",
                      "Offline only: no collector, file or network access and no trace execution."]}


def compare_otlp_traces(before, after, limit):
    summary = _inputs(before, after, limit)
    parsed = [_parse(content, 50) for content in (before, after)]
    views = [item[1] for item in parsed]
    match = _match(parsed[0][2], parsed[1][2], lambda row: row["key"])
    changes, duration_increases = [], []
    for old, new in match["matched"]:
        complete_duration = old["missing_duration_count"] == new["missing_duration_count"] == 0
        explicit_status = old["status_counts"]["unset"] == new["status_counts"]["unset"] == 0
        duration = {name: _change(old["duration_ms"][name], new["duration_ms"][name], complete_duration)
                    for name in ("mean", "median")}
        row = {"identity": _operation_identity(old, summary),
               "span_count": _change(old["span_count"], new["span_count"]),
               "error_count": _change(old["status_counts"]["error"], new["status_counts"]["error"]),
               "before_status_counts": old["status_counts"], "after_status_counts": new["status_counts"],
               "error_fraction_of_explicit_statuses": _change(old["error_fraction"], new["error_fraction"], explicit_status),
               "before_duration_ms": old["duration_ms"], "after_duration_ms": new["duration_ms"],
               "before_missing_duration_count": old["missing_duration_count"],
               "after_missing_duration_count": new["missing_duration_count"],
               "duration_ms": duration}
        if (old["span_count"] != new["span_count"] or old["status_counts"] != new["status_counts"]
                or old["duration_ms"] != new["duration_ms"]):
            changes.append(row)
        if duration["mean"]["delta"] is not None and duration["mean"]["delta"] > 0:
            duration_increases.append(row)
    duration_increases.sort(key=lambda row: row["duration_ms"]["mean"]["delta"], reverse=True)
    identity = lambda row: _operation_identity(row, summary)
    return {"before": views[0], "after": views[1],
            "matching": _matching(match, identity, summary),
            "observed_added_operations": summary.take([_operation_view(row, summary) for row in match["added"]]),
            "observed_removed_operations": summary.take([_operation_view(row, summary) for row in match["removed"]]),
            "changed_operation_count": len(changes), "changes": summary.take(changes),
            "observed_mean_duration_increase_count": len(duration_increases),
            "largest_observed_mean_duration_increases": summary.take(duration_increases),
            "truncated": summary.truncated,
            "notes": ["Operations are grouped by exact service.namespace, service.name, span name and kind; trace/span IDs are never matched across inputs. Spans without unambiguous service identity remain outside operation matching.",
                      "Duration deltas require measured durations on every span in both groups. Error-fraction deltas require explicit OK or ERROR on every span; unset status is not success.",
                      "Counts and measured durations describe supplied, possibly sampled or partial windows. They do not establish equal traffic, rates, statistical significance or causal regressions.",
                      "All bounded spans are counted before display limits. Added/removed means observed in only one supplied input, not proof of a new/deleted operation.",
                      "Offline only; raw IDs, events, links, attributes and status messages are omitted. Service and span names may still contain supplied sensitive data."]}
