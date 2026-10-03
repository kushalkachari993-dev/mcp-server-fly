import json
import re
import tomllib


_MAX_INPUT = 2_000_000
_MAX_PACKAGES = 500
_VERSION = re.compile(r"\S{1,200}\Z")


def _text(value, maximum=300):
    return value[:maximum] if isinstance(value, str) else ""


def _exact_version(value, label):
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise ValueError(f"{label} must be a nonempty exact version without whitespace")
    return value


def _package_name(value, label="package name"):
    if not isinstance(value, str) or not 1 <= len(value) <= 214:
        raise ValueError(f"{label} must be 1-214 characters")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{label} must not contain whitespace or control characters")
    return value


def _node_package_name(path):
    marker = "node_modules/"
    if marker not in path:
        return path
    return path.rsplit(marker, 1)[1]


def _package_lock(content, limit):
    try:
        data = json.loads(content)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("package-lock.json is not valid JSON") from error
    if not isinstance(data, dict) or data.get("lockfileVersion") not in {2, 3}:
        raise ValueError("Only package-lock.json lockfileVersion 2 or 3 is supported")
    records = data.get("packages")
    if not isinstance(records, dict):
        raise ValueError("package-lock.json must contain a packages object")

    packages = []
    unresolved = 0
    for path, record in records.items():
        if path == "":
            continue
        if not isinstance(path, str) or not isinstance(record, dict):
            raise ValueError("package-lock.json contains an invalid package record")
        version = record.get("version")
        if version is None:
            unresolved += 1
            continue
        name = record.get("name") or _node_package_name(path)
        _package_name(name)
        _exact_version(version, "package version")
        row = {"name": name, "version": version, "ecosystem": "npm", "path": path}
        for field in ("dev", "optional", "devOptional", "peer"):
            if field in record:
                if not isinstance(record[field], bool):
                    raise ValueError(f"package-lock.json field {field} must be boolean")
                row[field] = record[field]
        packages.append(row)

    return {
        "format": "package-lock.json",
        "lockfile_version": data["lockfileVersion"],
        "package_count": len(packages),
        "unresolved_count": unresolved,
        "packages": packages[:limit],
        "truncated": len(packages) > limit,
        "notice": "Resolved lockfile versions only, not installed versions; no packages were read from disk.",
    }


def _pylock(content, limit):
    try:
        data = tomllib.loads(content)
    except (tomllib.TOMLDecodeError, TypeError) as error:
        raise ValueError("pylock.toml is not valid TOML") from error
    records = data.get("packages")
    if not isinstance(records, list):
        raise ValueError("pylock.toml must contain a packages array")

    packages = []
    unresolved = 0
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("pylock.toml contains an invalid package record")
        name, version = record.get("name"), record.get("version")
        if name is None or version is None:
            unresolved += 1
            continue
        _package_name(name)
        _exact_version(version, "package version")
        row = {"name": name, "version": version, "ecosystem": "PyPI"}
        if "requires-python" in record:
            row["requires_python"] = _text(record["requires-python"], 200)
        packages.append(row)

    return {
        "format": "pylock.toml",
        "lock_version": _text(data.get("lock-version"), 50),
        "package_count": len(packages),
        "unresolved_count": unresolved,
        "packages": packages[:limit],
        "truncated": len(packages) > limit,
        "notice": "Resolved lockfile versions only, not installed versions; no packages were read from disk.",
    }


def inspect_lockfile(content, format, limit):
    if format not in {"package-lock.json", "pylock.toml"}:
        raise ValueError("format must be package-lock.json or pylock.toml")
    if not isinstance(content, str) or len(content) > _MAX_INPUT:
        raise ValueError("Lockfile input must not exceed 2 MB (2000000 characters)")
    if not 1 <= limit <= _MAX_PACKAGES:
        raise ValueError(f"limit must be between 1 and {_MAX_PACKAGES}")
    return _package_lock(content, limit) if format == "package-lock.json" else _pylock(content, limit)
