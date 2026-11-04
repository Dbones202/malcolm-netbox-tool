"""Read-only NetBox API discovery for the v2 importer.

Introspects a live NetBox instance so v2 is built against the *real* API,
not assumptions. Makes ONLY GET and OPTIONS calls — never writes.

Probes:
  * server version + installed plugins (/api/status/)
  * whether MAC addresses are first-class objects (NetBox 4.2+) or a legacy
    ``mac_address`` field on the interface
  * writable fields + choice lists for interfaces, IP addresses, and services
    (via OPTIONS -> actions.POST)
  * the netbox-data-flows plugin endpoints and their fields (if installed)
  * current object counts, so we know the starting state of the instance
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from urllib.parse import urlparse

from .connection import get_connection, NetBoxConn

CORE_ENDPOINTS = [
    "dcim/sites",
    "dcim/manufacturers",
    "dcim/device-types",
    "dcim/device-roles",
    "dcim/platforms",
    "dcim/devices",
    "dcim/interfaces",
    "dcim/mac-addresses",
    "dcim/cables",
    "ipam/prefixes",
    "ipam/ip-addresses",
    "ipam/services",
    "ipam/vlans",
    "ipam/vrfs",
]


def _safe_get_json(conn: NetBoxConn, path: str, params: Optional[dict] = None):
    try:
        r = conn.get(path, params=params)
        payload = r.json() if r.content else None
        return r.status_code, payload
    except Exception as e:  # network / TLS / JSON errors
        return None, {"error": str(e)}


def options_fields(conn: NetBoxConn, path: str) -> Dict[str, Any]:
    """Return the writable field map from an OPTIONS call (actions.POST)."""
    try:
        r = conn.options(path)
        if r.status_code != 200 or not r.content:
            return {}
        j = r.json()
        actions = j.get("actions") or {}
        return actions.get("POST") or actions.get("PUT") or {}
    except Exception:
        return {}


def summarize_fields(fields: Dict[str, Any], names: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for n in names:
        f = fields.get(n)
        if not isinstance(f, dict):
            continue
        info = {"required": f.get("required"), "type": f.get("type")}
        choices = f.get("choices")
        if isinstance(choices, list):
            info["choices"] = [c.get("value") for c in choices if isinstance(c, dict)][:60]
        out[n] = info
    return out


def get_status(conn: NetBoxConn) -> Dict[str, Any]:
    code, data = _safe_get_json(conn, "status/")
    return {"status_code": code, "data": data}


def detect_mac_model(conn: NetBoxConn) -> Dict[str, Any]:
    code, data = _safe_get_json(conn, "dcim/mac-addresses/", params={"limit": 1})
    first_class = code == 200 and isinstance(data, dict) and "results" in data
    iface_fields = options_fields(conn, "dcim/interfaces/")
    has_primary = "primary_mac_address" in iface_fields
    has_legacy = "mac_address" in iface_fields
    if first_class or has_primary:
        rec = "Use dcim/mac-addresses objects assigned to interfaces, then set interface.primary_mac_address (NetBox 4.2+ model)."
    else:
        rec = "Set the legacy interface.mac_address string field (pre-4.2 model)."
    return {
        "mac_addresses_endpoint_http": code,
        "first_class_mac_objects": bool(first_class),
        "interface_has_primary_mac_address": has_primary,
        "interface_has_legacy_mac_field": has_legacy,
        "recommended_approach": rec,
    }


def counts(conn: NetBoxConn) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for ep in CORE_ENDPOINTS:
        code, data = _safe_get_json(conn, ep + "/", params={"limit": 1})
        out[ep] = data.get("count") if (code == 200 and isinstance(data, dict)) else f"n/a (HTTP {code})"
    return out


def discover_dataflows(conn: NetBoxConn) -> Dict[str, Any]:
    """Enumerate the netbox-data-flows plugin API if present."""
    for base in ("plugins/data-flows/", "plugins/data_flows/"):
        code, data = _safe_get_json(conn, base)
        if code == 200 and isinstance(data, dict):
            detail: Dict[str, Any] = {}
            for name, url in data.items():
                if not isinstance(url, str):
                    continue
                fields = options_fields(conn, url)
                detail[name] = {"url": url, "fields": sorted(fields.keys())}
            return {"installed": True, "base": base, "endpoints": data, "detail": detail}
    return {
        "installed": False,
        "note": "No /api/plugins/data-flows/ root found. Confirm the plugin is enabled and the API path.",
    }


def run_discovery(env_file: Optional[str] = None) -> Dict[str, Any]:
    conn = get_connection(env_file=env_file)

    # Auto-detect the working base URL if the configured one does not answer.
    code, _ = _safe_get_json(conn, "status/")
    autodetected = None
    if code != 200:
        host = urlparse(conn.base_url).hostname or conn.base_url.replace("https://", "").replace("http://", "").split("/")[0]
        candidates = [f"https://{host}", f"https://{host}/netbox", f"http://{host}:8000",
                      f"http://{host}", f"https://{host}:8443", f"https://{host}:443/netbox"]
        for base in candidates:
            test = NetBoxConn(base_url=base.rstrip("/"), api_url=base.rstrip("/") + "/api",
                              token=conn.token, verify_ssl=conn.verify_ssl, session=conn.session)
            c, _ = _safe_get_json(test, "status/")
            if c == 200:
                conn = test
                autodetected = base
                break

    status = get_status(conn)
    st_data = status.get("data") or {}

    report: Dict[str, Any] = {
        "connection": {"api_url": conn.api_url, "verify_ssl": conn.verify_ssl, "autodetected_base": autodetected},
        "netbox_version": st_data.get("netbox-version"),
        "python_version": st_data.get("python-version"),
        "installed_plugins": st_data.get("plugins", {}),
        "status": status,
        "counts": counts(conn),
        "mac_model": detect_mac_model(conn),
        "interface_fields": summarize_fields(
            options_fields(conn, "dcim/interfaces/"),
            ["type", "mode", "primary_mac_address", "mac_address", "vrf"],
        ),
        "ip_address_fields": summarize_fields(
            options_fields(conn, "ipam/ip-addresses/"),
            ["status", "role", "assigned_object_type"],
        ),
        "service_fields": summarize_fields(
            options_fields(conn, "ipam/services/"),
            ["protocol", "ports", "parent_object_type", "ipaddresses", "device", "virtual_machine"],
        ),
        "dataflows": discover_dataflows(conn),
    }
    return report
