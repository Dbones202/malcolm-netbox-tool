"""Day 4 merge behavior, with no live NetBox access."""

import copy
import unittest

from src.netbox_importer_v2.inventory_text import clean_exercise_text, merge_notes
from src.netbox_importer_v2.partial_generator import TOMATO_ASCII
from src.netbox_importer_v2.reconcile import build_plan


class TestExerciseText(unittest.TestCase):
    def test_cleanup_preserves_surrounding_config_and_notes(self):
        text = (
            "hostname user-1\r\n"
            + TOMATO_ASCII.replace("\n", "\r\n")
            + "\r\nStudent finding: RDP enabled"
        )
        self.assertEqual(
            clean_exercise_text(text), "hostname user-1\nStudent finding: RDP enabled"
        )

    def test_signature_variants_and_description_prefix(self):
        self.assertEqual(
            clean_exercise_text(
                "Tomato: Allen Broodley Was Here | Student description"
            ),
            "Student description",
        )
        self.assertEqual(
            clean_exercise_text("Allen Broodly Was Here\nStudent note"), "Student note"
        )

    def test_merge_notes_is_idempotent(self):
        first = merge_notes("Student finding", "Instructor finding")
        self.assertIn("Student finding", first)
        self.assertIn("Instructor finding", first)
        self.assertEqual(merge_notes(first, "Instructor finding"), first)
        self.assertEqual(merge_notes("Student finding", ""), "Student finding")


class ReconciliationFixtures:
    def snapshot(self):
        return {
            "objects": {
                "dcim/sites/": [{"id": 1, "name": "Acme", "slug": "acme"}],
                "dcim/device-roles/": [{"id": 2, "name": "Host", "slug": "host"}],
                "dcim/manufacturers/": [
                    {"id": 3, "name": "Unknown", "slug": "unknown"}
                ],
                "dcim/device-types/": [
                    {"id": 4, "model": "Generic Device", "manufacturer": {"id": 3}}
                ],
                "extras/tags/": [{"id": 5, "name": "DtA v2", "slug": "dta-v2"}],
                "dcim/devices/": [
                    {
                        "id": 10,
                        "name": "user-1",
                        "role": {"id": 2},
                        "device_type": {"id": 4},
                        "site": {"id": 1},
                        "status": {"value": "active"},
                        "description": "Student description",
                        "comments": TOMATO_ASCII + "\nStudent finding",
                        "config_data": TOMATO_ASCII + "\nhostname user-1",
                        "tags": [{"id": 20, "slug": "student-tag"}],
                        "custom_fields": {"student_cf": "keep me"},
                        "primary_ip4": {"id": 12},
                    }
                ],
                "dcim/interfaces/": [
                    {
                        "id": 11,
                        "device": {"id": 10},
                        "name": "eth0",
                        "type": {"value": "1000base-t"},
                        "tags": [],
                    }
                ],
                "ipam/ip-addresses/": [
                    {
                        "id": 12,
                        "address": "172.16.220.71/24",
                        "assigned_object_type": "dcim.interface",
                        "assigned_object_id": 11,
                    }
                ],
            },
            "device_text_fields": ["config_data"],
            "target": "test",
        }

    def master(self):
        return {
            "meta": {"site": "Acme"},
            "devices": [
                {
                    "name": "user-1",
                    "notes": "Instructor note",
                    "interfaces": [
                        {"name": "eth0", "ips": ["172.16.220.181/24"], "primary": True}
                    ],
                }
            ],
        }


class TestReconciliation(ReconciliationFixtures, unittest.TestCase):
    def test_reconciles_in_place_preserving_student_content(self):
        snapshot = self.snapshot()
        original = copy.deepcopy(snapshot)
        plan = build_plan(self.master(), snapshot)
        self.assertEqual(snapshot, original)
        self.assertEqual(plan["conflicts"], [])
        device = plan["desired"]["dcim/devices/"][0]
        self.assertEqual(device["id"], 10)
        self.assertIn("Student finding", device["comments"])
        self.assertIn("Instructor note", device["comments"])
        self.assertNotIn("Allen Brood", device["comments"])
        self.assertEqual(device["config_data"], "hostname user-1")
        self.assertEqual(device["description"], "Student description")
        self.assertEqual(device["custom_fields"]["student_cf"], "keep me")
        self.assertIn("student-tag", [t["slug"] for t in device["tags"]])
        self.assertFalse(any(op["op"] == "DELETE" for op in plan["operations"]))
        self.assertEqual(len(plan["desired"]["dcim/devices/"]), 1)
        self.assertNotEqual(device["primary_ip4"], 12)
        self.assertTrue(plan["contributions"])

    def test_second_run_has_no_operations(self):
        plan = build_plan(self.master(), self.snapshot())
        again = build_plan(
            self.master(), {**self.snapshot(), "objects": plan["desired"]}
        )
        self.assertEqual(again["operations"], [])

    def test_ambiguous_device_blocks_apply(self):
        snapshot = self.snapshot()
        snapshot["objects"]["dcim/devices/"].append(
            {**snapshot["objects"]["dcim/devices/"][0], "id": 99}
        )
        plan = build_plan(self.master(), snapshot)
        self.assertTrue(plan["conflicts"])

    def test_extra_devices_and_interfaces_are_retained(self):
        snapshot = self.snapshot()
        snapshot["objects"]["dcim/devices/"].append(
            {"id": 88, "name": "student-discovery", "comments": "keep"}
        )
        snapshot["objects"]["dcim/interfaces/"].append(
            {"id": 89, "device": {"id": 10}, "name": "eth1"}
        )
        plan = build_plan(self.master(), snapshot)
        self.assertTrue(any(d["id"] == 88 for d in plan["desired"]["dcim/devices/"]))
        self.assertTrue(any(d["id"] == 89 for d in plan["desired"]["dcim/interfaces/"]))


class TestConnectionReconciliation(ReconciliationFixtures, unittest.TestCase):
    def test_known_bogus_ip_is_detached_without_deleting_student_ip(self):
        snapshot = self.snapshot()
        snapshot["objects"]["ipam/ip-addresses/"].append(
            {
                "id": 30,
                "address": "172.16.220.199/24",
                "assigned_object_type": "dcim.interface",
                "assigned_object_id": 11,
            }
        )
        plan = build_plan(self.master(), snapshot)
        addresses = {r["id"]: r for r in plan["desired"]["ipam/ip-addresses/"]}
        self.assertIsNone(addresses[12]["assigned_object_id"])
        self.assertEqual(addresses[30]["assigned_object_id"], 11)

    def test_does_not_steal_a_students_address_from_another_device(self):
        snapshot = self.snapshot()
        snapshot["objects"]["dcim/interfaces/"].append(
            {"id": 31, "device": {"id": 99}, "name": "eth0"}
        )
        snapshot["objects"]["ipam/ip-addresses/"].append(
            {
                "id": 32,
                "address": "172.16.220.181/24",
                "assigned_object_type": "dcim.interface",
                "assigned_object_id": 31,
            }
        )
        self.assertTrue(build_plan(self.master(), snapshot)["conflicts"])

    def test_repairs_existing_flow_and_preserves_its_notes_and_tags(self):
        snapshot = self.snapshot()
        snapshot["objects"].update(
            {
                "plugins/data-flows/applications/": [{"id": 40, "name": "App"}],
                "plugins/data-flows/objectalias/": [
                    {"id": 41, "name": "user-1", "ip_addresses": []}
                ],
                "plugins/data-flows/dataflows/": [
                    {
                        "id": 42,
                        "name": "Expected flow",
                        "application": {"id": 40},
                        "sources": [],
                        "destinations": [],
                        "protocol": "udp",
                        "destination_ports": [1],
                        "comments": "Student connection note",
                        "tags": [{"slug": "student-tag"}],
                    }
                ],
            }
        )
        master = self.master()
        master["dataflows"] = [
            {
                "name": "Expected flow",
                "application": "App",
                "src": "user-1",
                "dst": "user-1",
                "port": 443,
            }
        ]
        plan = build_plan(master, snapshot)
        flow = plan["desired"]["plugins/data-flows/dataflows/"][0]
        self.assertEqual(flow["id"], 42)
        self.assertEqual(flow["sources"], [41])
        self.assertEqual(flow["destination_ports"], [443])
        self.assertEqual(flow["comments"], "Student connection note")
        self.assertIn("student-tag", [t["slug"] for t in flow["tags"]])


class TestPlanScope(ReconciliationFixtures, unittest.TestCase):
    def test_day1_json_cannot_be_used_as_day4_answer_key(self):
        master = self.master()
        master["meta"]["profile"] = {"name": "day1_kye"}
        self.assertTrue(build_plan(master, self.snapshot())["conflicts"])

    def test_baseline_from_other_target_is_rejected(self):
        with self.assertRaises(ValueError):
            build_plan(
                self.master(), self.snapshot(), {"target": "other", "objects": {}}
            )


class TestStudentMetadata(ReconciliationFixtures, unittest.TestCase):
    def test_student_zone_prefixed_tags_and_unknown_status_survive(self):
        snapshot = self.snapshot()
        snapshot["objects"]["dcim/devices/"][0]["tags"].append(
            {"slug": "zone-student-investigation"}
        )
        snapshot["objects"]["dcim/devices/"][0]["status"] = {"value": "planned"}
        master = self.master()
        master["devices"][0]["zone"] = "Corporate"
        plan = build_plan(master, snapshot)
        device = plan["desired"]["dcim/devices/"][0]
        self.assertIn("zone-student-investigation", [t["slug"] for t in device["tags"]])
        self.assertEqual(device["status"], {"value": "planned"})

    def test_custom_config_field_cleanup_preserves_other_student_fields(self):
        snapshot = self.snapshot()
        snapshot["objects"]["extras/custom-fields/"] = [
            {"id": 77, "name": "running_config", "label": "Configuration"}
        ]
        device = snapshot["objects"]["dcim/devices/"][0]
        device["custom_fields"]["running_config"] = TOMATO_ASCII + "\nhostname user-1"
        result = build_plan(self.master(), snapshot)["desired"]["dcim/devices/"][0]
        self.assertEqual(result["custom_fields"]["running_config"], "hostname user-1")
        self.assertEqual(result["custom_fields"]["student_cf"], "keep me")

    def test_unknown_model_does_not_replace_students_more_specific_model(self):
        snapshot = self.snapshot()
        snapshot["objects"]["dcim/device-types/"][0]["model"] = (
            "Student documented model"
        )
        master = self.master()
        master["devices"][0]["manufacturer"] = "Unknown"
        master["devices"][0]["model"] = None
        plan = build_plan(master, snapshot)
        self.assertEqual(plan["desired"]["dcim/devices/"][0]["device_type"], {"id": 4})


if __name__ == "__main__":
    unittest.main()
