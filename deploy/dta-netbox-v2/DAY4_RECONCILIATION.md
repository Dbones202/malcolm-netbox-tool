# Day 4 inventory completion

Day 1 still loads `partial_day1.json`, including the six incorrect addresses and
Allen Broodly tomato markings. Day 4 uses `reconcile` and `master.json` to update
existing objects in place. The dashboard's **Complete Day 4 Inventory** button
uses the same engine. It never calls reset or deletes objects.

## Classroom procedure

After seeding Day 1, capture the actual starting inventory for each team before
students begin editing. Use a new filename for each class:

```sh
./netbox-v2.sh snapshot --team delta --out v2_reports/day1-delta.json
./netbox-v2.sh snapshot --team omega --out v2_reports/day1-omega.json
```

These snapshots contain raw object IDs, comments, config fields, tags, custom
fields, interfaces, addresses, services, contacts, cables, config contexts and
dataflow relationships. The older `dump` command is a compact discovery export;
use `snapshot` for preservation and contribution comparisons.

Before Day 4, generate a live comparison without writing to NetBox:

```sh
./netbox-v2.sh reconcile --team delta --baseline v2_reports/day1-delta.json
```

Inspect `plan.json` and `contributions.json` in the printed report directory.
Apply that exact plan by passing its path (substitute the actual run directory):

```sh
./netbox-v2.sh reconcile --team delta --baseline v2_reports/day1-delta.json \
  --plan v2_reports/day4/delta/RUN/plan.json --apply
```

Alternatively, omit `--plan` to snapshot, plan and apply the current inventory in
one invocation. `--localhost delta` / `--localhost omega` works on the Malcolm
hosts. `--master` selects another full answer key; Day 1 JSON is rejected.

## Merge rules

- Correct the answer key's device role/type/platform, interface attributes,
  primary addresses, services, contact assignments and dataflow fields. Add
  missing objects; retain matching object IDs. Device types are matched by both
  manufacturer and model; interfaces and services are scoped to their device.
- Preserve student descriptions, comments, tags, custom fields and additional
  devices/interfaces/addresses/services/flows/cables. Required tags are added;
  conflicting known inventory zone tags are replaced. Other tags survive.
- An absent/null master value is not a command to clear a field. Existing device
  status remains unless the answer key explicitly specifies a status.
- Remove the complete known tomato artwork and standalone Allen Broodly/Broodley
  signature from matched devices' comments/descriptions, writable config text,
  local context data and custom fields whose names/labels identify config,
  comments or notes. Preserve surrounding text and configuration. Unrecognized
  text is retained. Inherited config contexts are captured and preserved, not
  rewritten globally.
- Append missing instructor notes/telemetry in a marked section. Repeated runs
  do not duplicate the notes. This does not generate executable configuration
  commands from prose.
- Correct the primary address and detach a known Day 1 bogus address from its
  original device, without deleting that address record or unrelated student
  addresses. Refuse to take an expected address assigned elsewhere.
- Repair known dataflows and aliases. Extra independent student flows survive.
  Equivalent renamed flows are reused when the match is unique. Endpoints that
  are logical aliases in the answer key (for example syslog and physical skids)
  do not require a fabricated device.

The master only defines dataflow connections. Physical cables are retained and
reported; there is no inferred cable answer key.

## Contribution evidence

With `--baseline`, the report records fields changed since that actual Day 1
snapshot and whether Day 4 retained or updated them. Managed values that agree
with the answer key are identified as `matches_day4`. Other additions require
instructor review; absence from the answer key is not evidence of an error.
Without a baseline, the report explicitly labels existing data as observations,
not proven student additions. Neither mode attributes changes to individual
students; no username is inferred without changelog evidence.

The dashboard preserves student data and saves the same reports. For a baseline
comparison or review of an exact saved plan, use the CLI with `--baseline`.

## Failure and recovery

Each run writes a private directory beneath `v2_reports/day4/`, containing
`before.json`, `plan.json`, `contributions.json` and `result.json`. Apply runs
also save immutable operation journals and, on successful execution,
`after.json`. Report files use mode 0600 and new run directories use mode 0700;
existing snapshots cannot be overwritten. Keep these files on the instructor
host; they may contain configuration and student notes.

Failed/forbidden reads, ambiguous identities and expected-IP ownership conflicts
block completion. Saved plans are bound to their target, answer-key hash and
inventory snapshot; edits since review require a new plan. Before each patch,
the executor re-reads the affected fields and stops on changes. This is a
best-effort concurrency check: the NetBox API does not provide a transaction
across all objects. Avoid simultaneous classroom edits while applying Day 4.

A failed write stops dependent writes and records the completed operations. Do
not replay an interrupted saved plan. Generate a fresh comparison; already
completed changes are reused. The raw before-snapshot and journal support
manual recovery of particular fields; automatic rollback is not implemented.
After applying, the engine captures another snapshot and checks that a second
plan has zero changes. A mismatch is reported as `verification_failed`, not a
successful completion.

Day 4 completion is separate from **Clean Slate**, which remains an explicitly
destructive classroom reset. The legacy `seed --master master.json` command is
for fresh seeding; use `reconcile` to upgrade student inventories.
