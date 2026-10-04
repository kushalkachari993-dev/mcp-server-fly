import re
from collections import Counter

from app.tools.log_utils import service as logs
from app.tools.report_comparison.service import _change, _inputs, _match, _matching


_LEVELS = {"trace", "debug", "info", "notice", "warning", "error", "critical", "alert", "emergency", "unknown"}
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,99}\Z")


def _event_code(value):
    if type(value) is int and 0 <= value <= 1000000000000:
        return str(value)
    if isinstance(value, str) and _TOKEN.fullmatch(value):
        return value
    return None


def _event_identity(row):
    return {"event": row["event"]}


def _event_view(row):
    return {"identity": _event_identity(row), "count": row["count"],
            "error_count": row["error_count"], "level_counts": row["level_counts"]}


def _parse(content, level_field, event_field, timestamp_field):
    rows = []
    view = logs.analyze(content, 50, level_field, "message", timestamp_field,
                        _records=rows, _event_field=event_field)
    levels, groups = Counter(), {}
    unmatchable = 0
    for row in rows:
        level = row["level"] if row["level"] in _LEVELS else "other"
        levels[level] += 1
        event = _event_code(row["event"])
        if event is None:
            unmatchable += 1
            continue
        group = groups.setdefault(event, {"event": event, "count": 0, "levels": Counter()})
        group["count"] += 1
        group["levels"][level] += 1
    events = [{"event": row["event"], "count": row["count"],
               "error_count": row["levels"]["error"] + row["levels"]["critical"],
               "level_counts": dict(sorted(row["levels"].items()))} for row in groups.values()]
    events.sort(key=lambda row: (-row["count"], row["event"]))
    overview = {name: view[name] for name in ("line_count", "parsed_entries", "invalid_entries", "blank_lines",
                                             "invalid_timestamps", "missing_timestamps", "timestamp_range")}
    overview.update({"level_counts": dict(sorted(levels.items())), "error_count": view["error_count"],
                     "error_fraction_of_parsed_entries": view["error_count"] / view["parsed_entries"]
                     if view["parsed_entries"] else None,
                     "event_count": len(events), "unmatchable_event_entry_count": unmatchable})
    return overview, events


def compare_jsonl_logs(before, after, level_field, event_field, timestamp_field, limit):
    summary = _inputs(before, after, limit)
    if not isinstance(event_field, str):
        raise ValueError("event_field must be a nonempty top-level field name")
    views, events = [], []
    for content in (before, after):
        view, grouped = _parse(content, level_field, event_field, timestamp_field)
        views.append(view)
        events.append(grouped)
    match = _match(*events, lambda row: row["event"])
    changes = []
    for old, new in match["matched"]:
        levels = sorted(old["level_counts"].keys() | new["level_counts"].keys())
        level_changes = [{"level": level,
                          **_change(old["level_counts"].get(level, 0), new["level_counts"].get(level, 0))}
                         for level in levels if old["level_counts"].get(level, 0) != new["level_counts"].get(level, 0)]
        if old["count"] != new["count"] or level_changes:
            changes.append({"identity": _event_identity(old),
                            "count": _change(old["count"], new["count"]),
                            "error_count": _change(old["error_count"], new["error_count"]),
                            "level_change_count": len(level_changes),
                            "level_changes": summary.take(level_changes)})
    changed_levels = sorted(views[0]["level_counts"].keys() | views[1]["level_counts"].keys())
    level_changes = [{"level": level,
                      **_change(views[0]["level_counts"].get(level, 0), views[1]["level_counts"].get(level, 0))}
                     for level in changed_levels]
    increases = sorted((row for row in changes if row["error_count"]["delta"] > 0),
                       key=lambda row: row["error_count"]["delta"], reverse=True)
    return {"before": views[0], "after": views[1],
            "level_changes": summary.take(level_changes),
            "error_count": _change(views[0]["error_count"], views[1]["error_count"]),
            "error_fraction_of_parsed_entries": _change(views[0]["error_fraction_of_parsed_entries"],
                                                         views[1]["error_fraction_of_parsed_entries"]),
            "matching": _matching(match, _event_identity, summary),
            "observed_added_events": summary.take([_event_view(row) for row in match["added"]]),
            "observed_removed_events": summary.take([_event_view(row) for row in match["removed"]]),
            "changed_event_count": len(changes), "changes": summary.take(changes),
            "event_error_count_increase_count": len(increases),
            "largest_event_error_count_increases": summary.take(increases),
            "truncated": summary.truncated,
            "notes": ["Only supplied JSON object lines are parsed; invalid and blank lines remain separate. Levels use the existing warn/err/fatal aliases; unfamiliar levels are grouped as other. Error counts cover error and critical only.",
                      "Events require a top-level string identifier of at most 100 token characters or a nonnegative integer. Missing/free-text identifiers are unmatchable; the default message field and other unselected fields are not returned.",
                      "Counts include all bounded parsed lines before display limits. Added/removed means observed in only one input, not proof of a new/deleted event type.",
                      "Inputs are caller-supplied windows. Counts and fractions do not establish equal traffic, elapsed-time rates, statistical significance or causal regressions.",
                      "Offline only: no file/network access. Selected event identifiers may still contain sensitive caller-supplied data."]}
