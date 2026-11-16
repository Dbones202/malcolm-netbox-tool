"""Unit tests for the classroom dashboard server admin endpoints."""
import io
import json
import unittest
from unittest.mock import MagicMock, patch, call

from src.netbox_importer_v2.dashboard_server import (
    DashboardHandler,
    ADMIN_PIN,
    PARTIAL_DAY1,
    MASTER_JSON,
)


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
        handler = self._create_mock_handler("/api/admin/reset", {"pin": "wrong_pin"})
        handler.do_POST()
        handler.send_response.assert_called_with(403)
        res = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("Invalid PIN", res.get("error", ""))

    @patch("src.netbox_importer_v2.dashboard_server.refresh_scores")
    @patch("src.netbox_importer_v2.dashboard_server.run_seed")
    @patch("src.netbox_importer_v2.dashboard_server.run_reset")
    def test_fill_kye_day1_does_not_delete(self, mock_reset, mock_seed, mock_refresh):
        handler = self._create_mock_handler("/api/admin/reset", {"pin": ADMIN_PIN, "target": "delta"})
        handler.do_POST()
        handler.send_response.assert_called_with(200)

        mock_reset.assert_not_called()
        mock_seed.assert_called_once_with(PARTIAL_DAY1, apply=True, team="delta", show_progress=False)
        res = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("no items deleted", res.get("message", ""))

    @patch("src.netbox_importer_v2.dashboard_server.refresh_scores")
    @patch("src.netbox_importer_v2.dashboard_server.run_seed")
    @patch("src.netbox_importer_v2.dashboard_server.run_reset")
    def test_complete_inventory_deletes_and_rebuilds(self, mock_reset, mock_seed, mock_refresh):
        manager = MagicMock()
        manager.attach_mock(mock_reset, "run_reset")
        manager.attach_mock(mock_seed, "run_seed")

        handler = self._create_mock_handler("/api/admin/complete", {"pin": ADMIN_PIN, "target": "omega"})
        handler.do_POST()
        handler.send_response.assert_called_with(200)

        self.assertEqual(
            manager.mock_calls,
            [
                call.run_reset(apply=True, team="omega", show_progress=False),
                call.run_seed(MASTER_JSON, apply=True, team="omega", show_progress=False),
            ],
        )
        res = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("Wiped and rebuilt", res.get("message", ""))

    @patch("src.netbox_importer_v2.dashboard_server.refresh_scores")
    @patch("src.netbox_importer_v2.dashboard_server.run_seed")
    @patch("src.netbox_importer_v2.dashboard_server.run_reset")
    def test_clean_slate_deletes_without_seeding(self, mock_reset, mock_seed, mock_refresh):
        handler = self._create_mock_handler("/api/admin/clean-slate", {"pin": ADMIN_PIN, "target": "delta"})
        handler.do_POST()
        handler.send_response.assert_called_with(200)

        mock_reset.assert_called_once_with(apply=True, team="delta", show_progress=False)
        mock_seed.assert_not_called()
        res = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertIn("Clean Slate", res.get("message", ""))

    def test_perms_endpoints_removed(self):
        for ep in ("/api/admin/verify-perms", "/api/admin/fix-perms"):
            handler = self._create_mock_handler(ep, {"pin": ADMIN_PIN, "target": "delta"})
            handler.do_POST()
            handler.send_response.assert_called_with(404)


if __name__ == "__main__":
    unittest.main()
