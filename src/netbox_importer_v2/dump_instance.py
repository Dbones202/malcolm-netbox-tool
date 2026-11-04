"""Read-only export of existing NetBox objects, so the seeder matches the
instance's own naming/conventions (and so we never create duplicates).

GET-only, paginated. Writes v2_reports/instance_inventory.json and prints a
compact name summary per category.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from .connection import get_connection, NetBoxConn


def fetch_all(conn: NetBoxConn, path: str) -> List[dict]:
    out, url = [], path + ("&" if "?" in path else "?") + "limit=200"
    while url:
        r = conn.get(url)
        if r.status_code != 200:
            return [{"_error": f"HTTP {r.status_code}", "_path": path}]
        j = r.json()
        out.extend(j.get("results", []))
        url = j.get("next")
    return out


def _nm(v):
    if isinstance(v, dict):
        return v.get("name") or v.get("model") or v.get("display") or v.get("address") or v.get("slug")
    return v


def run_dump(env_file=None) -> Dict[str, Any]:
    conn = get_connection(env_file=env_file)
    inv: Dict[str, Any] = {"_api": conn.api_url}

    inv["sites"] = [{"name": x["name"], "slug": x["slug"]} for x in fetch_all(conn, "dcim/sites/")]
    inv["device_roles"] = [{"name": x["name"], "slug": x["slug"]} for x in fetch_all(conn, "dcim/device-roles/")]
    inv["manufacturers"] = [{"name": x["name"], "slug": x["slug"]} for x in fetch_all(conn, "dcim/manufacturers/")]
    inv["device_types"] = [{"model": x["model"], "slug": x["slug"], "manufacturer": _nm(x.get("manufacturer"))} for x in fetch_all(conn, "dcim/device-types/")]
    inv["platforms"] = [{"name": x["name"], "slug": x["slug"]} for x in fetch_all(conn, "dcim/platforms/")]
    inv["vlans"] = [{"vid": x["vid"], "name": x["name"]} for x in fetch_all(conn, "ipam/vlans/")]
    inv["prefixes"] = [{"prefix": x["prefix"], "description": x.get("description"), "site": _nm(x.get("site")), "vlan": _nm(x.get("vlan")), "role": _nm(x.get("role"))} for x in fetch_all(conn, "ipam/prefixes/")]
    inv["devices"] = [{"name": x["name"], "role": _nm(x.get("role")), "device_type": _nm(x.get("device_type")),
                       "manufacturer": _nm((x.get("device_type") or {}).get("manufacturer") if isinstance(x.get("device_type"), dict) else None),
                       "site": _nm(x.get("site")), "status": _nm(x.get("status")), "primary_ip": _nm(x.get("primary_ip"))} for x in fetch_all(conn, "dcim/devices/")]
    inv["interfaces"] = [{"device": _nm(x.get("device")), "name": x["name"], "type": _nm(x.get("type")),
                          "primary_mac": _nm(x.get("primary_mac_address")), "mac_legacy": x.get("mac_address")} for x in fetch_all(conn, "dcim/interfaces/")]
    inv["mac_addresses"] = [{"mac": x.get("mac_address"), "assigned": _nm(x.get("assigned_object"))} for x in fetch_all(conn, "dcim/mac-addresses/")]
    inv["ip_addresses"] = [{"address": x["address"], "assigned": _nm(x.get("assigned_object")), "dns_name": x.get("dns_name")} for x in fetch_all(conn, "ipam/ip-addresses/")]
    inv["services"] = [{"name": x["name"], "protocol": _nm(x.get("protocol")), "ports": x.get("ports"), "parent": _nm(x.get("parent_object") or x.get("device") or x.get("virtual_machine"))} for x in fetch_all(conn, "ipam/services/")]

    def _cf_type(t):
        if isinstance(t, dict):
            return t.get("value") or t.get("label")
        return t
    inv["custom_fields"] = [{"name": x.get("name"), "label": x.get("label"), "type": _cf_type(x.get("type")),
                             "object_types": x.get("object_types"),
                             "choice_set": _nm(x.get("choice_set")),
                             "choice_set_id": (x.get("choice_set") or {}).get("id") if isinstance(x.get("choice_set"), dict) else None}
                            for x in fetch_all(conn, "extras/custom-fields/")]
    inv["custom_field_choice_sets"] = [{"id": x.get("id"), "name": x.get("name"),
                                        "choices": [c[0] if isinstance(c, (list, tuple)) else c
                                                    for c in (x.get("extra_choices") or [])]}
                                       for x in fetch_all(conn, "extras/custom-field-choice-sets/")]

    df = "plugins/data-flows/"
    inv["df_applications"] = [{"name": x["name"], "role": _nm(x.get("role")), "tenant": _nm(x.get("tenant"))} for x in fetch_all(conn, df + "applications/")]
    inv["df_application_roles"] = [{"name": x["name"], "slug": x["slug"]} for x in fetch_all(conn, df + "application-roles/")]
    inv["df_groups"] = [{"name": x["name"], "application": _nm(x.get("application")), "status": _nm(x.get("status")), "parent": _nm(x.get("parent"))} for x in fetch_all(conn, df + "dataflow-groups/")]
    inv["df_dataflows"] = [{"name": x["name"], "application": _nm(x.get("application")), "protocol": _nm(x.get("protocol")),
                            "dest_ports": x.get("destination_ports"), "sources": [_nm(s) for s in (x.get("sources") or [])],
                            "destinations": [_nm(s) for s in (x.get("destinations") or [])], "status": _nm(x.get("status"))} for x in fetch_all(conn, df + "dataflows/")]
    inv["df_objectalias"] = [{"name": x["name"], "ips": [_nm(i) for i in (x.get("ip_addresses") or [])], "prefixes": [_nm(i) for i in (x.get("prefixes") or [])]} for x in fetch_all(conn, df + "objectalias/")]
    return inv


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Export existing NetBox objects (read-only).")
    ap.add_argument("--env-file", default=None)
    ap.add_argument("--out", default="v2_reports/instance_inventory.json")
    args = ap.parse_args()
    inv = run_dump(env_file=args.env_file)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    json.dump(inv, open(args.out, "w"), indent=2)
    def names(key, field="name"):
        return ", ".join(str(x.get(field)) for x in inv.get(key, [])) or "(none)"
    print("Sites        :", names("sites"))
    print("Device roles :", names("device_roles"))
    print("Manufacturers:", names("manufacturers"))
    print("Device types :", ", ".join(f'{x["manufacturer"]}/{x["model"]}' for x in inv.get("device_types", [])) or "(none)")
    print("Platforms    :", names("platforms"))
    print("VLANs        :", ", ".join(f'{x["vid"]}:{x["name"]}' for x in inv.get("vlans", [])) or "(none)")
    print("Devices (%d) :" % len(inv.get("devices", [])), ", ".join(x["name"] for x in inv.get("devices", [])) or "(none)")
    print("Custom fields:", ", ".join(f'{x["name"]}({x["type"]})' for x in inv.get("custom_fields",[])) or "(none)")
    print("DF apps      :", names("df_applications"))
    print("DF obj-alias :", ", ".join(x["name"] for x in inv.get("df_objectalias", [])) or "(none)")
    print("DF dataflows :", ", ".join(x["name"] for x in inv.get("df_dataflows", [])) or "(none)")
    print("\nWrote", args.out)


if __name__ == "__main__":
    main()
