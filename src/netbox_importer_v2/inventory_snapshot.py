"""Complete, fail-closed inventory snapshots for Day 4 planning and recovery."""

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

# Raw serializers retain student fields, IDs, tags and relationship references.
ENDPOINTS = (
    "extras/tags/",
    "dcim/sites/",
    "dcim/device-roles/",
    "dcim/manufacturers/",
    "dcim/device-types/",
    "dcim/platforms/",
    "dcim/devices/",
    "dcim/interfaces/",
    "dcim/mac-addresses/",
    "dcim/cables/",
    "ipam/roles/",
    "ipam/prefixes/",
    "ipam/ip-addresses/",
    "ipam/services/",
    "ipam/vlans/",
    "ipam/vrfs/",
    "tenancy/contacts/",
    "tenancy/contact-roles/",
    "tenancy/contact-assignments/",
    "extras/custom-fields/",
    "extras/custom-field-choice-sets/",
    "extras/config-contexts/",
    "plugins/data-flows/applications/",
    "plugins/data-flows/application-roles/",
    "plugins/data-flows/dataflow-groups/",
    "plugins/data-flows/objectalias/",
    "plugins/data-flows/dataflows/",
)
OPTIONAL = {"extras/config-contexts/", "dcim/cables/"}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_objects(conn, endpoint, optional=False):
    rows, url, visited = [], endpoint + "?limit=100", set()
    while url:
        if url in visited:
            raise RuntimeError("Pagination loop at " + endpoint)
        visited.add(url)
        response = conn.get(url)
        if optional and response.status_code == 404:
            return None
        if response.status_code != 200:
            raise RuntimeError(
                f"Snapshot failed: {endpoint} HTTP {response.status_code}"
            )
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise TypeError("Invalid paginated response: " + endpoint)
        rows.extend(data["results"])
        url = data.get("next")
    return rows


def capture_snapshot(conn, target=None, require_dataflows=True):
    objects, unavailable = {}, []
    for endpoint in ENDPOINTS:
        optional = endpoint in OPTIONAL or (
            endpoint.startswith("plugins/") and not require_dataflows
        )
        rows = read_objects(conn, endpoint, optional)
        if rows is None:
            unavailable.append(endpoint)
        else:
            objects[endpoint] = rows
    response = conn.options("dcim/devices/")
    if response.status_code != 200:
        raise RuntimeError("Cannot discover writable device/config fields")
    actions = response.json().get("actions", {})
    writable = actions.get("POST") or actions.get("PUT") or {}
    if not writable:
        raise RuntimeError("Device field discovery returned no writable fields")
    text_fields = [
        key
        for key, field in writable.items()
        if ("config" in key.lower()) and field.get("type") in ("string", "field")
    ]
    return {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "target": target or conn.api_url,
        "api_url": conn.api_url,
        "objects": objects,
        "unavailable": unavailable,
        "device_text_fields": text_fields,
    }


def write_private_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Exclusive creation prevents overwriting the only pre-update snapshot.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    return path
