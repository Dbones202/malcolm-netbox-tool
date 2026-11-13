"""Unit tests for the student permissions manager in netbox_importer_v2."""
import unittest
from unittest.mock import MagicMock

from src.netbox_importer_v2.permissions import (
    fetch_object_types,
    get_or_create_group,
    fix_student_permissions,
    EXCLUDED_APPS_FOR_GENERAL,
    CHANGELOG_MODELS,
)


class TestPermissions(unittest.TestCase):
    def test_fetch_object_types_filtering(self):
        mock_conn = MagicMock()
        mock_conn.get.return_value.status_code = 200
        mock_conn.get.return_value.json.return_value = {
            "results": [
                {"app_label": "dcim", "model": "device"},
                {"app_label": "dcim", "model": "interface"},
                {"app_label": "ipam", "model": "ipaddress"},
                {"app_label": "users", "model": "user"},
                {"app_label": "users", "model": "token"},
                {"app_label": "auth", "model": "group"},
                {"app_label": "core", "model": "objectchange"},
                {"app_label": "admin", "model": "logentry"},
            ],
            "next": None,
        }

        general, changelog = fetch_object_types(mock_conn)

        self.assertIn("dcim.device", general)
        self.assertIn("dcim.interface", general)
        self.assertIn("ipam.ipaddress", general)
        self.assertNotIn("users.user", general)
        self.assertNotIn("users.token", general)
        self.assertNotIn("auth.group", general)
        self.assertNotIn("admin.logentry", general)
        self.assertNotIn("core.objectchange", general)

        self.assertEqual(changelog, ["core.objectchange"])

    def test_get_or_create_group_existing(self):
        mock_conn = MagicMock()
        mock_conn.get.return_value.status_code = 200
        mock_conn.get.return_value.json.return_value = {
            "results": [
                {"id": 4, "name": "student"},
                {"id": 1, "name": "admin"},
            ],
            "next": None,
        }

        gid, created, err = get_or_create_group(mock_conn, "student", apply=True)
        self.assertEqual(gid, 4)
        self.assertFalse(created)
        self.assertIsNone(err)
        mock_conn.post.assert_not_called()

    def test_get_or_create_group_creates_when_missing(self):
        mock_conn = MagicMock()
        mock_conn.get.return_value.status_code = 200
        mock_conn.get.return_value.json.return_value = {
            "results": [{"id": 1, "name": "admin"}],
            "next": None,
        }
        mock_conn.post.return_value.status_code = 201
        mock_conn.post.return_value.json.return_value = {"id": 8, "name": "student"}

        gid, created, err = get_or_create_group(mock_conn, "student", apply=True)
        self.assertEqual(gid, 8)
        self.assertTrue(created)
        self.assertIsNone(err)
        mock_conn.post.assert_called_once_with(
            "users/groups/",
            json={"name": "student", "description": "Cyber Range student group (student)"},
        )

    def test_fix_permissions_dry_run(self):
        mock_conn = MagicMock()
        mock_conn.api_url = "https://127.0.0.1/netbox/api"

        def mock_get(path, **kw):
            resp = MagicMock()
            resp.status_code = 200
            if "users/groups" in path:
                resp.json.return_value = {"results": [], "next": None}
            elif "users/users" in path:
                resp.json.return_value = {
                    "results": [
                        {
                            "id": 10,
                            "username": "delta-user",
                            "is_superuser": True,
                            "is_staff": True,
                            "groups": [{"id": 1, "name": "admin"}],
                        },
                        {
                            "id": 11,
                            "username": "omega-user",
                            "is_superuser": True,
                            "is_staff": False,
                            "groups": [],
                        },
                    ],
                    "next": None,
                }
            elif "object-types" in path:
                resp.json.return_value = {
                    "results": [
                        {"app_label": "dcim", "model": "device"},
                        {"app_label": "core", "model": "objectchange"},
                    ],
                    "next": None,
                }
            elif "users/permissions" in path:
                resp.json.return_value = {"results": [], "next": None}
            return resp

        mock_conn.get.side_effect = mock_get

        summary = fix_student_permissions(mock_conn, usernames=["delta-user", "omega-user"], apply=False)

        self.assertFalse(summary["apply"])
        self.assertTrue(summary["group_created"])
        self.assertEqual(len(summary["users_found"]), 2)
        # Verify no writes occurred during dry-run
        mock_conn.patch.assert_not_called()
        mock_conn.post.assert_not_called()

    def test_fix_permissions_apply_strips_old_groups(self):
        mock_conn = MagicMock()
        mock_conn.api_url = "https://127.0.0.1/netbox/api"

        def mock_get(path, **kw):
            resp = MagicMock()
            resp.status_code = 200
            if "users/groups" in path:
                resp.json.return_value = {
                    "results": [{"id": 1, "name": "admin"}],
                    "next": None,
                }
            elif "users/users" in path:
                resp.json.return_value = {
                    "results": [
                        {
                            "id": 10,
                            "username": "delta-user",
                            "is_superuser": True,
                            "is_staff": True,
                            "groups": [{"id": 1, "name": "admin"}],  # assigned to admin
                        },
                    ],
                    "next": None,
                }
            elif "object-types" in path:
                resp.json.return_value = {
                    "results": [
                        {"app_label": "dcim", "model": "device"},
                        {"app_label": "core", "model": "objectchange"},
                    ],
                    "next": None,
                }
            elif "users/permissions" in path:
                resp.json.return_value = {"results": [], "next": None}
            return resp

        mock_conn.get.side_effect = mock_get
        mock_conn.patch.return_value.status_code = 200

        # Mock POST for creating 'student' group and creating permissions
        def mock_post(path, **kw):
            resp = MagicMock()
            resp.status_code = 201
            if "users/groups" in path:
                resp.json.return_value = {"id": 5, "name": "student"}
            else:
                resp.json.return_value = {"id": 100}
            return resp

        mock_conn.post.side_effect = mock_post

        summary = fix_student_permissions(mock_conn, usernames=["delta-user"], group_name="student", apply=True)

        self.assertTrue(summary["apply"])
        self.assertEqual(summary["group_id"], 5)
        self.assertIn("delta-user", summary["users_updated"])

        # Check that user was patched:
        # 1. is_superuser = False
        # 2. is_staff = False
        # 3. groups = [5] (admin group removed, student group assigned!)
        mock_conn.patch.assert_any_call(
            "users/users/10/",
            json={"is_superuser": False, "is_staff": False, "groups": [5]},
        )

        # Permissions were created and include the group id [5]
        perm_posts = [c[1]["json"] for c in mock_conn.post.call_args_list if "groups" in c[1]["json"]]
        self.assertEqual(len(perm_posts), 2)
        for p in perm_posts:
            self.assertEqual(p["groups"], [5])


if __name__ == "__main__":
    unittest.main()
