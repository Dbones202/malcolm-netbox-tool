"""Derive a reduced 'student' environment from the master by subtraction.

Philosophy:
  - Master is the complete 100% answer key.
  - Day 1 is the KYE student starting state with:
    1. 9 Redacted Devices removed (must be discovered).
    2. 6 Prepopulated Devices tampered with wrong IPs & tomato ASCII note.
    3. Exactly 24 Dataflows prepopulated (13 withheld to be discovered).
    4. Stripped MAC addresses and raw nmap service clutter.
"""
from __future__ import annotations

import copy
import json
import os
from typing import Tuple, Dict, Any

# 9 Redacted Devices (removed from Day 1 student view)
REDACTED_DEVICE_NAMES = {
    "database",
    "database-asc",
    "database-acs",
    "database-acd",
    "internal-ftp",
    "acd-plc",
    "asc-l55-plc",
    "apl-rtu-2",
    "sign-asc",
}

# 6 Tampered Devices (wrong IPs + Allen Broodly tomato comment)
TAMPERED_DEVICES = {
    "user-1": {"wrong_ip": "172.16.220.71/24"},
    "finance-1": {"wrong_ip": "172.16.220.72/24"},
    "mail": {"wrong_ip": "172.16.220.73/24"},
    "ews-1": {"wrong_ip": "192.168.0.74/24"},
    "hmi-acs": {"wrong_ip": "192.168.32.75/24"},
    "hmi-acd": {"wrong_ip": "192.168.32.76/24"},
}

TOMATO_ASCII = """      \\ | /
    '-.;;;.-'
   -==;;;;;==-
    .-';;;'-.
   /  / | \\  \\
  |           |
  |  ( ) ( )  |
  \\     _     /
   '-._____.-'
Allen Broodly Was Here"""

# 13 Missing Dataflows (withheld from Day 1 student view)
WITHHELD_FLOW_KEYS = {
    ("acd-plc", "indusoft-overview", 18245),
    ("apl-rtu", "indusoft-overview", 502),
    ("acs-s7-1500-plc", "indusoft-overview", 102),
    ("acs-s7-1500-plc", "syslog", 514),
    ("apl-rtu-2", "apl-breaker-panel", 20000),
    ("hmi-acs", "asc-l81-plc", 2222),
    ("asc-l81-plc", "syslog", 514),
    ("asc-l81-plc", "asc-l55-plc", 44818),
    ("asc-l55-plc", "indusoft-overview", 44818),
    ("asc-l81-plc", "rssql-asc", 44818),
    ("asc-l81-plc", "hmi-asc", 44818),
    ("asc-remote-io-eip", "asc-l81-plc", 2222),
    ("rssql-asc", "database-asc", 1433),
}


def reduce_master_day1(master: dict) -> Tuple[dict, dict]:
    out = copy.deepcopy(master)
    stats = {
        "redacted_devices_dropped": 0,
        "scan_only_dropped": 0,
        "tampered_devices_modified": 0,
        "macs_stripped": 0,
        "services_dropped": 0,
        "dataflows_withheld": 0,
        "dataflows_kept": 0,
    }

    kept_devices = []
    for d in out["devices"]:
        name = d["name"]
        
        # 1. Drop scan-only rogue hosts
        if d.get("provenance") == "scan-only":
            stats["scan_only_dropped"] += 1
            continue

        # 2. Redact the 9 target challenge devices
        if name in REDACTED_DEVICE_NAMES:
            stats["redacted_devices_dropped"] += 1
            continue

        # 3. Strip MAC addresses
        for nic in d.get("interfaces", []):
            if nic.get("mac"):
                nic["mac"] = None
                stats["macs_stripped"] += 1

        # 4. Tamper the 6 targeted devices
        if name in TAMPERED_DEVICES:
            wrong_ip = TAMPERED_DEVICES[name]["wrong_ip"]
            if d.get("interfaces"):
                d["interfaces"][0]["ips"] = [wrong_ip]
            d["notes"] = TOMATO_ASCII
            d["description"] = f"Tomato: Allen Broodly Was Here | {d.get('description', '')}"[:200]
            stats["tampered_devices_modified"] += 1

        # 5. Drop nmap raw services (keep dataflow-inferred services)
        before_svc = len(d.get("services", []))
        d["services"] = [s for s in d.get("services", []) if s.get("source") != "nmap"]
        stats["services_dropped"] += before_svc - len(d["services"])

        kept_devices.append(d)

    out["devices"] = kept_devices

    # Filter dataflows: withhold the 13 target flows
    kept_flows = []
    for f in out.get("dataflows", []):
        key = (f.get("src"), f.get("dst"), f.get("port"))
        if key in WITHHELD_FLOW_KEYS:
            stats["dataflows_withheld"] += 1
            continue
        kept_flows.append(f)

    out["dataflows"] = kept_flows
    stats["dataflows_kept"] = len(kept_flows)

    out.setdefault("meta", {})["profile"] = {
        "name": "day1_kye",
        "desc": "KYE Day 1 Student Starting State: 9 Redacted, 6 Tampered, 24 Flows Prepopulated, 13 Withheld.",
    }
    return out, stats


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Generate KYE Day 1 student state from master.")
    ap.add_argument("--master", default="v2_reports/master.json")
    ap.add_argument("--out", default="v2_reports/partial_day1.json")
    args = ap.parse_args()

    master = json.load(open(args.master, encoding="utf-8"))
    out, stats = reduce_master_day1(master)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print("=== KYE Day 1 State Generation Complete ===")
    print(f"Master Devices       : {len(master['devices'])}")
    print(f"Student Devices      : {len(out['devices'])}")
    print(f"  Redacted Devices   : {stats['redacted_devices_dropped']} (Part 1 - 18 pts)")
    print(f"  Tampered Devices   : {stats['tampered_devices_modified']} (Part 3 - 18 pts)")
    print(f"  Scan-only Dropped  : {stats['scan_only_dropped']}")
    print(f"Master Dataflows     : {len(master['dataflows'])}")
    print(f"Student Dataflows    : {stats['dataflows_kept']} prepopulated")
    print(f"  Withheld Dataflows : {stats['dataflows_withheld']} (Part 2 - 39 pts)")
    print(f"Output File          : {args.out}")


if __name__ == "__main__":
    main()
