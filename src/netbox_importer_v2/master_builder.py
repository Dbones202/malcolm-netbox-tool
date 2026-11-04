"""Assemble the complete-picture master from nmap facts + the knowledge layer.

Inputs:
  * nmap_facts.json          (from nmap_parser.py)  -- discovered: MACs, open ports/services
  * knowledge/acme_knowledge.json                   -- human intel: zones, identity, roles,
                                                       types, multi-homing, owners, dataflows, coverage

Output:
  * master.json  -- the single source of truth that drives seed / seed-partial / score.

Merge rules:
  - A device's canonical name = annotation.name, else nmap hostname stem, else IP.
  - merge_ips fold other *scanned* IPs into one multi-NIC device (services+MAC per NIC).
  - extra_ips add additional (unscanned) NIC IPs.
  - Services come from curated open ports (nmap) AND from dataflow destinations
    (so a PLC's S7comm/EtherNet/IP shows up even when the -F scan missed it),
    each tagged with its source ('nmap' or 'dataflow').
  - Zone is resolved by longest-prefix match on the primary IP.
Pure standard library.
"""
from __future__ import annotations

import ipaddress
import json
import os
from collections import defaultdict

try:
    from .malcolm_services import malcolm_service_name
except ImportError:  # allow running as a plain script (python3 src/.../master_builder.py)
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from malcolm_services import malcolm_service_name
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE = os.path.join(HERE, "knowledge", "acme_knowledge.json")


def stem(hostname: str) -> str:
    return hostname.split(".")[0] if hostname else ""


def good_stem(hostnames):
    """First hostname stem that is a real name (has letters), else None.

    Rejects generic reverse-DNS like '10.15.15-240' or '172-16-220-188'."""
    for h in hostnames or []:
        st = stem(h)
        if st and any(c.isalpha() for c in st):
            return st
    return None


def infer_role(name: str, vendor: Optional[str], ports: List[int], hostnames: List[str]) -> str:
    n = name.lower()
    hoststr = " ".join(hostnames).lower()
    for key, role in [("firewall", "Firewall"), ("mail", "Mail-Server"), ("internal-dns", "DNS-Server"),
                      ("dns", "DNS-Server"), ("ad", "Domain-Controller"), ("file", "File-Server"),
                      ("ftp", "FTP-Server"), ("www", "Web-Server"), ("database", "Database"),
                      ("rssql", "Database"), ("hmi", "HMI"), ("ews", "EWS")]:
        if n.startswith(key) or key in hoststr:
            return role
    if any(n.startswith(p) for p in ("finance", "mgmt", "sales", "user", "hr")):
        return "Workstation"
    v = (vendor or "").lower()
    if "rockwell" in v or "siemens" in v or "intelligent platforms" in v:
        return "PLC"
    if "turck" in v:
        return "Remote-IO"
    if "facts engineering" in v:
        return "Network-Display"
    return "Host"


class ZoneResolver:
    def __init__(self, prefixes):
        self.nets = []
        for p in prefixes:
            try:
                self.nets.append((ipaddress.ip_network(p["prefix"]), p))
            except ValueError:
                pass
        self.nets.sort(key=lambda t: t[0].prefixlen, reverse=True)  # longest match first

    def resolve(self, ip: str):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return None, None
        for net, p in self.nets:
            if addr in net:
                return p.get("zone"), net.prefixlen
        return None, None


def build():
    know = json.load(open(KNOWLEDGE))
    facts_path = "v2_reports/nmap_facts.json"
    facts = json.load(open(facts_path)) if os.path.exists(facts_path) else {}

    zr = ZoneResolver(know["prefixes"])
    ann = know["annotations"]
    inv = know["inventory"]
    cov_fleet = set(know["coverage"]["fleet_agent"])
    cov_malcolm = set(know["coverage"]["malcolm_syslog"])

    merged_ips = set()
    for a in ann.values():
        merged_ips.update(a.get("merge_ips", []))

    devices: Dict[str, dict] = {}
    name_by_ip: Dict[str, str] = {}

    def curated_services(host):
        out = []
        for s in host.get("curated_services", []):
            nm = malcolm_service_name(s["port"], s["protocol"]) or s["label"] or str(s.get("port"))
            out.append({"name": nm, "protocol": s["protocol"],
                        "ports": [s["port"]], "source": "nmap"})
        return out

    def add_interface(dev, ip, mac, zr):
        _, plen = zr.resolve(ip)
        cidr = f"{ip}/{plen}" if plen else ip
        idx = len(dev["interfaces"])
        dev["interfaces"].append({
            "name": f"eth{idx}", "ips": [cidr], "mac": mac,
            "primary": idx == 0,
        })

    # ---- 1. scanned hosts ----
    for ip, host in facts.items():
        if ip in merged_ips:
            continue
        a = ann.get(ip, {})
        name = a.get("name") or good_stem(host.get("hostnames", [])) or ("host-" + ip.replace(".", "-"))
        name_by_ip[ip] = name
        zone, _ = zr.resolve(ip)
        open_ports = [p["port"] for p in host.get("curated_services", [])]
        role = a.get("role") or infer_role(name, host.get("mac_vendor"), open_ports, host.get("hostnames", []))
        dev = {
            "name": name, "role": role, "zone": zone,
            "manufacturer": a.get("mfr") or host.get("mac_vendor"),
            "model": a.get("model"),
            "software": a.get("software"),
            "interfaces": [], "services": [], "tags": [], "notes": a.get("notes", ""),
            "hostnames": host.get("hostnames", []), "_ann": bool(a), "platform": a.get("platform"),
        }
        add_interface(dev, ip, host.get("mac"), zr)
        dev["services"].extend(curated_services(host))
        # fold merged (multi-NIC scanned) IPs
        for mip in a.get("merge_ips", []):
            mh = facts.get(mip)
            add_interface(dev, mip, mh.get("mac") if mh else None, zr)
            if mh:
                dev["services"].extend(curated_services(mh))
            name_by_ip[mip] = name
        # extra (unscanned) NIC IPs
        for eip in a.get("extra_ips", []):
            add_interface(dev, eip, None, zr)
            name_by_ip[eip] = name
        # owner/os from inventory
        if name in inv:
            dev["owner"] = inv[name]
            dev["platform"] = inv[name].get("os")
        devices[name] = dev

    # ---- 1b. annotation-only devices (primary IP never scanned / host was down) ----
    for ip, a in ann.items():
        if ip in facts or ip in merged_ips:
            continue
        name = a.get("name") or ip
        if name in devices:
            continue
        zone, _ = zr.resolve(ip)
        dev = {
            "name": name, "role": a.get("role") or "Host", "zone": zone,
            "manufacturer": a.get("mfr"), "model": a.get("model"), "software": a.get("software"),
            "interfaces": [], "services": [], "tags": [], "notes": a.get("notes", ""),
            "provenance": "knowledge", "platform": a.get("platform"),
        }
        add_interface(dev, ip, None, zr)
        name_by_ip[ip] = name
        for eip in a.get("extra_ips", []):
            add_interface(dev, eip, None, zr)
            name_by_ip[eip] = name
        if name in inv:
            dev["owner"] = inv[name]
        devices[name] = dev

    # ---- 2. extra (unscanned) devices ----
    for ed in know["extra_devices"]:
        dev = {
            "name": ed["name"], "role": ed.get("role", "Host"), "zone": ed.get("zone"),
            "manufacturer": ed.get("mfr"), "model": ed.get("model"), "software": ed.get("software"),
            "interfaces": [], "services": [], "tags": [], "notes": ed.get("notes", ""),
            "provenance": "knowledge", "platform": ed.get("platform"),
        }
        for i, iface in enumerate(ed.get("interfaces", [])):
            dev["interfaces"].append({"name": iface.get("name", f"eth{i}"), "ips": iface["ips"],
                                      "mac": iface.get("mac"), "primary": iface.get("primary", i == 0)})
            for cidr in iface["ips"]:
                name_by_ip[cidr.split("/")[0]] = ed["name"]
        if ed["name"] in inv:
            dev["owner"] = inv[ed["name"]]
            dev["platform"] = inv[ed["name"]].get("os")
        devices[ed["name"]] = dev

    # ---- 3. services from dataflows (dst listens) + resolved flows ----
    resolved_flows, unresolved = [], []
    for f in know["dataflows"]:
        src, dst = f["src"], f["dst"]
        ok = src in devices  # dst may be a non-device sink (syslog, breaker panel)
        (resolved_flows if ok else unresolved).append(f)
        if dst in devices and f.get("port"):
            svcs = devices[dst]["services"]
            if not any(f["port"] in s["ports"] for s in svcs):
                nm = malcolm_service_name(f["port"], "tcp") or f["protocol"]
                svcs.append({"name": nm, "protocol": "tcp", "ports": [f["port"]], "source": "dataflow"})

    # ---- 4. SIEM coverage (custom field only; no tags) ----
    for dev in devices.values():
        dev_ips = {ip.split("/")[0] for iface in dev["interfaces"] for ip in iface["ips"]}
        if dev_ips & cov_fleet:
            dev["siem"] = "Security Onion"
        if dev_ips & cov_malcolm:
            dev["siem"] = "Malcolm"

    # ---- 3b. rename NICs per annotation iface_names (ip -> name) ----
    iface_name_by_ip = {}
    for a in ann.values():
        for ip, nm in (a.get("iface_names") or {}).items():
            iface_name_by_ip[ip] = nm
    for dev in devices.values():
        for nic in dev["interfaces"]:
            bare = nic["ips"][0].split("/")[0] if nic["ips"] else None
            if bare in iface_name_by_ip:
                nic["name"] = iface_name_by_ip[bare]

    # ---- 4a. provenance: knowledge (given) vs scan-only (discoverable) ----
    flow_names = set()
    for f in resolved_flows:
        flow_names.update([f["src"], f["dst"]])
    extra_names = {ed["name"] for ed in know["extra_devices"]}
    for name, dev in devices.items():
        if dev.get("provenance"):
            dev.pop("_ann", None)
            continue
        named = any(any(c.isalpha() for c in stem(h)) for h in dev.get("hostnames", []))
        known = dev.pop("_ann", False) or name in inv or name in extra_names or name in flow_names or named
        dev["provenance"] = "knowledge" if known else "scan-only"

    # ---- 4b. dedupe services per device by (protocol, ports) ----
    for dev in devices.values():
        merged = {}
        order = []
        for svc in dev["services"]:
            key = (svc["name"], svc["protocol"])
            if key not in merged:
                merged[key] = {"name": svc["name"], "protocol": svc["protocol"],
                               "ports": list(svc["ports"]), "source": svc["source"]}
                order.append(key)
            else:
                for pt in svc["ports"]:
                    if pt not in merged[key]["ports"]:
                        merged[key]["ports"].append(pt)
                if svc["source"] == "nmap":
                    merged[key]["source"] = "nmap"
        for k in order:
            merged[k]["ports"].sort()
        dev["services"] = [merged[k] for k in order]

    # ---- 5. catalogs ----
    manus = sorted({d["manufacturer"] for d in devices.values() if d.get("manufacturer")})
    dtypes = sorted({(d.get("manufacturer") or "Unknown", d["model"]) for d in devices.values() if d.get("model")})
    roles = sorted({d["role"] for d in devices.values()})

    # telemetry / log-source summary per device (from the coverage report)
    tele_path = os.path.join(HERE, "knowledge", "telemetry.json")
    if os.path.exists(tele_path):
        tele = json.load(open(tele_path))
        for _n, _dev in devices.items():
            if _n in tele:
                _dev["telemetry"] = tele[_n]

    # contacts from device owners (unique person -> the devices they use)
    contacts = {}
    for d in devices.values():
        o = d.get("owner")
        if not o:
            continue
        key = o.get("email") or o.get("user") or o.get("full_name")
        c = contacts.setdefault(key, {"name": o.get("full_name") or o.get("user") or key,
                                      "email": o.get("email", ""), "login": o.get("user", ""),
                                      "devices": []})
        c["devices"].append(d["name"])
    contacts_list = [contacts[k] for k in sorted(contacts, key=lambda e: contacts[e]["name"])]

    master = {
        "meta": {"name": "ACME Chemical ICS Range", "course": "ICS 311 DtA",
                 "source": "diagram v2.5 / dataflows v1.5 / nmap Jun-2025 / inventory+coverage sheets",
                 "site": know["site"]},
        "prefixes": know["prefixes"],
        "device_roles": roles,
        "manufacturers": manus,
        "device_types": [{"manufacturer": m, "model": mo} for (m, mo) in dtypes],
        "devices": [devices[k] for k in sorted(devices)],
        "contacts": contacts_list,
        "dataflows": resolved_flows,
        "coverage_legend": {"security-onion-fleet": "Security Onion Fleet agent (endpoint)",
                            "malcolm-syslog": "Malcolm syslog/PCAP (network)"},
    }
    os.makedirs("v2_reports", exist_ok=True)
    json.dump(master, open("v2_reports/master.json", "w"), indent=2)

    # ---- summary ----
    by_zone = defaultdict(int); by_role = defaultdict(int)
    multihomed = []
    svc_total = 0
    for d in devices.values():
        by_zone[d["zone"]] += 1
        by_role[d["role"]] += 1
        svc_total += len(d["services"])
        if len(d["interfaces"]) > 1:
            ips = [ip for i in d["interfaces"] for ip in i["ips"]]
            multihomed.append((d["name"], ips))

    prov = defaultdict(int)
    for d in devices.values():
        prov[d.get("provenance","?")] += 1
    print(f"PROVENANCE: " + ", ".join(f"{k}={v}" for k,v in sorted(prov.items())))
    print(f"CONTACTS: {len(contacts_list)} people from device owners")
    print(f"MASTER: {len(devices)} devices | {svc_total} services | {len(resolved_flows)} flows | {len(manus)} mfrs | {len(dtypes)} device-types")
    print("\nBy zone:   " + ", ".join(f"{z}={n}" for z, n in sorted(by_zone.items(), key=lambda x:(x[0] or ''))))
    print("By role:   " + ", ".join(f"{r}={n}" for r, n in sorted(by_role.items())))
    print(f"\nMulti-homed devices ({len(multihomed)}):")
    for name, ips in sorted(multihomed):
        print(f"  {name:<18} {', '.join(ips)}")
    if unresolved:
        print(f"\n[!] {len(unresolved)} unresolved flow endpoints:")
        for f in unresolved:
            print(f"    {f['application']}: {f['src']} -> {f['dst']}")
    nozone = [d['name'] for d in devices.values() if not d['zone']]
    if nozone:
        print(f"\n[!] devices with no zone: {nozone}")
    print("\nWrote v2_reports/master.json")


if __name__ == "__main__":
    build()
