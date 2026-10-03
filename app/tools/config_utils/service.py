import re
from graphlib import CycleError, TopologicalSorter

import yaml
from yaml.nodes import MappingNode, SequenceNode

from app.tools.yaml_utils.tool import _JsonSafeLoader, _json_compatible


class _ConfigLimit(ValueError):
    pass


class _ConfigLoader(_JsonSafeLoader):
    def __init__(self, stream):
        super().__init__(stream)
        self.node_count = self.node_depth = 0

    def compose_node(self, parent, index):
        self.node_count += 1
        self.node_depth += 1
        try:
            if self.node_count > 10000 or self.node_depth > 50:
                raise _ConfigLimit("Configuration exceeds 10000 YAML nodes or 50 nesting levels")
            return super().compose_node(parent, index)
        finally:
            self.node_depth -= 1

    def construct_document(self, node):
        active, count = set(), 0

        def visit(item, depth):
            nonlocal count
            count += 1
            if count > 10000 or depth > 50:
                raise _ConfigLimit("Expanded configuration exceeds 10000 YAML nodes or 50 nesting levels")
            if id(item) in active:
                raise _ConfigLimit("Recursive YAML aliases are not supported")
            active.add(id(item))
            try:
                if isinstance(item, MappingNode):
                    for key, value in item.value:
                        visit(key, depth + 1)
                        visit(value, depth + 1)
                elif isinstance(item, SequenceNode):
                    for child in item.value:
                        visit(child, depth + 1)
            finally:
                active.remove(id(item))

        # Bound alias and merge expansion before PyYAML constructs mappings.
        visit(node, 0)
        return super().construct_document(node)


_ConfigLoader.yaml_implicit_resolvers = {
    char: [(tag, pattern) for tag, pattern in entries if tag not in {
        "tag:yaml.org,2002:bool", "tag:yaml.org,2002:int", "tag:yaml.org,2002:float"}]
    for char, entries in _JsonSafeLoader.yaml_implicit_resolvers.items()
}
_ConfigLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF"))
_ConfigLoader.add_implicit_resolver("tag:yaml.org,2002:int", re.compile(r"^[-+]?(?:[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$"), list("-+0123456789"))
_ConfigLoader.add_implicit_resolver("tag:yaml.org,2002:float", re.compile(
    r"^([-+]?([0-9]+\.[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?|[-+]?[0-9]+[eE][-+]?[0-9]+|[-+]?\.(inf|Inf|INF)|\.(nan|NaN|NAN))$"
), list("-+0123456789."))


def _integer(loader, node):
    value = loader.construct_scalar(node)
    unsigned = value.lstrip("+-")
    return int(value, 8 if unsigned.startswith("0o") else 16 if unsigned.startswith("0x") else 10)


_ConfigLoader.add_constructor("tag:yaml.org,2002:int", _integer)


def _load(content):
    if not content.strip() or len(content) > 200000:
        raise ValueError("Supply nonempty YAML of at most 200000 characters")
    try:
        return _mapping(_json_compatible(yaml.load(content, Loader=_ConfigLoader)), "Configuration")
    except _ConfigLimit:
        raise
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise ValueError(f"Invalid or unsupported configuration YAML{location}") from error
    except (ValueError, RecursionError) as error:
        raise ValueError("Configuration YAML must have unique string keys, finite JSON-compatible values, and a mapping root") from error


def _mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _name(value):
    if not isinstance(value, str) or not value or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ValueError("Configuration names must be nonempty strings of at most 200 characters without controls")
    return value


def _strings(value, label, scalar=False):
    if scalar and isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or len(value) > 100 or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must contain at most 100 strings")
    return value


def _env_names(value, compose=False):
    if isinstance(value, dict):
        return [_name(key) for key in value]
    if compose and isinstance(value, list):
        return sorted({_name(entry.partition("=")[0]) for entry in _strings(value, "environment")})
    raise ValueError("Environment declarations must be mappings" + (" or name/value string lists" if compose else ""))


def _graph(rows):
    names = {row["name"] for row in rows}
    unknown = [{"name": row["name"], "dependency": dependency} for row in rows
               for dependency in row["needs"] if dependency not in names]
    try:
        order = list(TopologicalSorter({row["name"]: set(row["needs"]) & names for row in rows}).static_order())
        cycle = False
    except CycleError:
        order, cycle = None, True
    return {"has_cycle": cycle, "unknown_dependencies": unknown[:100],
            "unknown_dependency_count": len(unknown), "order": None if unknown else order}


class _Summary:
    def __init__(self, limit):
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        self.limit, self.truncated = limit, False

    def text(self, value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Declared text fields must be strings")
        self.truncated |= len(value) > 2000
        return value[:2000]

    def items(self, values, maximum=None):
        maximum = self.limit if maximum is None else maximum
        self.truncated |= len(values) > maximum
        return values[:maximum]


def inspect_compose(content, limit):
    summary, data = _Summary(limit), _load(content)
    services = _mapping(data.get("services"), "services")
    if not 1 <= len(services) <= 100:
        raise ValueError("Compose must declare between one and 100 services")
    rows, graph_rows = [], []
    for name, raw in services.items():
        name, raw = _name(name), _mapping(raw, "Service")
        dependencies = raw.get("depends_on", [])
        if isinstance(dependencies, dict):
            dependencies = [{"service": _name(key), "condition": summary.text(_mapping(value, "Dependency").get("condition")),
                             "required": value.get("required"), "restart": value.get("restart")}
                            for key, value in dependencies.items()]
        else:
            dependencies = [{"service": _name(value), "condition": None, "required": None, "restart": None}
                            for value in _strings(dependencies, "depends_on")]
        if any(row[key] is not None and type(row[key]) is not bool for row in dependencies for key in ("required", "restart")):
            raise ValueError("Dependency required/restart declarations must be booleans")
        graph_rows.append({"name": name, "needs": [row["service"] for row in dependencies]})
        ports = raw.get("ports", [])
        if not isinstance(ports, list) or len(ports) > 100:
            raise ValueError("ports must be an array of at most 100 declarations")
        declared_ports = []
        for port in ports:
            if isinstance(port, str):
                declared_ports.append(summary.text(port))
            elif type(port) is int:
                declared_ports.append(port)
            elif isinstance(port, dict):
                values = {}
                for key in ("target", "published", "host_ip", "protocol", "mode"):
                    if key in port:
                        values[key] = port[key] if key in {"target", "published"} and type(port[key]) is int else summary.text(port[key])
                declared_ports.append(values)
            else:
                raise ValueError("Ports must use strings, integers, or long-form mappings")
        build = raw.get("build")
        if isinstance(build, str):
            build = {"context": build}
        if build is not None:
            _mapping(build, "build")
        health = _mapping(raw.get("healthcheck", {}), "healthcheck")
        if "disable" in health and type(health["disable"]) is not bool:
            raise ValueError("healthcheck.disable must be a boolean")
        if "retries" in health and (type(health["retries"]) is not int or health["retries"] < 0):
            raise ValueError("healthcheck.retries must be a nonnegative integer")
        test = health.get("test")
        if isinstance(test, list):
            _strings(test, "healthcheck.test")
            form = test[0] if test and test[0] in {"CMD", "CMD-SHELL", "NONE"} else "unknown"
        elif isinstance(test, str):
            form = "shell"
        elif test is None:
            form = None
        else:
            raise ValueError("healthcheck.test must be a string or string array")
        rows.append({"name": name, "image": summary.text(raw.get("image")),
                     "build": {key: summary.text(build.get(key)) for key in ("context", "dockerfile", "target")} if build is not None else None,
                     "ports": declared_ports, "dependencies": dependencies,
                     "environment_names": summary.items(_env_names(raw.get("environment", {}), compose=True), 100),
                     "healthcheck": {"declared": "healthcheck" in raw, "test_form": form,
                                     "disabled": health.get("disable") is True or form == "NONE",
                                     "interval": summary.text(health.get("interval")), "timeout": summary.text(health.get("timeout")),
                                     "retries": health.get("retries")},
                     "extends_declared": "extends" in raw})
    declarations = {key: summary.items([_name(name) for name in _mapping(data.get(key, {}), key)], 100)
                    for key in ("networks", "volumes", "secrets", "configs")}
    graph = _graph(graph_rows)
    summary.truncated |= graph["unknown_dependency_count"] > 100
    return {"name": summary.text(data.get("name")), "service_count": len(rows),
            "services": summary.items(rows), "declarations": declarations, "dependencies": graph,
            "include_declared": "include" in data, "truncated": summary.truncated,
            "notes": ["Declared configuration only, not full Compose validation or effective runtime settings.",
                      "Variables, includes, extends, profiles, and override files are not evaluated; no file/image/network access.",
                      "Environment values, build arguments, commands, and health-check command bodies are intentionally omitted."]}


def _permissions(value):
    if value is None:
        return None
    if isinstance(value, str) and value in {"read-all", "write-all"}:
        return {"mode": value, "scopes": None}
    scopes = _mapping(value, "permissions")
    if any(not isinstance(level, str) or level not in {"read", "write", "none"} for level in scopes.values()):
        raise ValueError("Permission values must be read, write, or none")
    return {"mode": "explicit", "scopes": {_name(name): level for name, level in scopes.items()}}


def inspect_actions(content, limit, max_steps):
    summary, data = _Summary(limit), _load(content)
    if type(max_steps) is not int or not 1 <= max_steps <= 50:
        raise ValueError("max_steps must be between 1 and 50")
    on = data.get("on")
    if isinstance(on, str):
        on = {on: None}
    elif isinstance(on, list):
        on = {_name(name): None for name in _strings(on, "on")}
    on = _mapping(on, "on")
    events = []
    for name, config in on.items():
        name = _name(name)
        if name == "schedule":
            if not isinstance(config, list) or len(config) > 100:
                raise ValueError("schedule must contain at most 100 cron declarations")
            events.append({"name": name, "schedules": [summary.text(_mapping(entry, "Schedule").get("cron")) for entry in config]})
            continue
        config = {} if config is None else _mapping(config, "Event configuration")
        filters = {key: [summary.text(item) for item in _strings(config[key], "Event filter")]
                   for key in ("types", "branches", "branches-ignore", "tags", "tags-ignore", "paths", "paths-ignore", "workflows") if key in config}
        events.append({"name": name, "filters": filters,
                       "input_names": summary.items([_name(key) for key in _mapping(config.get("inputs", {}), "inputs")], 100),
                       "secret_names": summary.items([_name(key) for key in _mapping(config.get("secrets", {}), "secrets")], 100)})
    jobs = _mapping(data.get("jobs"), "jobs")
    if not 1 <= len(jobs) <= 100:
        raise ValueError("Workflow must declare between one and 100 jobs")
    rows, graph_rows, step_count = [], [], 0
    for name, job in jobs.items():
        name, job = _name(name), _mapping(job, "Job")
        needs = [_name(item) for item in _strings(job.get("needs", []), "needs", scalar=True)]
        graph_rows.append({"name": name, "needs": needs})
        runners = job.get("runs-on")
        if isinstance(runners, dict):
            runners = {"group": summary.text(runners.get("group")),
                       "labels": [summary.text(value) for value in _strings(runners.get("labels", []), "Runner labels", scalar=True)]}
        elif runners is not None:
            runners = [summary.text(value) for value in _strings(runners, "runs-on", scalar=True)]
        steps = job.get("steps", [])
        if not isinstance(steps, list):
            raise ValueError("steps must be an array")
        step_count += len(steps)
        if step_count > 1000:
            raise ValueError("Workflow exceeds 1000 total steps")
        step_rows = []
        for index, step in enumerate(steps):
            _mapping(step, "Step")
            if "run" in step and not isinstance(step["run"], str):
                raise ValueError("Step run declarations must be strings")
            step_rows.append({"index": index + 1, "id": summary.text(step.get("id")),
                              "name": summary.text(step.get("name")), "uses": summary.text(step.get("uses")),
                              "run_declared": "run" in step,
                              "environment_names": summary.items(_env_names(step.get("env", {})), 100)})
        strategy = _mapping(job.get("strategy", {}), "strategy")
        matrix = strategy.get("matrix", {})
        if not isinstance(matrix, (dict, str)):
            raise ValueError("matrix must be a mapping or expression string")
        rows.append({"id": name, "name": summary.text(job.get("name")), "needs": needs, "runs_on": runners,
                     "uses": summary.text(job.get("uses")), "permissions": _permissions(job.get("permissions")),
                     "environment_names": summary.items(_env_names(job.get("env", {})), 100),
                     "matrix_axes": [_name(key) for key in matrix if key not in {"include", "exclude"}] if isinstance(matrix, dict) else [],
                     "matrix_expression": isinstance(matrix, str), "step_count": len(steps),
                     "steps": summary.items(step_rows, max_steps), "steps_truncated": len(steps) > max_steps})
    graph = _graph(graph_rows)
    summary.truncated |= graph["unknown_dependency_count"] > 100
    return {"name": summary.text(data.get("name")), "events": summary.items(events, 100),
            "permissions": _permissions(data.get("permissions")),
            "environment_names": summary.items(_env_names(data.get("env", {})), 100),
            "job_count": len(rows), "step_count": step_count, "jobs": summary.items(rows),
            "dependencies": graph, "truncated": summary.truncated,
            "notes": ["Declared workflow only, not full GitHub Actions validation; expressions, matrices, reusable workflows, and repository permission defaults are not resolved.",
                      "Environment values, run bodies, with arguments, and secret values are intentionally omitted; no file/network access or execution."]}
