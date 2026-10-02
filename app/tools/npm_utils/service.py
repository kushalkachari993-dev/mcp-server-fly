import json
import re
from urllib.parse import quote

from app.tools.webpage.service import fetch_page


_NAME = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*\Z")


def get_package(name):
    if not 1 <= len(name) <= 214 or not _NAME.fullmatch(name):
        raise ValueError("Provide a lowercase npm package name, optionally @scope/name (max 214 characters)")
    url = f"https://registry.npmjs.org/{quote(name, safe='')}/latest"
    body, _, _ = fetch_page(url, media_types={"application/json"}, allowed_host="registry.npmjs.org")
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("npm returned invalid JSON") from error
    if (not isinstance(data, dict) or data.get("name") != name
            or not isinstance(data.get("version"), str) or not data["version"]):
        raise ValueError("npm did not return package version metadata")
    truncated = False

    def text(value, maximum):
        nonlocal truncated
        if not isinstance(value, str):
            return ""
        truncated |= len(value) > maximum
        return value[:maximum]

    def dependencies(key):
        nonlocal truncated
        entries = data.get(key, {})
        if not isinstance(entries, dict) or any(not isinstance(value, str) for value in entries.values()):
            raise ValueError("npm returned invalid dependency metadata")
        truncated |= len(entries) > 30
        return [{"name": text(key, 214), "requirement": text(value, 500)}
                for key, value in list(entries.items())[:30]]

    repository = data.get("repository", "")
    license_value = data.get("license", "")
    engines = data.get("engines", {})
    result = {
        "name": name, "version": text(data["version"], 100),
        "description": text(data.get("description"), 1000),
        "requires_node": text(engines.get("node"), 200) if isinstance(engines, dict) else "",
        "dependencies": dependencies("dependencies"),
        "peer_dependencies": dependencies("peerDependencies"),
        "license": text(license_value.get("type") if isinstance(license_value, dict) else license_value, 300),
        "repository": text(repository.get("url") if isinstance(repository, dict) else repository, 1000),
        "homepage": text(data.get("homepage"), 1000),
        "deprecated": text(data.get("deprecated"), 1000),
        "url": f"https://www.npmjs.com/package/{name}",
    }
    result["truncated"] = truncated
    return result
