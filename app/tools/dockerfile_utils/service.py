import json
import re
from collections import Counter
from io import BytesIO

from dockerfile_parse import DockerfileParser
from dockerfile_parse.parser import image_from


_INSTRUCTIONS = {"ADD", "ARG", "CMD", "COPY", "ENTRYPOINT", "ENV", "EXPOSE", "FROM", "HEALTHCHECK",
                 "LABEL", "MAINTAINER", "ONBUILD", "RUN", "SHELL", "STOPSIGNAL", "USER", "VOLUME", "WORKDIR"}
_FROM = re.compile(r"(?:--platform=(?P<platform>\S+)\s+)?(?P<image>\S+)(?:\s+AS\s+(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*))?\Z", re.I)


def inspect_content(content):
    if not content.strip() or len(content) > 200000 or "\0" in content:
        raise ValueError("Supply nonempty Dockerfile text of at most 200000 characters without NUL bytes")
    lines = content.split("\n")
    if len(lines) - (lines[-1] == "") > 5000:
        raise ValueError("Dockerfile must not exceed 5000 physical lines")
    parser = DockerfileParser(fileobj=BytesIO(content.encode("utf-8")), env_replace=False)
    structure = parser.structure
    covered = {line for item in structure for line in range(item["startline"], item["endline"] + 1)}
    for index, line in enumerate(lines):
        if line.strip() and index not in covered:
            raise ValueError(f"Unparsed Dockerfile line {index + 1}; check missing arguments or unfinished continuations")
    instructions = [item for item in structure if item["instruction"] != "COMMENT"]
    if len(instructions) > 1000:
        raise ValueError("Dockerfile must not exceed 1000 instructions")
    stages, global_args, counts = [], [], Counter()
    truncated = False
    notes = ["Declared values only: no build, variable expansion, image lookup, or inherited image settings are evaluated.",
             "This is a structural summary, not Docker build validation. BuildKit heredocs are not supported."]

    def text(value):
        nonlocal truncated
        truncated |= len(value) > 2000
        return value[:2000]

    def command(value, line):
        nonlocal truncated
        try:
            parsed = json.loads(value)
        except (ValueError, RecursionError):
            parsed = None
        if isinstance(parsed, list) and all(isinstance(part, str) for part in parsed):
            truncated |= len(parsed) > 100
            return {"line": line, "form": "exec", "value": [text(part) for part in parsed[:100]]}
        return {"line": line, "form": "shell", "value": text(value)}

    for item in instructions:
        instruction, value, line = item["instruction"], item["value"].strip(), item["startline"] + 1
        if instruction not in _INSTRUCTIONS or not value:
            raise ValueError(f"Unsupported or empty Dockerfile instruction at line {line}")
        if instruction in {"RUN", "COPY", "ADD"} and "<<" in value:
            raise ValueError("BuildKit heredoc/<< syntax is not supported by this Dockerfile inspector")
        counts[instruction] += 1
        if instruction == "FROM":
            match = _FROM.fullmatch(value)
            if not match:
                raise ValueError(f"Invalid FROM instruction at line {line}")
            if len(stages) >= 20:
                raise ValueError("Dockerfile must not exceed 20 stages")
            image, name = image_from(value)
            if name and any(stage["name"] and stage["name"].lower() == name.lower() for stage in stages):
                raise ValueError(f"Duplicate stage name at line {line}")
            parent = next((stage["index"] for stage in stages
                           if stage["name"] and stage["name"].lower() == image.lower()), None)
            stages.append({"index": len(stages), "line": line, "name": text(name) if name else None,
                           "base_image": text(image), "platform": text(match["platform"]) if match["platform"] else None,
                           "parent_stage": parent, "instruction_count": 1, "declared_user": None,
                           "declared_workdir": None, "declared_ports": [], "cmd": None, "entrypoint": None})
        elif not stages:
            if instruction != "ARG":
                raise ValueError(f"Only ARG is allowed before the first FROM (line {line})")
            global_args.append({"line": line, "value": text(value)})
        else:
            stage = stages[-1]
            stage["instruction_count"] += 1
            if instruction in {"USER", "WORKDIR"}:
                stage["declared_" + instruction.lower()] = {"line": line, "value": text(value)}
            elif instruction in {"CMD", "ENTRYPOINT"}:
                stage[instruction.lower()] = command(value, line)
            elif instruction == "EXPOSE":
                stage["declared_ports"].extend(text(port) for port in value.split())
                if len(stage["declared_ports"]) > 100:
                    stage["declared_ports"] = stage["declared_ports"][:100]
                    truncated = True
    if not stages:
        raise ValueError("Dockerfile must contain a FROM instruction")
    return {"stage_count": len(stages), "instruction_count": len(instructions), "instruction_counts": dict(counts),
            "global_args": global_args, "stages": stages, "final_stage": len(stages) - 1,
            "notes": notes, "truncated": truncated}
