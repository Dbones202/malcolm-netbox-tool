"""Serializer comparisons, exercise cleanup and student contribution evidence."""

from .inventory_text import clean_exercise_text


class InventoryConflict(RuntimeError):
    pass


def scalar(value):
    """Compare serializer references with their writable API representation."""
    if isinstance(value, dict):
        if "id" in value:
            return value["id"]
        if "value" in value:
            return value["value"]
        return {k: scalar(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scalar(v) for v in value]
    return value


def tag_slug(tag):
    return tag.get("slug") if isinstance(tag, dict) else tag


def clean_nested(value):
    if isinstance(value, str):
        return clean_exercise_text(value)
    if isinstance(value, dict):
        return {k: clean_nested(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_nested(v) for v in value]
    return value


def contribution_report(snapshot, desired, baseline=None, verified_fields=()):
    records = []
    for path, rows in snapshot["objects"].items():
        if path.startswith("extras/") and path != "extras/config-contexts/":
            continue
        old = {r["id"]: r for r in (baseline or {}).get("objects", {}).get(path, [])}
        after = {r["id"]: r for r in desired.get(path, [])}
        for row in rows:
            for field, value in row.items():
                if field in (
                    "id",
                    "url",
                    "display",
                    "created",
                    "last_updated",
                ) or value in (None, "", [], {}):
                    continue
                if row["id"] in old and scalar(old[row["id"]].get(field)) == scalar(
                    value
                ):
                    continue
                records.append(
                    {
                        "path": path,
                        "id": row["id"],
                        "name": row.get("name"),
                        "field": field,
                        "value": value,
                        "after": after.get(row["id"], {}).get(field),
                        "status": "retained"
                        if scalar(value) == scalar(after.get(row["id"], {}).get(field))
                        else "updated",
                        "evidence": "changed_since_baseline"
                        if baseline
                        else "observed_without_baseline",
                        "attribution": "unknown",
                        "verification": (
                            "matches_day4"
                            if (path, row["id"], field) in verified_fields
                            and scalar(value)
                            == scalar(after.get(row["id"], {}).get(field))
                            else "requires_instructor_review"
                        ),
                    }
                )
    return records
