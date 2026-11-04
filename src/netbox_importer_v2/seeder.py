"""Seed / reset the NetBox instance from a master-shaped file.

Design:
  * Read-only PLAN by default; pass apply=True to write.
  * Idempotent upserts (get-or-create by natural key), so re-running is safe.
  * Everything created is tagged 'dta-v2' for clean, selective rollback.
  * First-class MACs (NetBox 4.2+): mac-address objects assigned to interfaces,
    then interface.primary_mac_address.
  * Dataflows via netbox_data_flows: applications + objectalias(per device IP) + dataflows.
  * Every action + API response is logged to v2_reports/seed_result.json.

Network calls run wherever this executes (i.e. on the Mac, which can reach the box).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .connection import get_connection, NetBoxConn

TAG_SLUG = "dta-v2"
TAG_NAME = "DtA v2"
SITE_DEFAULT = "Acme"

# device-type model fallback when the master has no explicit model
MODEL_FALLBACK = {"VMware": "VMware Virtual Machine", "Netgate": "pfSense Appliance"}
GENERIC_MFR = "Unknown"
GENERIC_MODEL = "Generic Device"


def _slug(s: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in (s or "").strip())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "na"


class Seeder:
    def __init__(self, conn: NetBoxConn, apply: bool = False):
        self.c = conn
        self.apply = apply
        self.actions: List[dict] = []
        self.errors: List[dict] = []
        self.cache: Dict[str, Any] = {}

    # ---- low-level ----
    def _get(self, path, **params):
        r = self.c.get(path, params=params)
        if r.status_code != 200:
            return None
        res = r.json()
        return res.get("results", res)

    def _all(self, path):
        """Return ALL objects at a path, following pagination (NetBox pages at 50)."""
        out = []
        url = path + ("&" if "?" in path else "?") + "limit=500"
        while url:
            r = self.c.get(url)
            if r.status_code != 200:
                break
            j = r.json()
            if not isinstance(j, dict):
                break
            out.extend(j.get("results", []))
            url = j.get("next")
        return out

    def get_one(self, path, **params):
        res = self._get(path, **params)
        if isinstance(res, list):
            return res[0] if res else None
        return None

    def create(self, path, data, label):
        if not self.apply:
            self.actions.append({"op": "CREATE", "path": path, "label": label, "data": data})
            return {"id": f"<new:{label}>", "_planned": True}
        r = self.c.session.post(self.c._url(path), json=data, timeout=90)
        if r.status_code in (200, 201):
            obj = r.json()
            self.actions.append({"op": "CREATED", "path": path, "label": label, "id": obj.get("id")})
            return obj
        self.errors.append({"op": "CREATE", "path": path, "label": label, "status": r.status_code,
                            "resp": r.text[:400], "data": data})
        return None

    def patch(self, path, obj_id, data, label):
        if not self.apply:
            self.actions.append({"op": "PATCH", "path": path, "label": label, "data": data})
            return True
        r = self.c.session.patch(self.c._url(f"{path}{obj_id}/"), json=data, timeout=90)
        if r.status_code in (200, 201):
            return True
        self.errors.append({"op": "PATCH", "path": path, "label": label, "status": r.status_code, "resp": r.text[:400]})
        return False

    def get_or_create(self, path, lookup: dict, create_data: dict, label: str):
        existing = self.get_one(path, **lookup)
        if existing:
            return existing, False
        return self.create(path, create_data, label), True

    # ---- taxonomy ----
    def ensure_tag(self):
        self.get_or_create("extras/tags/", {"slug": TAG_SLUG},
                           {"name": TAG_NAME, "slug": TAG_SLUG, "color": "2196f3"}, f"tag {TAG_NAME}")

    def ensure_named(self, path, name, extra=None, key="name"):
        ck = f"{path}:{name}"
        if ck in self.cache:
            return self.cache[ck]
        slug = (extra or {}).get("slug") or _slug(name)
        existing = self.get_one(path, slug=slug) or self.get_one(path, **{key: name})
        if existing:
            self.cache[ck] = existing
            return existing
        data = {key: name, "slug": slug}
        if extra:
            data.update(extra)
        obj = self.create(path, data, f"{path.split('/')[-2]} {name}")
        self.cache[ck] = obj
        return obj

    def ensure_device_type(self, manufacturer: Optional[str], model: Optional[str]):
        mfr_name = manufacturer or GENERIC_MFR
        if not model:
            model = MODEL_FALLBACK.get(mfr_name, GENERIC_MODEL)
        ck = f"dt:{mfr_name}/{model}"
        if ck in self.cache:
            return self.cache[ck]
        mfr = self.ensure_named("dcim/manufacturers/", mfr_name)
        data = {"model": model, "slug": _slug(f"{mfr_name}-{model}"), "manufacturer": self._id(mfr)}
        obj, _ = self.get_or_create("dcim/device-types/", {"model": model}, data, f"device-type {model}")
        self.cache[ck] = obj
        return obj

    @staticmethod
    def _id(obj):
        if isinstance(obj, dict):
            return obj.get("id")
        return obj

    # ---- main seed ----
    def seed(self, master: dict):
        self.ensure_tag()
        site = self.ensure_named("dcim/sites/", master.get("meta", {}).get("site", SITE_DEFAULT))
        site_id = self._id(site)

        # zones -> ipam roles (for prefixes) + collected for device tags
        zone_roles = {}
        for p in master.get("prefixes", []):
            z = p.get("zone")
            if z and z not in zone_roles:
                zone_roles[z] = self.ensure_named("ipam/roles/", z)

        # prefixes
        for p in master.get("prefixes", []):
            pfx = p["prefix"]
            existing = self.get_one("ipam/prefixes/", prefix=pfx)
            if existing:
                continue
            data = {"prefix": pfx, "status": "active", "description": p.get("zone", "") or "",
                    "tags": [{"slug": TAG_SLUG}]}
            if p.get("zone") in zone_roles:
                data["role"] = self._id(zone_roles[p["zone"]])
            if site_id:
                data["scope_type"] = "dcim.site"; data["scope_id"] = site_id
            obj = self.create("ipam/prefixes/", data, f"prefix {pfx}")
            if obj is None and site_id:  # retry without scope (older/newer field shape)
                data.pop("scope_type", None); data.pop("scope_id", None)
                self.create("ipam/prefixes/", data, f"prefix {pfx} (no-scope)")

        # devices
        for d in master.get("devices", []):
            self._seed_device(d, site_id)

        # contacts (device owners -> NetBox contacts + assignments)
        self._seed_contacts(master)

        # SIEM custom field (Security Onion / Malcolm)
        self._seed_siem(master)

        # Telemetry / log-sources custom field (from coverage report)
        self._seed_telemetry(master)

        # dataflows
        self._seed_dataflows(master)

    def _device_tags(self, d):
        tags = [{"slug": TAG_SLUG}]
        if d.get("zone"):
            z = self.ensure_named("extras/tags/", f"zone: {d['zone']}",
                                  {"slug": _slug('zone-' + d['zone']), "color": "9e9e9e"})
            tags.append({"slug": _slug('zone-' + d['zone'])})
        for t in d.get("tags", []):
            self.ensure_named("extras/tags/", t, {"slug": _slug(t), "color": "607d8b"})
            tags.append({"slug": _slug(t)})
        return tags

    def _seed_device(self, d, site_id):
        role = self.ensure_named("dcim/device-roles/", d.get("role", "Host"),
                                 {"color": "607d8b", "slug": _slug(d.get("role", "Host"))})
        dt = self.ensure_device_type(d.get("manufacturer"), d.get("model"))
        fqdn = (d.get("hostnames") or [None])[0]
        dev_data = {"name": d["name"], "role": self._id(role), "device_type": self._id(dt),
                    "site": site_id, "status": "active", "tags": self._device_tags(d),
                    "description": (d.get("software") or d.get("notes") or "")[:200]}
        if d.get("platform"):
            plat = self.ensure_named("dcim/platforms/", d["platform"])
            dev_data["platform"] = self._id(plat)
        dev, created = self.get_or_create("dcim/devices/", {"name": d["name"]}, dev_data, f"device {d['name']}")
        dev_id = self._id(dev)

        primary_ip_id = None
        for nic in d.get("interfaces", []):
            vm = (d.get("manufacturer") == "VMware")
            itype = "virtual" if vm else "1000base-t"
            iface_data = {"device": dev_id, "name": nic["name"], "type": itype, "tags": [{"slug": TAG_SLUG}]}
            iface, _ = self.get_or_create("dcim/interfaces/",
                                          {"device_id": dev_id, "name": nic["name"]} if self.apply else {"name": "__plan__"},
                                          iface_data, f"iface {d['name']}/{nic['name']}")
            iface_id = self._id(iface)
            # MAC (first-class) + primary_mac
            if nic.get("mac"):
                mac_obj = self.create("dcim/mac-addresses/",
                                      {"mac_address": nic["mac"], "assigned_object_type": "dcim.interface",
                                       "assigned_object_id": iface_id}, f"mac {nic['mac']}")
                if self.apply and mac_obj and iface_id:
                    self.patch("dcim/interfaces/", iface_id, {"primary_mac_address": self._id(mac_obj)},
                               f"primary_mac {d['name']}/{nic['name']}")
            # IPs
            for cidr in nic.get("ips", []):
                ip_data = {"address": cidr, "status": "active", "assigned_object_type": "dcim.interface",
                           "assigned_object_id": iface_id, "tags": [{"slug": TAG_SLUG}]}
                if nic.get("primary") and fqdn:
                    ip_data["dns_name"] = fqdn
                ip_obj, _ = self.get_or_create("ipam/ip-addresses/",
                                               {"address": cidr} if self.apply else {"address": "__plan__"},
                                               ip_data, f"ip {cidr} -> {d['name']}/{nic['name']}")
                if self.apply and isinstance(ip_obj, dict) and iface_id and not str(iface_id).startswith("<"):
                    if ip_obj.get("assigned_object_id") != iface_id:
                        self.patch("ipam/ip-addresses/", self._id(ip_obj),
                                   {"assigned_object_type": "dcim.interface", "assigned_object_id": iface_id},
                                   f"rebind {cidr} -> {d['name']}/{nic['name']}")
                if nic.get("primary") and primary_ip_id is None:
                    primary_ip_id = self._id(ip_obj)
        if self.apply and dev_id and primary_ip_id and not str(primary_ip_id).startswith("<"):
            self.patch("dcim/devices/", dev_id, {"primary_ip4": primary_ip_id}, f"primary_ip {d['name']}")

        # services
        for s in d.get("services", []):
            svc_data = {"name": s["name"], "protocol": s.get("protocol", "tcp"), "ports": s["ports"],
                        "parent_object_type": "dcim.device", "parent_object_id": dev_id, "tags": [{"slug": TAG_SLUG}]}
            self.get_or_create("ipam/services/",
                               {"device_id": dev_id, "name": s["name"]} if self.apply else {"name": "__plan__"},
                               svc_data, f"service {d['name']}:{s['name']}/{s['ports']}")

    def _seed_contacts(self, master):
        people = master.get("contacts") or []
        if not people:
            return
        role = self.ensure_named("tenancy/contact-roles/", "User", {"slug": "user"})
        for person in people:
            cdata = {"name": person["name"], "tags": [{"slug": TAG_SLUG}]}
            if person.get("email"):
                cdata["email"] = person["email"]
            if person.get("login"):
                cdata["title"] = person["login"]
            contact, _ = self.get_or_create("tenancy/contacts/", {"name": person["name"]},
                                            cdata, f"contact {person['name']}")
            cid = self._id(contact)
            for dev_name in person.get("devices", []):
                did = None
                if self.apply:
                    dev = self.get_one("dcim/devices/", name=dev_name)
                    did = self._id(dev) if dev else None
                adata = {"object_type": "dcim.device", "object_id": did, "contact": cid,
                         "role": self._id(role), "priority": "primary", "tags": [{"slug": TAG_SLUG}]}
                lookup = ({"contact_id": cid, "object_type": "dcim.device", "object_id": did}
                          if self.apply else {"object_id": "__plan__"})
                self.get_or_create("tenancy/contact-assignments/", lookup, adata,
                                   f"assign {person['name']} -> {dev_name}")

    def _ensure_choice_set_values(self, field, needed):
        """Make sure the select field's choice set carries every value in `needed`.
        Returns the choice-set id (creating/attaching one if the field has none)."""
        cs = field.get("choice_set")
        cs_id = cs.get("id") if isinstance(cs, dict) else cs
        if cs_id:
            r = self.c.get(f"extras/custom-field-choice-sets/{cs_id}/")
            cur = r.json() if r.status_code == 200 else {}
            norm, have = [], set()
            for ch in (cur.get("extra_choices") or []):
                if isinstance(ch, (list, tuple)):
                    norm.append([ch[0], ch[1] if len(ch) > 1 else ch[0]]); have.add(ch[0])
                else:
                    norm.append([ch, ch]); have.add(ch)
            added = [v for v in needed if v not in have]
            if added:
                norm.extend([v, v] for v in added)
                self.patch("extras/custom-field-choice-sets/", cs_id,
                           {"extra_choices": norm}, f"choice-set += {added}")
            return cs_id
        # select field with no choice set -> create one and attach it
        cs_new = self.create("extras/custom-field-choice-sets/",
                             {"name": "SIEM Platforms", "extra_choices": [[v, v] for v in needed]},
                             "choice-set SIEM Platforms")
        self.patch("extras/custom-fields/", self._id(field),
                   {"choice_set": self._id(cs_new)}, f"attach choice-set -> {field.get('name')}")
        return self._id(cs_new)

    def _seed_siem(self, master):
        """Two fields: a boolean 'Logging to SIEM' flag (Yes on covered hosts) and a
        'SIEM Platform' select carrying Security Onion / Malcolm."""
        targets = [(d["name"], d["siem"]) for d in master["devices"] if d.get("siem")]
        if not targets:
            return
        needed = sorted({v for _, v in targets})
        flag_field = plat_field = None
        if self.apply:
            for cf in self._all("extras/custom-fields/"):
                nm = str(cf.get("name", "")).lower()
                lb = str(cf.get("label", "")).lower()
                if "siem" not in nm and "siem" not in lb:
                    continue
                if "platform" in nm or "platform" in lb:
                    plat_field = cf
                else:
                    flag_field = cf
            # ensure the SIEM Platform select field + choice set
            if plat_field is None:
                cs = self.create("extras/custom-field-choice-sets/",
                                 {"name": "SIEM Platforms", "extra_choices": [[v, v] for v in needed]},
                                 "choice-set SIEM Platforms")
                plat_field = self.create("extras/custom-fields/",
                                         {"object_types": ["dcim.device"], "name": "siem_platform",
                                          "type": "select", "label": "SIEM Platform",
                                          "choice_set": self._id(cs),
                                          "description": "Which SIEM this host logs to (Security Onion / Malcolm)"},
                                         "custom-field siem_platform")
            else:
                pt = plat_field.get("type")
                pt = pt.get("value") if isinstance(pt, dict) else pt
                if pt in ("select", "multiselect"):
                    self._ensure_choice_set_values(plat_field, needed)
        flag_name = (flag_field or {}).get("name")
        ftype = (flag_field or {}).get("type")
        ftype = ftype.get("value") if isinstance(ftype, dict) else ftype
        plat_name = (plat_field or {}).get("name") or "siem_platform"
        for name, val in targets:
            cf = {plat_name: val}
            if flag_name:
                cf[flag_name] = True if ftype == "boolean" else val
            if not self.apply:
                self.actions.append({"op": "PATCH", "path": "dcim/devices/",
                                     "label": f"siem {name}={val}", "data": {"custom_fields": cf}})
                continue
            dev = self.get_one("dcim/devices/", name=name)
            if dev:
                self.patch("dcim/devices/", self._id(dev), {"custom_fields": cf}, f"siem {name}={val}")

    def _seed_telemetry(self, master):
        targets = [(d["name"], d["telemetry"]) for d in master["devices"] if d.get("telemetry")]
        if not targets:
            return
        field, cf_name = None, None
        if self.apply:
            for cf in self._all("extras/custom-fields/"):
                blob = (str(cf.get("name", "")) + " " + str(cf.get("label", ""))).lower()
                if "telemetry" in blob or "log source" in blob:
                    field = cf; cf_name = cf.get("name"); break
        if not field:
            cf_name = "telemetry"
            if self.apply:
                self.create("extras/custom-fields/",
                            {"object_types": ["dcim.device"], "name": cf_name, "type": "longtext",
                             "label": "Telemetry / Log Sources",
                             "description": "SIEM pipeline and specific log sources this host feeds"},
                            f"custom-field {cf_name}")
        else:
            ftype = field.get("type")
            ftype = ftype.get("value") if isinstance(ftype, dict) else ftype
            if ftype == "text":
                # single-line field can't hold the multi-line per-host detail -> widen it
                self.patch("extras/custom-fields/", self._id(field),
                           {"type": "longtext"}, f"custom-field {cf_name} text->longtext")
        for name, val in targets:
            if not self.apply:
                self.actions.append({"op": "PATCH", "path": "dcim/devices/",
                                     "label": f"telemetry {name}", "data": {"custom_fields": {cf_name: val}}})
                continue
            dev = self.get_one("dcim/devices/", name=name)
            if dev:
                self.patch("dcim/devices/", self._id(dev), {"custom_fields": {cf_name: val}}, f"telemetry {name}")

    def _seed_dataflows(self, master):
        flows = master.get("dataflows", [])
        if not flows:
            return
        dev_by_name = {d["name"]: d for d in master["devices"]}

        # Applications: this plugin's Application model has NO slug; match by name.
        def upsert_app(name):
            existing = self.get_one("plugins/data-flows/applications/", name=name)
            if existing:
                return existing
            return self.create("plugins/data-flows/applications/",
                               {"name": name, "tags": [{"slug": TAG_SLUG}]}, f"application {name}")
        apps = {a: upsert_app(a) for a in sorted({f["application"] for f in flows})}

        # Existing flows keyed by (name, application id) so same-named flows in
        # different applications both persist and re-runs stay idempotent.
        existing_keys = set()
        if self.apply:
            for df in (self._get("plugins/data-flows/dataflows/") or []):
                existing_keys.add((df.get("name"), self._id(df.get("application"))))

        def alias_for(dev_name):
            d = dev_by_name.get(dev_name)
            if not d:
                return None
            ck = f"alias:{dev_name}"
            if ck in self.cache:
                return self.cache[ck]
            cidr = None
            for nic in d.get("interfaces", []):
                if nic.get("ips"):
                    cidr = nic["ips"][0]; break
            ip_id = None
            if cidr and self.apply:
                ipobj = self.get_one("ipam/ip-addresses/", address=cidr)
                ip_id = self._id(ipobj) if ipobj else None
            data = {"name": dev_name, "tags": [{"slug": TAG_SLUG}]}
            if ip_id:
                data["ip_addresses"] = [ip_id]
            obj, _ = self.get_or_create("plugins/data-flows/objectalias/", {"name": dev_name}, data, f"alias {dev_name}")
            self.cache[ck] = obj
            return obj

        for f in flows:
            app_pk = self._id(apps[f["application"]])
            if self.apply and (f["name"], app_pk) in existing_keys:
                continue
            src = alias_for(f["src"]); dst = alias_for(f["dst"])
            data = {"name": f["name"], "application": app_pk,
                    "protocol": f.get("transport", "tcp"), "status": "enabled",
                    "destination_ports": [f["port"]] if f.get("port") else [],
                    "sources": [self._id(src)] if src else [], "destinations": [self._id(dst)] if dst else [],
                    "tags": [{"slug": TAG_SLUG}]}
            self.create("plugins/data-flows/dataflows/", data, f"dataflow {f['application']}:{f['name']}")
            existing_keys.add((f["name"], app_pk))

    # ---- reset / wipe ----
    def _bulk_delete(self, path, ids, chunk=100, timeout=300):
        """Delete ids in batches so slow/large instances don't hit the read timeout.
        Returns count deleted. Falls back to per-object for any batch that errors."""
        done = 0
        for i in range(0, len(ids), chunk):
            batch = ids[i:i + chunk]
            ok = False
            for attempt in (1, 2):
                try:
                    r = self.c.session.delete(self.c._url(path),
                                              json=[{"id": x} for x in batch], timeout=timeout)
                    if r.status_code in (200, 204):
                        done += len(batch); ok = True
                    break
                except Exception:
                    if attempt == 2:
                        break
            if not ok:
                # per-object fallback for this batch
                for x in batch:
                    try:
                        rr = self.c.session.delete(self.c._url(f"{path}{x}/"), timeout=120)
                        if rr.status_code in (200, 204):
                            done += 1
                    except Exception:
                        pass
        return done

    def reset(self):
        order = [
            "plugins/data-flows/dataflows/", "plugins/data-flows/dataflow-groups/",
            "plugins/data-flows/objectalias/", "plugins/data-flows/applications/",
            "plugins/data-flows/application-roles/",
            "tenancy/contact-assignments/",
            "ipam/services/", "ipam/ip-addresses/", "dcim/mac-addresses/",
            "virtualization/virtual-machines/", "virtualization/clusters/",
            "virtualization/cluster-groups/", "virtualization/cluster-types/",
            "dcim/interfaces/", "dcim/devices/", "ipam/prefixes/", "ipam/vlans/",
            "dcim/device-types/", "dcim/manufacturers/", "dcim/platforms/",
            "dcim/device-roles/", "ipam/roles/",
            "tenancy/contacts/", "tenancy/contact-roles/", "dcim/sites/",
        ]
        for path in order:
            items = self._all(path)
            ids = [it["id"] for it in items if isinstance(it, dict) and "id" in it]
            if not ids:
                continue
            if not self.apply:
                self.actions.append({"op": "DELETE", "path": path, "count": len(ids)})
                continue
            # chunked delete (slow embedded NetBox can't delete thousands in one call)
            print(f"   deleting {len(ids):>5} from {path} ...", flush=True)
            deleted = self._bulk_delete(path, ids)
            self.actions.append({"op": "DELETED", "path": path, "count": deleted, "attempted": len(ids)})

        # retire the old SIEM coverage tag definitions (SIEM now lives in a custom field)
        orphan = [t for t in self._all("extras/tags/")
                  if str(t.get("slug", "")).startswith("seen-by")]
        if orphan:
            if not self.apply:
                self.actions.append({"op": "DELETE", "path": "extras/tags/ (seen-by:*)", "count": len(orphan)})
            else:
                ok = 0
                for t in orphan:
                    rr = self.c.session.delete(self.c._url(f"extras/tags/{t['id']}/"), timeout=30)
                    ok += 1 if rr.status_code in (200, 204) else 0
                self.actions.append({"op": "DELETED", "path": "extras/tags/ (seen-by:*)", "count": ok})


def _write_result(seeder, mode, out="v2_reports/seed_result.json"):
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    json.dump({"mode": mode, "applied": seeder.apply, "actions": seeder.actions, "errors": seeder.errors},
              open(out, "w"), indent=2)
    return out


def run_seed(master_path, apply=False, env_file=None):
    conn = get_connection(env_file=env_file)
    master = json.load(open(master_path))
    s = Seeder(conn, apply=apply)
    s.seed(master)
    out = _write_result(s, "seed")
    created = sum(1 for a in s.actions if a["op"] in ("CREATE", "CREATED"))
    print(f"SEED {'APPLIED' if apply else '(plan / dry-run)'}: {created} create actions, {len(s.errors)} errors -> {out}")
    return s


def run_reset(apply=False, env_file=None):
    conn = get_connection(env_file=env_file)
    s = Seeder(conn, apply=apply)
    s.reset()
    out = _write_result(s, "reset", out="v2_reports/reset_result.json")
    tot = sum(a.get("count", 0) for a in s.actions)
    print(f"RESET {'APPLIED' if apply else '(plan / dry-run)'}: {tot} objects across {len(s.actions)} types -> {out}")
    for a in s.actions:
        print(f"   {a['op']:<8} {a['path']:<40} {a.get('count')}")
    return s
