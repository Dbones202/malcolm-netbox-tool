"""Parse nmap XML scans into normalized host facts (stdlib only).

This is the nmap-derived layer of the v2 pipeline: open ports -> services,
MAC + vendor -> interface MACs, hostnames and OS guesses. Hosts are merged by
IP across multiple scan files (a host can appear in several scans), unioning
their open ports and filling in whichever scan has richer detail.

Pure standard library (xml.etree) so it runs anywhere, including air-gapped.
"""
from __future__ import annotations

import glob
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

# Curated, meaningful ports (ICS protocols + notable IT/mgmt). Used to label
# and, later, to decide which open ports become NetBox services. Ephemeral
# RPC (49152+) is intentionally excluded from the "curated" view.
ICS_PORTS = {
    502: "Modbus TCP", 44818: "EtherNet/IP (CIP)", 2222: "EtherNet/IP I/O",
    102: "S7comm (ISO-TSAP)", 34964: "PROFINET", 20000: "DNP3",
    18245: "GE-SRTP", 1962: "PCWorx", 9600: "OMRON FINS",
}
MGMT_PORTS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 80: "HTTP",
    88: "Kerberos", 110: "POP3", 111: "rpcbind", 135: "MSRPC", 139: "NetBIOS-SSN",
    143: "IMAP", 389: "LDAP", 443: "HTTPS", 445: "SMB", 464: "kpasswd",
    465: "SMTPS", 587: "SMTP-submission", 593: "RPC-HTTP", 636: "LDAPS",
    993: "IMAPS", 995: "POP3S", 1433: "MS-SQL", 3000: "firewall-mgmt",
    3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL", 8000: "HTTP-alt",
    8080: "HTTP-proxy", 8443: "HTTPS-alt", 9100: "JetDirect",
}
CURATED = {**MGMT_PORTS, **ICS_PORTS}


def is_curated(port: int) -> bool:
    return port in CURATED


@dataclass
class PortFact:
    port: int
    protocol: str
    state: str
    service: str = ""
    product: str = ""
    version: str = ""
    extrainfo: str = ""


@dataclass
class HostFact:
    ip: str
    mac: Optional[str] = None
    mac_vendor: Optional[str] = None
    hostnames: List[str] = field(default_factory=list)
    os_guess: Optional[str] = None
    scan_sources: List[str] = field(default_factory=list)
    ports: Dict[int, PortFact] = field(default_factory=dict)

    def open_curated(self) -> List[PortFact]:
        return [p for p in self.ports.values() if p.state == "open" and is_curated(p.port)]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ports"] = [asdict(p) for p in sorted(self.ports.values(), key=lambda x: x.port)]
        d["curated_services"] = [
            {"port": p.port, "protocol": p.protocol, "label": CURATED.get(p.port, p.service or "")}
            for p in sorted(self.open_curated(), key=lambda x: x.port)
        ]
        return d


def _text(el, default=""):
    return el if isinstance(el, str) else (el.get(default) if el is not None else default)


def parse_file(path: str, hosts: Dict[str, HostFact]) -> None:
    source = os.path.basename(path)
    root = ET.parse(path).getroot()
    for host in root.findall("host"):
        status = host.find("status")
        if status is not None and status.get("state") != "up":
            continue

        ipv4 = mac = mac_vendor = None
        for addr in host.findall("address"):
            at = addr.get("addrtype")
            if at == "ipv4":
                ipv4 = addr.get("addr")
            elif at == "mac":
                mac = addr.get("addr")
                mac_vendor = addr.get("vendor") or None
        if not ipv4:
            continue

        hf = hosts.get(ipv4)
        if hf is None:
            hf = HostFact(ip=ipv4)
            hosts[ipv4] = hf
        if source not in hf.scan_sources:
            hf.scan_sources.append(source)
        if mac and not hf.mac:
            hf.mac = mac
            hf.mac_vendor = mac_vendor

        for hn in host.findall("./hostnames/hostname"):
            name = hn.get("name")
            if name and name not in hf.hostnames:
                hf.hostnames.append(name)

        osmatch = host.find("./os/osmatch")
        if osmatch is not None and not hf.os_guess:
            hf.os_guess = osmatch.get("name")

        for port in host.findall("./ports/port"):
            pid = int(port.get("portid"))
            proto = port.get("protocol", "tcp")
            st = port.find("state")
            state = st.get("state") if st is not None else "unknown"
            svc = port.find("service")
            pf = PortFact(
                port=pid, protocol=proto, state=state,
                service=(svc.get("name") if svc is not None else "") or "",
                product=(svc.get("product") if svc is not None else "") or "",
                version=(svc.get("version") if svc is not None else "") or "",
                extrainfo=(svc.get("extrainfo") if svc is not None else "") or "",
            )
            # Prefer an existing 'open' record; otherwise take the richer one.
            prev = hf.ports.get(pid)
            if prev is None or (prev.state != "open" and state == "open") or (not prev.product and pf.product):
                hf.ports[pid] = pf


def parse_dir(pattern: str) -> Dict[str, HostFact]:
    hosts: Dict[str, HostFact] = {}
    for path in sorted(glob.glob(pattern)):
        parse_file(path, hosts)
    return hosts


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Parse nmap XML scans -> normalized host facts JSON.")
    ap.add_argument("inputs", nargs="+", help="nmap .xml files or globs")
    ap.add_argument("--out", default="v2_reports/nmap_facts.json")
    args = ap.parse_args()

    hosts: Dict[str, HostFact] = {}
    files = []
    for patt in args.inputs:
        files.extend(sorted(glob.glob(patt)) or ([patt] if os.path.exists(patt) else []))
    for f in files:
        parse_file(f, hosts)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    ordered = dict(sorted(hosts.items(), key=lambda kv: tuple(int(x) for x in kv[0].split("."))))
    out = {ip: hf.to_dict() for ip, hf in ordered.items()}
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)

    # Console summary
    print(f"Parsed {len(files)} scan file(s) -> {len(hosts)} unique hosts up\n")
    print(f"{'IP':<16}{'MAC vendor':<22}{'host/OS':<26}curated open services")
    print("-" * 100)
    for ip, hf in ordered.items():
        label = (hf.hostnames[0] if hf.hostnames else "") or (hf.os_guess or "")
        svcs = ", ".join(f"{p.port}/{p.protocol}:{CURATED.get(p.port,'')}" for p in sorted(hf.open_curated(), key=lambda x: x.port))
        print(f"{ip:<16}{(hf.mac_vendor or ''):<22}{label[:25]:<26}{svcs}")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
