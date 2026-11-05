# Malcolm NetBox Automation & Cyber Range Tooling

![Version](https://img.shields.io/badge/version-2.0.1-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-green.svg)
![NetBox](https://img.shields.io/badge/NetBox-v4.2%2B%20%7C%20v4.6%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)

A complete Python automation suite for **NetBox** deployments running within **Malcolm** network traffic analysis environments and Cyber Range exercises (Defend the Arch / Know Your Environment / CTF).

---

## What's Included

The repository provides two complementary toolsets:

1. **`netbox-v2` (`src/netbox_importer_v2`)**: Modern master-driven seeding engine, automated 75-point challenge scorer, and live classroom split-screen scoreboard for cyber range exercises.
2. **`netbox-excel-importer` (`src/netbox_importer`)**: 3-sheet Excel spreadsheet importer for bulk provisioning devices, IPAM prefixes, interfaces, and primary IPs.

---

## 🚀 NetBox v2 Toolset (`netbox-v2`)

Designed for NetBox v4.2+ and v4.6+ with first-class `dcim/mac-addresses` and the `netbox-data-flows` plugin.

### Key Capabilities

- **Master-Driven Seeding (`seed`)**: Provisions sites, roles, IPAM prefixes, devices, interfaces, MAC addresses, primary IPs, services, telemetry/SIEM custom fields, and dataflows from a JSON master key.
- **KYE Day 1 Challenge Engine**: Includes `partial_generator.py` to produce a student starting baseline with 9 redacted devices, 13 withheld dataflows, and 6 tampered devices featuring ASCII tomato comments signed *"Allen Broodly Was Here"*.
- **Automated 75-Point Rubric Scorer (`score`)**: Instant audit and grading with fuzzy/normalized matching across:
  - **Corrected Data**: 6 tampered devices × 3 pts = 18 pts
  - **Missing Entries**: 9 redacted devices × 2 pts = 18 pts
  - **Missing DataFlows**: 13 withheld flows × 3 pts = 39 pts
- **Live Classroom Scoreboard (`dashboard`)**: Browser-based split-screen dashboard (`http://localhost:8080/`) displaying Team Delta (Neon Blue) vs Team Omega (Energetic Orange) with auto-updating progress bars and a hidden PIN-protected admin console (`Ctrl+Shift+A`).
- **Unified Multi-Team Environment (`.env`)**: Manages both Delta and Omega instances from one `.env` file with support for `--localhost [delta|omega]` and `--team [delta|omega]`.
- **Adaptive Rate Limiting & Terminal Progress Bar**: Paced requests (`NETBOX_PACE_MS`), 4-tier exponential backoff retries, and live `rich.progress` displays (`102/500 items`) to prevent Docker/Gunicorn worker exhaustion on Malcolm VMs.

---

### Command-Line Usage (`netbox-v2`)

```bash
# 1. API Discovery & Plugin Introspection
python -m src.netbox_importer_v2.cli discover

# 2. Export Current Inventory to JSON
python -m src.netbox_importer_v2.cli dump --out v2_reports/instance_inventory.json

# 3. Seed NetBox (Dry-Run Plan vs Live Apply)
python -m src.netbox_importer_v2.cli seed --master v2_reports/partial_day1.json         # dry-run
python -m src.netbox_importer_v2.cli seed --master v2_reports/partial_day1.json --apply # live apply

# 4. Score a Live Instance (75-pt Rubric)
python -m src.netbox_importer_v2.cli score
python -m src.netbox_importer_v2.cli score --team delta
python -m src.netbox_importer_v2.cli score --localhost delta

# 5. Selective Wipe / Reset (Cleans challenge objects; preserves vendor models)
python -m src.netbox_importer_v2.cli reset --apply

# 6. Start Classroom Live Scoreboard
python -m src.netbox_importer_v2.cli dashboard --port 8080
```

---

### Multi-Instance Environment Setup (`.env`)

Copy [`.env.example`](.env.example) to `.env`:

```env
# Shared connection and rate-limiting options
NETBOX_VERIFY_SSL=false
NETBOX_PACE_MS=75
NETBOX_TIMEOUT=45
NETBOX_LOCAL_URL=https://127.0.0.1/netbox

# Team Delta NetBox Instance
DELTA_NETBOX_URL=https://192.168.1.50/netbox
DELTA_NETBOX_TOKEN=your_delta_token_here

# Team Omega NetBox Instance
OMEGA_NETBOX_URL=https://192.168.1.60/netbox
OMEGA_NETBOX_TOKEN=your_omega_token_here

# Default / Fallback Instance
NETBOX_URL=https://127.0.0.1/netbox
NETBOX_TOKEN=your_token_here
```

- **Running locally on the Malcolm VM host:** Use `--localhost delta` or `--localhost omega` for local loopback (`127.0.0.1`).
- **Running remotely from an instructor machine:** Use `--team delta` or `--team omega` to target VM IP addresses over the network.

For full rubric specifications and breakdown, see [KYE_DAY1_CHALLENGE_AND_SCORING.md](KYE_DAY1_CHALLENGE_AND_SCORING.md).

---

## 📊 Legacy Excel Device Importer (`netbox-excel-importer`)

For spreadsheet-based bulk provisioning of IPAM prefixes and devices.

### 3-Sheet Excel Workflow
1. **`Config`**: Environment settings (`NETBOX_HOST`, `NETBOX_PATH`, `NETBOX_TOKEN`, `SITE_NAME`, `DEFAULT_SUBNET_MASK`, `VERIFY_SSL`).
2. **`Devices`**: Device inventory with `Device Name`, `IP Address`, and `Overwrite` (`TRUE`/`FALSE`).
3. **`Prefixes`**: IPAM subnet definitions with `Prefix`, `Description`, `Site`, `Status`.

### Excel CLI Commands
```bash
# Generate template workbook
./netbox-excel-importer generate-template test_devices.xlsx

# Validate workbook syntax
./netbox-excel-importer validate test_devices.xlsx

# Dry-run preview
./netbox-excel-importer import test_devices.xlsx --dry-run

# Live import
./netbox-excel-importer import test_devices.xlsx
```

---

## 📦 Standalone Offline Deployment

To build an air-gapped deployment package containing all wheel dependencies for offline Malcolm / Linux nodes:

```bash
python build_offline_bundle.py
```
Outputs: `dist/netbox_importer_offline_bundle.tar.gz` and `dist/netbox_importer_offline_bundle.zip`.

---

## Documentation Links

- [KYE Day 1 Challenge & Scoring Rubric](KYE_DAY1_CHALLENGE_AND_SCORING.md)
- [Project Changelog](CHANGELOG.md)
- [Version Tracker](VERSION)
