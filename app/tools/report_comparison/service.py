import math
from collections import Counter, defaultdict

from app.tools.coverage_utils import service as coverage
from app.tools.performance_utils import service as performance
from app.tools.report_utils import service as reports


def _inputs(before, after, limit):
    summary = reports._Summary(before, limit)
    reports._Summary(after, limit)
    return summary


def _change(before, after, compatible=True):
    reason = None
    delta = relative = None
    if not compatible:
        reason = "incompatible_or_unknown_dimension"
    elif before is None or after is None:
        reason = "missing_measurement"
    else:
        delta = after - before
        if not math.isfinite(delta):
            delta, reason = None, "numeric_range_exceeded"
        elif before != 0:
            relative = delta / abs(before) * 100
            if not math.isfinite(relative):
                relative = None
    return {"before": before, "after": after, "delta": delta,
            "relative_percent": relative, "comparable": reason is None, "reason": reason}


def _valid_name(value, required=False):
    if value is None:
        return not required
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= 1000
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _match(before, after, key):
    indexes, unknown = [], []
    for rows in (before, after):
        index, missing = defaultdict(list), 0
        for row in rows:
            identity = key(row)
            if identity is None:
                missing += 1
            else:
                index[identity].append(row)
        indexes.append(index)
        unknown.append(missing)
    left, right = indexes
    matched, added, removed, ambiguous = [], [], [], []
    for identity in dict.fromkeys([*left, *right]):
        old, new = left.get(identity, []), right.get(identity, [])
        if len(old) > 1 or len(new) > 1:
            ambiguous.append({"record": (old or new)[0], "before_count": len(old), "after_count": len(new)})
        elif old and new:
            matched.append((old[0], new[0]))
        elif new:
            added.append(new[0])
        else:
            removed.append(old[0])
    return {"matched": matched, "added": added, "removed": removed, "ambiguous": ambiguous,
            "unmatchable_before_count": unknown[0], "unmatchable_after_count": unknown[1]}


def _matching(match, identity, summary):
    return {"matched_count": len(match["matched"]), "added_count": len(match["added"]),
            "removed_count": len(match["removed"]), "ambiguous_count": len(match["ambiguous"]),
            "unmatchable_before_count": match["unmatchable_before_count"],
            "unmatchable_after_count": match["unmatchable_after_count"],
            "added": summary.take([identity(row) for row in match["added"]]),
            "removed": summary.take([identity(row) for row in match["removed"]]),
            "ambiguous": summary.take([{"identity": identity(row["record"]), "before_count": row["before_count"],
                                         "after_count": row["after_count"]} for row in match["ambiguous"]])}


def _finish(output, summary, notes):
    output["notes"] = notes + [
        "All bounded records are inspected before output limiting. Added/removed means present in only one supplied report, not proof of completeness.",
        "Missing measurements stay unknown. Relative percentages use abs(before); a zero baseline gives null relative percent.",
        "Offline comparison only: no file/network access, test execution or threshold evaluation. Returned names/paths may contain caller-supplied sensitive data."]
    output["truncated"] = summary.truncated
    return output


def _coverage_delta(old, new, compatible=True):
    known = compatible and old["unknown"] == 0 and new["unknown"] == 0
    return {"before": old, "after": new,
            "found_delta": _change(old["found"], new["found"], known)["delta"],
            "hit_delta": _change(old["hit"], new["hit"], known)["delta"],
            "percentage_point_delta": _change(old["coverage_percent"], new["coverage_percent"], compatible)["delta"],
            "comparable": known and old["coverage_percent"] is not None and new["coverage_percent"] is not None}


def compare_coverage(before, after, format, limit):
    summary = _inputs(before, after, limit)
    if not isinstance(format, str) or format not in {"lcov", "cobertura"}:
        raise ValueError("Coverage format must be lcov or cobertura; both reports must use that format")
    records, views = [], []
    parser = coverage.inspect_lcov if format == "lcov" else coverage.inspect_cobertura
    for content in (before, after):
        rows = []
        views.append(parser(content, 50, _records=rows))
        records.append(rows)

    def key(row):
        if format == "lcov":
            return row["file"], row["test_name"]
        if not _valid_name(row["package"], True) or not _valid_name(row["class"], True):
            return None
        return row["file"], row["package"], row["class"]

    def identity(row):
        if format == "lcov":
            return {"file": row["file"], "test_name": row["test_name"]}
        return {"file": row["file"], "package": row["package"], "class": row["class"]}

    match = _match(*records, key)
    comparisons, totals = [], Counter()
    for old, new in match["matched"]:
        left, right = old["lines"], new["lines"]
        common = left.keys() & right.keys()
        transitions = {"newly_uncovered_lines": sorted(number for number in common if left[number] > 0 and right[number] == 0),
                       "newly_covered_lines": sorted(number for number in common if left[number] == 0 and right[number] > 0),
                       "added_lines": sorted(right.keys() - left.keys()), "removed_lines": sorted(left.keys() - right.keys()),
                       "uncovered_added_lines": sorted(number for number in right.keys() - left.keys() if right[number] == 0)}
        row = {"identity": identity(old), "coverage": {}}
        for kind in old["observed"]:
            compatible = kind != "functions" or old.get("function_format") == new.get("function_format")
            row["coverage"][kind] = _coverage_delta(old["observed"][kind], new["observed"][kind], compatible)
        row["line_change_counts"] = {name: len(values) for name, values in transitions.items()}
        totals.update(row["line_change_counts"])
        row.update({name: summary.take(values) for name, values in transitions.items()})
        comparisons.append(row)
    files = [set(row["file"] for row in rows) for rows in records]
    added_files, removed_files = sorted(files[1] - files[0]), sorted(files[0] - files[1])
    overviews = []
    for view in views:
        if format == "lcov":
            overviews.append({name: view[name] for name in ("record_count", "unique_file_count", "observed_record_totals",
                                                          "mismatched_record_count", "ignored_record_types")})
        else:
            overviews.append({name: view[name] for name in ("class_count", "unique_file_count", "observed_class_lines",
                                                          "observed_class_branches", "declared")})
    observed = [view["observed_record_totals"] if format == "lcov" else
                {"lines": view["observed_class_lines"], "branches": view["observed_class_branches"]} for view in views]
    function_formats = [{row.get("function_format") for row in rows if row.get("function_format") is not None} for rows in records]
    functions_comparable = function_formats[0] == function_formats[1] and len(function_formats[0]) <= 1
    total_changes = {kind: _coverage_delta(observed[0][kind], observed[1][kind],
                                          kind != "functions" or functions_comparable) for kind in observed[0]}
    return _finish({"format": format, "before": overviews[0], "after": overviews[1],
                    "observed_total_changes": total_changes,
                    "matching": _matching(match, identity, summary), "comparisons": summary.take(comparisons),
                    "added_file_count": len(added_files), "removed_file_count": len(removed_files),
                    "added_files": summary.take(added_files), "removed_files": summary.take(removed_files),
                    "line_change_counts": {name: totals[name] for name in ("newly_uncovered_lines", "newly_covered_lines",
                                                                          "added_lines", "removed_lines", "uncovered_added_lines")}},
                   summary, ["LCOV identities are exact (file, test_name); Cobertura identities are exact (file, package, class). Repeated identities are not merged.",
                             "Coverage deltas use observed records, never declared rates. LCOV function-format changes and mixed-format aggregate function totals are not directly comparable; Cobertura has no observed function coverage.",
                             "Newly covered/uncovered transitions require an observed line number in both matched records. Added uncovered lines are separate; removed lines are not treated as improved coverage.",
                             "Line numbers are not remapped across revisions. Equal paths/line numbers do not prove equal source code, tests or coverpoints. Totals sum record observations, not unique-file coverage."])


def compare_junit(before, after, limit):
    summary = _inputs(before, after, limit)
    records, views = [], []
    for content in (before, after):
        rows = []
        views.append(reports.inspect_junit(content, 50, _records=rows))
        records.append(rows)

    def key(row):
        if (not _valid_name(row["name"], True) or not _valid_name(row["classname"])
                or not all(_valid_name(name, True) for name in row["suite_path"])):
            return None
        return row["suite_path"], row["classname"], row["name"]

    def identity(row):
        return {"suite_path": list(row["suite_path"]), "classname": row["classname"], "name": row["name"]}

    match = _match(*records, key)
    comparisons, failing, recovered, changed, uncertain = [], [], [], [], []
    for old, new in match["matched"]:
        known = not old["mixed"] and not new["mixed"]
        row = {"identity": identity(old), "before_outcome": old["outcome"], "after_outcome": new["outcome"],
               "outcome_comparable": known, "duration_seconds": _change(old["time_seconds"], new["time_seconds"])}
        comparisons.append(row)
        if not known:
            uncertain.append(row)
        elif old["outcome"] == "passed" and new["outcome"] in {"failed", "error"}:
            failing.append(row)
        elif old["outcome"] in {"failed", "error"} and new["outcome"] == "passed":
            recovered.append(row)
        if known and old["outcome"] != new["outcome"]:
            changed.append(row)
    slower = sorted((row for row in comparisons if row["duration_seconds"]["delta"] is not None
                     and row["duration_seconds"]["delta"] > 0), key=lambda row: row["duration_seconds"]["delta"], reverse=True)
    fields = ("test_count", "suite_count", "outcomes", "mixed_outcome_count", "timed_test_count", "missing_time_count", "total_testcase_time_seconds")
    return _finish({"before": {name: views[0][name] for name in fields}, "after": {name: views[1][name] for name in fields},
                    "matching": _matching(match, identity, summary), "comparisons": summary.take(comparisons),
                    "newly_failing_count": len(failing), "newly_failing_tests": summary.take(failing),
                    "recovered_count": len(recovered), "recovered_tests": summary.take(recovered),
                    "outcome_changed_count": len(changed), "outcome_changes": summary.take(changed),
                    "uncertain_outcome_count": len(uncertain), "uncertain_outcomes": summary.take(uncertain),
                    "slower_test_count": len(slower), "largest_duration_increases": summary.take(slower)}, summary,
                   ["Matches use exact suite ancestry, classname and test name. Missing/oversized/control-containing identities and duplicates are not guessed or paired by position.",
                    "Newly failing means passed to failed/error; recovered means failed/error to passed. Skipped transitions remain separate outcome changes. Mixed markers retain inspector precedence but are not classified as new failures/recoveries. Unmarked cases use the inspector's passed outcome; vendor retry/flaky extensions are not interpreted.",
                    "Durations are reported testcase seconds, not elapsed wall time. Differences do not establish flaky tests, a causal performance regression or comparable environments. Diagnostic bodies/messages and stdout/stderr are omitted."])


def _har_groups(rows):
    groups, unsupported = {}, 0
    for row in rows:
        target = row["target"]
        if not target["supported"]:
            unsupported += 1
            continue
        port = target["port"] if target["port"] is not None else 443 if target["scheme"] == "https" else 80
        key = row["method"], target["scheme"], target["host"], port, target["path"]
        groups.setdefault(key, []).append(row)
    output = []
    for key, entries in groups.items():
        durations = [row["time_ms"] for row in entries if row["time_ms"] is not None]
        body = [row["response_body_size"] for row in entries if row["response_body_size"] is not None]
        content = [row["response_content_size"] for row in entries if row["response_content_size"] is not None]
        output.append({"key": key, "entry_count": len(entries), "status_counts": dict(sorted(Counter(str(row["status"]) for row in entries).items())),
                       "duration_ms": performance._stats(durations), "missing_duration_count": len(entries) - len(durations),
                       "body_bytes": {"reported_total": sum(body), "unknown_count": len(entries) - len(body)},
                       "content_bytes": {"reported_total": sum(content), "unknown_count": len(entries) - len(content)}})
    return output, unsupported


def compare_har(before, after, limit):
    summary = _inputs(before, after, limit)
    groups, views = [], []
    for content in (before, after):
        rows = []
        view = performance.inspect_har(content, 50, _records=rows)
        grouped, excluded = _har_groups(rows)
        groups.append(grouped)
        views.append({"entry_count": view["entry_count"], "group_count": len(grouped), "unsupported_url_count": excluded,
                      "duration_ms": view["duration_ms"], "missing_duration_count": view["missing_duration_count"],
                      "status_counts": view["status_counts"]})

    def identity(row):
        method, scheme, host, port, path = row["key"]
        return {"method": method, "scheme": scheme, "host": host, "port": port, "path": summary.text(path)}

    match = _match(*groups, lambda row: row["key"])
    comparisons = []
    for old, new in match["matched"]:
        duration = {name: _change(old["duration_ms"][name], new["duration_ms"][name]) for name in ("min", "max", "mean", "median")}
        statuses = sorted(old["status_counts"].keys() | new["status_counts"].keys())
        sizes = {}
        for name in ("body_bytes", "content_bytes"):
            sizes[name] = {"before": old[name], "after": new[name],
                           "total_delta": _change(old[name]["reported_total"], new[name]["reported_total"],
                                                  old[name]["unknown_count"] == new[name]["unknown_count"] == 0)["delta"]}
        comparisons.append({"identity": identity(old), "entry_count": _change(old["entry_count"], new["entry_count"]),
                            "duration_ms": duration, "before_measured_duration_count": old["duration_ms"]["count"],
                            "after_measured_duration_count": new["duration_ms"]["count"],
                            "before_missing_duration_count": old["missing_duration_count"], "after_missing_duration_count": new["missing_duration_count"],
                            "status_counts": {status: _change(old["status_counts"].get(status, 0), new["status_counts"].get(status, 0)) for status in statuses},
                            **sizes})
    increases = sorted((row for row in comparisons if row["duration_ms"]["mean"]["delta"] is not None
                        and row["duration_ms"]["mean"]["delta"] > 0), key=lambda row: row["duration_ms"]["mean"]["delta"], reverse=True)
    return _finish({"before": views[0], "after": views[1], "matching": _matching(match, identity, summary),
                    "comparisons": summary.take(comparisons), "mean_duration_increase_count": len(increases),
                    "largest_mean_duration_increases": summary.take(increases)}, summary,
                   ["Groups use method, scheme, lowercase parsed host, effective port and exact full path; default ports normalize. Percent-escapes are not decoded. Display paths are shortened to 1000 characters only after exact matching.",
                    "Userinfo, query/fragment, headers, cookies, bodies and comments are omitted. Different queries intentionally merge into one group; unsupported schemes are counted but not compared. Repeated requests are grouped, never paired by position.",
                    "Timing comparisons describe available samples, not identical requests or workloads, statistical significance or proven regressions. Missing sizes prevent complete total deltas; reported body/content sizes are not wire traffic."])


def compare_k6(before, after, limit):
    summary = _inputs(before, after, limit)
    records, views = [], []
    for content in (before, after):
        rows = {}
        views.append(performance.inspect_k6(content, 50, _records=rows))
        records.append(rows)
    same_format = views[0]["format"] == views[1]["format"]

    def identity(row):
        return {"source": row["source"], "name": row["name"]}

    match = _match(records[0]["metrics"], records[1]["metrics"], lambda row: (row["source"], row["name"]))
    comparisons = []
    value_count, unknown_count = 0, 0
    for old, new in match["matched"]:
        compatible = same_format and old["type"] == new["type"] and old["contains"] is not None and old["contains"] == new["contains"]
        values = []
        for name in dict.fromkeys([*old["values"], *new["values"]]):
            change = _change(old["values"].get(name), new["values"].get(name), compatible)
            values.append({"name": name, **change})
            value_count += 1
            unknown_count += not change["comparable"]
        comparisons.append({"identity": identity(old), "before_type": old["type"], "after_type": new["type"],
                            "before_contains": old["contains"], "after_contains": new["contains"],
                            "dimensions_comparable": compatible, "value_count": len(values), "values": summary.take(values),
                            "before_thresholds_available": old["thresholds_available"], "after_thresholds_available": new["thresholds_available"]})
    thresholds = _match(records[0]["thresholds"], records[1]["thresholds"],
                        lambda row: (row["source"], row["metric"], row["expression"]))
    metric_pairs = {(old["source"], old["name"]): (old, new) for old, new in match["matched"]}
    transitions, failing, recovered = [], [], []
    for old, new in thresholds["matched"]:
        left, right = metric_pairs[(old["source"], old["metric"])]
        known = (same_format and left["type"] == right["type"] and left["contains"] is not None
                 and left["contains"] == right["contains"] and old["ok"] is not None and new["ok"] is not None)
        row = {"source": old["source"], "metric": old["metric"], "expression": old["expression"],
               "before_ok": old["ok"], "after_ok": new["ok"], "comparable": known}
        transitions.append(row)
        if known and old["ok"] is True and new["ok"] is False:
            failing.append(row)
        if known and old["ok"] is False and new["ok"] is True:
            recovered.append(row)
    fields = ("format", "schema_version", "duration_seconds", "metric_count", "type_counts", "threshold_count", "threshold_counts",
              "all_reported_thresholds_passed", "check_results_available", "check_result_count", "check_totals")
    return _finish({"before": {name: views[0][name] for name in fields}, "after": {name: views[1][name] for name in fields},
                    "same_format": same_format, "matching": _matching(match, identity, summary),
                    "metric_comparisons": summary.take(comparisons), "value_comparison_count": value_count,
                    "unknown_value_comparison_count": unknown_count,
                    "threshold_matching": _matching(thresholds, lambda row: {"source": row["source"], "metric": row["metric"], "expression": row["expression"]}, summary),
                    "threshold_comparisons": summary.take(transitions), "newly_failing_threshold_count": len(failing),
                    "newly_failing_thresholds": summary.take(failing), "recovered_threshold_count": len(recovered),
                    "recovered_thresholds": summary.take(recovered)}, summary,
                   ["Metrics match exact source/name and numeric fields match exact keys. Deltas require the same supported summary format, metric type and known contains dimension. Cross-format, missing dimensions/values or changed types produce unknown deltas.",
                    "Reported statistics/rates/percentiles are not recomputed, unit-converted or summed across tagged/check metrics. Field keys are not translated between formats. Caller must ensure consistent actual units, test scripts, load and environments.",
                    "Thresholds match exact source/metric/expression. Only explicit compatible boolean transitions are classified; absent/empty/unknown thresholds do not mean pass. Expressions are never evaluated. Check counts remain separate reported overviews, not paired assertions.",
                    "Numeric differences and threshold transitions do not prove causal or statistically significant regressions or production capacity."])
