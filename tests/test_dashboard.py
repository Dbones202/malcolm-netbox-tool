"""Unit tests for the classroom dashboard server admin endpoints."""
import io
import json
import unittest
from unittest.mock import MagicMock, patch

from src.netbox_importer_v2.dashboard_server import DashboardHandler, ADMIN_PIN


class TestDashboardAdminEndpoints(unittest.TestCase):
    def _create_mock_handler(self, path: str, payload: dict):
        handler = DashboardHandler.__new__(DashboardHandler)
        body = json.dumps(payload).encode("utf-8")
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.headers = {"Content-Length": str(len(body))}
        handler.path = path
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        return handler

    def test_admin_pin_rejected(self):
        handler = self._create_mock_handler("/api/admin/verify-perms", {"pin": "wrong_pin"})
        handler.do_POST()
        handler.send_response.assert_called_with(403)
        res = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("Invalid PIN", res.get("error", ""))

    @patch("src.netbox_importer_v2.dashboard_server._get_team_conn")
    @patch("src.netbox_importer_v2.dashboard_server.fix_student_permissions")
    def test_admin_verify_perms_detects_issues(self, mock_fix, mock_conn):
        mock_fix.return_value = {
            "apply": False,
            "group_created": False,
            "users_found": [
                {"id": 10, "username": "delta-user", "is_superuser": True, "is_staff": False, "groups": ["admin"]},
            ],
            "errors": [],
        }

        handler = self._create_mock_handler("/api/admin/verify-perms", {"pin": ADMIN_PIN, "target": "delta"})
        handler.do_POST()
        handler.send_response.assert_called_with(200)

        res = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertTrue(res.get("has_issues"))
        self.assertIn("DELTA", res.get("message", ""))
        self.assertIn("superuser active", res.get("message", ""))
        self.assertIn("groups: ['admin']", res.get("message", ""))
        mock_fix.assert_called_once_with(conn=mock_conn.return_value, usernames=None, group_name="student", apply=False)

    @patch("src.netbox_importer_v2.dashboard_server._get_team_conn")
    @patch("src.netbox_importer_v2.dashboard_server.fix_student_permissions")
    def test_admin_verify_perms_protected_state(self, mock_fix, mock_conn):
        mock_fix.return_value = {
            "apply": False,
            "group_created": False,
            "users_found": [
                {"id": 10, "username": "delta-user", "is_superuser": False, "is_staff": False, "groups": ["student"]},
            ],
            "errors": [],
        }

        handler = self._create_mock_handler("/api/admin/verify-perms", {"pin": ADMIN_PIN, "target": "delta"})
        handler.do_POST()
        handler.send_response.assert_called_with(200)

        res = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertFalse(res.get("has_issues"))
        self.assertIn("Protected", res.get("message", ""))

    @patch("src.netbox_importer_v2.dashboard_server._get_team_conn")
    @patch("src.netbox_importer_v2.dashboard_server.fix_student_permissions")
    def test_admin_fix_perms_applies(self, mock_fix, mock_conn):
        mock_fix.return_value = {
            "apply": True,
            "group_id": 5,
            "group_created": False,
            "users_found": [{"id": 10, "username": "delta-user"}],
            "users_updated": ["delta-user"],
            "permissions_created": [],
            "permissions_updated": ["Student-General-Access", "Student-Own-Changelog"],
            "errors": [],
        }

        handler = self._create_mock_handler("/api/admin/fix-perms", {"pin": ADMIN_PIN, "target": "delta"})
        handler.do_POST()
        handler.send_response.assert_called_with(200)

        res = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("Lockdown complete", res.get("message", ""))
        mock_fix.assert_called_once_with(conn=mock_conn.return_value, usernames=None, group_name="student", apply=True)


if __name__ == "__main__":
    unittest.main()
