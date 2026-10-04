import json
from collections import Counter
from datetime import datetime, timezone

from app.tools.json_query.service import _check_tree
from app.tools.json_utils.tool import _load_bounded_json


_LEVEL_ALIASES = {"warn": "warning", "err": "error", "fatal": "critical"}


def analyze(content, limit, level_field, message_field, timestamp_field, *, _records=None, _event_field=None):
    if len(content) > 1000000:
        raise ValueError("Log input must not exceed 1000000 characters")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    for field in (level_field, message_field, timestamp_field):
        if not isinstance(field, str) or not field or len(field) > 100 or any(ord(char) < 32 for char in field):
            raise ValueError("Field names must be nonempty and at most 100 characters without controls")
    if _event_field is not None and (not isinstance(_event_field, str) or not _event_field
                                     or len(_event_field) > 100
                                     or any(ord(char) < 32 for char in _event_field)):
        raise ValueError("Field names must be nonempty and at most 100 characters without controls")
    lines = content.split("\n") if content else []
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) > 5000:
        raise ValueError("Log input must not exceed 5000 lines")
    levels, messages = Counter(), Counter()
    invalid_samples, error_samples = [], []
    valid = invalid = blank = errors = invalid_timestamps = missing_timestamps = 0
    first = last = None
    truncated = False
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            blank += 1
            continue
        try:
            entry = _load_bounded_json(line)
            _check_tree(entry, max_nodes=1000, max_depth=20)
            if not isinstance(entry, dict):
                raise ValueError("Log entry must be a JSON object")
        except (ValueError, RecursionError) as error:
            invalid += 1
            if len(invalid_samples) < limit:
                reason = error.msg if isinstance(error, json.JSONDecodeError) else str(error)
                invalid_samples.append({"line": line_number, "reason": reason[:200]})
            continue
        valid += 1
        raw_level = entry.get(level_field)
        level = raw_level.strip().lower() if isinstance(raw_level, str) and raw_level.strip() else "unknown"
        level = _LEVEL_ALIASES.get(level, level)
        levels[level] += 1
        if _records is not None:
            _records.append({"level": level, "event": entry.get(_event_field) if _event_field is not None else None})
        message = entry.get(message_field)
        if isinstance(message, str) and message:
            messages[message] += 1
        timestamp = entry.get(timestamp_field)
        timestamp_utc = None
        if timestamp is None:
            missing_timestamps += 1
        else:
            try:
                if not isinstance(timestamp, str):
                    raise ValueError("Timestamp must be an ISO datetime string")
                parsed = datetime.fromisoformat(timestamp)
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError("Timestamp must include an offset")
                parsed = parsed.astimezone(timezone.utc)
                timestamp_utc = parsed.isoformat()
                first = parsed if first is None else min(first, parsed)
                last = parsed if last is None else max(last, parsed)
            except (ValueError, OverflowError):
                invalid_timestamps += 1
        if level in {"error", "critical"}:
            errors += 1
            if len(error_samples) < limit:
                error_samples.append({"line": line_number, "level": level, "timestamp": timestamp_utc,
                                      "message": message[:1000] if isinstance(message, str) else "",
                                      "message_truncated": isinstance(message, str) and len(message) > 1000})
                truncated |= isinstance(message, str) and len(message) > 1000
    level_rows = []
    for level, count in levels.most_common(20):
        truncated |= len(level) > 100
        level_rows.append({"level": level[:100], "count": count})
    frequent = []
    for message, count in messages.most_common(limit):
        truncated |= len(message) > 1000
        frequent.append({"message": message[:1000], "count": count, "message_truncated": len(message) > 1000})
    truncated |= len(levels) > 20 or len(messages) > limit or invalid > limit or errors > limit
    return {"line_count": len(lines), "parsed_entries": valid, "invalid_entries": invalid, "blank_lines": blank,
            "level_counts": level_rows, "omitted_level_entries": sum(count for _, count in levels.most_common()[20:]),
            "error_count": errors, "error_samples": error_samples, "invalid_samples": invalid_samples,
            "unique_message_count": len(messages), "frequent_messages": frequent,
            "timestamp_range": {"first": first.isoformat() if first else None,
                                "last": last.isoformat() if last else None},
            "invalid_timestamps": invalid_timestamps, "missing_timestamps": missing_timestamps,
            "truncated": truncated,
            "notice": "Supplied JSON object lines only; blank lines are counted separately. Fields are top-level "
                      "keys. Levels are text; warn/err/fatal map to warning/error/critical. Numeric levels are "
                      "unknown. Only ISO datetime strings with explicit offsets enter the UTC time range. "
                      "Message grouping uses exact text. No logs are fetched or stored."}
