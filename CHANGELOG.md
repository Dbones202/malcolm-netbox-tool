# Changelog

All notable changes to the **NetBox Excel Device Importer** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.2.0] - 2026-08-07

### Added
- **IPAM Prefixes Sheet (`Prefixes`)**:
  - Added Sheet 3 `Prefixes` to the template spreadsheet allowing users to define IPAM subnet prefixes before importing devices.
  - Columns: `Prefix` (e.g. `192.168.70.0/24`), `Description`, `Site` (optional, defaults to Config site), `Status` (default `active`).
  - Pre-flight validator validates subnet prefix CIDR syntax using `ipaddress.ip_network` and checks for internal duplicate prefixes.
  - Core importer creates or verifies NetBox IPAM prefixes prior to device import loop.
- **Template Generator & Version Update**:
  - Updated `generate-template` command to output `Prefixes` sheet with `CONFIG_VERSION` = `1.2.0`.

---

## [1.1.0] - 2026-08-07

### Added
- **`Overwrite` Column Support**:
  - Added a 3rd column `Overwrite` (`TRUE` / `FALSE`) to the `Devices` spreadsheet sheet.
  - Useful during live event days when student device names or IP assignments need forced correction.
  - When `Overwrite` is set to `TRUE`, the importer will:
    - Unbind the specified IP address from its previous device/interface.
    - Clear the `primary_ip4` on the previous device if applicable.
    - Re-assign the IP address to the target device's `eth0` interface and set it as the new primary IPv4 address.
  - When `Overwrite` is set to `FALSE` or omitted, the importer maintains safe conflict checking (logging a warning and skipping re-assignment).

---

## [1.0.0] - 2026-08-07

### Added
- **Initial Release of NetBox Excel Device Importer CLI (`v1.0.0`)**.
- **Spreadsheet Template Generator (`generate-template`)**:
  - Generates a 2-sheet Excel file (`netbox_test_devices.xlsx`) containing environment settings (`Config` sheet) and 10 sample device entries (`Devices` sheet).
- **Pre-Flight Spreadsheet Validator (`validate`)**:
  - Pre-flight input validation checks for missing device names, missing IP addresses, duplicate device names, duplicate IP addresses, and malformed IPv4 syntax using Python's `ipaddress` module.
- **Idempotent NetBox API Importer (`import`)**:
  - Connects to NetBox API via `pynetbox` (supports Malcolm NetBox `/netbox/api/` endpoint and SSL warning suppression).
  - Auto-creates prerequisite objects if missing (`Site`: `Malcolm Site`, `Manufacturer`: `Unknown`, `Device Type`: `Unknown Model`, `Device Role`: `Generic Device`).
  - Idempotent device creation, attached network interface (`eth0`, type `1000base-t`), IP address creation in IPAM, interface binding, and primary IPv4 assignment.
  - `--dry-run` flag for simulation without modifying database state.
- **Air-Gapped / Offline Deployment Packager**:
  - `build_offline_bundle.py` script downloads all wheel dependencies into `./wheels` and creates offline installation tarballs (`dist/netbox_importer_offline_bundle.tar.gz`) and zip archives (`dist/netbox_importer_offline_bundle.zip`).
  - `install.sh` (Linux/Malcolm) and `install.ps1` (Windows) scripts for offline installation (`pip install --no-index --find-links ./wheels .`).
