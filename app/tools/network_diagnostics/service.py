import json
import re
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlencode

from app.tools.webpage.service import _public_destination, fetch_page


_LABEL = re.compile(r"(?:_[a-z0-9-]{1,62}|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)\Z")
_RECORD_TYPES = {"A": 1, "AAAA": 28, "MX": 15, "TXT": 16}


def _domain(value, *, allow_service=False):
    if not value or len(value) > 253 or value.endswith(".."):
        raise ValueError("Provide a valid public domain name")
    try:
        name = value.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError("Provide a valid public domain name") from error
    labels = name.split(".")
    if len(name) > 253 or len(labels) < 2 or any(not _LABEL.fullmatch(label) for label in labels):
        raise ValueError("Provide a valid public domain name")
    if not allow_service and any("_" in label for label in labels):
        raise ValueError("Provide a valid public domain name")
    return name


def inspect_certificate(domain):
    hostname = _domain(domain)
    _, _, port, address = _public_destination(f"https://{hostname}/")
    context = ssl.create_default_context()
    with socket.create_connection((address, port), timeout=5) as connection:
        with context.wrap_socket(connection, server_hostname=hostname) as secure:
            secure.settimeout(5)
            cert = secure.getpeercert()
    if not cert or not cert.get("notAfter"):
        raise ValueError("Server did not provide a readable certificate")
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), timezone.utc)
    started = cert.get("notBefore")
    issued = (datetime.fromtimestamp(ssl.cert_time_to_seconds(started), timezone.utc).isoformat()
              if started else None)
    issuer = [value for group in cert.get("issuer", ()) for key, value in group
              if key in {"commonName", "organizationName"}]
    names = [value for kind, value in cert.get("subjectAltName", ()) if kind == "DNS"]
    return {"domain": hostname, "issuer": issuer[:5], "valid_from": issued,
            "expires_at": expires.isoformat(),
            "days_remaining": round((expires - datetime.now(timezone.utc)).total_seconds() / 86400, 1),
            "dns_names": names[:20], "names_truncated": len(names) > 20,
            "verified": True}


def lookup_records(domain, record_type, limit):
    name = _domain(domain, allow_service=True)
    record_type = record_type.upper()
    if record_type not in _RECORD_TYPES:
        raise ValueError("record_type must be A, AAAA, MX, or TXT")
    url = "https://cloudflare-dns.com/dns-query?" + urlencode({"name": name, "type": record_type})
    body, _, _ = fetch_page(url, media_types={"application/dns-json"},
                            allowed_host="cloudflare-dns.com")
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("DNS resolver returned invalid JSON") from error
    if not isinstance(data, dict) or not isinstance(data.get("Status"), int):
        raise ValueError("DNS resolver returned an invalid response")
    answers = data.get("Answer", [])
    if not isinstance(answers, list):
        raise ValueError("DNS resolver returned invalid answers")
    records = [{"name": str(row.get("name", ""))[:253],
                "type": record_type if row.get("type") == _RECORD_TYPES[record_type] else "CNAME",
                "ttl": row.get("TTL"), "value": str(row.get("data", ""))[:500]}
               for row in answers if isinstance(row, dict)
               and row.get("type") in {_RECORD_TYPES[record_type], 5}]
    return {"domain": name, "record_type": record_type, "dns_status": data["Status"],
            "records": records[:limit], "truncated": len(records) > limit,
            "resolver": "Cloudflare 1.1.1.1"}
