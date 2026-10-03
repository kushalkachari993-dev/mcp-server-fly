import hashlib
import json
import math
from collections import Counter

from packageurl import PackageURL

from app.tools.report_comparison.service import _change, _inputs, _match, _matching
from app.tools.report_utils import service as reports
from app.tools.sbom_utils import service as sboms


def _finish(output, summary, notes):
    output["notes"] = notes + [
        "All bounded records are compared before display limits. Added/removed means observed in only one supplied input, not proof of completeness.",
        "Offline comparison only: no file/network access, execution or external reference resolution. Returned names, labels and paths may contain supplied sensitive data.",
    ]
    output["truncated"] = summary.truncated
    return output


def _fingerprint(row):
    for kind in ("fingerprints", "partial_fingerprints"):
        values = row[kind]
        if (isinstance(values, dict) and 1 <= len(values) <= 20
                and all(isinstance(key, str) and 0 < len(key) <= 200
                        and isinstance(value, str) and 0 < len(value) <= 2000
                        for key, value in values.items())):
            return kind, tuple(sorted(values.items()))
    return None


def _sarif_key(row):
    fingerprint = _fingerprint(row)
    if row["rule_id"] is None or fingerprint is None:
        return None
    return row["tool"], row["rule_id"], fingerprint


def _sarif_identity(row):
    kind, values = _fingerprint(row)
    digest = hashlib.sha256(json.dumps([kind, values], ensure_ascii=True).encode("utf-8")).hexdigest()
    return {"tool": row["tool"], "rule_id": row["rule_id"],
            "fingerprint_kind": kind, "fingerprint_sha256": digest}


def _sarif_observation(row, summary):
    location = row["locations"][0] if row["locations"] else None
    return {"identity": _sarif_identity(row), "run_index": row["run_index"],
            "result_index": row["result_index"], "reported_level": row["reported_level"],
            "reported_kind": row["reported_kind"], "suppression_state": row["suppression_state"],
            "first_location": None if location is None else {
                "uri": summary.text(location["uri"], 1000),
                "uri_base_id": summary.text(location["uri_base_id"]),
                "start_line": location["startLine"], "start_column": location["startColumn"],
            }}


def compare_sarif(before, after, limit):
    summary = _inputs(before, after, limit)
    records, views = [], []
    for content in (before, after):
        rows = []
        views.append(reports.inspect_sarif(content, 50, _records=rows))
        records.append(rows)
    match = _match(*records, _sarif_key)
    changes = []
    for old, new in match["matched"]:
        fields = [name for name in ("reported_level", "reported_kind", "suppression_state") if old[name] != new[name]]
        if fields:
            changes.append({"identity": _sarif_identity(old), "changed_fields": fields,
                            "before": _sarif_observation(old, summary),
                            "after": _sarif_observation(new, summary)})
    overview = []
    for view in views:
        inline = bool(view["runs"]) and all(run["results_available"] and not run["external_properties_declared"]
                                             for run in view["runs"])
        overview.append({"run_count": view["run_count"], "result_count": view["result_count"],
                         "reported_level_counts": view["reported_level_counts"],
                         "suppression_state_counts": view["suppression_state_counts"],
                         "inline_results_available": inline})
    fully_matchable = not (match["ambiguous"] or match["unmatchable_before_count"]
                           or match["unmatchable_after_count"])
    output = {"before": overview[0], "after": overview[1],
              "selected_results_completely_matchable": all(item["inline_results_available"] for item in overview)
              and fully_matchable,
              "matching": _matching(match, _sarif_identity, summary),
              "observed_added": summary.take([_sarif_observation(row, summary) for row in match["added"]]),
              "observed_removed": summary.take([_sarif_observation(row, summary) for row in match["removed"]]),
              "changed_count": len(changes), "changes": summary.take(changes)}
    return _finish(output, summary, [
        "Matches require exact scanner name, rule ID and complete bounded fingerprints or partialFingerprints mappings. No location/message fallback is guessed; duplicate identities are ambiguous.",
        "Fingerprint values are not returned; SHA-256 identifies the selected fingerprint mapping for display. Rule defaults, message templates and URI bases are not resolved.",
        "Observed additions/removals are not a full new/resolved-finding verdict when results are unavailable, external properties are declared, or identities are ambiguous/missing. Scanner coverage itself is not verified.",
        "Only explicit result levels, kinds and suppression requests are compared; findings and vulnerabilities are not validated.",
    ])


def _purl(row):
    try:
        return PackageURL.from_string(row["purl"]) if row["purl"] is not None else None
    except (TypeError, ValueError):
        return None


def _component_key(row):
    if row["purl"] is not None:
        purl = _purl(row)
        if purl is None:
            return None
        return (row["role"], row["type"], "purl", purl.type, purl.namespace, purl.name,
                tuple(sorted((purl.qualifiers or {}).items())), purl.subpath)
    return row["role"], row["type"], "declared", row["group"], row["name"]


def _component_identity(row, summary):
    purl = _purl(row)
    if purl is None:
        return {"basis": "declared", "role": row["role"], "type": row["type"],
                "group": summary.text(row["group"], 500), "name": summary.text(row["name"], 500)}
    stable = PackageURL(type=purl.type, namespace=purl.namespace, name=purl.name,
                        qualifiers=purl.qualifiers, subpath=purl.subpath).to_string()
    return {"basis": "purl", "role": row["role"], "type": row["type"],
            "purl_without_version": summary.text(stable, 1000)}


def _licenses(row):
    return sorted(json.dumps(item, sort_keys=True, ensure_ascii=True) for item in row["licenses"])


def _license_preview(row, summary):
    values = []
    for item in row["licenses"]:
        values.append({key: summary.text(value, 200) for key, value in item.items()})
    return summary.take(values, 5)


def _component_observation(row, summary):
    purl = _purl(row)
    return {"identity": _component_identity(row, summary), "version": summary.text(row["version"], 500),
            "purl_version": summary.text(purl.version, 500) if purl else None,
            "scope": summary.text(row["scope"], 500), "license_count": len(row["licenses"]),
            "licenses": _license_preview(row, summary)}


def compare_sboms(before, after, limit):
    summary = _inputs(before, after, limit)
    records, views = [], []
    for content in (before, after):
        rows = {}
        views.append(sboms.inspect_sbom(content, 50, _records=rows))
        records.append(rows["components"])
    match = _match(*records, _component_key)
    changed, versions, licenses = [], [], []
    for old, new in match["matched"]:
        old_purl, new_purl = _purl(old), _purl(new)
        version_changed = (old["version"] != new["version"]
                           or (old_purl.version if old_purl else None) != (new_purl.version if new_purl else None))
        license_changed = _licenses(old) != _licenses(new)
        fields = [name for name, different in (
            ("version", version_changed), ("licenses", license_changed), ("scope", old["scope"] != new["scope"]),
            ("group", old["group"] != new["group"]), ("name", old["name"] != new["name"])) if different]
        if fields:
            row = {"identity": _component_identity(old, summary), "changed_fields": fields,
                   "before": _component_observation(old, summary),
                   "after": _component_observation(new, summary)}
            changed.append(row)
            if version_changed:
                versions.append(row)
            if license_changed:
                licenses.append(row)
    overview = [{"spec_version": view["spec_version"], "component_count": view["component_count"],
                 "types": view["types"], "dependency_entry_count": view["dependency_graph"]["entry_count"],
                 "dependency_edge_count": view["dependency_graph"]["edge_count"],
                 "unresolved_reference_count": view["dependency_graph"]["unresolved_reference_count"]}
                for view in views]
    identity = lambda row: _component_identity(row, summary)
    return _finish({"before": overview[0], "after": overview[1],
                    "matching": _matching(match, identity, summary),
                    "added_components": summary.take([_component_observation(row, summary) for row in match["added"]]),
                    "removed_components": summary.take([_component_observation(row, summary) for row in match["removed"]]),
                    "changed_count": len(changed), "changes": summary.take(changed),
                    "version_change_count": len(versions), "version_changes": summary.take(versions),
                    "license_change_count": len(licenses), "license_changes": summary.take(licenses)}, summary, [
        "Package URL matches omit the parsed version but retain type, namespace, name, qualifiers and subpath. BOM-local bom-ref values are not cross-report identities.",
        "Without PURLs, exact role/type/group/name matches are weaker declared-coordinate matches. Invalid PURLs and duplicate identities remain unresolved; version order or upgrade direction is not inferred.",
        "License choice order is ignored. Dependency counts are context only; dependency edges, nested-parent links and BOM completeness are not compared.",
        "Supplied inventories are not evidence of installed packages, vulnerabilities, license compliance or release safety.",
    ])


def _series_rows(families):
    counts = Counter(family["name"] for family in families)
    return [{"family": family["name"], "family_type": family["type"],
             "family_unique": counts[family["name"]] == 1, **sample}
            for family in families for sample in family["samples"]]


def _series_key(row):
    if not row["family_unique"]:
        return None
    return row["family"], row["name"], tuple(sorted(row["labels"].items()))


def _series_identity(row, summary):
    return {"family": row["family"], "sample": row["name"],
            "labels": {key: summary.text(value, 200) for key, value in sorted(row["labels"].items())}}


def _finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _series_change(old, new, summary):
    row = {"identity": _series_identity(old, summary), "before_type": old["family_type"],
           "after_type": new["family_type"], "before_value": old["value"], "after_value": new["value"],
           "before_timestamp_seconds": old["timestamp_seconds"],
           "after_timestamp_seconds": new["timestamp_seconds"],
           "snapshot_delta": None, "raw_counter_difference": None, "possible_counter_reset": False}
    if old["family_type"] != new["family_type"]:
        row["reason"] = "family_type_changed"
    elif not (_finite_number(old["value"]) and _finite_number(new["value"])):
        row["reason"] = "nonfinite_value"
    elif old["family_type"] == "gauge":
        row["snapshot_delta"] = _change(old["value"], new["value"])["delta"]
        row["reason"] = None if row["snapshot_delta"] is not None else "numeric_range_exceeded"
    elif old["family_type"] == "counter" and old["name"].endswith("_total"):
        row["raw_counter_difference"] = _change(old["value"], new["value"])["delta"]
        row["possible_counter_reset"] = new["value"] < old["value"]
        row["reason"] = None if row["raw_counter_difference"] is not None else "numeric_range_exceeded"
    else:
        row["reason"] = "not_a_scalar_gauge_or_counter_total"
    return row


def compare_metrics(before, after, limit):
    summary = _inputs(before, after, limit)
    families, views = [], []
    for content in (before, after):
        rows = []
        views.append(reports.inspect_metrics(content, 50, _records=rows))
        families.append(rows)
    family_match = _match(*families, lambda row: row["name"])
    type_changes = [{"family": old["name"], "before_type": old["type"], "after_type": new["type"]}
                    for old, new in family_match["matched"] if old["type"] != new["type"]]
    series_match = _match(_series_rows(families[0]), _series_rows(families[1]), _series_key)
    comparisons = [_series_change(old, new, summary) for old, new in series_match["matched"]]
    changed = [row for row in comparisons if row["before_type"] != row["after_type"]
               or row["before_value"] != row["after_value"]]
    counter_decreases = [row for row in comparisons if row["possible_counter_reset"]]
    overview = [{name: view[name] for name in ("family_count", "unique_family_count", "sample_count",
                                               "unique_series_count", "duplicate_sample_count",
                                               "nonfinite_value_count", "type_counts")}
                for view in views]
    identity = lambda row: _series_identity(row, summary)
    return _finish({"before": overview[0], "after": overview[1],
                    "family_matching": _matching(family_match, lambda row: {"name": row["name"]}, summary),
                    "family_type_change_count": len(type_changes), "family_type_changes": summary.take(type_changes),
                    "series_matching": _matching(series_match, identity, summary),
                    "series_comparisons": summary.take(comparisons), "changed_value_or_type_count": len(changed),
                    "changed_series": summary.take(changed),
                    "raw_counter_decrease_count": len(counter_decreases),
                    "raw_counter_decreases": summary.take(counter_decreases)}, summary, [
        "Series match exact parsed family/sample names and label pairs. Duplicate family names or sample identities are not paired by position; names may be normalized by prometheus-client.",
        "Gauge deltas are differences between two observed snapshots. Counter differences are raw values, not event counts or rates; a lower value may indicate reset or series replacement, and a reset can occur even without a decrease.",
        "Histogram/summary components, nonfinite values and changed family types receive no numeric delta. Timestamps are displayed but not used to infer rates or comparable collection windows.",
        "Uses the existing permissive Prometheus text parser, not full exposition validation or OpenMetrics/protobuf parsing.",
    ])


def _path_rows(records):
    status_by_path = {}
    for (method, path, status), count in records["path_statuses"].items():
        status_by_path.setdefault((method, path), Counter())[status] += count
    rows = []
    for (method, path), count in records["paths"].items():
        statuses = status_by_path.get((method, path), Counter())
        known = sum(statuses.values())
        errors = sum(number for status, number in statuses.items() if 400 <= status <= 599)
        rows.append({"method": method, "path": path, "count": count,
                     "known_status_count": known, "error_count": errors,
                     "status_counts": {str(status): number for status, number in sorted(statuses.items())}})
    return rows


def _path_identity(row, summary):
    return {"method": row["method"], "path": summary.text(row["path"], 1000)}


def _fraction(errors, known):
    return errors / known if known else None


def compare_access(before, after, format, limit):
    summary = _inputs(before, after, limit)
    records, views = [], []
    for content in (before, after):
        rows = {}
        views.append(reports.analyze_access(content, format, 50, _records=rows))
        records.append(_path_rows(rows))
    match = _match(*records, lambda row: (row["method"], row["path"]))
    comparisons = []
    for old, new in match["matched"]:
        before_fraction = _fraction(old["error_count"], old["known_status_count"])
        after_fraction = _fraction(new["error_count"], new["known_status_count"])
        statuses = sorted(old["status_counts"].keys() | new["status_counts"].keys(), key=int)
        status_changes = [{"status": status,
                           **_change(old["status_counts"].get(status, 0), new["status_counts"].get(status, 0))}
                          for status in statuses]
        changed_statuses = [item for item in status_changes if item["delta"] != 0]
        comparisons.append({"identity": _path_identity(old, summary),
                            "request_count": _change(old["count"], new["count"]),
                            "error_count": _change(old["error_count"], new["error_count"]),
                            "known_status_count": _change(old["known_status_count"], new["known_status_count"]),
                            "error_fraction": _change(before_fraction, after_fraction),
                            "status_change_count": len(changed_statuses),
                            "status_changes": summary.take(changed_statuses)})
    changed = [row for row in comparisons if row["request_count"]["delta"] != 0
               or row["known_status_count"]["delta"] != 0
               or row["status_change_count"] != 0]
    increases = sorted((row for row in comparisons if row["error_count"]["delta"] > 0),
                       key=lambda row: row["error_count"]["delta"], reverse=True)
    statuses = sorted(views[0]["status_counts"].keys() | views[1]["status_counts"].keys(), key=int)
    status_changes = [{"status": status,
                       **_change(views[0]["status_counts"].get(status, 0),
                                 views[1]["status_counts"].get(status, 0))} for status in statuses]
    fields = ("format", "line_count", "parsed_entries", "invalid_entries", "blank_lines", "unknown_status_count",
              "client_error_count", "server_error_count", "error_response_fraction", "unique_path_count",
              "unclassified_request_target_count", "timestamp_range")
    overview = [{name: view[name] for name in fields} for view in views]
    identity = lambda row: _path_identity(row, summary)
    return _finish({"before": overview[0], "after": overview[1],
                    "error_fraction_change": _change(views[0]["error_response_fraction"],
                                                     views[1]["error_response_fraction"]),
                    "status_changes": summary.take(status_changes),
                    "matching": _matching(match, identity, summary),
                    "changed_path_count": len(changed), "changed_paths": summary.take(changed),
                    "path_error_count_increase_count": len(increases),
                    "largest_path_error_count_increases": summary.take(increases)}, summary, [
        "Only valid parsed lines contribute counts. Status fractions divide by known statuses; invalid/blank/unknown-status observations remain separately reported.",
        "Paths match exact method and query-free path; queries, user information, referrers and agents are omitted. Different queries intentionally merge, and route templates are not inferred.",
        "Inputs are caller-supplied windows. Counts and fractions do not establish comparable traffic, elapsed-time rates, statistical significance or a causal regression; common/combined logs do not provide latency.",
    ])
