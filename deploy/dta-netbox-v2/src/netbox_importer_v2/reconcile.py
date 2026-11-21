"""Plan Day 4 changes in memory using the existing inventory builder.

All reads use a captured snapshot. No method here sends a live write.
"""

import copy

from .inventory_merge import (
    InventoryConflict,
    clean_nested,
    contribution_report,
    scalar,
    tag_slug,
)
from .inventory_snapshot import digest
from .inventory_text import clean_exercise_text, merge_notes
from .partial_generator import TAMPERED_DEVICES
from .reconcile_enrichment import ReconcileEnrichment
from .seeder import Seeder, _slug


class Reconciler(ReconcileEnrichment, Seeder):
    def __init__(self, snapshot):
        super().__init__(None, apply=True, show_progress=False)
        self.objects = copy.deepcopy(snapshot["objects"])
        self.snapshot = snapshot
        self.operations = []
        self.next_id = 0
        self.verified_fields = set()
        self.managed_zone_tags = set()
        self.device_specs = {}

    def _all(self, path):
        return self.objects.get(path, [])

    def _get(self, path, **params):
        def matches(row):
            for key, value in params.items():
                field = key if key in row else key[:-3] if key.endswith("_id") else key
                actual = row.get(field)
                if field == "device" and path == "ipam/services/":
                    actual = row.get("parent_object_id", row.get("device"))
                if scalar(actual) != scalar(value):
                    return False
            return True

        return [row for row in self._all(path) if matches(row)]

    def get_one(self, path, **params):
        matches = self._get(path, **params)
        if len(matches) > 1:
            raise InventoryConflict(f"Ambiguous match at {path}: {params}")
        return matches[0] if matches else None

    def create(self, path, data, label):
        # The old seed method always creates prefixes/MACs. Reuse existing ones.
        key = {"ipam/prefixes/": "prefix", "dcim/mac-addresses/": "mac_address"}.get(
            path
        )
        if key:
            existing = self.get_one(path, **{key: data[key]})
            if existing:
                self.update_existing(path, existing, data, label)
                return existing
        self.next_id += 1
        row = {"id": f"@new:{self.next_id}", **copy.deepcopy(data)}
        self.objects.setdefault(path, []).append(row)
        self.operations.append(
            {
                "op": "CREATE",
                "path": path,
                "ref": row["id"],
                "data": copy.deepcopy(data),
                "label": label,
            }
        )
        return row

    def patch(self, path, obj_id, data, label):
        row = self.get_one(path, id=obj_id)
        if row is None:
            raise InventoryConflict(f"Missing object {path}{obj_id}")
        if path == "ipam/ip-addresses/" and data.get("assigned_object_id") is not None:
            assigned = row.get("assigned_object_id")
            if assigned is not None and (
                assigned != data["assigned_object_id"]
                or row.get("assigned_object_type") != "dcim.interface"
            ):
                raise InventoryConflict(
                    "Expected IP is assigned elsewhere: " + row["address"]
                )
        changes = {k: v for k, v in data.items() if scalar(row.get(k)) != scalar(v)}
        if not changes:
            return True
        before = {k: copy.deepcopy(row.get(k)) for k in changes}
        if "custom_fields" in changes:
            current = row.get("custom_fields") or {}
            changes["custom_fields"] = {
                k: v for k, v in changes["custom_fields"].items() if current.get(k) != v
            }
            before["custom_fields"] = {
                k: current.get(k) for k in changes["custom_fields"]
            }
        self.operations.append(
            {
                "op": "PATCH",
                "path": path,
                "id": obj_id,
                "before": before,
                "data": copy.deepcopy(changes),
                "label": label,
            }
        )
        if "custom_fields" in changes:
            row["custom_fields"] = {
                **(row.get("custom_fields") or {}),
                **changes["custom_fields"],
            }
        row.update(
            copy.deepcopy({k: v for k, v in changes.items() if k != "custom_fields"})
        )
        return True

    def update_existing(self, path, row, desired, label):
        desired = {k: v for k, v in desired.items() if v is not None}
        if path == "dcim/devices/" and "name" in desired:
            spec = self.device_specs.get(desired["name"], {})
            if spec.get("status") is None:
                desired.pop("status", None)
            else:
                desired["status"] = spec["status"]
        self.verified_fields.update(
            (path, row["id"], k)
            for k in desired
            if k not in ("comments", "description", "tags", "custom_fields")
        )
        if "tags" in desired:
            # Retain student tags; replace zone tags only when the master defines a zone.
            zones = {
                tag_slug(t)
                for t in desired["tags"]
                if str(tag_slug(t)).startswith("zone-")
            }
            kept = [
                t
                for t in row.get("tags", [])
                if not (
                    zones
                    and tag_slug(t) in self.managed_zone_tags
                    and tag_slug(t) not in zones
                )
            ]
            have = {tag_slug(t) for t in kept}
            desired["tags"] = kept + [
                t for t in desired["tags"] if tag_slug(t) not in have
            ]
            # Write tags by slug so nested serializer metadata is never sent.
            desired["tags"] = [{"slug": tag_slug(t)} for t in desired["tags"]]
        if "comments" in desired:
            desired["comments"] = merge_notes(row.get("comments"), desired["comments"])
        if "description" in desired:
            # Descriptions are prose. Keep student text; only fill an empty description.
            desired["description"] = (
                clean_exercise_text(row.get("description") or "")
                or desired["description"]
            )
        if "extra_choices" in desired:
            choices = row.get("extra_choices") or []
            have = {c[0] if isinstance(c, list) else c for c in choices}
            desired["extra_choices"] = choices + [
                c
                for c in desired["extra_choices"]
                if (c[0] if isinstance(c, list) else c) not in have
            ]
        if "custom_fields" in desired:
            desired["custom_fields"] = {
                **row.get("custom_fields", {}),
                **desired["custom_fields"],
            }
        # Serializer tag IDs differ from write-by-slug form, so compare slug sets.
        if "tags" in desired and {tag_slug(t) for t in row.get("tags", [])} == {
            tag_slug(t) for t in desired["tags"]
        }:
            desired.pop("tags")
        self.patch(path, row["id"], desired, label)

    def get_or_create(self, path, lookup, create_data, label):
        if path == "dcim/device-types/":
            lookup = {**lookup, "manufacturer": create_data["manufacturer"]}
        existing = self.get_one(path, **lookup)
        if existing:
            self.update_existing(path, existing, create_data, label)
            return existing, False
        return self.create(path, create_data, label), True

    def _seed_device(self, device, site_id):
        # The base builder supplies safe API representations and primary-IP links.
        device = copy.deepcopy(device)
        # Absent manufacturer/model/platform are not an instruction to erase values.
        existing = self.get_one("dcim/devices/", name=device["name"])
        if existing and not device.get("model"):
            dtype = self.get_one(
                "dcim/device-types/", id=scalar(existing.get("device_type"))
            )
            if dtype:
                manufacturer = self.get_one(
                    "dcim/manufacturers/", id=scalar(dtype.get("manufacturer"))
                )
                existing_mfr = (manufacturer or {}).get("name")
                if (
                    not device.get("manufacturer")
                    or device["manufacturer"] == existing_mfr
                ):
                    device["manufacturer"] = existing_mfr
                    device["model"] = dtype.get("model")
        if existing and not device.get("role"):
            role = self.get_one("dcim/device-roles/", id=scalar(existing.get("role")))
            if role:
                device["role"] = role["name"]
        super()._seed_device(device, site_id)
        wrong = (TAMPERED_DEVICES.get(device["name"]) or {}).get("wrong_ip")
        if wrong and all(
            wrong not in nic.get("ips", []) for nic in device.get("interfaces", [])
        ):
            address = self.get_one("ipam/ip-addresses/", address=wrong)
            if address and address.get("assigned_object_type") == "dcim.interface":
                interface = self.get_one(
                    "dcim/interfaces/", id=address.get("assigned_object_id")
                )
                owner = self.get_one("dcim/devices/", name=device["name"])
                if interface and scalar(interface.get("device")) == owner["id"]:
                    self.patch(
                        "ipam/ip-addresses/",
                        address["id"],
                        {"assigned_object_type": None, "assigned_object_id": None},
                        "Detach known Day 1 bogus IP",
                    )
        row = self.get_one("dcim/devices/", name=device["name"])
        updates = {}
        if device.get("status") is not None:
            updates["status"] = device["status"]
        fields = set(self.snapshot.get("device_text_fields", [])) | {
            "comments",
            "description",
            "local_context_data",
        }
        for field in fields:
            if isinstance(row.get(field), str):
                updates[field] = clean_exercise_text(row[field])
            elif isinstance(row.get(field), dict):
                updates[field] = clean_nested(row[field])
        custom = row.get("custom_fields") or {}
        cleaned = dict(custom)
        for field in self._all("extras/custom-fields/"):
            name = field.get("name", "")
            label = str(field.get("label", ""))
            if name in cleaned and any(
                word in (name + " " + label).lower()
                for word in ("config", "comment", "note")
            ):
                cleaned[name] = clean_nested(cleaned[name])
        if cleaned != custom:
            updates["custom_fields"] = cleaned
        self.patch(
            "dcim/devices/", row["id"], updates, "Clean exercise text " + device["name"]
        )


def build_plan(master, snapshot, baseline=None):
    if baseline and (
        baseline.get("target") != snapshot.get("target")
        or baseline.get("api_url") != snapshot.get("api_url")
    ):
        raise ValueError("Baseline belongs to a different target")
    worker = Reconciler(snapshot)
    conflicts = []
    if master.get("meta", {}).get("profile", {}).get("name") == "day1_kye":
        conflicts.append("Day 1 exercise JSON is not a Day 4 answer key")
    worker.device_specs = {d["name"]: d for d in master["devices"]}
    worker.managed_zone_tags = {
        _slug("zone-" + d["zone"]) for d in master["devices"] if d.get("zone")
    }
    names = [d["name"] for d in master["devices"]]
    if len(names) != len(set(names)):
        conflicts.append("Duplicate device names in Day 4 specification")
    try:
        if not conflicts:
            worker.seed(master)
    except InventoryConflict as error:
        conflicts.append(str(error))
    return {
        "schema_version": 1,
        "target": snapshot.get("target"),
        "api_url": snapshot.get("api_url"),
        "master_hash": digest(master),
        "snapshot_hash": digest(snapshot),
        "objects_hash": digest(snapshot["objects"]),
        "operations": worker.operations,
        "conflicts": conflicts,
        "desired": worker.objects,
        "contributions": contribution_report(
            snapshot, worker.objects, baseline, worker.verified_fields
        ),
    }
