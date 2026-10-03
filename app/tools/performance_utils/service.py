import json
import math
import re
import statistics
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlsplit

from app.tools.json_query.service import _check_tree
from app.tools.manifest_utils.service import _unique_object
from app.tools.report_utils.service import _Summary, _array, _choice, _integer, _mapping, _name


def _json_report(content):
    try:
        value = json.loads(content, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ValueError("Invalid report JSON; duplicate keys rejected and source text omitted") from error
    _mapping(value)
    _check_tree(value, max_nodes=20000, max_depth=50)
    return value


def _number(value, minimum=None):
    if value is not None and (type(value) not in (int, float) or abs(value) > 1000000000000000
                              or not math.isfinite(value) or minimum is not None and value < minimum):
        raise ValueError("Report numeric fields must be finite numbers within the supported range")
    return value


def _timestamp(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or len(value) > 100:
            raise ValueError
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise ValueError("Report timestamps must be valid ISO datetimes with a timezone; source omitted") from error


def _stats(values):
    return {"count": len(values), "min": min(values) if values else None, "max": max(values) if values else None,
            "mean": statistics.fmean(values) if values else None, "median": statistics.median(values) if values else None}


def _har_url(value, summary):
    if not isinstance(value, str) or len(value) > 10000 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("HAR URLs must be strings of at most 10000 characters without controls")
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return {"supported": False, "scheme": None, "host": None, "port": None, "path": None}
        return {"supported": True, "scheme": parsed.scheme, "host": _name(parsed.hostname, required=True),
                "port": parsed.port, "path": summary.text(parsed.path or "/")}
    except ValueError as error:
        raise ValueError("Invalid or unsupported HAR URL fields; source text omitted") from error


def _har_size(value):
    value = _integer(value, -1)
    return None if value == -1 else value


def inspect_har(content, limit):
    summary = _Summary(content, limit)
    data = _json_report(content)
    log = _mapping(data.get("log"))
    if log.get("version") != "1.2":
        raise ValueError("Only HAR version 1.2 is supported")
    entries = _array(log.get("entries"), 1000)
    pages = _array(log.get("pages", []), 200)
    for page in pages:
        _mapping(page)
    rows, status_counts, host_counts, mime_counts = [], Counter(), Counter(), Counter()
    stage_values = {key: [] for key in ("blocked", "dns", "connect", "ssl", "send", "wait", "receive")}
    times, starts, body_sizes, content_sizes = [], [], [], []
    for index, entry in enumerate(entries):
        entry = _mapping(entry)
        request, response = _mapping(entry.get("request")), _mapping(entry.get("response"))
        method = _name(request.get("method"), required=True)
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,100}", method):
            raise ValueError("Invalid HAR HTTP method token")
        target = _har_url(request.get("url"), summary)
        status = _integer(response.get("status"))
        if status is None or status != 0 and not 100 <= status <= 599:
            raise ValueError("HAR status must be 0 or 100-599")
        status_counts[str(status)] += 1
        if target["supported"]:
            host_counts[target["host"]] += 1
        duration = _number(entry.get("time"), 0)
        if duration is not None:
            times.append(duration)
        timing = _mapping(entry.get("timings", {}))
        stages = {}
        for key in stage_values:
            value = _number(timing.get(key), -1)
            if value is not None and value < 0 and value != -1:
                raise ValueError("HAR timing values must be nonnegative or -1")
            stages[key] = None if value == -1 else value
            if stages[key] is not None:
                stage_values[key].append(stages[key])
        started = _timestamp(entry.get("startedDateTime"))
        if started is not None:
            starts.append(started)
        payload = _mapping(response.get("content", {}))
        mime = None if payload.get("mimeType") == "" else _name(payload.get("mimeType"))
        if mime is not None:
            mime_counts[mime] += 1
        body_size, content_size = _har_size(response.get("bodySize")), _integer(payload.get("size"))
        if body_size is not None:
            body_sizes.append(body_size)
        if content_size is not None:
            content_sizes.append(content_size)
        rows.append({"index": index, "method": method, "target": target, "status": status, "time_ms": duration,
                     "timings_ms": stages, "started_at": started.isoformat() if started else None,
                     "mime_type": mime, "response_body_size": body_size, "response_content_size": content_size})
    slowest = sorted((row for row in rows if row["time_ms"] is not None), key=lambda row: row["time_ms"], reverse=True)
    errors = [row for row in rows if row["status"] == 0 or row["status"] >= 400]
    output = {"version": "1.2", "entry_count": len(rows), "page_count": len(pages), "status_counts": dict(sorted(status_counts.items())),
              "client_error_count": sum(400 <= row["status"] <= 499 for row in rows),
              "server_error_count": sum(500 <= row["status"] <= 599 for row in rows),
              "zero_status_count": status_counts["0"], "unsupported_url_count": sum(not row["target"]["supported"] for row in rows),
              "duration_ms": _stats(times), "missing_duration_count": len(rows) - len(times),
              "timing_stages_ms": {key: _stats(values) for key, values in stage_values.items()},
              "response_body_bytes": {"reported_total": sum(body_sizes), "unknown_count": len(rows) - len(body_sizes)},
              "response_content_bytes": {"reported_total": sum(content_sizes), "unknown_count": len(rows) - len(content_sizes)},
              "timestamp_range": {"first": min(starts).isoformat() if starts else None, "last": max(starts).isoformat() if starts else None},
              "missing_start_time_count": len(rows) - len(starts),
              "hosts": summary.take([{"host": host, "count": count} for host, count in host_counts.most_common()]),
              "mime_types": summary.take([{"mime_type": mime, "count": count} for mime, count in mime_counts.most_common()]),
              "entries": summary.take(rows), "slowest_requests": summary.take(slowest), "error_requests": summary.take(errors),
              "notes": ["Supplied HAR 1.2 observations only, not a live request, full schema validation or proof of service health/completeness.",
                        "HTTP/HTTPS targets are split into scheme/host/port/path. Userinfo, queries/fragments, headers, cookies, bodies, page titles, server-IP fields and comments are omitted; other schemes have no returned target text.",
                        "Missing values and -1 timing/size sentinels stay unknown, not zero; status 0 stays separate from HTTP errors.",
                        "Timings are milliseconds; ssl is included in connect and is not added twice. Durations are individual entry observations, not page-load/wall-clock time.",
                        "Body/content sizes are separate reported fields, not total wire traffic. No cache/connection/server-cause inference. Remaining hosts/paths/MIME values may contain supplied sensitive data."]}
    output["truncated"] = summary.truncated
    return output


def _metric_values(raw, kind, variant):
    values = _mapping(raw)
    if len(values) > 50:
        raise ValueError("k6 metrics exceed 50 value fields per metric")
    output = {}
    for key, value in values.items():
        _name(key, required=True)
        number = _number(value)
        if key in {"count", "rate", "passes", "fails", "matches", "total"} and number is not None and number < 0:
            raise ValueError("k6 count/rate fields must be nonnegative")
        if kind == "rate" and key == "rate" and number is not None and number > 1:
            raise ValueError("k6 rate metric proportions must be between 0 and 1")
        if variant == "machine_v1" and kind == "rate" and key in {"matches", "total"}:
            _integer(number)
        output[key] = number
    if kind == "rate" and output.get("matches") is not None and output.get("total") is not None and output["matches"] > output["total"]:
        raise ValueError("k6 rate matches exceed total events")
    return output


def inspect_k6(content, limit):
    summary = _Summary(content, limit)
    data = _json_report(content)
    checks_raw, sources = [], []
    metadata = {}
    if "version" in data:
        if data["version"] != "1.0.0":
            raise ValueError("Unsupported k6 summary version; supported machine-readable version is 1.0.0")
        variant = "machine_v1"
        result = _mapping(data.get("results"))
        config, meta = _mapping(data.get("config")), _mapping(data.get("metadata"))
        duration_seconds = _number(config.get("duration"), 0)
        execution = _choice(config.get("execution"), {"local", "cloud"})
        generated = _timestamp(meta.get("generatedAt"))
        metadata = {"k6_version": _name(meta.get("k6Version")), "execution": execution,
                    "generated_at": generated.isoformat() if generated else None}
        sources.append(("metrics", _array(result.get("metrics"), 500)))
        check_data = result.get("checks")
        if check_data is not None:
            check_data = _mapping(check_data)
            sources.append(("check_metrics", _array(check_data.get("metrics", []), 500)))
            checks_raw = [(None, item) for item in _array(check_data.get("results", []), 1000)]
        checks_available = check_data is not None and "results" in check_data
    else:
        variant = "legacy_handle_summary"
        if any(key in data for key in ("results", "scenarios", "groups", "thresholds")):
            raise ValueError("Supply flat legacy handleSummary JSON or version 1.0.0 machine JSON, not grouped/raw summaries")
        metrics = _mapping(data.get("metrics"))
        if len(metrics) > 500:
            raise ValueError("k6 exceeds 500 metrics per collection")
        legacy = []
        for name, item in metrics.items():
            item = _mapping(item)
            if "type" not in item or "values" not in item:
                raise ValueError("Supply flat legacy handleSummary metrics, not grouped/raw export data")
            legacy.append({**item, "name": name})
        sources.append(("metrics", legacy))
        duration = _number(_mapping(data.get("state", {})).get("testRunDurationMs"), 0)
        duration_seconds = duration / 1000 if duration is not None else None
        checks_available = data.get("root_group") is not None
        group_count = 0

        def visit(group):
            nonlocal group_count
            group = _mapping(group)
            group_count += 1
            if group_count > 200:
                raise ValueError("k6 exceeds 200 legacy check groups")
            group_name = summary.text(group.get("name"))
            for item in _array(group.get("checks", []), 1000):
                checks_raw.append((group_name, item))
                if len(checks_raw) > 1000:
                    raise ValueError("k6 exceeds 1000 individual checks")
            for child in _array(group.get("groups", []), 200):
                visit(child)
        if checks_available:
            visit(data["root_group"])
    metrics_out, thresholds, types = [], [], Counter()
    for source, metrics in sources:
        names = set()
        for raw in metrics:
            raw = _mapping(raw)
            name = _name(raw.get("name"), required=True)
            if name in names:
                raise ValueError("Duplicate k6 metric names within a collection are unsupported")
            names.add(name)
            kind = _choice(raw.get("type"), {"counter", "gauge", "rate", "trend"})
            if kind is None:
                raise ValueError("k6 metric type is required")
            contains = _choice(raw.get("contains"), {"default", "time", "data"})
            values = _metric_values(raw.get("values"), kind, variant)
            declared = raw.get("thresholds")
            declared = _mapping(declared) if declared is not None else {}
            if len(declared) > 50 or len(thresholds) + len(declared) > 1000:
                raise ValueError("k6 exceeds 50 thresholds per metric or 1000 total thresholds")
            for expression, status in declared.items():
                _name(expression, required=True)
                ok = _mapping(status).get("ok")
                if ok is not None and type(ok) is not bool:
                    raise ValueError("k6 threshold ok values must be booleans or unknown")
                thresholds.append({"source": source, "metric": name, "expression": expression, "ok": ok})
            metrics_out.append({"source": source, "name": name, "type": kind, "contains": contains, "values": values,
                                "thresholds_available": raw.get("thresholds") is not None, "threshold_count": len(declared)})
            types[kind] += 1
    checks = []
    for group, raw in checks_raw:
        raw = _mapping(raw)
        name = _name(raw.get("name"), required=True)
        passes, fails = _integer(raw.get("passes")), _integer(raw.get("fails"))
        total = passes + fails if passes is not None and fails is not None else None
        checks.append({"group": group, "name": name, "passes": passes, "fails": fails,
                       "failure_fraction": fails / total if total else None})
    passed = sum(row["ok"] is True for row in thresholds)
    failed = sum(row["ok"] is False for row in thresholds)
    unknown = sum(row["ok"] is None for row in thresholds)
    output = {"format": variant, "schema_version": data.get("version"), "metadata": metadata, "duration_seconds": duration_seconds,
              "metric_count": len(metrics_out), "type_counts": dict(sorted(types.items())), "metrics": summary.take(metrics_out),
              "threshold_count": len(thresholds), "threshold_counts": {"passed": passed, "failed": failed, "unknown": unknown},
              "all_reported_thresholds_passed": False if failed else True if passed and not unknown else None,
              "thresholds": summary.take(thresholds), "failed_thresholds": summary.take([row for row in thresholds if row["ok"] is False]),
              "check_results_available": checks_available, "check_result_count": len(checks),
              "check_totals": {"reported_passes": sum(row["passes"] or 0 for row in checks),
                               "reported_fails": sum(row["fails"] or 0 for row in checks),
                               "incomplete_count": sum(row["passes"] is None or row["fails"] is None for row in checks)},
              "checks": summary.take(checks), "attention_checks": summary.take([row for row in checks if row["fails"] and row["fails"] > 0]),
              "notes": ["Supplied flat legacy handleSummary JSON or version 1.0.0 machine-readable JSON only; not raw JSONL, grouped summaries, execution or full schema validation.",
                        "Metric values (including custom percentiles/rates) are preserved as reported, not recalculated or summed across tagged/check metrics. Display time-unit options are not applied.",
                        "Threshold expressions are never evaluated: only explicit metric-level ok statuses count. Absent thresholds do not prove a test passed; machine v1 without threshold metadata stays unknown.",
                        "Check names/counts come from individual check records, not rate-metric inference. Missing counters are tracked as incomplete, not measured zero.",
                        "Legacy group check lists are walked once; machine v1 check metrics remain a separate collection. Group/scenario metric aggregation is unsupported to avoid overlapping totals.",
                        "Setup data, script paths and options are omitted. Metric/check/group names and threshold expressions may contain supplied sensitive data; results do not predict production capacity."]}
    output["truncated"] = summary.truncated
    return output
