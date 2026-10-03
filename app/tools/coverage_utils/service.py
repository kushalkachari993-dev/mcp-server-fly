import re
from collections import Counter
from io import StringIO

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.tools.report_utils.service import _Summary, _duration, _lines, _name


def _count(value, minimum=0):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,13}", value) or not minimum <= int(value) <= 1000000000000:
        raise ValueError("Coverage counts/line numbers must be decimal integers within range")
    return int(value)


def _coverage(found, hit, unknown=0):
    return {"found": found, "hit": hit, "unknown": unknown,
            "coverage_percent": 100 * hit / found if found and not unknown else None}


def _declared_lcov(record):
    result = {}
    for kind, found, hit in (("lines", "LF", "LH"), ("functions", "FNF", "FNH"), ("branches", "BRF", "BRH")):
        total, covered = record["declared"].get(found), record["declared"].get(hit)
        if total is not None and covered is not None and covered > total:
            raise ValueError("Coverage declared hits exceed declared totals")
        result[kind] = {"found": total, "hit": covered}
    return result


def _lcov_record(record, summary, index):
    old = record["definitions"] or record["executions"]
    modern = record["groups"] or record["aliases"]
    if old and modern:
        raise ValueError("Mixed legacy/grouped LCOV function records in one section are unsupported")
    functions = []
    if modern:
        if set(record["groups"]) != set(record["aliases"]):
            raise ValueError("LCOV function groups must have definitions and aliases")
        for key, position in record["groups"].items():
            aliases = record["aliases"][key]
            functions.append({"index": key, **position, "hit": any(count > 0 for count in aliases.values()),
                              "alias_count": len(aliases), "aliases": summary.take([
                                  {"name": name, "execution_count": count} for name, count in aliases.items()])})
    else:
        names = dict.fromkeys([*record["definitions"], *record["executions"]])
        for name in names:
            count = record["executions"].get(name)
            functions.append({"name": name, **record["definitions"].get(name, {"start_line": None, "end_line": None}),
                              "execution_count": count, "hit": count > 0 if count is not None else None})
    branches = [item for item in record["branches"].values() if not item["excluded"]]
    uncovered = sorted(line for line, count in record["lines"].items() if count == 0)
    observed = {"lines": _coverage(len(record["lines"]), sum(count > 0 for count in record["lines"].values())),
                "functions": _coverage(len(functions), sum(row["hit"] is True for row in functions), sum(row["hit"] is None for row in functions)),
                "branches": _coverage(len(branches), sum(row["taken"] is not None and row["taken"] > 0 for row in branches))}
    declared = _declared_lcov(record)
    mismatches = [f"{kind}.{field}" for kind in declared for field in ("found", "hit")
                  if declared[kind][field] is not None and declared[kind][field] != observed[kind][field]
                  and not (field == "hit" and observed[kind]["unknown"])]
    return {"record_index": index, "file": record["file"], "test_name": summary.text(record["test_name"]),
            "function_format": "grouped" if modern else "legacy" if old else None,
            "observed": observed, "declared": declared, "declared_mismatches": mismatches,
            "uncovered_lines": summary.take(uncovered), "uncovered_line_count": len(uncovered),
            "functions": summary.take(functions), "branch_records": summary.take(list(record["branches"].values())),
            "unknown_branch_taken_count": sum(row["taken"] is None for row in branches),
            "excluded_branch_count": len(record["branches"]) - len(branches)}


def inspect_lcov(content, limit, *, _records=None):
    summary = _Summary(content, limit)
    rows, paths, ignored = [], set(), Counter()
    record, pending_test = None, None
    for line in _lines(content):
        if not line.strip() or line.startswith("#"):
            continue
        if line == "end_of_record":
            if record is None:
                raise ValueError("LCOV end_of_record has no open section")
            row = _lcov_record(record, summary, len(rows))
            rows.append(row)
            if _records is not None:
                _records.append({**record, "observed": row["observed"], "function_format": row["function_format"]})
            record = None
            continue
        key, separator, value = line.partition(":")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,30}", key):
            raise ValueError("Invalid LCOV record syntax; source text is omitted")
        if key == "TN":
            if record is not None or pending_test is not None:
                raise ValueError("Misplaced or repeated LCOV test name")
            if value:
                _name(value, required=True)
            pending_test = value
            continue
        if key in {"SF", "KF"}:
            if record is not None or len(rows) >= 200:
                raise ValueError("LCOV has an unclosed section or exceeds 200 sections")
            path = _name(value, required=True)
            paths.add(path)
            record = {"file": path, "test_name": pending_test, "lines": {}, "definitions": {}, "executions": {},
                      "groups": {}, "aliases": {}, "branches": {}, "declared": {}}
            pending_test = None
            continue
        if record is None:
            raise ValueError("LCOV coverage records must be inside a source section")
        if key in {"LF", "LH", "FNF", "FNH", "BRF", "BRH"}:
            if key in record["declared"]:
                raise ValueError("Duplicate LCOV summary fields are unsupported")
            record["declared"][key] = _count(value)
        elif key == "DA":
            fields = value.split(",")
            if len(fields) not in {2, 3}:
                raise ValueError("Invalid LCOV line record")
            number, hits = _count(fields[0], 1), _count(fields[1])
            if number in record["lines"]:
                raise ValueError("Duplicate LCOV line records within a section are unsupported")
            record["lines"][number] = hits
        elif key in {"FN", "FNL"}:
            first, separator, rest = value.partition(",")
            if not separator:
                raise ValueError("Invalid LCOV function definition")
            if key == "FNL":
                fields = rest.split(",")
                if len(fields) not in {1, 2}:
                    raise ValueError("Invalid LCOV function group definition")
                identity = _count(first)
                start, end = _count(fields[0], 1), _count(fields[1], 1) if len(fields) == 2 else None
                target = record["groups"]
            else:
                start, end = _count(first, 1), None
                candidate, separator, name = rest.partition(",")
                if separator and candidate.isascii() and candidate.isdecimal():
                    end, rest = _count(candidate, 1), name
                identity, target = _name(rest, required=True), record["definitions"]
            if end is not None and end < start or identity in target:
                raise ValueError("Invalid range or duplicate LCOV function definition")
            target[identity] = {"start_line": start, "end_line": end}
        elif key in {"FNDA", "FNA"}:
            fields = value.split(",", 2 if key == "FNA" else 1)
            if len(fields) != (3 if key == "FNA" else 2):
                raise ValueError("Invalid LCOV function execution record")
            if key == "FNA":
                identity, count, name = _count(fields[0]), _count(fields[1]), _name(fields[2], required=True)
                target = record["aliases"].setdefault(identity, {})
            else:
                count, name, target = _count(fields[0]), _name(fields[1], required=True), record["executions"]
            if name in target:
                raise ValueError("Duplicate LCOV function execution/alias records are unsupported")
            target[name] = count
        elif key == "BRDA":
            fields = value.split(",", 2)
            if len(fields) != 3 or "," not in fields[2]:
                raise ValueError("Invalid LCOV branch record")
            number, block = _count(fields[0], 1), fields[1]
            if not re.fullmatch(r"[ef]?U?[0-9]{1,13}", block):
                raise ValueError("Unsupported LCOV branch block identifier")
            _count(block.lstrip("efU"))
            branch, taken = fields[2].rsplit(",", 1)
            branch = _name(branch, required=True)
            identity = number, block, branch
            if identity in record["branches"]:
                raise ValueError("Duplicate LCOV branch records within a section are unsupported")
            record["branches"][identity] = {"line": number, "block": block, "branch": branch,
                                              "taken": None if taken == "-" else _count(taken), "excluded": "U" in block}
        elif key != "VER":
            ignored[key] += 1
    if record is not None or pending_test is not None:
        raise ValueError("LCOV has an unterminated source section/test name")
    totals = {kind: _coverage(sum(row["observed"][kind]["found"] for row in rows),
                             sum(row["observed"][kind]["hit"] for row in rows),
                             sum(row["observed"][kind]["unknown"] for row in rows)) for kind in ("lines", "functions", "branches")}
    output = {"record_count": len(rows), "unique_file_count": len(paths), "observed_record_totals": totals,
              "mismatched_record_count": sum(bool(row["declared_mismatches"]) for row in rows),
              "ignored_record_types": dict(sorted(ignored.items())), "files": summary.take(rows),
              "notes": ["Supplied LCOV text only, not test execution or full format validation. Source paths are never opened.",
                        "Totals sum separate sections; repeated files/test names are not merged, so totals are not unique-file coverage.",
                        "Observed coverpoints are separate from declared summaries; no missing records are invented. Zero denominators or unknown function hits give null percentages.",
                        "Legacy FN/FNDA and grouped FNL/FNA are supported; aliases count as one function group. Mixed formats and duplicate coverpoints within a section are rejected.",
                        "Branch '-' means no reported taken count and counts as not hit; U-marked branches are returned but excluded from coverage totals.",
                        "VER/checksums are not checked; other record types (including MC/DC) are counted as ignored. Paths, names and expressions can contain supplied sensitive data."]}
    output["truncated"] = summary.truncated
    return output


def _cobertura_root(content):
    root, depth, nodes = None, 0, 0
    try:
        # Common exporters include an external DOCTYPE. Never load its DTD or resolve entities.
        for event, element in ElementTree.iterparse(StringIO(content), events=("start", "end"),
                                                  forbid_dtd=False, forbid_entities=True, forbid_external=True):
            if event == "start":
                depth += 1
                nodes += 1
                if depth > 50 or nodes > 10000:
                    raise ValueError("Cobertura exceeds 10000 XML elements or 50 nesting levels")
                if root is None:
                    root = element
            else:
                depth -= 1
    except (ElementTree.ParseError, DefusedXmlException) as error:
        raise ValueError("Invalid or forbidden Cobertura XML; entities/external references forbidden and source omitted") from error
    if root is None or root.tag.rsplit("}", 1)[-1] != "coverage":
        raise ValueError("Expected a Cobertura coverage root")
    return root


def _xml_declared(element):
    result = {}
    for kind in ("lines", "branches"):
        found, hit = element.get(f"{kind}-valid"), element.get(f"{kind}-covered")
        found, hit = _count(found) if found is not None else None, _count(hit) if hit is not None else None
        if found is not None and hit is not None and hit > found:
            raise ValueError("Cobertura declared hits exceed totals")
        value = element.get("line-rate" if kind == "lines" else "branch-rate")
        rate = _duration(value)
        if rate is not None and rate > 1:
            raise ValueError("Cobertura declared rates must be between 0 and 1")
        result[kind] = {"found": found, "hit": hit, "rate": rate}
    return result


def _condition_counts(value):
    if value is None:
        return None
    if len(value) > 100:
        raise ValueError("Cobertura condition coverage text exceeds its limit")
    match = re.fullmatch(r"([0-9]{1,3}(?:\.[0-9]+)?)%\s*\(([0-9]{1,13})/([0-9]{1,13})\)", value)
    if not match or float(match[1]) > 100:
        raise ValueError("Unsupported Cobertura condition coverage; expected percent (hit/total)")
    hit, found = _count(match[2]), _count(match[3])
    if hit > found:
        raise ValueError("Cobertura condition hits exceed totals")
    return found, hit


def inspect_cobertura(content, limit, *, _records=None):
    summary = _Summary(content, limit)
    root = _cobertura_root(content)
    namespace = root.tag[:root.tag.rfind("}") + 1] if root.tag.startswith("{") else ""
    packages, classes, files = [], [], set()
    line_count = 0
    for package in root.findall(f"{namespace}packages/{namespace}package"):
        if len(packages) >= 200:
            raise ValueError("Cobertura exceeds 200 packages")
        package_index = len(packages)
        packages.append({"index": package_index, "name": summary.text(package.get("name")), "declared": _xml_declared(package)})
        for cls in package.findall(f"{namespace}classes/{namespace}class"):
            if len(classes) >= 1000:
                raise ValueError("Cobertura exceeds 1000 classes")
            filename = _name(cls.get("filename"), required=True)
            files.add(filename)
            lines, branch_found, branch_hit, unknown_branches = {}, 0, 0, 0
            branch_lines = 0
            for line in cls.findall(f"{namespace}lines/{namespace}line"):
                line_count += 1
                if line_count > 5000:
                    raise ValueError("Cobertura exceeds 5000 direct class line records")
                number, hits = _count(line.get("number"), 1), _count(line.get("hits"))
                if number in lines:
                    raise ValueError("Duplicate Cobertura line records within a class are unsupported")
                lines[number] = hits
                branch = line.get("branch")
                if branch not in {None, "true", "false"}:
                    raise ValueError("Unsupported Cobertura branch flag")
                conditions = _condition_counts(line.get("condition-coverage"))
                if branch == "true":
                    branch_lines += 1
                    if conditions is None:
                        unknown_branches += 1
                    else:
                        branch_found += conditions[0]
                        branch_hit += conditions[1]
            uncovered = sorted(number for number, hits in lines.items() if hits == 0)
            classes.append({"index": len(classes), "package_index": package_index, "name": summary.text(cls.get("name")),
                            "file": filename, "declared": _xml_declared(cls),
                            "observed_lines": _coverage(len(lines), len(lines) - len(uncovered)),
                            "observed_branches": _coverage(branch_found, branch_hit, unknown_branches),
                            "branch_line_count": branch_lines, "uncovered_line_count": len(uncovered),
                            "uncovered_lines": summary.take(uncovered)})
            if _records is not None:
                _records.append({"file": filename, "package": package.get("name"), "class": cls.get("name"),
                                 "lines": lines, "observed": {"lines": classes[-1]["observed_lines"],
                                                              "branches": classes[-1]["observed_branches"]}})
    measured = [row for row in classes if row["observed_lines"]["coverage_percent"] is not None]
    output = {"package_count": len(packages), "class_count": len(classes), "unique_file_count": len(files),
              "declared": _xml_declared(root),
              "observed_class_lines": _coverage(line_count, sum(row["observed_lines"]["hit"] for row in classes)),
              "observed_class_branches": _coverage(sum(row["observed_branches"]["found"] for row in classes),
                                                  sum(row["observed_branches"]["hit"] for row in classes),
                                                  sum(row["observed_branches"]["unknown"] for row in classes)),
              "packages": summary.take(packages), "classes": summary.take(classes),
              "least_covered_classes": summary.take(sorted(measured, key=lambda row: row["observed_lines"]["coverage_percent"])),
              "notes": ["Supplied common Cobertura XML only, not execution or full schema validation. Source files and source-root text are never read/resolved.",
                        "Declared root/package/class counts and rates stay separate from direct class line observations; method copies are not counted twice.",
                        "Class observations are summed without merging repeated filenames across classes; they are not unique-file coverage.",
                        "Branch totals use explicit condition-coverage hit/total counts only. Unknown branch lines or zero denominators give null percentages; percentages are not reverse-engineered into counts.",
                        "External DOCTYPE declarations are ignored without loading DTDs; entity definitions/references are forbidden. XInclude and vendor extensions are not processed.",
                        "Paths/class/package names may contain supplied sensitive data. Coverage does not prove test quality or correctness."]}
    output["truncated"] = summary.truncated
    return output
