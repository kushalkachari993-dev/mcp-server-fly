import json
from collections import Counter
from graphlib import CycleError, TopologicalSorter

from app.tools.manifest_utils.service import _check_structure, _mapping, _string, _unique_object


def _text(value, label, required=False):
    return None if value is None and not required else _string(value, label, 2000)


def _array(value, label, maximum=1000):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{label} must be an array of at most {maximum} entries")
    return value


def _licenses(values):
    result = []
    for entry in _array(values, "Licenses", 50):
        entry = _mapping(entry, "License choice")
        if ("license" in entry) == ("expression" in entry):
            raise ValueError("License choices must declare either license or expression")
        if "expression" in entry:
            result.append({"expression": _text(entry["expression"], "License expression", required=True)})
        else:
            license = _mapping(entry["license"], "License")
            identifier, name = _text(license.get("id"), "License ID"), _text(license.get("name"), "License name")
            if (identifier is None) == (name is None):
                raise ValueError("License declarations must contain either id or name")
            result.append({"id": identifier, "name": name})
    return result


def inspect_sbom(content, limit):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    if not isinstance(content, str) or len(content) > 200000:
        raise ValueError("SBOM input must be text of at most 200000 characters")
    try:
        data = json.loads(content, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ValueError("Invalid SBOM JSON; duplicate keys are not supported and source text is omitted") from error
    _mapping(data, "SBOM")
    _check_structure(data)
    if data.get("bomFormat") != "CycloneDX" or data.get("specVersion") not in ("1.5", "1.6", "1.7"):
        raise ValueError("Supply CycloneDX JSON specVersion 1.5, 1.6 or 1.7; XML/SPDX are not supported")
    version = data.get("version")
    if version is not None and (type(version) is not int or version < 1):
        raise ValueError("BOM version must be a positive integer")
    rows, references, types = [], set(), Counter()

    def component(raw, parent=None, role="component"):
        raw = _mapping(raw, "Component")
        if len(rows) >= 1000:
            raise ValueError("SBOM exceeds 1000 components including metadata/nested components")
        ref = _text(raw.get("bom-ref"), "Component reference")
        if ref is not None:
            if ref in references:
                raise ValueError("Duplicate inspected component bom-ref values are not supported")
            references.add(ref)
        kind = _text(raw.get("type"), "Component type", required=True)
        types[kind] += 1
        rows.append({"bom_ref": ref, "parent_bom_ref": parent, "role": role, "type": kind,
                     "group": _text(raw.get("group"), "Component group"),
                     "name": _text(raw.get("name"), "Component name", required=True),
                     "version": _text(raw.get("version"), "Component version"),
                     "purl": _text(raw.get("purl"), "Package URL"),
                     "scope": _text(raw.get("scope"), "Component scope"),
                     "licenses": _licenses(raw.get("licenses", []))})
        for child in _array(raw.get("components", []), "Nested components"):
            component(child, ref)

    metadata = _mapping(data.get("metadata", {}), "Metadata")
    if "component" in metadata:
        component(metadata["component"], role="metadata")
    for raw in _array(data.get("components", []), "Components"):
        component(raw)
    graph, edges = {}, 0
    for raw in _array(data.get("dependencies", []), "Dependencies"):
        raw = _mapping(raw, "Dependency")
        ref = _text(raw.get("ref"), "Dependency ref", required=True)
        if ref in graph:
            raise ValueError("Duplicate dependency ref entries are not supported")
        children = [_text(value, "Dependency target", required=True) for value in _array(raw.get("dependsOn", []), "Dependency targets")]
        graph[ref] = list(dict.fromkeys(children))
        edges += len(graph[ref])
        if edges > 5000:
            raise ValueError("SBOM exceeds 5000 dependency edges")
    unresolved = sorted((set(graph) | {child for children in graph.values() for child in children}) - references)
    try:
        tuple(TopologicalSorter(graph).static_order())
        cycle = False
    except CycleError:
        cycle = True
    dependency_rows = [{"ref": ref, "dependency_count": len(children), "depends_on": children[:limit],
                        "truncated": len(children) > limit} for ref, children in graph.items()]
    truncated = len(rows) > limit or len(graph) > limit or len(unresolved) > limit or any(row["truncated"] for row in dependency_rows)
    return {"format": "CycloneDX", "spec_version": data["specVersion"], "bom_version": version,
            "component_count": len(rows), "types": dict(sorted(types.items())), "components": rows[:limit],
            "dependency_graph": {"entry_count": len(graph), "edge_count": edges, "has_cycle": cycle,
                                 "dependencies": dependency_rows[:limit], "unresolved_reference_count": len(unresolved),
                                 "unresolved_references": unresolved[:limit]},
            "truncated": truncated,
            "notes": ["Inventory of supplied CycloneDX JSON declarations only, not full schema validation, installed-package verification or a vulnerability/license-compliance audit.",
                      "Component nesting is not a dependency edge. dependsOn relationships only; graph completeness and runtime reachability are not inferred.",
                      "Unresolved references are absent from inspected components; they may refer to uninspected services or external BOMs, not necessarily invalid.",
                      "No file/network access, schema/license downloads or execution. Properties, descriptions, license text and external references are omitted."]}
