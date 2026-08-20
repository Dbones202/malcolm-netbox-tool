# Changelog

All notable changes to the **NetBox Excel Device Importer** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.3.0] - 2026-08-20

### Added
- **Self-Healing Multi-Tier Offline Installer (`install.sh`)**:
  - Implemented 3-tier installation engine for air-gapped Linux environments.
  - **Tier 1 (Standard `venv`)**: Uses native `python3 -m venv`.
  - **Tier 2 (Bundled `virtualenv`)**: Automatically falls back to running standalone `virtualenv` wheels loaded directly from `./wheels` on `sys.path` if the OS lacks `python3-venv` / `ensurepip` (e.g. minimal Debian/Ubuntu/Malcolm installations).
  - **Tier 3 (Isolated `lib/` Target)**: Falls back to installing into an isolated `./lib` target folder if system filesystem policy restricts creating virtual environments.
  - Automated executable wrapper creation (`netbox-excel-importer` and `run.sh`) allowing direct CLI execution without manual venv activation.
- **Enhanced Offline Bundler (`build_offline_bundle.py`)**:
  - Automatically packages pure-Python universal dependencies alongside multi-version Linux binary wheels (`manylinux2014_x86_64`, `manylinux_2_17_x86_64`, `manylinux_2_28_x86_64`, `manylinux2014_aarch64`, `manylinux_2_17_aarch64`) for Python 3.8 through 3.14.
  - Packages standalone `virtualenv`, `distlib`, `filelock`, `platformdirs`, and `python-discovery` to guarantee self-contained installation.
  - Automatically compiles `netbox_excel_importer` into a wheel package directly into `./wheels`.

### Fixed
- Fixed relative package imports in unit test suite (`tests/test_validator.py`).
- Synchronized repository and package metadata across `VERSION`, `pyproject.toml`, and `src/netbox_importer/`.

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
