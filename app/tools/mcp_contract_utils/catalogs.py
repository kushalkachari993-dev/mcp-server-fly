import hashlib
from urllib.parse import urlsplit, urlunsplit

from app.tools.report_utils.service import _Summary

from . import catalog_parser


def _identity(value, summary):
    try:
        parts = urlsplit(value)
        target = urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))
    except ValueError:
        target = None
    return {"scheme": catalog_parser.scheme(value),
            "display_uri": summary.text(target, 1000),
            "sha256_prefix": hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]}


def _shown_resource(identity, raw, summary):
    return {"identity": _identity(identity, summary), "name": summary.text(raw["name"], 200),
            "mime_type": summary.text(raw.get("mimeType"), 200), "size_bytes": raw.get("size"),
            "title_present": "title" in raw, "description_present": "description" in raw,
            "annotations_present": "annotations" in raw, "icon_count": len(raw.get("icons", []))}


def inspect_mcp_resource_manifest(resources, templates, protocol_version, limit):
    summary = _Summary(resources, limit)
    if templates:
        _Summary(templates, limit)
    resource_rows, resource_partial, template_rows, template_partial = catalog_parser.resource_catalog(
        resources, templates, protocol_version)
    return {"protocol_version": protocol_version, "resource_count": len(resource_rows),
            "resource_list_partial": resource_partial, "templates_supplied": bool(templates),
            "template_count": len(template_rows) if templates else None,
            "template_list_partial": template_partial if templates else None,
            "resources": summary.take([_shown_resource(uri, raw, summary)
                                       for uri, raw in sorted(resource_rows.items())]),
            "templates": summary.take([_shown_resource(uri, raw, summary)
                                       for uri, raw in sorted(template_rows.items())]) if templates else None,
            "truncated": summary.truncated,
            "notes": ["Inspects supplied resources/list and optional resources/templates/list results only; no resource is read or URI dereferenced.",
                      "A nextCursor means that list is partial. Templates are unknown when no templates response is supplied, not empty.",
                      "Display URIs omit userinfo, query and fragment; full identities are hashed for disambiguation. Paths and names may still be sensitive.",
                      "Content, descriptions, annotations and icon details are omitted. This is not full URI-template or MCP conformance validation."]}


def _resource_changes(changes, kind, old_rows, new_rows, summary):
    for identity in sorted(old_rows.keys() | new_rows.keys()):
        old, new = old_rows.get(identity), new_rows.get(identity)
        shown = _identity(identity, summary)
        if old is None or new is None:
            changes.append({"kind": kind, "identity": shown, "field": "presence",
                            "before": old is not None, "after": new is not None})
            continue
        for field, key in (("mime_type", "mimeType"), ("size_bytes", "size")):
            if old.get(key) != new.get(key):
                left, right = old.get(key), new.get(key)
                if key == "mimeType":
                    left, right = summary.text(left, 200), summary.text(right, 200)
                changes.append({"kind": kind, "identity": shown, "field": field,
                                "before": left, "after": right})
        for key in ("name", "title", "description", "annotations", "icons"):
            if old.get(key) != new.get(key):
                changes.append({"kind": kind, "identity": shown, "field": key, "changed": True})


def compare_mcp_resource_manifests(before_resources, after_resources, before_templates,
                                   after_templates, protocol_version, limit):
    summary = _Summary(before_resources, limit)
    _Summary(after_resources, limit)
    if bool(before_templates) != bool(after_templates):
        raise ValueError("Supply both template lists or omit both")
    if before_templates:
        _Summary(before_templates, limit)
        _Summary(after_templates, limit)
    old_resources, old_partial, old_templates, old_template_partial = catalog_parser.resource_catalog(
        before_resources, before_templates, protocol_version)
    new_resources, new_partial, new_templates, new_template_partial = catalog_parser.resource_catalog(
        after_resources, after_templates, protocol_version)
    if any((old_partial, new_partial, old_template_partial, new_template_partial)):
        raise ValueError("Compare complete MCP resource lists; follow nextCursor on every supplied page first")
    changes = []
    _resource_changes(changes, "resource", old_resources, new_resources, summary)
    if before_templates:
        _resource_changes(changes, "template", old_templates, new_templates, summary)
    return {"protocol_version": protocol_version, "before_resource_count": len(old_resources),
            "after_resource_count": len(new_resources), "templates_compared": bool(before_templates),
            "before_template_count": len(old_templates) if before_templates else None,
            "after_template_count": len(new_templates) if before_templates else None,
            "selected_change_count": len(changes), "changes": summary.take(changes),
            "truncated": summary.truncated,
            "notes": ["Matches full exact resource URIs and URI templates before display sanitization; no rename inference or compatibility verdict.",
                      "Only declared names, MIME types, sizes and selected metadata are compared. Resource contents and runtime access are not checked.",
                      "Display URIs omit userinfo, query and fragment; paths may still be sensitive. Complete supplied lists are required."]}


def _shown_prompt(name, raw, arguments, summary):
    return {"name": summary.text(name, 200), "argument_count": len(arguments),
            "required_argument_count": sum(argument.get("required", False) for argument in arguments.values()),
            "arguments": summary.take([{"name": summary.text(argument_name, 200),
                                        "required": argument.get("required", False)}
                                       for argument_name, argument in sorted(arguments.items())]),
            "title_present": "title" in raw, "description_present": "description" in raw,
            "icon_count": len(raw.get("icons", []))}


def inspect_mcp_prompt_manifest(manifest, protocol_version, limit):
    summary = _Summary(manifest, limit)
    rows, partial = catalog_parser.prompt_catalog(manifest, protocol_version)
    return {"protocol_version": protocol_version, "prompt_count": len(rows), "partial_list": partial,
            "prompts": summary.take([_shown_prompt(name, *rows[name], summary) for name in sorted(rows)]),
            "truncated": summary.truncated,
            "notes": ["Inspects one supplied prompts/list page or complete snapshot; no prompt is fetched or rendered.",
                      "A nextCursor marks a partial page, not proof that an absent prompt was removed.",
                      "Prompt and argument names may be sensitive. Descriptions, icon details and generated message content are omitted."]}


def compare_mcp_prompt_manifests(before, after, protocol_version, limit):
    summary = _Summary(before, limit)
    _Summary(after, limit)
    old_rows, old_partial = catalog_parser.prompt_catalog(before, protocol_version)
    new_rows, new_partial = catalog_parser.prompt_catalog(after, protocol_version)
    if old_partial or new_partial:
        raise ValueError("Compare complete prompts/list snapshots; follow nextCursor on every page first")
    changes = []
    for name in sorted(old_rows.keys() | new_rows.keys()):
        old, new = old_rows.get(name), new_rows.get(name)
        shown_name = summary.text(name, 200)
        if old is None or new is None:
            changes.append({"prompt": shown_name, "field": "presence",
                            "before": old is not None, "after": new is not None})
            continue
        old_raw, old_args = old
        new_raw, new_args = new
        for argument_name in sorted(old_args.keys() | new_args.keys()):
            previous, current = old_args.get(argument_name), new_args.get(argument_name)
            identity = {"prompt": shown_name, "argument": summary.text(argument_name, 200)}
            if previous is None or current is None:
                changes.append({**identity, "field": "argument_presence",
                                "before": previous is not None, "after": current is not None})
            else:
                before_required = previous.get("required", False)
                after_required = current.get("required", False)
                if before_required != after_required:
                    changes.append({**identity, "field": "required", "before": before_required,
                                    "after": after_required})
                if previous.get("description") != current.get("description"):
                    changes.append({**identity, "field": "argument_description", "changed": True})
        for key in ("title", "description", "icons"):
            if old_raw.get(key) != new_raw.get(key):
                changes.append({"prompt": shown_name, "field": key, "changed": True})
    return {"protocol_version": protocol_version, "before_prompt_count": len(old_rows),
            "after_prompt_count": len(new_rows), "selected_change_count": len(changes),
            "changes": summary.take(changes), "truncated": summary.truncated,
            "notes": ["Matches full exact case-sensitive prompt and argument names before display shortening; no rename inference.",
                      "Added/removed arguments and required-flag changes are reported; descriptions and icon changes are flags only.",
                      "Prompt content and runtime behavior are not checked. This is not a compatibility verdict; complete supplied lists are required."]}
