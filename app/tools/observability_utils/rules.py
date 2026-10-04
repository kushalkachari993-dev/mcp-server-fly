from app.tools.config_utils.service import _load
from app.tools.report_comparison.service import _inputs, _match, _matching
from app.tools.report_utils.service import _array, _mapping


_GROUP_FIELDS = {"name", "interval", "limit", "query_offset", "labels", "rules"}
_RULE_FIELDS = {"alert", "record", "expr", "for", "keep_firing_for", "labels", "annotations"}


def _name(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 200
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("Rule/group names must be nonempty strings of at most 200 characters without controls")
    return value


def _string(value, label, maximum=5000, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > maximum:
        raise ValueError(f"Invalid {label}; source text is omitted")
    return value


def _labels(value, label):
    mapping = _mapping(value)
    if len(mapping) > 50:
        raise ValueError(f"{label} exceeds 50 keys")
    for key, item in mapping.items():
        _name(key)
        if not isinstance(item, str) or len(item) > 2000:
            raise ValueError(f"Invalid {label}; source text is omitted")
    return mapping


def _parse(content):
    data = _load(content)
    groups, rules = [], []
    ignored_group_fields = ignored_rule_fields = 0
    for group_index, raw in enumerate(_array(data.get("groups"), 100)):
        raw = _mapping(raw)
        name = _name(raw.get("name"))
        rule_items = _array(raw.get("rules"), 1000)
        ignored_group_fields += len(raw.keys() - _GROUP_FIELDS)
        limit = raw.get("limit")
        if limit is not None and (type(limit) is not int or not 0 <= limit <= 1000000000):
            raise ValueError("Group limit must be a nonnegative integer")
        groups.append({"name": name, "position": group_index,
                       "interval": _string(raw.get("interval"), "group interval", 100),
                       "limit": limit, "query_offset": _string(raw.get("query_offset"), "group query_offset", 100),
                       "labels": _labels(raw.get("labels", {}), "group labels"),
                       "rule_count": len(rule_items)})
        for rule_index, item in enumerate(rule_items):
            if len(rules) >= 1000:
                raise ValueError("Rule file exceeds 1000 rules")
            item = _mapping(item)
            kind = "alert" if "alert" in item else "record" if "record" in item else None
            if kind is None or "alert" in item and "record" in item:
                raise ValueError("Each rule must declare exactly one alert or record name")
            ignored_rule_fields += len(item.keys() - _RULE_FIELDS)
            rules.append({"group": name, "kind": kind, "name": _name(item[kind]),
                          "position": rule_index, "expr": _string(item.get("expr"), "rule expression", required=True),
                          "for": _string(item.get("for"), "alert for duration", 100),
                          "keep_firing_for": _string(item.get("keep_firing_for"), "alert keep_firing_for duration", 100),
                          "labels": _labels(item.get("labels", {}), "rule labels"),
                          "annotations": _labels(item.get("annotations", {}), "rule annotations")})
    view = {"group_count": len(groups), "rule_count": len(rules),
            "alert_rule_count": sum(row["kind"] == "alert" for row in rules),
            "recording_rule_count": sum(row["kind"] == "record" for row in rules),
            "ignored_group_field_count": ignored_group_fields,
            "ignored_rule_field_count": ignored_rule_fields}
    return view, groups, rules


def _group_identity(row):
    return {"group": row["name"]}


def _rule_identity(row):
    return {"group": row["group"], "kind": row["kind"], "name": row["name"]}


def _changed_keys(before, after):
    return sorted(key for key in before.keys() | after.keys()
                  if key not in before or key not in after or before[key] != after[key])


def compare_prometheus_rule_files(before, after, limit):
    summary = _inputs(before, after, limit)
    parsed = [_parse(content) for content in (before, after)]
    group_match = _match(parsed[0][1], parsed[1][1], lambda row: row["name"])
    rule_match = _match(parsed[0][2], parsed[1][2], lambda row: (row["group"], row["kind"], row["name"]))
    group_changes = []
    for old, new in group_match["matched"]:
        fields = [field for field in ("position", "interval", "limit", "query_offset", "labels", "rule_count")
                  if old[field] != new[field]]
        if fields:
            group_changes.append({"identity": _group_identity(old), "changed_fields": fields,
                                  "changed_label_keys": summary.take(_changed_keys(old["labels"], new["labels"])),
                                  "before_position": old["position"], "after_position": new["position"],
                                  "before_rule_count": old["rule_count"], "after_rule_count": new["rule_count"]})
    rule_changes = []
    for old, new in rule_match["matched"]:
        fields = [field for field in ("position", "expr", "for", "keep_firing_for", "labels", "annotations")
                  if old[field] != new[field]]
        if fields:
            rule_changes.append({"identity": _rule_identity(old), "changed_fields": fields,
                                 "changed_label_keys": summary.take(_changed_keys(old["labels"], new["labels"])),
                                 "changed_annotation_keys": summary.take(_changed_keys(old["annotations"], new["annotations"])),
                                 "before_position": old["position"], "after_position": new["position"]})
    known_change = bool(group_changes or rule_changes or group_match["added"] or group_match["removed"]
                        or rule_match["added"] or rule_match["removed"])
    ambiguous = bool(group_match["ambiguous"] or rule_match["ambiguous"])
    return {"before": parsed[0][0], "after": parsed[1][0],
            "selected_fields_equal": False if known_change else None if ambiguous else True,
            "group_matching": _matching(group_match, _group_identity, summary),
            "rule_matching": _matching(rule_match, _rule_identity, summary),
            "changed_group_count": len(group_changes), "group_changes": summary.take(group_changes),
            "changed_rule_count": len(rule_changes), "rule_changes": summary.take(rule_changes),
            "truncated": summary.truncated,
            "notes": ["Supplied Prometheus YAML rule files only. Group identities use exact names; rule identities use exact group/kind/name. Duplicate identities stay ambiguous; moves between groups are observed removal/addition, not inferred renames.",
                      "Selected group fields: order, interval, limit, query_offset, labels and rule count. Selected rule fields: order, expression, for, keep_firing_for, labels and annotations. Unrecognized fields are counted but not compared.",
                      "Changed field/key names are returned, but expression text, label/annotation values and template bodies are omitted. Group/rule names and label keys may still contain sensitive data.",
                      "Declarations are not PromQL-parsed, duration-validated, template-expanded or evaluated. No effective rule behavior, alert state or deployment-safety verdict is inferred; use promtool for full rule validation.",
                      "All bounded declarations are compared before display limits. Offline only: no file/network access or command execution."]}
