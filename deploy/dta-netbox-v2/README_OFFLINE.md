# DtA NetBox v2 — Offline Deploy (air-gapped)

Target: Malcolm host, x86_64, python3 (tested 3.10-3.14). No internet used.
NOTE: Malcolm's base python has no venv/ensurepip, so install.sh installs into ./vendor
(no venv needed). netbox-v2.sh uses ./venv if present, else ./vendor automatically.

## 1. Install
    ./install.sh

## 2. Configure Localhost Connection
Create or edit `.env` in the bundle directory:
```bash
NETBOX_URL=https://127.0.0.1/netbox
NETBOX_TOKEN=<your_malcolm_netbox_api_token>
NETBOX_VERIFY_SSL=false
```
*(Alternatively, copy and edit the included `.env.example`)*

## 3. Seed NetBox for Day 1 KYE Class (Student Scaffold)
To seed the Day 1 student starting state (57 scaffold devices with unmapped MACs/scan-only devices dropped for discovery):

    # Plan / Dry-Run:
    ./netbox-v2.sh seed --master v2_reports/partial_day1.json

    # Apply / Live Import:
    ./netbox-v2.sh seed --master v2_reports/partial_day1.json --apply

## 4. Seed Full Master Environment (Optional / Answer Key)
To seed the complete 70-device environment:

    ./netbox-v2.sh seed --master v2_reports/master.json --apply

## 5. Other Operations
    # Snapshot existing NetBox instance:
    ./netbox-v2.sh dump

    # Wipe NetBox DtA objects (clean reset):
    ./netbox-v2.sh reset --apply

