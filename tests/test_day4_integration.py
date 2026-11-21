"""Exercise real master/Day 1 data through the planner, executor and verifier."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from src.netbox_importer_v2.inventory_snapshot import capture_snapshot
from src.netbox_importer_v2.reconcile import build_plan
from src.netbox_importer_v2.reconcile_apply import apply_plan, run_reconcile
from src.netbox_importer_v2.seeder import Seeder

ROOT = Path(__file__).resolve().parents[1]


class Response:
    def __init__(self, payload, status=200):
        self.payload = copy.deepcopy(payload)
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return copy.deepcopy(self.payload)


class FakeNetBox:
    api_url = "https://test/api"

    def __init__(self):
        self.rows = {}
        self.next_id = 0
        self.writes = []

    def get(self, path, params=None):
        path = urlsplit(path).path
        parts = path.rstrip("/").split("/")
        if parts[-1].isdigit():
            endpoint = "/".join(parts[:-1]) + "/"
            obj = next(
                (r for r in self.rows.get(endpoint, []) if r["id"] == int(parts[-1])),
                None,
            )
            return Response(obj or {}, 200 if obj else 404)
        rows = self.rows.get(path, [])
        if params:
            from src.netbox_importer_v2.reconcile import scalar

            def matches(row):
                for key, value in params.items():
                    field = (
                        key if key in row else key[:-3] if key.endswith("_id") else key
                    )
                    actual = row.get(field)
                    if field == "device" and path == "ipam/services/":
                        actual = row.get("parent_object_id")
                    if scalar(actual) != value:
                        return False
                return True

            rows = [r for r in rows if matches(r)]
        return Response({"results": rows, "next": None})

    def options(self, path):
        return Response(
            {
                "actions": {
                    "POST": {
                        "name": {"type": "string"},
                        "config_data": {"type": "string"},
                    }
                }
            }
        )

    def post(self, path, json):
        self.next_id += 1
        row = {"id": self.next_id, **copy.deepcopy(json)}
        if path == "dcim/devices/":
            row.setdefault("custom_fields", {})
        self.rows.setdefault(path, []).append(row)
        self.writes.append(("POST", path))
        return Response(row, 201)

    def patch(self, path, json):
        endpoint, pk = path.rstrip("/").rsplit("/", 1)
        row = next(r for r in self.rows[endpoint + "/"] if r["id"] == int(pk))
        row.update(copy.deepcopy(json))
        self.writes.append(("PATCH", path))
        return Response(row)

    def delete(self, *args, **kwargs):
        raise AssertionError("Day 4 must not delete objects")


class TestDay4Integration(unittest.TestCase):
    def setUp(self):
        self.master = json.loads((ROOT / "v2_reports/master.json").read_text())
        self.day1 = json.loads((ROOT / "v2_reports/partial_day1.json").read_text())
        self.conn = FakeNetBox()

    def test_full_class_transition_preserves_student_work_and_is_idempotent(self):
        # Seed actual exercise JSON, then emulate student additions.
        Seeder(self.conn, apply=True, show_progress=False).seed(self.day1)
        baseline = capture_snapshot(self.conn, target="delta")
        user = next(d for d in self.conn.rows["dcim/devices/"] if d["name"] == "user-1")
        original_id = user["id"]
        user["comments"] += "\nStudent found RDP exposure"
        user["config_data"] = user["comments"] + "\nhostname user-1"
        user["custom_fields"]["student_evidence"] = "packet capture #42"
        user["tags"].append({"slug": "student-investigated"})
        snapshot = capture_snapshot(self.conn, target="delta")
        self.conn.writes.clear()
        plan = build_plan(self.master, snapshot, baseline)
        self.assertFalse(self.conn.writes, "Planning must not write")
        self.assertEqual(plan["conflicts"], [])
        result = apply_plan(self.conn, plan)
        self.assertEqual(
            result["status"],
            "applied",
            result.get("errors") or result.get("remaining_operations"),
        )
        self.assertEqual(
            len(self.conn.rows["dcim/devices/"]), len(self.master["devices"])
        )
        self.assertEqual(user["id"], original_id)
        self.assertIn("Student found RDP exposure", user["comments"])
        self.assertNotIn("Allen Brood", user["comments"])
        self.assertNotIn("Allen Brood", user["config_data"])
        self.assertEqual(
            user["custom_fields"]["student_evidence"], "packet capture #42"
        )
        self.assertIn("student-investigated", [t["slug"] for t in user["tags"]])
        after = capture_snapshot(self.conn, target="delta")
        self.assertEqual(build_plan(self.master, after, baseline)["operations"], [])
        self.assertTrue(
            any(
                c["evidence"] == "changed_since_baseline" and c["field"] == "comments"
                for c in plan["contributions"]
            )
        )

    def test_runner_writes_private_snapshots_and_verifies_after_apply(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.netbox_importer_v2.reconcile_apply.get_connection",
            return_value=self.conn,
        ):
            planned = run_reconcile(
                str(ROOT / "v2_reports/master.json"), out_dir=directory
            )
            self.assertEqual(planned["status"], "planned")
            self.assertFalse(self.conn.writes)
            result = run_reconcile(
                str(ROOT / "v2_reports/master.json"), apply=True, out_dir=directory
            )
            self.assertEqual(
                result["status"],
                "applied",
                result.get("errors") or result.get("remaining_operations"),
            )
            for name in (
                "before.json",
                "after.json",
                "plan.json",
                "result.json",
                "contributions.json",
            ):
                path = Path(result["directory"]) / name
                self.assertTrue(path.exists())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_saved_plan_can_be_applied_without_replanning(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.netbox_importer_v2.reconcile_apply.get_connection",
            return_value=self.conn,
        ):
            planned = run_reconcile(
                str(ROOT / "v2_reports/master.json"), out_dir=directory
            )
            result = run_reconcile(
                str(ROOT / "v2_reports/master.json"),
                apply=True,
                plan_path=str(Path(planned["directory"]) / "plan.json"),
                out_dir=directory,
            )
            self.assertEqual(result["status"], "applied", result.get("errors"))

    def test_failed_post_apply_read_is_reported_as_verification_failure(self):
        before = capture_snapshot(self.conn)
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.netbox_importer_v2.reconcile_apply.get_connection",
            return_value=self.conn,
        ), patch(
            "src.netbox_importer_v2.reconcile_apply.capture_snapshot",
            side_effect=[before, RuntimeError("post-apply read unavailable")],
        ):
            result = run_reconcile(
                str(ROOT / "v2_reports/master.json"), apply=True, out_dir=directory
            )
            self.assertEqual(result["status"], "verification_failed")
            self.assertTrue((Path(result["directory"]) / "result.json").exists())

    def test_saved_plan_rejects_student_edits_without_writes(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "src.netbox_importer_v2.reconcile_apply.get_connection",
            return_value=self.conn,
        ):
            planned = run_reconcile(
                str(ROOT / "v2_reports/master.json"), out_dir=directory
            )
            self.conn.rows["dcim/devices/"] = [
                {"id": 999, "name": "student-added-device"}
            ]
            self.conn.writes.clear()
            with self.assertRaisesRegex(ValueError, "Inventory changed"):
                run_reconcile(
                    str(ROOT / "v2_reports/master.json"),
                    apply=True,
                    out_dir=directory,
                    plan_path=str(Path(planned["directory"]) / "plan.json"),
                )
            self.assertFalse(self.conn.writes)
