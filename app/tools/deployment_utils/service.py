import json
import re
import tomllib
from collections import Counter
from io import StringIO

import yaml
from dotenv.parser import parse_stream

from app.tools.config_utils.service import _ConfigLoader
from app.tools.manifest_utils.service import _check_structure, _string, _unique_object
from app.tools.yaml_utils.tool import _json_compatible


def _input(content):
    if not isinstance(content, str) or len(content) > 200000:
        raise ValueError("Input must be text of at most 200000 characters")


def _mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _array(value, label, maximum=100):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{label} must be an array of at most {maximum} entries")
    return value


def _text(value, label, required=False, maximum=2000):
    if value is None and not required:
        return None
    return _string(value, label, maximum)


def _integer(value, label, minimum=0, maximum=1000000):
    if value is not None and (type(value) is not int or not minimum <= value <= maximum):
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _boolean(value, label):
    if value is not None and type(value) is not bool:
        raise ValueError(f"{label} must be a boolean")
    return value


def _names(values, label):
    return [_text(value, label, required=True, maximum=200) for value in _array(values, label)]


def _limit(value):
    if type(value) is not int or not 1 <= value <= 50:
        raise ValueError("limit must be between 1 and 50")


def _tables(value, label):
    return [_mapping(item, label) for item in _array([value] if isinstance(value, dict) else value, label)]


def _duration(value, label):
    return _integer(value, label) if type(value) is int else _text(value, label)


def _fly_check(raw, kind):
    raw = _mapping(raw, "Health check")
    return {"kind": kind, "type": _text(raw.get("type"), "Check type"),
            "method": _text(raw.get("method"), "Check method"),
            "path": _text(raw.get("path"), "Check path"),
            "port": _integer(raw.get("port"), "Check port", 1, 65535),
            "interval": _duration(raw.get("interval"), "Check interval"),
            "timeout": _duration(raw.get("timeout"), "Check timeout"),
            "grace_period": _duration(raw.get("grace_period"), "Check grace period"),
            "header_names": _names(list(_mapping(raw.get("headers", {}), "Check headers")), "Header names"),
            "processes": _names(raw.get("processes", []), "Check processes")}


def inspect_fly(content):
    _input(content)
    if not content.strip():
        raise ValueError("Supply nonempty Fly TOML")
    try:
        data = tomllib.loads(content)
    except (tomllib.TOMLDecodeError, RecursionError) as error:
        raise ValueError("Invalid Fly TOML; source text is omitted") from error
    _check_structure(data)
    env = _mapping(data.get("env", {}), "env")
    if any(not isinstance(value, str) for value in env.values()):
        raise ValueError("Fly environment values must be strings")
    environment = _names(list(env), "Environment names")
    processes = _mapping(data.get("processes", {}), "processes")
    if any(not isinstance(value, str) for value in processes.values()):
        raise ValueError("Process commands must be strings")
    process_names = _names(list(processes), "Process names")
    warnings, services = [], []
    if any(name.startswith("FLY_") for name in environment):
        warnings.append("Environment names beginning with FLY_ are reserved by Fly.io.")
    declarations = []
    if "http_service" in data:
        declarations.append(("http_service", _mapping(data["http_service"], "http_service")))
    declarations.extend(("services", raw) for raw in _tables(data.get("services", []), "services"))
    for index, (source, raw) in enumerate(declarations, 1):
        stop = raw.get("auto_stop_machines")
        if stop is not None and type(stop) is not bool and stop not in ("off", "stop", "suspend"):
            raise ValueError("auto_stop_machines must be off, stop, suspend, or a legacy boolean")
        if type(stop) is bool:
            warnings.append(f"Service {index} uses a legacy boolean autostop declaration; current docs use off/stop/suspend.")
        if stop is False or stop == "off":
            warnings.append(f"Service {index} explicitly disables autostop; idle Machines may remain running.")
        start = _boolean(raw.get("auto_start_machines"), "auto_start_machines")
        if (stop is True or stop in ("stop", "suspend")) and start is False:
            warnings.append(f"Service {index} enables autostop but explicitly disables autostart.")
        ports = []
        for port in _array(raw.get("ports", []), "Service ports"):
            port = _mapping(port, "Service port")
            row = {key: _integer(port.get(key), "Service port", 1, 65535)
                   for key in ("port", "start_port", "end_port")}
            if (row["start_port"] is None) != (row["end_port"] is None):
                raise ValueError("Port ranges must declare both start_port and end_port")
            if row["start_port"] is not None and row["start_port"] > row["end_port"]:
                raise ValueError("Port range start must not exceed end")
            if row["port"] is None and row["start_port"] is None:
                raise ValueError("Service ports must declare a port or range")
            row.update(handlers=_names(port.get("handlers", []), "Port handlers"),
                       force_https=_boolean(port.get("force_https"), "Port force_https"))
            ports.append(row)
        checks = []
        for key in (("checks",) if source == "http_service" else ("http_checks", "tcp_checks")):
            checks.extend(_fly_check(check, key) for check in _array(raw.get(key, []), "Service checks"))
        concurrency = _mapping(raw.get("concurrency", {}), "concurrency")
        soft = _integer(concurrency.get("soft_limit"), "Concurrency soft_limit")
        hard = _integer(concurrency.get("hard_limit"), "Concurrency hard_limit")
        if soft is not None and hard is not None and soft > hard:
            warnings.append(f"Service {index} declares soft_limit greater than hard_limit.")
        targets = _names(raw.get("processes", []), "Service processes")
        if processes and any(target not in processes for target in targets):
            warnings.append(f"Service {index} references a process not declared in the supplied file.")
        services.append({"source": source, "internal_port": _integer(raw.get("internal_port"), "internal_port", 1, 65535),
                         "protocol": _text(raw.get("protocol"), "Service protocol"),
                         "force_https": _boolean(raw.get("force_https"), "force_https"),
                         "auto_stop_machines": stop, "auto_start_machines": start,
                         "min_machines_running": _integer(raw.get("min_machines_running"), "min_machines_running"),
                         "processes": targets, "ports": ports,
                         "implicit_http_ports": [80, 443] if source == "http_service" else [],
                         "checks": checks, "machine_checks_declared": "machine_checks" in raw,
                         "concurrency": {"type": _text(concurrency.get("type"), "Concurrency type"),
                                         "soft_limit": soft, "hard_limit": hard}})
    build = _mapping(data.get("build", {}), "build")
    deploy = _mapping(data.get("deploy", {}), "deploy")
    machines = []
    for vm in _tables(data.get("vm", []), "vm"):
        machines.append({"size": _text(vm.get("size"), "VM size"),
                         "memory": _text(vm.get("memory"), "VM memory"),
                         "memory_mb": _integer(vm.get("memory_mb"), "VM memory_mb", 1),
                         "cpus": _integer(vm.get("cpus"), "VM cpus", 1, 1000),
                         "cpu_kind": _text(vm.get("cpu_kind"), "VM cpu_kind"),
                         "processes": _names(vm.get("processes", []), "VM processes")})
    named_checks = _mapping(data.get("checks", {}), "checks")
    checks = [{"name": _text(name, "Check name", required=True, maximum=200), **_fly_check(raw, "checks")}
              for name, raw in named_checks.items()]
    if len(checks) > 100:
        raise ValueError("At most 100 named checks are supported")
    mounts = [{"source": _text(raw.get("source"), "Mount source"),
               "destination": _text(raw.get("destination"), "Mount destination"),
               "processes": _names(raw.get("processes", []), "Mount processes")}
              for raw in _tables(data.get("mounts", []), "mounts")]
    return {"app": _text(data.get("app"), "App name"),
            "primary_region": _text(data.get("primary_region"), "Primary region"),
            "environment_names": environment, "process_names": process_names,
            "build": {**{key: _text(build.get(key), "Build setting") for key in ("image", "dockerfile", "builder", "build-target")},
                      "argument_names": _names(list(_mapping(build.get("args", {}), "Build args")), "Build argument names")},
            "deploy": {"strategy": _text(deploy.get("strategy"), "Deploy strategy"),
                       "release_command_declared": "release_command" in deploy},
            "services": services, "machines": machines, "mounts": mounts, "checks": checks,
            "warnings": warnings,
            "notes": ["Supplied declarations only, not complete Fly validation or live configuration; defaults and CLI overrides are not applied.",
                      "No deployment, file/network access, secret retrieval, health-check execution, or cost estimate.",
                      "Environment, header and build-argument values, process commands and release commands are omitted."]}


def compare_environment(template, available_keys_json):
    _input(template)
    _input(available_keys_json)
    try:
        available = json.loads(available_keys_json, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ValueError("available_keys_json must be a JSON array of key names, not values") from error
    _array(available, "Available keys", 1000)

    def key_name(value):
        if not isinstance(value, str) or len(value) > 200 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("Environment keys must be ASCII identifiers of at most 200 characters")
        return value

    available_counts = Counter(key_name(value) for value in available)
    template_counts = Counter()
    declarations = 0
    for binding in parse_stream(StringIO(template.removeprefix("\ufeff"))):
        if binding.error:
            raise ValueError(f"Invalid dotenv template near line {binding.original.line}; source text is omitted")
        if binding.key is not None:
            template_counts[key_name(binding.key)] += 1
            declarations += 1
            if declarations > 1000:
                raise ValueError("Template exceeds 1000 key declarations")
    expected, supplied = set(template_counts), set(available_counts)
    return {"template_key_count": len(expected), "available_key_count": len(supplied),
            "keys_match": expected == supplied, "missing": sorted(expected - supplied),
            "unexpected": sorted(supplied - expected), "matched": sorted(expected & supplied),
            "template_duplicates": [{"key": key, "count": count} for key, count in sorted(template_counts.items()) if count > 1],
            "available_duplicates": [{"key": key, "count": count} for key, count in sorted(available_counts.items()) if count > 1],
            "notes": ["Case-sensitive key presence only; all template keys are compared without required/optional semantics or value validation.",
                      "Template values are omitted and not interpolated. Available input accepts names only; server environment and files are not read."]}


def _kubernetes_documents(content):
    _input(content)
    documents = []
    try:
        for index, document in enumerate(yaml.load_all(content, Loader=_ConfigLoader), 1):
            if index > 100:
                raise ValueError("At most 100 YAML documents are supported")
            if document is None:
                continue
            documents.append(_mapping(_json_compatible(document), "Kubernetes document"))
            _check_structure(documents)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        location = f" near line {mark.line + 1}" if mark else ""
        raise ValueError(f"Invalid or unsupported Kubernetes YAML{location}; source text is omitted") from error
    except (ValueError, RecursionError, KeyError, IndexError) as error:
        raise ValueError("Kubernetes YAML requires unique string keys and finite values; maximum 100 documents, 10000 expanded nodes and 50 nesting levels") from error
    if not documents:
        raise ValueError("Supply at least one Kubernetes object")
    objects = []
    for document in documents:
        if document.get("kind") == "List":
            objects.extend(_mapping(item, "List item") for item in _array(document.get("items"), "List items"))
        else:
            objects.append(document)
    if not 1 <= len(objects) <= 100 or any(obj.get("kind") == "List" for obj in objects):
        raise ValueError("Supply one to 100 objects; nested Lists are not supported")
    return objects


def _port(value, label, required=False):
    if value is None and not required:
        return None
    if isinstance(value, str):
        return _text(value, label, required=True, maximum=200)
    if value is None:
        raise ValueError(f"{label} is required")
    return _integer(value, label, 1, 65535)


def _reference(raw, kind, source, key=False):
    raw = _mapping(raw, "Reference")
    return {"kind": kind, "source": source,
            "name": _text(raw.get("name"), "Reference name", required=True, maximum=200),
            "key": _text(raw.get("key"), "Reference key", required=True, maximum=200) if key else None,
            "optional": _boolean(raw.get("optional"), "Reference optional")}


def _probe(raw):
    if raw is None:
        return None
    raw = _mapping(raw, "Probe")
    actions = [key for key in ("httpGet", "tcpSocket", "grpc", "exec") if key in raw]
    if len(actions) != 1:
        raise ValueError("Probe must declare exactly one supported action")
    kind = actions[0]
    action = _mapping(raw[kind], "Probe action")
    result = {"action": kind}
    if kind != "exec":
        result["port"] = _port(action.get("port"), "Probe port", required=True)
        if kind == "grpc" and type(result["port"]) is not int:
            raise ValueError("gRPC probe ports must be integers")
    if kind == "httpGet":
        result.update(path=_text(action.get("path"), "Probe path"), scheme=_text(action.get("scheme"), "Probe scheme"),
                      header_names=[_text(_mapping(item, "Probe header").get("name"), "Probe header name", required=True, maximum=200)
                                    for item in _array(action.get("httpHeaders", []), "Probe headers")])
    if kind == "exec":
        result["command_declared"] = "command" in action
    for field in ("initialDelaySeconds", "periodSeconds", "timeoutSeconds", "successThreshold", "failureThreshold", "terminationGracePeriodSeconds"):
        result[field] = _integer(raw.get(field), "Probe timing/threshold", 0 if field == "initialDelaySeconds" else 1)
    return result


def _resources(raw):
    raw = _mapping(raw, "Container resources")
    result = {}
    for field in ("requests", "limits"):
        values = _mapping(raw.get(field, {}), "Resource quantities")
        _names(list(values), "Resource names")
        quantities = {}
        for key, value in values.items():
            if type(value) in (int, float) and value >= 0:
                quantities[key] = value
            else:
                quantities[key] = _text(value, "Resource quantity", required=True, maximum=200)
        result[field] = quantities
    return result


def _container(raw, role, references):
    raw = _mapping(raw, "Container")
    environment = []
    for env in _array(raw.get("env", []), "Container environment"):
        env = _mapping(env, "Environment entry")
        name = _text(env.get("name"), "Environment name", required=True, maximum=200)
        value_from = _mapping(env.get("valueFrom", {}), "valueFrom")
        sources = [key for key in ("secretKeyRef", "configMapKeyRef", "fieldRef", "resourceFieldRef") if key in value_from]
        if len(sources) > 1 or ("value" in env and sources):
            raise ValueError("Environment entries must not declare multiple value sources")
        for key, kind in (("secretKeyRef", "Secret"), ("configMapKeyRef", "ConfigMap")):
            if key in value_from:
                references.append(_reference(value_from[key], kind, "environment", key=True))
        environment.append({"name": name, "source": sources[0] if sources else "literal" if "value" in env else "unspecified"})
    for env in _array(raw.get("envFrom", []), "envFrom"):
        env = _mapping(env, "envFrom entry")
        for key, kind in (("secretRef", "Secret"), ("configMapRef", "ConfigMap")):
            if key in env:
                ref = _reference(env[key], kind, "envFrom")
                ref["prefix"] = _text(env.get("prefix"), "Environment prefix")
                references.append(ref)
    ports = []
    for port in _array(raw.get("ports", []), "Container ports"):
        port = _mapping(port, "Container port")
        number = _integer(port.get("containerPort"), "containerPort", 1, 65535)
        if number is None:
            raise ValueError("Container ports must declare containerPort")
        ports.append({"name": _text(port.get("name"), "Port name"), "container_port": number,
                      "host_port": _integer(port.get("hostPort"), "hostPort", 1, 65535),
                      "protocol": _text(port.get("protocol"), "Port protocol")})
    return {"name": _text(raw.get("name"), "Container name", required=True, maximum=200), "role": role,
            "image": _text(raw.get("image"), "Container image"), "restart_policy": _text(raw.get("restartPolicy"), "Container restartPolicy"),
            "ports": ports, "environment": environment, "resources": _resources(raw.get("resources", {})),
            "probes": {key: _probe(raw.get(key)) for key in ("livenessProbe", "readinessProbe", "startupProbe")},
            "command_declared": "command" in raw, "args_declared": "args" in raw}


def _pod(raw):
    raw = _mapping(raw, "Pod spec")
    references, containers = [], []
    for key, role in (("containers", "regular"), ("initContainers", "init"), ("ephemeralContainers", "ephemeral")):
        entries = _array(raw.get(key, []), "Containers")
        if key == "containers" and not entries:
            raise ValueError("Pod specs must declare at least one regular container")
        containers.extend(_container(entry, role, references) for entry in entries)
    for value in _array(raw.get("imagePullSecrets", []), "imagePullSecrets"):
        references.append(_reference(value, "Secret", "imagePullSecrets"))
    for volume in _array(raw.get("volumes", []), "Volumes"):
        volume = _mapping(volume, "Volume")
        if "secret" in volume:
            secret = _mapping(volume["secret"], "Secret volume")
            references.append(_reference({**secret, "name": secret.get("secretName")}, "Secret", "volume"))
        if "configMap" in volume:
            references.append(_reference(volume["configMap"], "ConfigMap", "volume"))
        if "projected" in volume:
            for source in _array(_mapping(volume["projected"], "Projected volume").get("sources", []), "Projected sources"):
                source = _mapping(source, "Projected source")
                for key, kind in (("secret", "Secret"), ("configMap", "ConfigMap")):
                    if key in source:
                        references.append(_reference(source[key], kind, "projected_volume"))
    return {"containers": containers, "references": references,
            "service_account_name": _text(raw.get("serviceAccountName"), "Service account name"),
            "restart_policy": _text(raw.get("restartPolicy"), "Pod restartPolicy")}


def inspect_kubernetes(content, limit):
    _limit(limit)
    objects = _kubernetes_documents(content)
    rows, kinds, container_count = [], Counter(), 0
    workloads = {"Pod", "Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob"}
    for obj in objects:
        kind = _text(obj.get("kind"), "Object kind", required=True, maximum=200)
        metadata = _mapping(obj.get("metadata", {}), "Object metadata")
        name = _text(metadata.get("name"), "Object name", maximum=200)
        generated = _text(metadata.get("generateName"), "Object generateName", maximum=200)
        if name is None and generated is None:
            raise ValueError("Objects must declare metadata.name or metadata.generateName")
        kinds[kind] += 1
        row = {"kind": kind, "api_version": _text(obj.get("apiVersion"), "apiVersion", required=True, maximum=200),
               "name": name, "generate_name": generated, "namespace": _text(metadata.get("namespace"), "Namespace", maximum=200),
               "inspected": kind in workloads | {"Service", "Secret", "ConfigMap"}}
        if kind in workloads:
            spec = _mapping(obj.get("spec"), "Workload spec")
            pod_spec = spec
            if kind == "CronJob":
                pod_spec = _mapping(_mapping(spec.get("jobTemplate"), "jobTemplate").get("spec"), "Job spec")
                row["schedule"] = _text(spec.get("schedule"), "CronJob schedule")
            if kind != "Pod":
                pod_spec = _mapping(_mapping(pod_spec.get("template"), "Pod template").get("spec"), "Pod spec")
            row["pod"] = _pod(pod_spec)
            container_count += len(row["pod"]["containers"])
            if container_count > 200:
                raise ValueError("Manifest exceeds 200 container declarations")
            if kind in {"Deployment", "StatefulSet", "ReplicaSet"}:
                row["replicas"] = _integer(spec.get("replicas"), "Replicas")
        elif kind == "Service":
            spec = _mapping(obj.get("spec"), "Service spec")
            ports = []
            for port in _array(spec.get("ports", []), "Service ports"):
                port = _mapping(port, "Service port")
                number = _integer(port.get("port"), "Service port", 1, 65535)
                if number is None:
                    raise ValueError("Service port entries must declare port")
                ports.append({"name": _text(port.get("name"), "Port name"), "port": number,
                              "target_port": _port(port.get("targetPort"), "targetPort"),
                              "node_port": _integer(port.get("nodePort"), "nodePort", 1, 65535),
                              "protocol": _text(port.get("protocol"), "Port protocol")})
            selector = _mapping(spec.get("selector", {}), "Service selector")
            _names(list(selector), "Selector keys")
            row.update(service_type=_text(spec.get("type"), "Service type"), ports=ports,
                       selector={key: _text(value, "Selector value", required=True) for key, value in selector.items()})
        elif kind in {"Secret", "ConfigMap"}:
            fields = ("data", "stringData") if kind == "Secret" else ("data", "binaryData")
            row["data_keys"] = {field: _names(list(_mapping(obj.get(field, {}), "Data declarations")), "Data keys") for field in fields}
        rows.append(row)
    return {"object_count": len(rows), "container_count": container_count, "kinds": dict(sorted(kinds.items())),
            "objects": rows[:limit], "truncated": len(rows) > limit,
            "notes": ["Common workload, Service, Secret and ConfigMap declarations only; other kinds receive metadata-only summaries.",
                      "No Kubernetes schema/API-version validation, cluster access, reference resolution, Helm/Kustomize rendering, defaults, or execution.",
                      "Environment and Secret/ConfigMap values, annotations, command bodies, arguments and probe header values are omitted.",
                      "Resource quantities are reported as declared, without unit parsing or scheduling evaluation."]}
