"""Scoring Engine for KYE Day 1 NetBox Challenge.

Evaluates a live NetBox instance (Delta or Omega) against master answer key.
Total Points: 75
  - Corrected Data    : 18 pts (6 tampered devices * 3 pts)
  - Missing Entries   : 18 pts (9 redacted devices * 2 pts: 1 pt for IP, 1 pt for bound device)
  - Missing DataFlow  : 39 pts (13 withheld flows * 3 pts: 1 pt for flow, 1 pt for src IP, 1 pt for dst IP)
"""
from __future__ import annotations

import re
from typing import Dict, Any, List, Optional
from .connection import get_connection, NetBoxConn

REDACTED_DEVICES = {
    "database": {
        "ip": "10.15.15.10",
        "aliases": ["database", "corp-db", "dmz-database", "mysql", "db", "corp_db", "dmz_db"],
    },
    "database-asc": {
        "ip": "172.16.220.17",
        "aliases": ["database-asc", "asc-database", "db-asc", "corp-db-asc", "database_asc", "asc_database"],
    },
    "database-acs": {
        "ip": "10.5.5.153",
        "aliases": ["database-acs", "acs-database", "pcs-db-acs", "db-acs", "database_acs", "acs_database"],
    },
    "database-acd": {
        "ip": "10.5.5.117",
        "aliases": ["database-acd", "acd-database", "pcs-db-acd", "db-acd", "database_acd", "acd_database"],
    },
    "internal-ftp": {
        "ip": "172.16.220.199",
        "aliases": ["internal-ftp", "ftp", "ftp-server", "corp-ftp", "internal_ftp", "corp_ftp"],
    },
    "acd-plc": {
        "ip": "192.168.32.3",
        "aliases": ["acd-plc", "cpe330", "acd-cpe330", "ge-plc", "acd_plc", "rx3i"],
    },
    "asc-l55-plc": {
        "ip": "192.168.0.6",
        "aliases": ["asc-l55-plc", "l55", "asc-l55", "controllogix-l55", "asc_l55_plc", "asc_l55"],
    },
    "apl-rtu-2": {
        "ip": "192.168.32.5",
        "aliases": ["apl-rtu-2", "rtu-2", "apl-rtu2", "s7-1200", "apl_rtu_2", "rtu2"],
    },
    "sign-asc": {
        "ip": "192.168.0.155",
        "aliases": ["sign-asc", "delta-sign", "modbus-sign-1", "plant-sign", "sign", "sign_asc", "delta_sign"],
    },
}

TAMPERED_DEVICES = {
    "user-1": {"real_ip": "172.16.220.181", "wrong_ip": "172.16.220.71"},
    "finance-1": {"real_ip": "172.16.220.150", "wrong_ip": "172.16.220.72"},
    "mail": {"real_ip": "172.16.220.3", "wrong_ip": "172.16.220.73"},
    "ews-1": {"real_ip": "192.168.0.51", "wrong_ip": "192.168.0.74"},
    "hmi-acs": {"real_ip": "192.168.32.9", "wrong_ip": "192.168.32.75"},
    "hmi-acd": {"real_ip": "192.168.32.10", "wrong_ip": "192.168.32.76"},
}

TARGET_FLOWS = [
    {"app": "ACD", "name": "ACD PLC to Process Overview HMI", "src": "acd-plc", "dst": "indusoft-overview", "src_ip": "192.168.32.3", "dst_ip": "192.168.0.244", "port": 18245, "proto": "GE-SRTP"},
    {"app": "ACS", "name": "AP&L RTU to Process Overview HMI", "src": "apl-rtu", "dst": "indusoft-overview", "src_ip": "192.168.1.40", "dst_ip": "192.168.0.244", "port": 502, "proto": "Modbus TCP"},
    {"app": "ACS", "name": "ACS S7-1515 to Process Overview HMI", "src": "acs-s7-1500-plc", "dst": "indusoft-overview", "src_ip": "192.168.32.12", "dst_ip": "192.168.0.244", "port": 102, "proto": "S7comm"},
    {"app": "ACS", "name": "ACS S7-1515 to syslog", "src": "acs-s7-1500-plc", "dst": "syslog", "src_ip": "192.168.32.12", "dst_ip": "172.16.220.100", "port": 514, "proto": "syslog"},
    {"app": "ACS", "name": "AP&L RTU 2 to Breaker Panel", "src": "apl-rtu-2", "dst": "apl-breaker-panel", "src_ip": "192.168.32.5", "dst_ip": "192.168.1.200", "port": 20000, "proto": "DNP3"},
    {"app": "ASC", "name": "HMI-ACS to ASC L81 (CIP fails)", "src": "hmi-acs", "dst": "asc-l81-plc", "src_ip": "192.168.32.9", "dst_ip": "192.168.0.3", "port": 2222, "proto": "EtherNet/IP I/O"},
    {"app": "ASC", "name": "ASC L81 to syslog", "src": "asc-l81-plc", "dst": "syslog", "src_ip": "192.168.0.3", "dst_ip": "172.16.220.100", "port": 514, "proto": "syslog"},
    {"app": "ASC", "name": "ASC L81 to L55 (CIP)", "src": "asc-l81-plc", "dst": "asc-l55-plc", "src_ip": "192.168.0.3", "dst_ip": "192.168.0.6", "port": 44818, "proto": "EtherNet/IP"},
    {"app": "ASC", "name": "ASC L55 to Process Overview HMI", "src": "asc-l55-plc", "dst": "indusoft-overview", "src_ip": "192.168.0.6", "dst_ip": "192.168.0.244", "port": 44818, "proto": "EtherNet/IP"},
    {"app": "ASC", "name": "ASC L81 to PCS historian (rssql)", "src": "asc-l81-plc", "dst": "rssql-asc", "src_ip": "192.168.0.3", "dst_ip": "10.5.5.35", "port": 44818, "proto": "EtherNet/IP"},
    {"app": "ASC", "name": "ASC L81 to RSView32 HMI", "src": "asc-l81-plc", "dst": "hmi-asc", "src_ip": "192.168.0.3", "dst_ip": "192.168.0.97", "port": 44818, "proto": "EtherNet/IP"},
    {"app": "ASC", "name": "ASC Remote I/O to L81", "src": "asc-remote-io-eip", "dst": "asc-l81-plc", "src_ip": "192.168.32.105", "dst_ip": "192.168.0.3", "port": 2222, "proto": "EtherNet/IP I/O"},
    {"app": "ASC", "name": "rssql-asc to CORP database-asc", "src": "rssql-asc", "dst": "database-asc", "src_ip": "10.5.5.35", "dst_ip": "172.16.220.17", "port": 1433, "proto": "MS-SQL"},
]


def _normalize(s: str) -> str:
    """Normalize string for adaptive/fuzzy matching: lower, alphanumeric only."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class NetBoxScorer:
    def __init__(
        self,
        conn: Optional[NetBoxConn] = None,
        env_file: Optional[str] = None,
        team: Optional[str] = None,
        localhost: bool = False,
    ):
        self.conn = conn or get_connection(env_file=env_file, team=team, localhost=localhost)

    def _fetch_all(self, path: str) -> List[dict]:
        out = []
        url = path + ("&" if "?" in path else "?") + "limit=500"
        while url:
            r = self.conn.get(url)
            if r.status_code != 200:
                break
            j = r.json()
            if not isinstance(j, dict):
                break
            out.extend(j.get("results", []))
            url = j.get("next")
        return out

    def score(self) -> Dict[str, Any]:
        """Calculates full score and returns structured audit results."""
        # 1. Fetch live NetBox state
        raw_ips = self._fetch_all("ipam/ip-addresses/")
        raw_devices = self._fetch_all("dcim/devices/")
        raw_interfaces = self._fetch_all("dcim/interfaces/")
        raw_flows = self._fetch_all("plugins/data-flows/dataflows/")
        raw_aliases = self._fetch_all("plugins/data-flows/objectalias/")

        # Maps for quick lookup
        device_by_id = {d["id"]: d for d in raw_devices if "id" in d}
        iface_by_id = {i["id"]: i for i in raw_interfaces if "id" in i}

        # IP address string -> IP object
        ip_map = {}
        for ip_obj in raw_ips:
            addr_str = ip_obj.get("address", "").split("/")[0]
            if addr_str:
                ip_map[addr_str] = ip_obj

        # Build alias -> list of IPs and names mapping
        alias_ip_map = {}
        alias_name_map = {}
        for al in raw_aliases:
            al_id = al.get("id")
            alias_name_map[al_id] = al.get("name", "")
            ips = []
            for ip_ref in al.get("ip_addresses", []):
                ip_id = ip_ref.get("id") if isinstance(ip_ref, dict) else ip_ref
                matched_ip = next((x.get("address", "").split("/")[0] for x in raw_ips if x.get("id") == ip_id), None)
                if matched_ip:
                    ips.append(matched_ip)
            alias_ip_map[al_id] = ips

        # ----------------------------------------------------
        # Part 1: Missing Entries (9 Redacted Devices * 2 pts = 18 pts)
        # ----------------------------------------------------
        part1_points = 0
        part1_details = []

        for canonical_name, spec in REDACTED_DEVICES.items():
            target_ip = spec["ip"]
            aliases_norm = [_normalize(a) for a in spec["aliases"]]

            ip_found = target_ip in ip_map
            device_bound = False
            found_dev_name = None

            if ip_found:
                ip_obj = ip_map[target_ip]
                # Check assigned object
                assigned_type = ip_obj.get("assigned_object_type")
                assigned_id = ip_obj.get("assigned_object_id")

                dev_obj = None
                if assigned_type == "dcim.interface" and assigned_id in iface_by_id:
                    dev_ref = iface_by_id[assigned_id].get("device")
                    dev_id = dev_ref.get("id") if isinstance(dev_ref, dict) else dev_ref
                    dev_obj = device_by_id.get(dev_id)

                # Alternatively, check device primary_ip4
                if not dev_obj:
                    for d in raw_devices:
                        p_ip = d.get("primary_ip4")
                        p_id = p_ip.get("id") if isinstance(p_ip, dict) else p_ip
                        if p_id == ip_obj.get("id"):
                            dev_obj = d
                            break

                if dev_obj:
                    c_name_norm = _normalize(dev_obj.get("name", ""))
                    if any(a in c_name_norm or c_name_norm in a for a in aliases_norm):
                        device_bound = True
                        found_dev_name = dev_obj.get("name")

            pts = (1 if ip_found else 0) + (1 if device_bound else 0)
            part1_points += pts
            part1_details.append({
                "canonical": canonical_name,
                "ip": target_ip,
                "ip_found": ip_found,
                "device_bound": device_bound,
                "found_dev_name": found_dev_name,
                "points": pts,
            })

        # ----------------------------------------------------
        # Part 2: Missing DataFlow (13 Flows * 3 pts = 39 pts)
        # ----------------------------------------------------
        part2_points = 0
        part2_details = []

        for tf in TARGET_FLOWS:
            t_port = tf["port"]
            t_src_ip = tf["src_ip"]
            t_dst_ip = tf["dst_ip"]
            t_src_name = _normalize(tf.get("src", ""))
            t_dst_name = _normalize(tf.get("dst", ""))
            t_flow_name = _normalize(tf.get("name", ""))

            flow_record_found = False
            src_ip_ok = False
            dst_ip_ok = False

            for df in raw_flows:
                # check destination port match if specified
                d_ports = df.get("destination_ports") or []
                if t_port and t_port not in d_ports:
                    continue

                # Check endpoints via object aliases
                src_alias_ids = [s.get("id") if isinstance(s, dict) else s for s in (df.get("sources") or [])]
                dst_alias_ids = [d.get("id") if isinstance(d, dict) else d for d in (df.get("destinations") or [])]

                src_ips = [ip for aid in src_alias_ids for ip in alias_ip_map.get(aid, [])]
                dst_ips = [ip for aid in dst_alias_ids for ip in alias_ip_map.get(aid, [])]
                src_names = [_normalize(alias_name_map.get(aid, "")) for aid in src_alias_ids]
                dst_names = [_normalize(alias_name_map.get(aid, "")) for aid in dst_alias_ids]

                cur_name = _normalize(df.get("name", ""))
                name_match = (cur_name == t_flow_name) or (t_flow_name in cur_name) or (cur_name in t_flow_name)

                src_match = (t_src_ip in src_ips) or (t_src_name in src_names)
                dst_match = (t_dst_ip in dst_ips) or (t_dst_name in dst_names)

                # Flow is matched if both endpoints match OR (name matches and at least one endpoint matches)
                if (src_match and dst_match) or (name_match and (src_match or dst_match or not (src_alias_ids or dst_alias_ids))):
                    flow_record_found = True
                    if (t_src_ip in src_ips) or (t_src_name in src_names):
                        src_ip_ok = True
                    if (t_dst_ip in dst_ips) or (t_dst_name in dst_names):
                        dst_ip_ok = True
                    break

            pts = (1 if flow_record_found else 0) + (1 if src_ip_ok else 0) + (1 if dst_ip_ok else 0)
            part2_points += pts
            part2_details.append({
                "name": tf["name"],
                "app": tf["app"],
                "port": t_port,
                "src_ip": t_src_ip,
                "dst_ip": t_dst_ip,
                "flow_found": flow_record_found,
                "src_ok": src_ip_ok,
                "dst_ok": dst_ip_ok,
                "points": pts,
            })

        # ----------------------------------------------------
        # Part 3: Corrected Data (6 Tampered Devices * 3 pts = 18 pts)
        # ----------------------------------------------------
        part3_points = 0
        part3_details = []

        for dev_name, spec in TAMPERED_DEVICES.items():
            real_ip = spec["real_ip"]
            wrong_ip = spec["wrong_ip"]

            is_corrected = False
            current_ip = None

            matched_dev = next((d for d in raw_devices if _normalize(d.get("name", "")) == _normalize(dev_name)), None)
            if matched_dev:
                p_ip = matched_dev.get("primary_ip4")
                if p_ip:
                    current_ip = p_ip.get("address", "").split("/")[0]
                else:
                    # check interfaces for device
                    d_ifaces = [i for i in raw_interfaces if (i.get("device") or {}).get("id") == matched_dev.get("id")]
                    for ifc in d_ifaces:
                        for ip_obj in raw_ips:
                            if ip_obj.get("assigned_object_id") == ifc.get("id"):
                                current_ip = ip_obj.get("address", "").split("/")[0]
                                break
                if current_ip == real_ip:
                    is_corrected = True

            pts = 3 if is_corrected else 0
            part3_points += pts
            part3_details.append({
                "device": dev_name,
                "real_ip": real_ip,
                "wrong_ip": wrong_ip,
                "current_ip": current_ip,
                "is_corrected": is_corrected,
                "points": pts,
            })

        total_score = part1_points + part2_points + part3_points
        return {
            "total_score": total_score,
            "max_score": 75,
            "percentage": round((total_score / 75.0) * 100, 1),
            "categories": {
                "corrected_data": {
                    "points": part3_points,
                    "max": 18,
                    "count": sum(1 for d in part3_details if d["is_corrected"]),
                    "total": 6,
                    "details": part3_details,
                },
                "missing_entries": {
                    "points": part1_points,
                    "max": 18,
                    "count": sum(1 for d in part1_details if d["device_bound"]),
                    "total": 9,
                    "details": part1_details,
                },
                "missing_dataflow": {
                    "points": part2_points,
                    "max": 39,
                    "count": sum(1 for d in part2_details if d["points"] == 3),
                    "total": 13,
                    "details": part2_details,
                },
            },
        }

