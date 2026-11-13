"""Manage and fix student permissions in NetBox via REST API.

Enforces least-privilege cyber range / student access:
  1. Ensures the target user group ('student') exists, creating it if necessary.
  2. Strips all other group memberships (e.g., 'admin') and assigns target users
     exclusively to the 'student' group.
  3. Revokes superuser and staff flags (is_superuser=False, is_staff=False)
     so NetBox permissions and constraints are strictly enforced.
  4. Creates/updates a general permission granting view/add/change/delete across all
     functional NetBox models (DCIM, IPAM, Circuits, Tenancy, Plugins, etc.)
     while excluding User Management (users.*, auth.*).
  5. Creates/updates a constrained changelog permission (core.objectchange) with
     the dynamic NetBox constraint '{"user": "$user"}' so students can ONLY
     see changes they personally made, hiding all admin/API seeding history.

Supports:
  - Plan (dry-run) by default; pass --apply to commit changes.
  - Multi-instance targeting: --team [delta|omega] or --localhost [delta|omega].
  - Custom student usernames and group name.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple

from rich.console import Console
from rich.table import Table

from .connection import get_connection, NetBoxConn

console = Console()

DEFAULT_STUDENT_USERS = ["delta-user", "omega-user"]
DEFAULT_STUDENT_GROUP = "student"

EXCLUDED_APPS_FOR_GENERAL = {
    "users",
    "auth",
    "account",
    "admin",
    "contenttypes",
    "sessions",
}

CHANGELOG_MODELS = {
    "core.objectchange",
    "extras.objectchange",
}


def _get_all_paginated(conn: NetBoxConn, endpoint: str) -> List[Dict[str, Any]]:
    """Fetch all pages from a NetBox endpoint."""
    items: List[Dict[str, Any]] = []
    path = endpoint
    while path:
        resp = conn.get(path)
        if resp.status_code != 200:
            break
        data = resp.json()
        if isinstance(data, dict) and "results" in data:
            items.extend(data["results"])
            next_url = data.get("next")
            if next_url:
                # Strip base URL to relative path
                if next_url.startswith(conn.api_url):
                    path = next_url[len(conn.api_url):].lstrip("/")
                elif next_url.startswith("http"):
                    path = next_url
                else:
                    path = next_url
            else:
                path = ""
        elif isinstance(data, list):
            items.extend(data)
            break
        else:
            break
    return items


def fetch_object_types(conn: NetBoxConn) -> Tuple[List[str], List[str]]:
    """Discover available object types in NetBox.
    Returns:
      (general_object_types, changelog_object_types)
    """
    # NetBox 4.x uses /api/core/object-types/, NetBox 3.x uses /api/extras/content-types/
    raw_types = _get_all_paginated(conn, "core/object-types/?limit=1000")
    if not raw_types:
        raw_types = _get_all_paginated(conn, "extras/content-types/?limit=1000")

    general_types: List[str] = []
    changelog_types: List[str] = []

    for item in raw_types:
        app = item.get("app_label", "").lower()
        model = item.get("model", "").lower()
        if not app or not model:
            continue
        key = f"{app}.{model}"

        if key in CHANGELOG_MODELS:
            changelog_types.append(key)
        elif app not in EXCLUDED_APPS_FOR_GENERAL:
            general_types.append(key)

    return sorted(general_types), sorted(changelog_types)


def get_or_create_group(
    conn: NetBoxConn,
    group_name: str,
    apply: bool = False,
) -> Tuple[Optional[int], bool, Optional[str]]:
    """Ensure the target group exists.
    Returns:
      (group_id, created_flag, error_message)
    """
    all_groups = _get_all_paginated(conn, "users/groups/?limit=1000")
    for g in all_groups:
        if g.get("name", "").strip().lower() == group_name.strip().lower():
            return g.get("id"), False, None

    # Group does not exist
    if not apply:
        return None, True, None

    resp = conn.post(
        "users/groups/",
        json={"name": group_name, "description": f"Cyber Range student group ({group_name})"},
    )
    if resp.status_code in (200, 201):
        created_data = resp.json()
        return created_data.get("id"), True, None

    return None, False, f"Failed to create group '{group_name}': {resp.status_code} {resp.text}"


def fix_student_permissions(
    conn: NetBoxConn,
    usernames: Optional[List[str]] = None,
    group_name: str = DEFAULT_STUDENT_GROUP,
    apply: bool = False,
) -> Dict[str, Any]:
    """Configure least-privilege permissions and group isolation for student accounts.

    Args:
        conn: Active NetBoxConn connection.
        usernames: List of student usernames (defaults to delta-user and omega-user).
        group_name: Target student group name (defaults to 'student').
        apply: If True, execute writes; otherwise print/return dry-run plan.
    """
    target_usernames = [u.strip().lower() for u in (usernames or DEFAULT_STUDENT_USERS) if u.strip()]
    summary: Dict[str, Any] = {
        "apply": apply,
        "group_name": group_name,
        "group_id": None,
        "group_created": False,
        "users_found": [],
        "users_updated": [],
        "permissions_created": [],
        "permissions_updated": [],
        "errors": [],
    }

    console.print(f"[bold cyan]Auditing NetBox permissions & groups:[/bold cyan] users=[white]{', '.join(target_usernames)}[/white] | target_group=[white]{group_name}[/white]")
    if not apply:
        console.print("[yellow]DRY-RUN MODE (plan only). Pass --apply to write changes to NetBox.[/yellow]\n")

    # 1. Ensure Target Group Exists
    group_id, group_created, group_err = get_or_create_group(conn, group_name, apply=apply)
    if group_err:
        console.print(f"[bold red]{group_err}[/bold red]")
        summary["errors"].append(group_err)
        return summary

    summary["group_id"] = group_id
    summary["group_created"] = group_created
    if group_created:
        if apply:
            console.print(f"[bold green]Created new group:[/bold green] [cyan]{group_name}[/cyan] (ID: {group_id})")
        else:
            console.print(f"[yellow]PLAN:[/yellow] Create missing group [cyan]'{group_name}'[/cyan]")
    else:
        console.print(f"[white]Group exists:[/white] [cyan]{group_name}[/cyan] (ID: {group_id})")

    # 2. Fetch Users
    all_users = _get_all_paginated(conn, "users/users/?limit=1000")
    matched_users = [u for u in all_users if u.get("username", "").lower() in target_usernames]

    if not matched_users:
        msg = f"None of the target users ({', '.join(target_usernames)}) were found in NetBox."
        console.print(f"[yellow]{msg}[/yellow]")
        summary["errors"].append(msg)
        return summary

    table_users = Table(title="Student User Account & Group Status", show_header=True, header_style="bold magenta")
    table_users.add_column("ID", style="cyan", width=6)
    table_users.add_column("Username", style="white", width=14)
    table_users.add_column("Superuser", width=10)
    table_users.add_column("Staff", width=8)
    table_users.add_column("Current Groups", style="dim", width=20)
    table_users.add_column("Action / New State", style="yellow")

    user_ids: List[int] = []
    for u in matched_users:
        uid = u["id"]
        uname = u["username"]
        is_super = u.get("is_superuser", False)
        is_staff = u.get("is_staff", False)
        user_ids.append(uid)

        # Extract current group names and IDs
        raw_user_groups = u.get("groups", [])
        current_group_names = []
        current_group_ids = []
        for g in raw_user_groups:
            if isinstance(g, dict):
                current_group_names.append(g.get("name", str(g.get("id"))))
                current_group_ids.append(g.get("id"))
            elif isinstance(g, int):
                current_group_ids.append(g)
                current_group_names.append(str(g))

        summary["users_found"].append({
            "id": uid,
            "username": uname,
            "is_superuser": is_super,
            "is_staff": is_staff,
            "groups": current_group_names,
        })

        color_super = "[red]True[/red]" if is_super else "[green]False[/green]"
        color_staff = "[red]True[/red]" if is_staff else "[green]False[/green]"
        groups_str = ", ".join(current_group_names) if current_group_names else "(none)"

        # Check if user needs update:
        # 1. is_superuser or is_staff is True
        # 2. current_group_ids is not strictly [group_id]
        needs_demote = is_super or is_staff
        group_mismatch = (group_id is not None and current_group_ids != [group_id]) or (group_id is None)

        actions = []
        if needs_demote:
            actions.append("Revoke Superuser/Staff")
        if group_mismatch:
            actions.append(f"Set group exclusively to '{group_name}'")

        action_summary = " & ".join(actions) if actions else "[green]OK (Protected)[/green]"
        table_users.add_row(str(uid), uname, color_super, color_staff, groups_str, action_summary)

        if (needs_demote or group_mismatch) and apply and group_id is not None:
            patch_payload: Dict[str, Any] = {
                "is_superuser": False,
                "is_staff": False,
                "groups": [group_id],  # Replaces existing groups with only 'student'
            }
            patch_resp = conn.patch(f"users/users/{uid}/", json=patch_payload)
            if patch_resp.status_code in (200, 204):
                summary["users_updated"].append(uname)
            else:
                err_msg = f"Failed to update user {uname}: {patch_resp.status_code} {patch_resp.text}"
                console.print(f"[bold red]{err_msg}[/bold red]")
                summary["errors"].append(err_msg)

    console.print(table_users)

    # 3. Discover Object Types
    general_types, changelog_types = fetch_object_types(conn)
    console.print(f"\nDiscovered [cyan]{len(general_types)}[/cyan] functional object types and [cyan]{len(changelog_types)}[/cyan] changelog model(s).")
    if not changelog_types:
        changelog_types = ["core.objectchange"]

    # 4. Existing Object Permissions
    existing_perms = _get_all_paginated(conn, "users/permissions/?limit=1000")
    perm_map = {p["name"]: p for p in existing_perms if "name" in p}

    target_group_ids = [group_id] if group_id is not None else []

    # Desired Permission 1: General Full Access
    p1_name = "Student-General-Access"
    p1_desc = f"Full access to inventory, networking, and plugins (managed by '{group_name}' group; no users or changelog)"
    p1_payload: Dict[str, Any] = {
        "name": p1_name,
        "description": p1_desc,
        "enabled": True,
        "actions": ["view", "add", "change", "delete"],
        "object_types": general_types,
        "users": user_ids,
        "constraints": None,
    }
    if target_group_ids:
        p1_payload["groups"] = target_group_ids

    # Desired Permission 2: Own Changelog Only
    p2_name = "Student-Own-Changelog"
    p2_desc = f"View-only access restricted strictly to personal audit log entries ($user) for '{group_name}' group"
    p2_payload: Dict[str, Any] = {
        "name": p2_name,
        "description": p2_desc,
        "enabled": True,
        "actions": ["view"],
        "object_types": changelog_types,
        "users": user_ids,
        "constraints": {"user": "$user"},
    }
    if target_group_ids:
        p2_payload["groups"] = target_group_ids

    def _sync_permission(name: str, payload: dict):
        if name in perm_map:
            perm_id = perm_map[name]["id"]
            if apply:
                resp = conn.patch(f"users/permissions/{perm_id}/", json=payload)
                if resp.status_code in (200, 204):
                    console.print(f"[green]Successfully updated permission:[/green] {name}")
                    summary["permissions_updated"].append(name)
                else:
                    err = f"Failed to update permission {name}: {resp.status_code} {resp.text}"
                    console.print(f"[bold red]{err}[/bold red]")
                    summary["errors"].append(err)
            else:
                console.print(f"[yellow]PLAN:[/yellow] Update existing permission [cyan]{name}[/cyan] (ID: {perm_id})")
        else:
            if apply:
                resp = conn.post("users/permissions/", json=payload)
                if resp.status_code in (200, 201):
                    console.print(f"[green]Successfully created permission:[/green] {name}")
                    summary["permissions_created"].append(name)
                else:
                    err = f"Failed to create permission {name}: {resp.status_code} {resp.text}"
                    console.print(f"[bold red]{err}[/bold red]")
                    summary["errors"].append(err)
            else:
                console.print(f"[yellow]PLAN:[/yellow] Create new permission [cyan]{name}[/cyan]")

    console.print("\n[bold]Configuring Object Permissions:[/bold]")
    _sync_permission(p1_name, p1_payload)
    _sync_permission(p2_name, p2_payload)

    if apply:
        console.print(f"\n[bold green]Success: Students moved exclusively to '{group_name}' group and restricted permissions applied.[/bold green]")
    else:
        console.print(f"\n[bold yellow]Dry-run complete.[/bold yellow] Run with [cyan]--apply[/cyan] to apply these changes.")

    return summary
