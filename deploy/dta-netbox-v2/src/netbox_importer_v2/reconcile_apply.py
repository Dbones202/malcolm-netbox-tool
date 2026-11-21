"""Execute reviewed in-memory plans with dependency and concurrency checks."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .connection import get_connection
from .inventory_snapshot import (
    capture_snapshot,
    digest,
    read_objects,
    write_private_json,
)
from .reconcile import build_plan, scalar


def resolve(value, references):
    if isinstance(value, str) and value.startswith("@new:"):
        if value not in references:
            raise ValueError("Unresolved dependency: " + value)
        return references[value]
    if isinstance(value, list):
        return [resolve(item, references) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, references) for key, item in value.items()}
    return value


def apply_plan(conn, plan, journal=None):
    if plan.get("conflicts"):
        raise ValueError("Unresolved inventory conflicts; no changes applied")
    if conn.api_url.rstrip("/") != (plan.get("api_url") or "").rstrip("/"):
        raise ValueError("Plan target does not match the selected NetBox instance")
    references, completed = {}, []
    result = {
        "status": "applying",
        "completed": completed,
        "errors": [],
        "references": references,
    }
    for operation in plan["operations"]:
        try:
            data = resolve(copy.deepcopy(operation["data"]), references)
            path = operation["path"]
            if operation["op"] == "CREATE":
                # Another user may have added an object after the snapshot.
                keys = (
                    ("slug",)
                    if "slug" in data
                    else ("name",)
                    if "name" in data
                    else ("address",)
                    if "address" in data
                    else ("prefix",)
                    if "prefix" in data
                    else ()
                )
                if keys:
                    rows = read_objects(conn, path)
                    candidates = [
                        r
                        for r in rows
                        if all(scalar(r.get(k)) == data[k] for k in keys)
                    ]
                    # Interface/service names are scoped; a same-name object elsewhere is fine.
                    if path == "dcim/interfaces/":
                        candidates = [
                            r
                            for r in candidates
                            if scalar(r.get("device")) == data["device"]
                        ]
                    if path == "ipam/services/":
                        candidates = [
                            r
                            for r in candidates
                            if r.get("parent_object_id") == data["parent_object_id"]
                        ]
                    if path == "plugins/data-flows/dataflows/":
                        candidates = [
                            r
                            for r in candidates
                            if scalar(r.get("application")) == data["application"]
                        ]
                    if candidates:
                        raise RuntimeError(
                            "Object appeared after planning; replan: "
                            + operation["label"]
                        )
                response = conn.post(path, json=data)
                if response.status_code not in (200, 201):
                    raise RuntimeError(
                        "CREATE HTTP {}: {}".format(
                            response.status_code, operation["label"]
                        )
                    )
                references[operation["ref"]] = response.json()["id"]
            elif operation["op"] == "PATCH":
                obj_id = resolve(operation["id"], references)
                url = f"{path}{obj_id}/"
                response = conn.get(url)
                if response.status_code != 200:
                    raise RuntimeError("Cannot re-read " + operation["label"])
                current = response.json()
                before = resolve(operation["before"], references)
                unchanged = all(
                    all((current.get(key) or {}).get(k) == v for k, v in value.items())
                    if key == "custom_fields"
                    else scalar(current.get(key)) == scalar(value)
                    for key, value in before.items()
                )
                if not unchanged:
                    raise RuntimeError(
                        "Concurrent change; replan: " + operation["label"]
                    )
                if "custom_fields" in data:
                    data["custom_fields"] = {
                        **(current.get("custom_fields") or {}),
                        **data["custom_fields"],
                    }
                response = conn.patch(url, json=data)
                if response.status_code not in (200, 201):
                    raise RuntimeError(
                        "PATCH HTTP {}: {}".format(
                            response.status_code, operation["label"]
                        )
                    )
            else:
                raise ValueError("Unsupported operation: " + operation["op"])
            completed.append(
                {
                    "index": len(completed),
                    "op": operation["op"],
                    "label": operation["label"],
                }
            )
        except Exception as error:  # noqa: BLE001 -- persist failure and stop all dependent writes
            result["errors"].append(str(error))
            result["status"] = "failed"
            if journal:
                journal(result)
            return result
        if journal:
            journal(result)
    result["status"] = "applied"
    if journal:
        journal(result)
    return result


def run_reconcile(
    master_path,
    apply=False,
    env_file=None,
    team=None,
    localhost=False,
    baseline_path=None,
    out_dir="v2_reports/day4",
    show_progress=False,
    plan_path=None,
):
    with open(master_path, encoding="utf-8") as handle:
        master = json.load(handle)
    baseline = None
    if baseline_path:
        with open(baseline_path, encoding="utf-8") as handle:
            baseline = json.load(handle)
    conn = get_connection(env_file=env_file, team=team, localhost=localhost)
    target = team or conn.api_url
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    directory = Path(out_dir) / str(team or "default") / stamp
    snapshot = capture_snapshot(
        conn, target=target, require_dataflows=bool(master.get("dataflows"))
    )
    write_private_json(directory / "before.json", snapshot)
    if plan_path:
        with open(plan_path, encoding="utf-8") as handle:
            plan = json.load(handle)
        if (
            plan.get("master_hash") != digest(master)
            or plan.get("api_url") != snapshot["api_url"]
            or plan.get("target") != snapshot["target"]
        ):
            raise ValueError(
                "Saved plan specification or target has changed; generate a new plan"
            )
        if plan.get("objects_hash") != digest(snapshot["objects"]):
            raise ValueError(
                "Inventory changed since the reviewed plan; generate a new plan"
            )
        # Capture the current contribution record while executing exactly the reviewed operations.
        current = build_plan(master, snapshot, baseline)
        plan["contributions"] = current["contributions"]
        plan["conflicts"] = list(
            dict.fromkeys(plan.get("conflicts", []) + current["conflicts"])
        )
    else:
        plan = build_plan(master, snapshot, baseline)
    write_private_json(directory / "plan.json", plan)
    write_private_json(directory / "contributions.json", plan["contributions"])
    result = {
        "status": "blocked" if plan["conflicts"] else "planned",
        "directory": str(directory),
        "operations": len(plan["operations"]),
        "conflicts": plan["conflicts"],
    }
    if apply and not plan["conflicts"]:
        # Journal each completed operation in a separate immutable file.
        sequence = [0]

        def journal(state):
            sequence[0] += 1
            write_private_json(directory / f"journal-{sequence[0]:05d}.json", state)

        outcome = apply_plan(conn, plan, journal=journal)
        result.update(outcome)
        if outcome["status"] == "applied":
            try:
                after = capture_snapshot(
                    conn, target=target, require_dataflows=bool(master.get("dataflows"))
                )
                write_private_json(directory / "after.json", after)
                remaining = build_plan(master, after, baseline)
                if remaining["conflicts"] or remaining["operations"]:
                    result["status"] = "verification_failed"
                    result["remaining_operations"] = remaining["operations"]
                    result["verification_conflicts"] = remaining["conflicts"]
            except Exception as error:  # noqa: BLE001 -- writes finished; persist verification failure
                result["status"] = "verification_failed"
                result.setdefault("errors", []).append(str(error))
    write_private_json(directory / "result.json", result)
    return result
