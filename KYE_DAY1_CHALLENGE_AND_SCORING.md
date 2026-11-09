# KYE Day 1 Challenge: NetBox Investigation & Scoring Specification

**Target Class:** Know Your Environment (KYE) — Day 1  
**Total Points:** 75 Points  
**Environment:** Malcolm (NetBox, Zeek, Arkime, OpenSearch)  
**Starting Dataset:** `v2_reports/partial_day1.json`  
**Master Answer Key:** `v2_reports/master.json`  

---

## Executive Summary & Challenge Narrative

Students start Day 1 with an incomplete, scaffolded network inventory in Malcolm's NetBox and a physical network diagram (`Dta_Network Diagram_v2.5_KYE_Breakout.pdf`). 

Through passive traffic analysis in Malcolm (Zeek connection logs, Arkime session inspection, protocol-specific decoders), students will discover that:
1. **9 critical servers and PLCs were omitted** from their diagram and inventory.
2. **6 documented devices were tampered with** (given bogus IP addresses), marked by a mysterious tomato ASCII art comment signed *"Allen Broodly Was Here"*.
3. **13 key industrial process dataflows** are missing from the `netbox-data-flows` add-on.

---

## Scoring Summary Table

| Category | Description | Scoring Rule | Total Possible |
| :--- | :--- | :--- | :---: |
| **Part 1: 9 Redacted Devices & IPs** | Critical assets erased from the Day 1 map | **1 pt** for adding IP to IPAM<br>**1 pt** for binding to device (*adaptive naming*) | **18 pts** (9 × 2) |
| **Part 2: 13 Missing Dataflows** | Process flows omitted from Data Flows add-on | **1 pt** for flow record<br>**1 pt** for source IP<br>**1 pt** for destination IP | **39 pts** (13 × 3) |
| **Part 3: 6 Tampered Devices** | Prepopulated devices with bogus IPs & tomato note | **3 pts** for restoring the correct IP on the device | **18 pts** (6 × 3) |
| **GRAND TOTAL** | | | **75 Points** |

---

## Part 1: The 9 Redacted Devices & IPs (18 Points)

These 9 assets appear on the complete CTF map and master inventory, but were redacted from the Day 1 student breakout map.

Students must identify these active hosts in Malcolm traffic, add their IP addresses into NetBox IPAM, create or identify the device object, and bind the IP to the device's interface.

| # | Ground-Truth Name | Real IPv4 | Subnet / Zone | Purdue Level | Role | Expected Student Device Name Variations (*Adaptive Matching*) |
| :-: | :--- | :--- | :--- | :-: | :--- | :--- |
| **1** | `database` | `10.15.15.10` | `10.15.15.0/24` (Corp-DMZ) | L3.5 | Database | `database`, `corp-db`, `dmz-database`, `mysql`, `db` |
| **2** | `database-asc` | `172.16.220.17` | `172.16.220.0/24` (Corporate) | L4 | Database | `database-asc`, `asc-database`, `db-asc`, `corp-db-asc` |
| **3** | `database-acs` | `10.5.5.153` | `10.5.5.0/24` (PCS-DMZ) | L3.5 | Database | `database-acs`, `acs-database`, `pcs-db-acs`, `db-acs` |
| **4** | `database-acd` | `10.5.5.117` | `10.5.5.0/24` (PCS-DMZ) | L3.5 | Database | `database-acd`, `acd-database`, `pcs-db-acd`, `db-acd` |
| **5** | `internal-ftp` | `172.16.220.199` | `172.16.220.0/24` (Corporate) | L4 | FTP-Server | `internal-ftp`, `ftp`, `ftp-server`, `corp-ftp` |
| **6** | `acd-plc` | `192.168.32.3` | `192.168.32.0/24` (PCS-Supervisory) | L2 | PLC | `acd-plc`, `cpe330`, `acd-cpe330`, `ge-plc` |
| **7** | `asc-l55-plc` | `192.168.0.6` | `192.168.0.0/24` (PCS-Process) | L1 | PLC | `asc-l55-plc`, `l55`, `asc-l55`, `controllogix-l55` |
| **8** | `apl-rtu-2` | `192.168.32.5` | `192.168.32.0/24` (PCS-Supervisory) | L2 | RTU | `apl-rtu-2`, `rtu-2`, `apl-rtu2`, `s7-1200` |
| **9** | `sign-asc` | `192.168.0.155` | `192.168.0.0/24` (PCS-Process) | L1 | Display | `sign-asc`, `delta-sign`, `modbus-sign-1`, `plant-sign` |

### Scoring Criteria:
* **+1 Point**: IP address created in NetBox `ipam/ip-addresses/` (with or without mask).
* **+1 Point**: IP address assigned as `primary_ip4` (or assigned to `eth0`) of the matching device. Adaptive matching will normalize case, whitespace, dashes, and underscores.

---

## Part 2: The 13 Missing Industrial Dataflows (39 Points)

The Day 1 environment prepopulates **24 operational flows** (80% of ACS, 80% of ACD, and 43% of ASC) so students have working examples. 

Students must discover the **13 withheld dataflows** by inspecting Zeek conn logs and Arkime sessions, then create them in the `netbox-data-flows` add-on.

| # | Application | Flow Name | Source Host (IP) | Destination Host (IP) | Port & Protocol | Clue / Discovery Trigger |
| :-: | :---: | :--- | :--- | :--- | :--- | :--- |
| **1** | `ACD` | HMI Overview Polling | `acd-plc` (`192.168.32.3`) | `indusoft-overview` (`192.168.0.244`) | `18245` (GE-SRTP) | Uncovers hidden HMI `192.168.0.244` |
| **2** | `ACS` | Substation RTU Overview | `apl-rtu` (`192.168.1.40`) | `indusoft-overview` (`192.168.0.244`) | `502` (Modbus TCP) | Uncovers hidden HMI `192.168.0.244` |
| **3** | `ACS` | S7-1500 Overview Polling | `acs-s7-1500-plc` (`192.168.32.12`) | `indusoft-overview` (`192.168.0.244`) | `102` (S7comm) | Uncovers hidden HMI `192.168.0.244` |
| **4** | `ACS` | S7-1500 Syslog Stream | `acs-s7-1500-plc` (`192.168.32.12`) | `syslog` (`172.16.220.100` / gateway) | `514` (UDP Syslog) | Outbound security event stream |
| **5** | `ACS` | Breaker Control Trip | `apl-rtu-2` (`192.168.32.5`) | `apl-breaker-panel` (`192.168.1.200`) | `20000` (DNP3) | Substation telecontrol signals |
| **6** | `ASC` | Faulted Cross-Plant CIP | `hmi-acs` (`192.168.32.9`) | `asc-l81-plc` (`192.168.0.3`) | `2222` (CIP I/O fails) | Anomalous cross-zone I/O attempt |
| **7** | `ASC` | L81 Syslog Stream | `asc-l81-plc` (`192.168.0.3`) | `syslog` (`172.16.220.100` / gateway) | `514` (UDP Syslog) | Outbound PLC syslog stream |
| **8** | `ASC` | CIP Peer-to-Peer Polling | `asc-l81-plc` (`192.168.0.3`) | `asc-l55-plc` (`192.168.0.6`) | `44818` (EtherNet/IP) | Inter-PLC coordination |
| **9** | `ASC` | L55 Overview Polling | `asc-l55-plc` (`192.168.0.6`) | `indusoft-overview` (`192.168.0.244`) | `44818` (EtherNet/IP) | Uncovers hidden HMI `192.168.0.244` |
| **10** | `ASC` | Historian Ingestion | `asc-l81-plc` (`192.168.0.3`) | `rssql-asc` (`10.5.5.35`) | `44818` (EtherNet/IP) | Industrial SQL logging channel |
| **11** | `ASC` | Plant Floor HMI Polling | `asc-l81-plc` (`192.168.0.3`) | `hmi-asc` (`192.168.0.97`) | `44818` (EtherNet/IP) | Local supervisory control loop |
| **12** | `ASC` | Remote I/O Ingestion | `asc-remote-io-eip` (`192.168.32.105`)| `asc-l81-plc` (`192.168.0.3`) | `2222` (EtherNet/IP I/O) | Field sensor I/O scanning |
| **13** | `ASC` | SQL Historian Replicate | `rssql-asc` (`10.5.5.35`) | `database-asc` (`172.16.220.17`) | `1433` (MS-SQL) | DMZ-to-Corporate database sync |

### Scoring Criteria (3 Points per Flow):
* **+1 Point**: Dataflow created in `plugins/data-flows/dataflows/` with the correct destination port and protocol.
* **+1 Point**: Source Object Alias properly resolves to the source device's IP.
* **+1 Point**: Destination Object Alias properly resolves to the destination device's IP.

---

## Part 3: The 6 Tampered "Allen Broodly" Devices (18 Points)

In `partial_day1.json`, 6 prepopulated devices are seeded with **incorrect, bogus IP addresses**. 

In each device's NetBox description/comments field, the student will see this clue:

```text
      \ | /
    '-.;;;.-'
   -==;;;;;==-
    .-';;;'-.
   /  / | \  \
  |           |
  |  ( ) ( )  |
  \     _     /
   '-._____.-'
Allen Broodly Was Here
```

Students must identify that these devices are generating traffic from their true IPs (or that the seeded IP is silent), update the interface in NetBox with the correct IP, and reassign it as `primary_ip4`.

| # | Device Name | Seeded Bogus IP (Day 1) | True Ground-Truth IP | Zone | How Students Discover the Tampering |
| :-: | :--- | :--- | :--- | :--- | :--- |
| **1** | `user-1` | `172.16.220.71/24` | **`172.16.220.181/24`** | Corporate | Malcolm traffic shows active workstation at `.181`; `.71` is completely silent. |
| **2** | `finance-1` | `172.16.220.72/24` | **`172.16.220.150/24`** | Corporate | NetFlow & Kerberos tickets originate from `.150`. |
| **3** | `mail` | `172.16.220.73/24` | **`172.16.220.3/24`** | Corporate | SMTP (port 25) connections route to `.3`. |
| **4** | `ews-1` | `192.168.0.74/24` | **`192.168.0.51/24`** | PCS-Process | Engineering workstation active on `.51`. |
| **5** | `hmi-acs` | `192.168.32.75/24` | **`192.168.32.9/24`** | PCS-Supervisory | S7comm traffic originates from `.9`. |
| **6** | `hmi-acd` | `192.168.32.76/24` | **`192.168.32.10/24`** | PCS-Supervisory | GE-SRTP traffic originates from `.10`. |

### Scoring Criteria:
* **+3 Points**: For each device where the bogus IP is corrected to its true ground-truth IPv4 address in NetBox.

---

## Complete Scorecard Summary

```text
======================================================================
  KYE DAY 1 NETBOX INVESTIGATION SCORECARD
======================================================================
  Section                                 Items     Points Each   Total
  --------------------------------------  --------  -----------   -----
  Part 1: Redacted Devices & IPs          9         2 pts         18
  Part 2: Missing Dataflows               13        3 pts         39
  Part 3: Tampered "Tomato" Devices       6         3 pts         18
  --------------------------------------  --------  -----------   -----
  FINAL SCORE                                                     75
======================================================================
```

---

## Instructor Operations: Live Dashboard & Remote Administration

The toolset includes a real-time, browser-based split-screen scoreboard designed for classroom projection and instructor monitoring during the exercise.

### 1. Prerequisites (`.env` Setup)
Ensure `.env` in the repository root has connection details and API tokens configured for both team VMs:

```env
# Shared connection settings
NETBOX_VERIFY_SSL=false
NETBOX_PACE_MS=75
NETBOX_TIMEOUT=45

# Team Delta Malcolm VM
DELTA_NETBOX_URL=https://<delta-vm-ip>/netbox
DELTA_NETBOX_TOKEN=<delta_api_token>

# Team Omega Malcolm VM
OMEGA_NETBOX_URL=https://<omega-vm-ip>/netbox
OMEGA_NETBOX_TOKEN=<omega_api_token>
```

### 2. Starting the Dashboard Server
Run the dashboard command from the repository root:

```bash
./netbox-v2.sh dashboard --port 8080
```
*(By default, binds to `0.0.0.0:8080`. To customize the interface or port, pass `--host <ip>` or `--port <port>`)*.

Open your browser to:
```text
http://localhost:8080
```

### 3. Dashboard Features & Classroom Usage
* **Live Split-Screen Display:** Side-by-side comparison of **Team Delta** (Neon Blue) vs. **Team Omega** (Orange).
* **Automated Background Polling:** Automatically queries each team's NetBox API every 30 seconds to update scores, percentage progress bars, and recent event logs.
* **Rubric Tracking:** Real-time breakdown across:
  * **Corrected Data:** (6 tampered devices × 3 pts = 18 pts max)
  * **Missing Entries:** (9 redacted assets × 2 pts = 18 pts max)
  * **Missing DataFlows:** (13 withheld flows × 3 pts = 39 pts max)

### 4. Hidden Admin Console & Scored Audit Dashboard
The scoreboard includes a built-in admin modal allowing instructors to remotely reset or re-seed either team's VM directly from the browser without opening a terminal, as well as an interactive **Scored Points Audit** that inspects each of the 28 challenge points.

* **Shortcut to Open:** Press **`Ctrl` + `Shift` + `A`** anywhere on the scoreboard page (or click the hidden dot `•` in the footer).
* **Admin PIN:**
  ```text
  instructor
  ```
* **Available Remote Controls:**
  * **Reset to Day 1:** Selectively wipes challenge objects and re-seeds the initial student starting baseline (`partial_day1.json`).
  * **Seed Complete CTF Inventory:** Populates the full 70-device ground truth / answer key (`master.json`).
  * **Force Refresh:** Bypasses the 30-second polling timer and immediately queries both student instances.
* **Item-by-Item Scored Audit Dashboard:**
  * Displays a full breakdown of all **28 scorable items** (75 total points) for either team (**Team Delta** or **Team Omega**).
  * **Filter Pills:** Filter by **All (28)**, **Missing / Incomplete**, or **Accounted For**.
  * **Real-Time Search:** Search by device name, IP address, flow name, or description.
  * **Summary KPI Cards:** Instantly view Total Score, Redacted Assets (Part 1), Missing DataFlows (Part 2), and Tampered Devices (Part 3).
  * **Granular Status Badges:**
    * **Part 1 (Redacted Assets, 9 items):** Shows separate indicators for *IP in IPAM* (+1 pt) and *Device Bound* (+1 pt).
    * **Part 2 (Missing DataFlows, 13 items):** Shows separate indicators for *Flow Created* (+1 pt), *Source Alias* (+1 pt), and *Dest Alias* (+1 pt).
    * **Part 3 (Tampered Devices, 6 items):** Shows *Status* (`Corrected` / `Tampered`), expected IP vs. current IP, and tamper comment detection.

### 5. Command-Line Scoring with Granular Audit
Instructors can also run an itemized scoring audit directly in the terminal using the `--details` (or `--audit`) flag:

```bash
# Audit Team Delta's scoring breakdown in terminal
./netbox-v2.sh score --team delta --details

# Audit Team Omega with full item-by-item tables
./netbox-v2.sh score --team omega --details

# Audit local VM loopback
./netbox-v2.sh score --localhost delta --details
```
This prints 3 detailed Rich tables showing the exact status and sub-point allocation for every single scorable asset, flow, and device.



