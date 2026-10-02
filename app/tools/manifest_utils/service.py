import json
import math
import tomllib

from packaging.requirements import Requirement


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys are not supported")
        result[key] = value
    return result


def _check_structure(value):
    stack = [(value, 0)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > 10000 or depth > 50:
            raise ValueError("Manifest exceeds 10000 nodes or 50 nested levels")
        if isinstance(node, float) and not math.isfinite(node):
            raise ValueError("Non-finite numbers are not supported")
        if isinstance(node, (dict, list)):
            if count + len(node) + len(stack) > 10000:
                raise ValueError("Manifest exceeds 10000 nodes")
            stack.extend((child, depth + 1) for child in (node.values() if isinstance(node, dict) else node))


def _string(value, label, maximum=1000, empty=False):
    if (not isinstance(value, str) or len(value) > maximum
            or (not empty and not value.strip()) or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"{label} must be a {'possibly empty' if empty else 'nonempty'} string of at most {maximum} characters without controls")
    return value


def _mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object/table")
    return value


def inspect_manifest(content, format, limit):
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    if len(content) > 200000:
        raise ValueError("Manifest input must not exceed 200000 characters")
    if format == "package.json":
        data = json.loads(content, object_pairs_hook=_unique_object)
    elif format == "pyproject.toml":
        data = tomllib.loads(content)
    else:
        raise ValueError("format must be package.json or pyproject.toml")
    _mapping(data, "Manifest")
    _check_structure(data)
    dependencies, includes, warnings = [], [], []
    dynamic = []

    def append(row):
        if len(dependencies) >= 1000:
            raise ValueError("Manifest exceeds 1000 dependency declarations")
        dependencies.append(row)

    if format == "package.json":
        project_name = _string(data.get("name", ""), "name", 214, empty=True)
        sections = {key: _mapping(data.get(key, {}), key)
                    for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")}
        for section, entries in sections.items():
            for name, requirement in entries.items():
                append({"name": _string(name, "Dependency name", 214),
                        "requirement": _string(requirement, "Dependency requirement", empty=True),
                        "group": section, "ecosystem": "npm",
                        "overridden_by_optional": section == "dependencies" and name in sections["optionalDependencies"]})
        if "workspaces" in data:
            warnings.append("Workspace manifests are not read or expanded.")
        if any(key in data for key in ("overrides", "resolutions", "packageExtensions", "peerDependenciesMeta")):
            warnings.append("Overrides and dependency metadata modifiers are not applied.")
        if any(key in data for key in ("bundleDependencies", "bundledDependencies")):
            warnings.append("Bundled dependency declarations are not inspected.")
    else:
        project = _mapping(data.get("project", {}), "project")
        project_name = _string(project.get("name", ""), "project.name", 214, empty=True)
        dynamic = project.get("dynamic", [])
        if not isinstance(dynamic, list) or any(not isinstance(field, str) for field in dynamic):
            raise ValueError("project.dynamic must be an array of field names")
        dynamic = [field for field in dynamic if field in {"dependencies", "optional-dependencies"}]
        if dynamic:
            warnings.append("Dynamic dependency declarations cannot be determined from this manifest.")
        if isinstance(data.get("tool"), dict) and data["tool"]:
            warnings.append("Tool-specific dependency declarations and source overrides are not inspected.")

        def python_dependencies(values, group):
            if not isinstance(values, list):
                raise ValueError(f"{group} must be an array of requirement strings")
            for value in values:
                raw = _string(value, "Python requirement")
                requirement = Requirement(raw)
                append({"name": requirement.name, "requirement": raw, "group": group, "ecosystem": "PyPI",
                        "specifier": str(requirement.specifier), "extras": sorted(requirement.extras),
                        "marker": str(requirement.marker) if requirement.marker else None, "url": requirement.url})

        python_dependencies(project.get("dependencies", []), "project.dependencies")
        optional = _mapping(project.get("optional-dependencies", {}), "project.optional-dependencies")
        for extra, values in optional.items():
            _string(extra, "Extra name", 100)
            python_dependencies(values, f"project.optional-dependencies.{extra}")
        build = _mapping(data.get("build-system", {}), "build-system")
        python_dependencies(build.get("requires", []), "build-system.requires")
        groups = _mapping(data.get("dependency-groups", {}), "dependency-groups")
        for group, values in groups.items():
            _string(group, "Dependency group name", 100)
            if not isinstance(values, list):
                raise ValueError("Dependency groups must be arrays")
            for value in values:
                if isinstance(value, dict):
                    if set(value) != {"include-group"}:
                        raise ValueError("Only include-group objects are supported in dependency groups")
                    target = _string(value["include-group"], "Included group", 100)
                    includes.append({"group": group, "include": target})
                else:
                    python_dependencies([value], f"dependency-groups.{group}")
        if includes:
            warnings.append("Dependency group includes are listed without expansion or cycle validation.")
    return {"format": format, "name": project_name, "dependencies": dependencies[:limit],
            "declaration_count": len(dependencies), "group_includes": includes[:limit],
            "dynamic": dynamic, "warnings": warnings,
            "truncated": len(dependencies) > limit or len(includes) > limit,
            "notice": "Declared requirements only, not installed versions. No resolution, installation, "
                      "file or URL access; environment markers are not evaluated."}
