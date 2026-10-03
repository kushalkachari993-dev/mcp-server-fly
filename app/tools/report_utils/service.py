import json
import math
import re
from collections import Counter
from datetime import timezone
from io import StringIO
from urllib.parse import urlsplit

from apachelogs import COMBINED, COMMON, LogParser
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from prometheus_client.parser import text_string_to_metric_families

from app.tools.json_query.service import _check_tree
from app.tools.manifest_utils.service import _unique_object


class _Summary:
    def __init__(self, content, limit):
        if not isinstance(content, str) or len(content) > 200000:
            raise ValueError("Report input must be text of at most 200000 characters")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        self.limit, self.truncated = limit, False

    def text(self, value, maximum=1000):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Report text fields must be strings")
        self.truncated |= len(value) > maximum
        return value[:maximum]

    def take(self, values, maximum=None):
        maximum = self.limit if maximum is None else maximum
        self.truncated |= len(values) > maximum
        return values[:maximum]


def _mapping(value):
    if not isinstance(value, dict):
        raise ValueError("Report object fields must be mappings")
    return value


def _array(value, maximum=2000):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"Report arrays must contain at most {maximum} entries")
    return value


def _name(value, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 1000 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Report identifiers must be nonempty strings of at most 1000 characters without controls")
    return value


def _integer(value, minimum=0):
    if value is not None and (type(value) is not int or not minimum <= value <= 1000000000000):
        raise ValueError("Report integer fields are outside their supported range")
    return value


def _duration(value):
    if value is None:
        return None
    try:
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError
        return number
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Report duration must be a finite nonnegative number") from error


def _lines(content):
    lines = content.splitlines()
    if len(lines) > 5000 or any(len(line) > 10000 for line in lines):
        raise ValueError("Report exceeds 5000 lines or 10000 characters per line")
    return lines


def _junit_root(content):
    root, depth, nodes = None, 0, 0
    try:
        for event, element in ElementTree.iterparse(StringIO(content), events=("start", "end"),
                                                  forbid_dtd=True, forbid_entities=True, forbid_external=True):
            if event == "start":
                depth += 1
                nodes += 1
                if nodes > 10000 or depth > 50:
                    raise ValueError("JUnit XML exceeds 10000 elements or 50 nesting levels")
                if root is None:
                    root = element
            else:
                depth -= 1
    except (ElementTree.ParseError, DefusedXmlException) as error:
        raise ValueError("Invalid or forbidden JUnit XML; DTDs/entities are not allowed and source text is omitted") from error
    if root is None or root.tag.rsplit("}", 1)[-1] not in {"testsuites", "testsuite"}:
        raise ValueError("Expected a JUnit testsuites or testsuite root")
    return root


def inspect_junit(content, limit, *, _records=None):
    summary = _Summary(content, limit)
    root = _junit_root(content)
    namespace = root.tag[:root.tag.rfind("}") + 1] if root.tag.startswith("{") else ""
    suites, tests, outcomes = [], [], Counter()
    mixed = 0

    def tag(element):
        return element.tag[len(namespace):] if element.tag.startswith(namespace) else ""

    def visit(element, parent=None, suite_path=()):
        nonlocal mixed
        if tag(element) == "testsuites":
            for child in element:
                if tag(child) in {"testsuite", "testsuites"}:
                    visit(child, parent, suite_path)
            return
        index = len(suites)
        if index >= 1000:
            raise ValueError("JUnit report exceeds 1000 suites")
        declared = {}
        for key in ("tests", "failures", "errors", "skipped", "disabled"):
            raw = element.get(key)
            if raw is not None and (not re.fullmatch(r"[0-9]{1,13}", raw) or int(raw) > 1000000000000):
                raise ValueError("JUnit declared counts must be nonnegative integers within range")
            declared[key] = int(raw) if raw is not None else None
        suite = {"index": index, "parent_index": parent, "name": summary.text(element.get("name")),
                 "declared_counts": declared, "declared_time_seconds": _duration(element.get("time")),
                 "observed_direct_test_count": 0}
        suites.append(suite)
        suite_path = (*suite_path, element.get("name"))
        for child in element:
            if tag(child) == "testsuite":
                visit(child, index, suite_path)
            elif tag(child) == "testcase":
                if len(tests) >= 2000:
                    raise ValueError("JUnit report exceeds 2000 test cases")
                markers = Counter(tag(item) for item in child if tag(item) in {"failure", "error", "skipped"})
                mixed += len(markers) > 1
                outcome = "error" if markers["error"] else "failed" if markers["failure"] else "skipped" if markers["skipped"] else "passed"
                diagnostics = [{"kind": tag(item), "type": summary.text(item.get("type")),
                                "message": summary.text(item.get("message"))}
                               for item in child if tag(item) in {"failure", "error", "skipped"}]
                tests.append({"suite_index": index, "name": summary.text(child.get("name")),
                              "classname": summary.text(child.get("classname")), "outcome": outcome,
                              "time_seconds": _duration(child.get("time")), "markers": dict(markers),
                              "diagnostics": summary.take(diagnostics, 5)})
                if _records is not None:
                    _records.append({"suite_path": suite_path, "classname": child.get("classname"),
                                     "name": child.get("name"), "outcome": outcome,
                                     "time_seconds": tests[-1]["time_seconds"], "mixed": len(markers) > 1})
                suite["observed_direct_test_count"] += 1
                outcomes[outcome] += 1
    visit(root)
    timed = [test for test in tests if test["time_seconds"] is not None]
    try:
        total_time = math.fsum(test["time_seconds"] for test in timed)
    except OverflowError as error:
        raise ValueError("Combined JUnit duration exceeds the numeric range") from error
    attention = [test for test in tests if test["outcome"] != "passed"]
    result = {"suite_count": len(suites), "test_count": len(tests),
              "outcomes": {key: outcomes[key] for key in ("passed", "failed", "error", "skipped")},
              "mixed_outcome_count": mixed, "timed_test_count": len(timed), "missing_time_count": len(tests) - len(timed),
              "total_testcase_time_seconds": total_time, "suites": summary.take(suites),
              "attention_tests": summary.take(attention),
              "slowest_tests": summary.take(sorted(timed, key=lambda item: item["time_seconds"], reverse=True)),
              "notes": ["Common JUnit XML declarations only, not test execution or a universal JUnit schema validator.",
                        "Observed counts use direct testcase elements once, not suite aggregate attributes; declared counts/times are separate.",
                        "Mixed markers use error > failure > skipped precedence; unmarked cases are reported as passed. Vendor retry/flaky extensions are not interpreted.",
                        "Failure element bodies, stdout/stderr, properties and file paths are omitted; diagnostic message attributes may contain supplied sensitive data."]}
    result["truncated"] = summary.truncated
    return result


def _choice(value, choices):
    if value is not None and (not isinstance(value, str) or value not in choices):
        raise ValueError("Unsupported report enum value")
    return value


def inspect_sarif(content, limit, *, _records=None):
    summary = _Summary(content, limit)
    try:
        data = json.loads(content, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ValueError("Invalid SARIF JSON; duplicate keys are rejected and source text is omitted") from error
    _mapping(data)
    _check_tree(data, max_nodes=20000, max_depth=50)
    if data.get("version") != "2.1.0":
        raise ValueError("Only inline SARIF version 2.1.0 is supported")
    runs = _array(data.get("runs"), 20)
    rows, run_rows, levels, rule_counts, suppression_states = [], [], Counter(), Counter(), Counter()
    for run_index, run in enumerate(runs):
        run = _mapping(run)
        driver = _mapping(_mapping(run.get("tool")).get("driver"))
        name = _name(driver.get("name"), required=True)
        rules = _array(driver.get("rules", []), 1000)
        rule_names = [_name(_mapping(rule).get("id"), required=True) for rule in rules]
        if len(rule_names) != len(set(rule_names)):
            raise ValueError("Duplicate driver rule IDs are not supported")
        artifacts = _array(run.get("artifacts", []), 1000)
        for artifact in artifacts:
            _mapping(artifact)
        results_available = run.get("results") is not None
        results = _array(run["results"]) if results_available else []
        if len(rows) + len(results) > 2000:
            raise ValueError("SARIF exceeds 2000 total results")
        run_rows.append({"index": run_index, "tool": name, "version": summary.text(driver.get("version")),
                         "result_count": len(results), "results_available": results_available, "rule_count": len(rules),
                         "external_properties_declared": "externalPropertyFileReferences" in run})
        for result_index, raw in enumerate(results):
            raw = _mapping(raw)
            reference = _mapping(raw.get("rule", {}))
            rule_id = _name(raw.get("ruleId", reference.get("id")))
            rule_index = _integer(raw.get("ruleIndex", reference.get("index")), -1)
            if rule_id is None and rule_index is not None and "toolComponent" not in reference and 0 <= rule_index < len(rule_names):
                rule_id = rule_names[rule_index]
            level = _choice(raw.get("level"), {"none", "note", "warning", "error"})
            kind = _choice(raw.get("kind"), {"notApplicable", "pass", "fail", "review", "open", "informational"})
            levels[level or "unspecified"] += 1
            rule_counts[(run_index, rule_id)] += 1
            message = _mapping(raw.get("message"))
            message_text = summary.text(message.get("text"))
            if message_text is None:
                message_text = summary.text(message.get("markdown"))
            suppressions = raw.get("suppressions")
            suppression_rows = []
            if suppressions is not None:
                for suppression in _array(suppressions, 20):
                    suppression = _mapping(suppression)
                    suppression_rows.append({"kind": _choice(suppression.get("kind"), {"inSource", "external"}),
                                             "status": _choice(suppression.get("status"), {"accepted", "underReview", "rejected"})})
            statuses = {item["status"] for item in suppression_rows}
            state = "unknown" if suppressions is None else "accepted" if "accepted" in statuses else "pending_or_unspecified" if statuses & {None, "underReview"} else "not_accepted"
            suppression_states[state] += 1
            locations = []
            for location in _array(raw.get("locations", []), 20):
                physical = _mapping(_mapping(location).get("physicalLocation", {}))
                artifact = _mapping(physical.get("artifactLocation", {}))
                uri = summary.text(artifact.get("uri"), 2000)
                uri_base_id = summary.text(artifact.get("uriBaseId"))
                artifact_index = _integer(artifact.get("index"), -1)
                if uri is None and artifact_index is not None and 0 <= artifact_index < len(artifacts):
                    indexed = _mapping(artifacts[artifact_index].get("location", {}))
                    uri = summary.text(indexed.get("uri"), 2000)
                    if uri_base_id is None:
                        uri_base_id = summary.text(indexed.get("uriBaseId"))
                region = _mapping(physical.get("region", {}))
                locations.append({"uri": uri, "uri_base_id": uri_base_id,
                                  "artifact_index": artifact_index,
                                  **{key: _integer(region.get(key), 1) for key in ("startLine", "startColumn", "endLine", "endColumn")}})
            rows.append({"run_index": run_index, "result_index": result_index, "rule_id": rule_id,
                         "rule_index": rule_index, "reported_level": level, "reported_kind": kind,
                         "message": message_text, "message_id": summary.text(message.get("id")),
                         "locations": summary.take(locations, 5), "suppression_state": state,
                         "suppressions": suppression_rows})
            if _records is not None:
                _records.append({"tool": name, "run_index": run_index, "result_index": result_index,
                                 "rule_id": rule_id, "reported_level": level, "reported_kind": kind,
                                 "suppression_state": state, "locations": locations,
                                 "fingerprints": raw.get("fingerprints"),
                                 "partial_fingerprints": raw.get("partialFingerprints")})
    rule_rows = [{"run_index": index, "rule_id": rule_id, "count": count} for (index, rule_id), count in rule_counts.most_common()]
    output = {"version": "2.1.0", "run_count": len(runs), "result_count": len(rows),
              "reported_level_counts": dict(sorted(levels.items())), "suppression_state_counts": dict(sorted(suppression_states.items())),
              "runs": summary.take(run_rows), "rules": summary.take(rule_rows), "results": summary.take(rows),
              "notes": ["Supplied scanner results only, not verified vulnerabilities or full SARIF validation; all results are counted, including suppressed results.",
                        "Missing/null run results are unavailable, not a clean scan; empty inline arrays are distinguished by results_available.",
                        "Only explicit result levels/kinds are reported. Rule defaults, invocation overrides, message templates, extensions and external properties are not resolved.",
                        "Missing suppression information is unknown; accepted, pending/unspecified and not-accepted requests are separated.",
                        "Inline artifact indexes can supply a URI; URI bases are not resolved. Paths and message text may contain supplied sensitive data.",
                        "Code snippets/flows, fixes, attachments, fingerprints and suppression justifications are omitted. No file/network access or scanner execution."]}
    output["truncated"] = summary.truncated
    return output


def _metric_number(value):
    try:
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "+Inf" if value > 0 else "-Inf"
        return value
    except (TypeError, OverflowError) as error:
        raise ValueError("Metric number is outside the supported numeric range") from error


def inspect_metrics(content, limit, *, _records=None):
    summary = _Summary(content, limit)
    lines = _lines(content)
    if any(line.strip().startswith(("# EOF", "# UNIT")) for line in lines):
        raise ValueError("Supply Prometheus text, not OpenMetrics/protobuf")
    families, series, types, names = [], set(), Counter(), set()
    sample_count = nonfinite = duplicates = 0
    try:
        for metric in text_string_to_metric_families(content):
            if len(families) >= 500:
                raise ValueError("Metrics exceed 500 family blocks")
            _name(metric.name, required=True)
            metric_type = "untyped" if metric.type == "unknown" else metric.type
            if metric_type not in {"counter", "gauge", "summary", "histogram", "untyped"}:
                raise ValueError("Unsupported Prometheus metric type")
            names.add(metric.name)
            types[metric_type] += 1
            samples, label_names = [], set()
            for sample in metric.samples:
                sample_count += 1
                if sample_count > 5000 or len(sample.labels) > 20:
                    raise ValueError("Metrics exceed 5000 samples or 20 labels per sample")
                _name(sample.name, required=True)
                labels = {}
                for key, value in sample.labels.items():
                    _name(key, required=True)
                    if not isinstance(value, str) or len(value) > 2000:
                        raise ValueError("Metric label values must be strings of at most 2000 characters")
                    labels[key] = value
                label_names.update(labels)
                identity = (sample.name, tuple(sorted(labels.items())))
                duplicates += identity in series
                series.add(identity)
                value = _metric_number(sample.value)
                nonfinite += isinstance(value, str)
                timestamp = _metric_number(sample.timestamp) if sample.timestamp is not None else None
                if isinstance(timestamp, str):
                    raise ValueError("Metric timestamps must be finite")
                samples.append({"name": sample.name, "labels": labels, "value": value, "timestamp_seconds": timestamp})
            families.append({"name": metric.name, "type": metric_type, "help": summary.text(metric.documentation),
                             "sample_count": len(samples), "label_names": sorted(label_names),
                             "samples": summary.take(samples), "samples_truncated": len(samples) > limit})
            if _records is not None:
                _records.append({"name": metric.name, "type": metric_type, "samples": samples})
    except (ValueError, OverflowError, IndexError, KeyError, AssertionError) as error:
        raise ValueError("Invalid or unsupported Prometheus text or exceeded metric limits; source text is omitted") from error
    output = {"family_count": len(families), "unique_family_count": len(names), "sample_count": sample_count,
              "unique_series_count": len(series), "duplicate_sample_count": duplicates, "nonfinite_value_count": nonfinite,
              "type_counts": dict(sorted(types.items())), "families": summary.take(families),
              "notes": ["One supplied Prometheus text snapshot only; no scraping, rates, trends, health conclusions or histogram quantile calculation.",
                        "Uses prometheus-client's permissive text parser, not full specification validation. OpenMetrics/protobuf are not supported.",
                        "Family names/counter samples may be normalized by the parser; family_count counts parsed blocks, not unique names.",
                        "NaN/+Inf/-Inf values are JSON strings; parser timestamps are seconds. Labels/help text may contain supplied sensitive data."]}
    output["truncated"] = summary.truncated
    return output


def _request_path(request):
    if not isinstance(request, str):
        return None, None
    parts = request.split()
    if len(parts) != 3 or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,100}", parts[0]) or not re.fullmatch(r"HTTP/[0-9]+(?:\.[0-9]+)?", parts[2]):
        return None, None
    method, target = parts[:2]
    if target == "*":
        return method, "*"
    try:
        parsed = urlsplit(target)
        if method == "CONNECT" or not (target.startswith("/") or parsed.scheme in {"http", "https"} and parsed.netloc):
            return method, None
        return method, parsed.path or "/"
    except ValueError:
        return method, None


def analyze_access(content, format, limit, *, _records=None):
    summary = _Summary(content, limit)
    if format not in ("common", "combined"):
        raise ValueError("format must be common or combined; custom formats are not supported")
    lines = _lines(content)
    parser = LogParser(COMMON if format == "common" else COMBINED)
    statuses, methods, paths, path_statuses = Counter(), Counter(), Counter(), Counter()
    invalid_samples = []
    parsed_count = invalid = blank = missing_bytes = unknown_status = unclassified = 0
    total_bytes = 0
    first = last = None
    for index, line in enumerate(lines, 1):
        if not line.strip():
            blank += 1
            continue
        try:
            entry = parser.parse(line)
            status, size = entry.final_status, entry.bytes_sent
            if status is not None and not 100 <= status <= 599:
                raise ValueError
            if size is not None and (size < 0 or size > 1000000000000):
                raise ValueError
            timestamp = getattr(entry, "request_time", None)
            if timestamp is None or timestamp.tzinfo is None:
                raise ValueError
            timestamp = timestamp.astimezone(timezone.utc)
        except (ValueError, OverflowError, UnicodeError):
            invalid += 1
            if len(invalid_samples) < limit:
                invalid_samples.append({"line": index, "reason": "Log entry or selected field does not match the supported format/range"})
            continue
        parsed_count += 1
        unknown_status += status is None
        if status is not None:
            statuses[status] += 1
        missing_bytes += size is None
        total_bytes += size or 0
        first = timestamp if first is None else min(first, timestamp)
        last = timestamp if last is None else max(last, timestamp)
        method, path = _request_path(entry.request_line)
        if method is not None:
            methods[method] += 1
        unclassified += path is None
        if path is not None:
            paths[(method, path)] += 1
            if status is not None:
                path_statuses[(method, path, status)] += 1
    client_errors = sum(count for status, count in statuses.items() if 400 <= status <= 499)
    server_errors = sum(count for status, count in statuses.items() if 500 <= status <= 599)
    known_status_count = sum(statuses.values())
    path_rows = [{"method": method, "path": summary.text(path), "count": count} for (method, path), count in paths.most_common()]
    method_rows = [{"method": method, "count": count} for method, count in methods.most_common()]
    if _records is not None:
        _records.update({"paths": paths, "path_statuses": path_statuses})
    summary.truncated |= invalid > limit
    output = {"format": format, "line_count": len(lines), "parsed_entries": parsed_count, "invalid_entries": invalid,
              "blank_lines": blank, "unknown_status_count": unknown_status,
              "status_counts": {str(status): count for status, count in sorted(statuses.items())},
              "client_error_count": client_errors, "server_error_count": server_errors,
              "error_response_fraction": (client_errors + server_errors) / known_status_count if known_status_count else None,
              "total_reported_bytes": total_bytes, "missing_bytes_count": missing_bytes,
              "methods": summary.take(method_rows), "unique_path_count": len(paths), "paths": summary.take(path_rows),
              "unclassified_request_target_count": unclassified, "invalid_samples": invalid_samples,
              "timestamp_range": {"first": first.isoformat() if first else None, "last": last.isoformat() if last else None},
              "notes": ["Supplied Apache common/combined logs only, not live monitoring. Lines with invalid fields are counted without source snippets.",
                        "Paths group exact method/path pairs, stripping query/fragment/authority without decoding percent escapes or inferring route templates.",
                        "Client IPs/users, referrers and user agents are omitted; remaining paths may contain supplied sensitive data.",
                        "CONNECT/unsupported/malformed targets are not grouped as paths; their valid log status/byte observations still count.",
                        "Byte totals include known values only, not missing '-' fields. Error fraction uses known statuses; timestamps do not imply complete coverage or request latency."]}
    output["truncated"] = summary.truncated
    return output
