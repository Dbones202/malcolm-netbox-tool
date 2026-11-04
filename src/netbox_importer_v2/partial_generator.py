"""Derive a reduced 'student' environment from the master by subtraction.

Philosophy (per white cell): the master is the complete answer key; the student
start-state is the master minus whatever they're meant to discover/build. It's
always easier to remove than to add, so every student view is a profile of
removals applied to one master. The output is itself master-shaped, so the same
seeder pushes it and the same scorer grades against the full master.

Profiles (knobs are all subtractive):
  strip_mac             drop discovered MAC addresses from NICs (keep IPs)
  drop_service_sources  drop services whose 'source' is in this list (nmap/dataflow)
  drop_scan_only        drop devices whose provenance == 'scan-only' (students find them)
  drop_dataflows        drop all dataflow objects
  drop_coverage         drop 'seen-by:*' sensor-coverage tags
  drop_owner            drop workstation owner/user info
Pure standard library.
"""
from __future__ import annotations

import copy
import json
import os

PROFILES = {
    "day1": {
        "desc": "Day-1 student start: scaffold given, nmap-discovered layer removed.",
        "strip_mac": True, "drop_service_sources": ["nmap"], "drop_scan_only": True,
        "drop_dataflows": False, "drop_coverage": True, "drop_owner": False,
    },
    "skeleton": {
        "desc": "Bare scaffold: devices + IPs + zones + roles only.",
        "strip_mac": True, "drop_service_sources": ["nmap", "dataflow"], "drop_scan_only": True,
        "drop_dataflows": True, "drop_coverage": True, "drop_owner": True,
    },
    "full": {
        "desc": "No removals (identity transform; sanity check).",
        "strip_mac": False, "drop_service_sources": [], "drop_scan_only": False,
        "drop_dataflows": False, "drop_coverage": False, "drop_owner": False,
    },
}


def reduce_master(master: dict, prof: dict) -> tuple[dict, dict]:
    out = copy.deepcopy(master)
    drop_src = set(prof.get("drop_service_sources", []))
    stats = {"devices_dropped": 0, "macs_stripped": 0, "services_dropped": 0,
             "owners_dropped": 0, "coverage_tags_dropped": 0, "dataflows_dropped": 0}

    kept_devices = []
    for d in out["devices"]:
        if prof.get("drop_scan_only") and d.get("provenance") == "scan-only":
            stats["devices_dropped"] += 1
            continue
        if prof.get("strip_mac"):
            for nic in d["interfaces"]:
                if nic.get("mac"):
                    nic["mac"] = None
                    stats["macs_stripped"] += 1
        if drop_src:
            before = len(d["services"])
            d["services"] = [s for s in d["services"] if s.get("source") not in drop_src]
            stats["services_dropped"] += before - len(d["services"])
        if prof.get("drop_owner") and d.pop("owner", None) is not None:
            stats["owners_dropped"] += 1
        if prof.get("drop_coverage"):
            before = len(d.get("tags", []))
            d["tags"] = [t for t in d.get("tags", []) if not t.startswith("seen-by")]
            stats["coverage_tags_dropped"] += before - len(d["tags"])
        kept_devices.append(d)
    out["devices"] = kept_devices

    kept_names = {d["name"] for d in kept_devices}
    if prof.get("drop_dataflows"):
        stats["dataflows_dropped"] = len(out.get("dataflows", []))
        out["dataflows"] = []
    else:
        before = len(out.get("dataflows", []))
        out["dataflows"] = [f for f in out["dataflows"] if f["src"] in kept_names and f["dst"] in kept_names]
        stats["dataflows_dropped"] = before - len(out["dataflows"])

    out.setdefault("meta", {})["profile"] = {"name": prof.get("_name"), "desc": prof.get("desc")}
    return out, stats


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Reduce the master to a student start-state.")
    ap.add_argument("--profile", default="day1", choices=list(PROFILES))
    ap.add_argument("--master", default="v2_reports/master.json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    master = json.load(open(args.master))
    prof = dict(PROFILES[args.profile]); prof["_name"] = args.profile
    out, stats = reduce_master(master, prof)

    out_path = args.out or f"v2_reports/partial_{args.profile}.json"
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    json.dump(out, open(out_path, "w"), indent=2)

    svc_now = sum(len(d["services"]) for d in out["devices"])
    print(f"Profile '{args.profile}': {prof['desc']}")
    print(f"  master  : {len(master['devices'])} devices, "
          f"{sum(len(d['services']) for d in master['devices'])} services, {len(master['dataflows'])} flows")
    print(f"  student : {len(out['devices'])} devices, {svc_now} services, {len(out['dataflows'])} flows")
    print(f"  removed : {stats['devices_dropped']} scan-only devices, {stats['macs_stripped']} MACs, "
          f"{stats['services_dropped']} services, {stats['coverage_tags_dropped']} coverage tags, "
          f"{stats['owners_dropped']} owners, {stats['dataflows_dropped']} flows")
    print(f"  -> {out_path}  (this is what students must rebuild to reach 100%)")


if __name__ == "__main__":
    main()
