"""Reconcile SIEM, telemetry and dataflow objects without deleting student additions."""

from .inventory_merge import InventoryConflict, scalar
from .inventory_text import merge_notes
from .partial_generator import TAMPERED_DEVICES
from .seeder import TAG_SLUG


class ReconcileEnrichment:
    def _seed_siem(self, master):
        values = sorted({d["siem"] for d in master["devices"] if d.get("siem")})
        if not values:
            return
        fields = self._all("extras/custom-fields/")
        field = next((f for f in fields if f.get("name") == "siem_platform"), None)
        if field is None:
            choices, _ = self.get_or_create(
                "extras/custom-field-choice-sets/",
                {"name": "SIEM Platforms"},
                {"name": "SIEM Platforms", "extra_choices": [[v, v] for v in values]},
                "SIEM choices",
            )
            field = self.create(
                "extras/custom-fields/",
                {
                    "name": "siem_platform",
                    "type": "select",
                    "object_types": ["dcim.device"],
                    "label": "SIEM Platform",
                    "choice_set": choices["id"],
                },
                "SIEM field",
            )
        elif scalar(field.get("type")) in ("select", "multiselect"):
            choices = self.get_one(
                "extras/custom-field-choice-sets/", id=scalar(field.get("choice_set"))
            )
            if not choices:
                raise InventoryConflict("SIEM field has no readable choice set")
            current = choices.get("extra_choices") or []
            have = {v[0] if isinstance(v, list) else v for v in current}
            self.patch(
                "extras/custom-field-choice-sets/",
                choices["id"],
                {"extra_choices": current + [[v, v] for v in values if v not in have]},
                "SIEM choices",
            )
        for device in master["devices"]:
            if device.get("siem"):
                value = device["siem"]
                if scalar(field.get("type")) == "multiselect":
                    row = self.get_one("dcim/devices/", name=device["name"])
                    value = list(
                        dict.fromkeys(
                            (row.get("custom_fields") or {}).get("siem_platform", [])
                            + [value]
                        )
                    )
                self.device_custom_field(device["name"], "siem_platform", value)

    def device_custom_field(self, name, field, value):
        device = self.get_one("dcim/devices/", name=name)
        self.update_existing(
            "dcim/devices/",
            device,
            {"custom_fields": {field: value}},
            "Custom field " + name,
        )

    def _seed_telemetry(self, master):
        targets = [d for d in master["devices"] if d.get("telemetry")]
        if not targets:
            return
        self.get_or_create(
            "extras/custom-fields/",
            {"name": "telemetry"},
            {
                "name": "telemetry",
                "type": "longtext",
                "label": "Telemetry / Log Sources",
                "object_types": ["dcim.device"],
            },
            "Telemetry field",
        )
        for device in targets:
            row = self.get_one("dcim/devices/", name=device["name"])
            value = merge_notes(
                (row.get("custom_fields") or {}).get("telemetry"), device["telemetry"]
            )
            self.device_custom_field(device["name"], "telemetry", value)

    def _seed_dataflows(self, master):
        for flow in master.get("dataflows", []):
            app, _ = self.get_or_create(
                "plugins/data-flows/applications/",
                {"name": flow["application"]},
                {"name": flow["application"], "tags": [{"slug": TAG_SLUG}]},
                "Application " + flow["application"],
            )
            aliases = []
            for name in (flow["src"], flow["dst"]):
                device = self.get_one("dcim/devices/", name=name)
                # The answer key also contains logical endpoints (syslog/skids)
                # which intentionally have aliases but no DCIM device/IP.
                primary = scalar((device or {}).get("primary_ip4"))
                data = {"name": name, "tags": [{"slug": TAG_SLUG}]}
                if primary:
                    existing = self.get_one(
                        "plugins/data-flows/objectalias/", name=name
                    )
                    ips = [scalar(x) for x in (existing or {}).get("ip_addresses", [])]
                    # Remove only the known Day 1 bogus address, retaining other IPs.
                    wrong = (TAMPERED_DEVICES.get(name) or {}).get("wrong_ip")
                    ips = [
                        pk
                        for pk in ips
                        if not wrong
                        or (self.get_one("ipam/ip-addresses/", id=pk) or {}).get(
                            "address"
                        )
                        != wrong
                    ]
                    data["ip_addresses"] = list(dict.fromkeys(ips + [primary]))
                alias, _ = self.get_or_create(
                    "plugins/data-flows/objectalias/",
                    {"name": name},
                    data,
                    "Alias " + name,
                )
                aliases.append(alias["id"])
            data = {
                "name": flow["name"],
                "application": app["id"],
                "protocol": flow.get("transport", "tcp"),
                "status": "enabled",
                "destination_ports": [flow["port"]] if flow.get("port") else [],
                "sources": [aliases[0]],
                "destinations": [aliases[1]],
                "tags": [{"slug": TAG_SLUG}],
            }
            lookup = {"name": flow["name"], "application": app["id"]}
            existing = self.get_one("plugins/data-flows/dataflows/", **lookup)
            if not existing:
                semantic = [
                    row
                    for row in self._all("plugins/data-flows/dataflows/")
                    if scalar(row.get("application")) == app["id"]
                    and scalar(row.get("sources")) == data["sources"]
                    and scalar(row.get("destinations")) == data["destinations"]
                    and row.get("destination_ports") == data["destination_ports"]
                    and scalar(row.get("protocol")) == data["protocol"]
                ]
                if len(semantic) > 1:
                    raise InventoryConflict(
                        "Ambiguous equivalent dataflows: " + flow["name"]
                    )
                existing = semantic[0] if semantic else None
                if existing:
                    data.pop("name")  # Retain a student's descriptive flow name.
            if existing:
                self.update_existing(
                    "plugins/data-flows/dataflows/",
                    existing,
                    data,
                    "Dataflow " + flow["name"],
                )
            else:
                self.create(
                    "plugins/data-flows/dataflows/", data, "Dataflow " + flow["name"]
                )
