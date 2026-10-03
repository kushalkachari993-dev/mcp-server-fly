from collections import defaultdict

from app.tools.config_utils import service as configurations
from app.tools.deployment_utils import service as deployments


class _Summary:
    def __init__(self, before, after, limit):
        deployments._input(before)
        deployments._input(after)
        deployments._limit(limit)
        self.limit, self.truncated = limit, False

    def display(self, value):
        if isinstance(value, str):
            self.truncated |= len(value) > 2000
            return value[:2000]
        if isinstance(value, list):
            self.truncated |= len(value) > self.limit
            return [self.display(item) for item in value[:self.limit]]
        if isinstance(value, dict):
            return {key: self.display(item) for key, item in value.items()}
        return value


def _same(before, after):
    if type(before) is not type(after):
        return False
    if isinstance(before, dict):
        return before.keys() == after.keys() and all(_same(value, after[key]) for key, value in before.items())
    if isinstance(before, list):
        return len(before) == len(after) and all(_same(old, new) for old, new in zip(before, after))
    return before == after


def _differences(before, after, path=""):
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in before or key not in after:
                changes.append({"path": pointer, "type": "added" if key not in before else "removed",
                                "before_present": key in before, "after_present": key in after,
                                "before": before.get(key), "after": after.get(key)})
            else:
                changes.extend(_differences(before[key], after[key], pointer))
        return changes
    if _same(before, after):
        return []
    # Lists are whole declared sequences, never guessed record matches by index.
    return [{"path": path, "type": "changed", "before_present": True, "after_present": True,
             "before": before, "after": after}]


def _without(row, *fields):
    return {key: value for key, value in row.items() if key not in fields}


def _compare_records(before, after, key, identity):
    indexes, unmatchable = [], []
    for rows in (before, after):
        index, unknown = defaultdict(list), []
        for row in rows:
            record_key = key(row)
            if record_key is None:
                unknown.append(identity(row))
            else:
                index[record_key].append(row)
        indexes.append(index)
        unmatchable.append(unknown)
    left, right = indexes
    matching = {"matched_count": 0, "added": [], "removed": [], "ambiguous": [],
                "unmatchable_before": unmatchable[0], "unmatchable_after": unmatchable[1]}
    comparisons, unchanged = [], 0
    for record_key in dict.fromkeys([*left, *right]):
        old, new = left.get(record_key, []), right.get(record_key, [])
        if len(old) > 1 or len(new) > 1:
            matching["ambiguous"].append({"identity": identity((old or new)[0]),
                                          "before_count": len(old), "after_count": len(new)})
        elif not old:
            matching["added"].append(identity(new[0]))
        elif not new:
            matching["removed"].append(identity(old[0]))
        else:
            matching["matched_count"] += 1
            changes = _differences(old[0], new[0])
            if changes:
                comparisons.append({"identity": identity(old[0]), "change_count": len(changes), "changes": changes})
            else:
                unchanged += 1
    for name in ("added", "removed", "ambiguous", "unmatchable_before", "unmatchable_after"):
        matching[name + "_count"] = len(matching[name])
    return matching, comparisons, unchanged


def _finish(format, summary, before, after, changes, notes, matching=None, comparisons=None, unchanged=0):
    comparisons = [] if comparisons is None else comparisons
    changed_count = len(comparisons)
    change_count = len(changes) + sum(row["change_count"] for row in comparisons)
    known_change = change_count > 0 or (matching is not None and (matching["added_count"] or matching["removed_count"]))
    uncertain = matching is not None and any(matching[name] for name in (
        "ambiguous_count", "unmatchable_before_count", "unmatchable_after_count"))
    result = {"format": format, "before": before, "after": after,
              "selected_fields_equal": False if known_change else None if uncertain else True,
              "change_count": change_count, "configuration_change_count": len(changes),
              "configuration_changes": summary.display(changes)}
    if matching is not None:
        result.update(matching=summary.display(matching), changed_count=changed_count,
                      unchanged_count=unchanged, comparisons=summary.display(comparisons))
    result["truncated"] = summary.truncated
    result["notes"] = notes + [
        "Only the existing inspectors' selected declarations are compared, not complete files or effective runtime configuration. No compatibility or deployment-safety verdict.",
        "All bounded records and full selected strings are compared before display limiting. Counts describe the supplied inputs, not omitted fields or live state.",
        "Object key order is ignored; list order and declaration spelling are retained. Lists are compared as whole sequences, not paired by position or inferred identity.",
        "Missing declarations are not replaced with platform defaults. Null inspector fields may represent absent declarations; normalization follows the existing inspectors.",
        "Environment/header/build-argument/Secret/ConfigMap values and command/script bodies are omitted, including value-only changes. Selected names, paths and image references can still contain sensitive caller data.",
        "Offline only: no file/network/cluster access, variable/expression/reference resolution, execution, deployment or cost lookup."]
    return result


def compare_compose(before, after, limit):
    summary = _Summary(before, after, limit)
    views = [configurations.inspect_compose(content, 50, _complete=True) for content in (before, after)]
    matching, comparisons, unchanged = _compare_records(
        *(view["services"] for view in views), key=lambda row: row["name"], identity=lambda row: {"name": row["name"]})
    fields = ("name", "declarations", "include_declared")
    changes = _differences(*({key: view[key] for key in fields} for view in views))
    return _finish("docker_compose", summary, *({"service_count": view["service_count"]} for view in views),
                   changes, ["Services match by exact declared name; a rename is added/removed. Ports, dependencies, environment names and health-check settings use inspector representations.",
                             "Variable interpolation, profiles, include/extends resolution, override merging and image-inherited health checks are not evaluated."],
                   matching, comparisons, unchanged)


def compare_actions(before, after, limit):
    summary = _Summary(before, after, limit)
    views = [configurations.inspect_actions(content, 50, 50, _complete=True) for content in (before, after)]
    rows = [[_without(row, "steps_truncated") for row in view["jobs"]] for view in views]
    matching, comparisons, unchanged = _compare_records(
        *rows, key=lambda row: row["id"], identity=lambda row: {"id": row["id"]})
    fields = ("name", "events", "permissions", "environment_names")
    changes = _differences(*({key: view[key] for key in fields} for view in views))
    return _finish("github_actions", summary,
                   *({key: view[key] for key in ("job_count", "step_count")} for view in views), changes,
                   ["Jobs match by exact declared job ID; steps and trigger lists remain declared sequences. Action references are compared literally, never resolved to commits.",
                    "Permissions are explicit declarations only, not effective token permissions. Event filters retain order; matrices expose only axis names/expression presence, not axis values or expansion.",
                    "Conditions, concurrency, reusable-workflow contents, with arguments and run bodies are outside the selected inspector fields."],
                   matching, comparisons, unchanged)


def _kubernetes_identity(row):
    version = row["api_version"]
    parts = version.split("/")
    group = "" if len(parts) == 1 else parts[0] if len(parts) == 2 and all(parts) else None
    return {"api_group": group, "kind": row["kind"], "namespace": row["namespace"], "name": row["name"]}


def _kubernetes_key(row):
    identity = _kubernetes_identity(row)
    if identity["api_group"] is None or identity["name"] is None:
        return None
    return tuple(identity.values())


def compare_kubernetes(before, after, limit):
    summary = _Summary(before, after, limit)
    views = [deployments.inspect_kubernetes(content, 50, _complete=True) for content in (before, after)]
    matching, comparisons, unchanged = _compare_records(
        *(view["objects"] for view in views), key=_kubernetes_key, identity=_kubernetes_identity)
    overviews = [{"object_count": view["object_count"], "container_count": view["container_count"],
                  "metadata_only_count": sum(not row["inspected"] for row in view["objects"])} for view in views]
    return _finish("kubernetes", summary, *overviews, [],
                   ["Object identity is exact (API group, kind, declared namespace, metadata.name). API version changes within one group remain matched and are reported. Kind/group/name changes are added/removed.",
                    "Duplicate identities are ambiguous even across API versions; generateName-only objects remain unmatchable. An omitted namespace is a distinct declaration, not an inferred default or cluster namespace.",
                    "Container/probe/Service/resource/reference summaries use existing inspector fields. Container and reference sequences retain order; duplicates are not merged. Quantities are literal declarations, not normalized units.",
                    "Unsupported kinds receive metadata-only comparison. Labels, annotations, rollout strategies, Helm/Kustomize output and cluster defaults are not compared."],
                   matching, comparisons, unchanged)


def compare_fly(before, after, limit):
    summary = _Summary(before, after, limit)
    views = [deployments.inspect_fly(content) for content in (before, after)]
    selected = [_without(view, "warnings", "notes") for view in views]
    changes = _differences(*selected)
    return _finish("fly", summary, *({"app": view["app"], "service_count": len(view["services"]),
                                      "machine_declaration_count": len(view["machines"])} for view in views), changes,
                   ["Compares selected app/region, build/deploy settings, environment/process names, services/ports/checks, VM declarations and mounts. Services/VMs/mounts are declared sequences, not live Machine identities.",
                    "Legacy boolean and current string autostop settings, VM size/memory spellings and omitted settings are not treated as equivalent. CLI overrides, region-specific capacity, pricing and actual uptime are not inferred."])
