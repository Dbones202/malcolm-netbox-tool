import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.netbox_importer_v2.inventory_snapshot import (
    capture_snapshot,
    write_private_json,
)
from src.netbox_importer_v2.reconcile_apply import apply_plan


class TestApplyPlan(unittest.TestCase):
    def response(self, data, status=200):
        response = MagicMock(status_code=status)
        response.json.return_value = copy.deepcopy(data)
        return response

    def plan(self):
        return {
            "api_url": "https://test/api",
            "conflicts": [],
            "operations": [
                {
                    "op": "CREATE",
                    "path": "dcim/devices/",
                    "ref": "@new:1",
                    "data": {"name": "host"},
                    "label": "host",
                },
                {
                    "op": "CREATE",
                    "path": "dcim/interfaces/",
                    "ref": "@new:2",
                    "data": {"device": "@new:1", "name": "eth0"},
                    "label": "interface",
                },
                {
                    "op": "PATCH",
                    "path": "dcim/devices/",
                    "id": "@new:1",
                    "before": {"comments": None},
                    "data": {"comments": "instructor"},
                    "label": "notes",
                },
            ],
        }

    def test_applies_with_resolved_ids_and_no_delete(self):
        conn = MagicMock(api_url="https://test/api")
        conn.post.side_effect = [
            self.response({"id": 10}, 201),
            self.response({"id": 11}, 201),
        ]
        conn.get.side_effect = lambda path: self.response(
            {"results": [], "next": None}
            if "?" in path
            else {"id": 10, "name": "host", "comments": None}
        )
        conn.patch.return_value = self.response({"id": 10})
        result = apply_plan(conn, self.plan())
        self.assertEqual(result["status"], "applied")
        self.assertEqual(conn.post.call_args_list[1].kwargs["json"]["device"], 10)
        conn.patch.assert_called_once_with(
            "dcim/devices/10/", json={"comments": "instructor"}
        )
        conn.delete.assert_not_called()

    def test_concurrent_student_edit_stops_update(self):
        plan = self.plan()
        plan["operations"] = [
            {
                "op": "PATCH",
                "path": "dcim/devices/",
                "id": 10,
                "before": {"comments": "original"},
                "data": {"comments": "merged"},
                "label": "notes",
            }
        ]
        conn = MagicMock(api_url="https://test/api")
        conn.get.return_value = self.response(
            {"id": 10, "comments": "new student work"}
        )
        result = apply_plan(conn, plan)
        self.assertEqual(result["status"], "failed")
        conn.patch.assert_not_called()

    def test_conflicts_and_wrong_target_write_nothing(self):
        conn = MagicMock(api_url="https://other/api")
        for plan in [
            self.plan(),
            {**self.plan(), "api_url": conn.api_url, "conflicts": ["ambiguous"]},
        ]:
            with self.assertRaises(ValueError):
                apply_plan(conn, plan)
        conn.post.assert_not_called()
        conn.patch.assert_not_called()

    def test_partial_failure_stops_dependent_operations(self):
        conn = MagicMock(api_url="https://test/api")
        conn.get.return_value = self.response({"results": [], "next": None})
        conn.post.return_value = self.response({"error": "bad request"}, 400)
        result = apply_plan(conn, self.plan())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(conn.post.call_count, 1)
        conn.patch.assert_not_called()


class TestSnapshot(unittest.TestCase):
    def test_snapshot_paginates_and_retains_raw_fields(self):
        conn = MagicMock(api_url="https://test/api")

        def get(path):
            r = MagicMock(status_code=200)
            r.json.return_value = {
                "results": [{"id": 1, "comments": "student"}],
                "next": "page2" if "dcim/devices/?" in path else None,
            }
            return r

        conn.get.side_effect = get
        conn.options.return_value.status_code = 200
        conn.options.return_value.json.return_value = {
            "actions": {"POST": {"config_data": {"type": "string"}}}
        }
        result = capture_snapshot(conn, require_dataflows=False)
        self.assertEqual(len(result["objects"]["dcim/devices/"]), 2)
        self.assertEqual(result["device_text_fields"], ["config_data"])

    def test_failed_read_is_not_an_empty_inventory(self):
        conn = MagicMock()
        conn.get.return_value.status_code = 403
        with self.assertRaises(RuntimeError):
            capture_snapshot(conn)
        conn.post.assert_not_called()

    def test_snapshot_is_private_and_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            write_private_json(path, {"comments": "student"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                write_private_json(path, {})
