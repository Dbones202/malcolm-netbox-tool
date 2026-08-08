# NetBox Excel Device Importer

![Version](https://img.shields.io/badge/version-1.2.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-green.svg)
![NetBox](https://img.shields.io/badge/NetBox-v4.x-blue.svg)

A packaged Python CLI tool and spreadsheet generator designed to import IPAM subnet prefixes, devices, attached network interfaces (`1000base-t`), and primary IPv4 addresses into a **NetBox** instance (including NetBox instances setup within **Malcolm**).

---

## Versioning & Architecture

- **Current Version**: `1.2.0` (tracked in [VERSION](file:///e:/GIT/Malcolm-Netbox/VERSION)).
- **Changelog**: See [CHANGELOG.md](file:///e:/GIT/Malcolm-Netbox/CHANGELOG.md) for detailed version history.

---

## Key Features

- **3-Sheet Excel Workflow**:
  - **Sheet 1 (`Config`)**: Environment configuration (`CONFIG_VERSION`, `NETBOX_HOST`, `NETBOX_PATH`, `NETBOX_TOKEN`, `SITE_NAME`, `DEVICE_ROLE`, `MANUFACTURER`, `DEVICE_TYPE`, `INTERFACE_NAME`, `DEFAULT_SUBNET_MASK`, `VERIFY_SSL`). `NETBOX_HOST` defaults to `localhost` if left blank.
  - **Sheet 2 (`Devices`)**: 3-column device inventory list: `Device Name`, `IP Address`, `Overwrite`.
  - **Sheet 3 (`Prefixes`)**: 4-column IPAM subnet list: `Prefix`, `Description`, `Site`, `Status`.
- **IPAM Subnet Prefixes (`Prefixes` Sheet)**:
  - Automatically creates or verifies NetBox IPAM prefixes (e.g. `192.168.70.0/24`) and binds them to specified sites prior to device imports.
- **Forced Overwrite Feature (`Overwrite = TRUE`)**:
  - Ideal for live event days when student device names or IP assignments require forced correction.
  - Automatically unbinds the IP from its former device, clears the former device's primary IPv4, and re-assigns the IP to the target device.
- **Dynamic CIDR Mask Parsing**: Automatically appends the default subnet mask (e.g. `/24`) if omitted, or preserves custom specified masks (e.g. `192.168.1.5/16`).
- **Pre-Flight Validation**: Validates the spreadsheet prior to any API connection or dry run, flagging missing names, missing IPs, duplicate names, duplicate IPs, and malformed IPv4/CIDR syntax using Python's `ipaddress` module.
- **Idempotency**: Prevents creating duplicate devices, interfaces, IPAM prefixes, or IP addresses. Logs warnings if an IP is already bound to a different device (when `Overwrite` is `FALSE`).
- **Malcolm Integration**: Supports Malcolm's reverse proxy path (`https://<host>/netbox/api/`) and SSL certificate warning suppression.
- **Air-Gapped / Offline Deployment Package**: Bundling script downloads all `.whl` dependencies into a single offline tarball (`.tar.gz`) or zip file for deployment on isolated Malcolm systems without internet connectivity.

---

## Quick Start Guide

### 1. Installation

#### Standard Online Installation:
```bash
pip install -e .
```

#### Air-Gapped Offline Installation (on Malcolm / Isolated Host):
Upload `netbox_importer_offline_bundle.tar.gz` to your target machine, extract, and run:
```bash
tar -xvf netbox_importer_offline_bundle.tar.gz
cd netbox_importer_offline_bundle
./install.sh
```

---

### 2. Generate Test Spreadsheet

Generate a sample test spreadsheet pre-populated with default config, 10 test devices, and IPAM subnet prefixes:

```bash
netbox-excel-importer generate-template test_devices.xlsx
```

---

### 3. Spreadsheet Structure

#### Sheet 2: `Devices`

| Device Name | IP Address | Overwrite | Notes |
| :--- | :--- | :--- | :--- |
| `srv-sensor-01` | `192.168.70.164` | `FALSE` | Standard creation/verification |
| `hmi-term-01` | `192.168.70.189/16` | `FALSE` | Custom CIDR subnet mask preserved |
| `srv-custom-01` | `192.168.70.27` | `TRUE` | **Forces unassignment from old device & re-assignment to this device** |

#### Sheet 3: `Prefixes`

| Prefix | Description | Site | Status |
| :--- | :--- | :--- | :--- |
| `192.168.70.0/24` | `Lab Test Devices Subnet` | `Malcolm Site` | `active` |
| `192.168.1.0/16` | `Corporate Infrastructure Subnet` | `Malcolm Site` | `active` |

---

### 4. Validate & Import

#### Validate Spreadsheet Syntax:
```bash
netbox-excel-importer validate test_devices.xlsx
```

#### Dry-Run Mode (No changes written to NetBox):
```bash
netbox-excel-importer import test_devices.xlsx --dry-run
```

#### Live Import:
```bash
netbox-excel-importer import test_devices.xlsx
```

---

## Building the Air-Gapped Deployment Bundle

To build a standalone offline deployment package containing all Python wheel dependencies:

```bash
python build_offline_bundle.py
```
This generates `dist/netbox_importer_offline_bundle.tar.gz` and `dist/netbox_importer_offline_bundle.zip`.
