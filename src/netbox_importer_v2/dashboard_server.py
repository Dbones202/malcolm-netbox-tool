"""Classroom Live Split-Screen Dashboard Server for KYE Day 1 NetBox Challenge.

Serves auto-updating split-screen dashboard for Team Delta (Blue) and Team Omega (Orange).
Polls NetBox APIs every 30 seconds or on demand.
Includes discrete, non-obvious Admin controls with an interactive item-by-item
Scored Audit Dashboard showing every scorable point (missing vs. accounted for).
"""
from __future__ import annotations

import http.server
import json
import os
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any

from .scorer import NetBoxScorer, REDACTED_DEVICES, TARGET_FLOWS, TAMPERED_DEVICES
from .seeder import run_reset, run_seed

HERE = Path(__file__).parent.resolve()
ROOT_REPO = HERE.parent.parent

DELTA_ENV = str(HERE / "delta_env.txt")
OMEGA_ENV = str(HERE / "omega_env.txt")
PARTIAL_DAY1 = str(ROOT_REPO / "v2_reports" / "partial_day1.json")
MASTER_JSON = str(ROOT_REPO / "v2_reports" / "master.json")

ADMIN_PIN = (os.environ.get("ADMIN_PIN") or "instructor").strip()


def _empty_score_result(err: str = "") -> dict:
    p1 = [
        {
            "canonical": k,
            "ip": v["ip"],
            "ip_found": False,
            "device_bound": False,
            "found_dev_name": None,
            "points": 0,
        }
        for k, v in REDACTED_DEVICES.items()
    ]
    p2 = [
        {
            "name": tf["name"],
            "app": tf["app"],
            "port": tf["port"],
            "src_ip": tf["src_ip"],
            "dst_ip": tf["dst_ip"],
            "flow_found": False,
            "src_ok": False,
            "dst_ok": False,
            "points": 0,
        }
        for tf in TARGET_FLOWS
    ]
    p3 = [
        {
            "device": k,
            "real_ip": v["real_ip"],
            "wrong_ip": v["wrong_ip"],
            "current_ip": None,
            "is_corrected": False,
            "points": 0,
        }
        for k, v in TAMPERED_DEVICES.items()
    ]
    return {
        "error": err,
        "total_score": 0,
        "max_score": 75,
        "percentage": 0.0,
        "categories": {
            "corrected_data": {"points": 0, "max": 18, "count": 0, "total": 6, "details": p3},
            "missing_entries": {"points": 0, "max": 18, "count": 0, "total": 9, "details": p1},
            "missing_dataflow": {"points": 0, "max": 39, "count": 0, "total": 13, "details": p2},
        },
    }


# In-memory score cache
CACHE_LOCK = threading.Lock()
LATEST_DATA: Dict[str, Any] = {
    "delta": _empty_score_result("Connecting to Team Delta..."),
    "omega": _empty_score_result("Connecting to Team Omega..."),
    "last_updated": None,
    "delta_online": False,
    "omega_online": False,
    "events": [],
}


def refresh_scores() -> None:
    """Queries both NetBox instances and caches results."""
    global LATEST_DATA

    # Delta
    delta_res, delta_ok = None, False
    try:
        scorer_d = NetBoxScorer(team="delta")
        delta_res = scorer_d.score()
        delta_ok = True
    except Exception as e:
        if os.path.exists(DELTA_ENV):
            try:
                scorer_d = NetBoxScorer(env_file=DELTA_ENV)
                delta_res = scorer_d.score()
                delta_ok = True
            except Exception as e2:
                e = e2
        if not delta_ok:
            delta_res = _empty_score_result(str(e))

    # Omega
    omega_res, omega_ok = None, False
    try:
        scorer_o = NetBoxScorer(team="omega")
        omega_res = scorer_o.score()
        omega_ok = True
    except Exception as e:
        if os.path.exists(OMEGA_ENV):
            try:
                scorer_o = NetBoxScorer(env_file=OMEGA_ENV)
                omega_res = scorer_o.score()
                omega_ok = True
            except Exception as e2:
                e = e2
        if not omega_ok:
            omega_res = _empty_score_result(str(e))

    with CACHE_LOCK:
        if delta_res:
            LATEST_DATA["delta"] = delta_res
        LATEST_DATA["delta_online"] = delta_ok
        if omega_res:
            LATEST_DATA["omega"] = omega_res
        LATEST_DATA["omega_online"] = omega_ok
        LATEST_DATA["last_updated"] = time.strftime("%H:%M:%S")


def background_poller(interval: int = 30):
    while True:
        try:
            refresh_scores()
        except Exception:
            pass
        time.sleep(interval)


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KYE Range Scoreboard</title>
<style>
  :root {
    --bg-dark: #0a0c10;
    --delta-blue: #00c3ff;
    --delta-glow: rgba(0, 195, 255, 0.4);
    --delta-dark: #071526;
    --omega-orange: #ff8c00;
    --omega-glow: rgba(255, 140, 0, 0.4);
    --omega-dark: #221205;
    --card-bg: rgba(255, 255, 255, 0.03);
    --border-line: rgba(255, 255, 255, 0.1);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background-color: var(--bg-dark);
    color: #e0e6ed;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  header {
    height: 64px;
    background: rgba(15, 20, 28, 0.85);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--border-line);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 32px;
  }
  .title-area { display: flex; align-items: center; gap: 12px; }
  .title-badge { background: #202b38; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 700; color: #8ba2b9; letter-spacing: 1px; }
  h1 { font-size: 20px; font-weight: 700; letter-spacing: 0.5px; }
  .sync-status { display: flex; align-items: center; gap: 16px; font-size: 13px; color: #7e8c9d; }
  .pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: #00e676; box-shadow: 0 0 8px #00e676; }

  /* Split Container */
  .arena {
    flex: 1;
    display: flex;
    overflow: hidden;
  }

  .team-panel {
    flex: 1;
    display: flex;
    flex-direction: column;
    padding: 40px;
    position: relative;
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: #2a3b4c #0a0c10;
  }
  .team-panel::-webkit-scrollbar {
    width: 8px;
  }
  .team-panel::-webkit-scrollbar-track {
    background: rgba(0, 0, 0, 0.2);
  }
  .team-panel::-webkit-scrollbar-thumb {
    background: #1e293b;
    border-radius: 4px;
  }
  .team-delta::-webkit-scrollbar-thumb:hover {
    background: var(--delta-blue);
  }
  .team-omega::-webkit-scrollbar-thumb:hover {
    background: var(--omega-orange);
  }
  .team-delta {
    background: radial-gradient(circle at 10% 20%, var(--delta-dark) 0%, var(--bg-dark) 70%);
    border-right: 1px solid var(--border-line);
  }
  .team-omega {
    background: radial-gradient(circle at 90% 20%, var(--omega-dark) 0%, var(--bg-dark) 70%);
  }

  .team-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 24px;
  }
  .team-name {
    font-size: 38px;
    font-weight: 900;
    letter-spacing: 2px;
    text-transform: uppercase;
  }
  .team-delta .team-name { color: var(--delta-blue); text-shadow: 0 0 20px var(--delta-glow); }
  .team-omega .team-name { color: var(--omega-orange); text-shadow: 0 0 20px var(--omega-glow); }

  .team-score-hero {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }
  .score-num { font-size: 64px; font-weight: 900; line-height: 1; }
  .team-delta .score-num { color: var(--delta-blue); }
  .team-omega .score-num { color: var(--omega-orange); }
  .score-max { font-size: 24px; color: #5a6e85; font-weight: 600; }

  /* Metrics Bars */
  .metrics-box {
    display: flex;
    flex-direction: column;
    gap: 28px;
    margin-top: 20px;
  }
  .metric-card {
    background: var(--card-bg);
    border: 1px solid var(--border-line);
    border-radius: 12px;
    padding: 20px 24px;
  }
  .metric-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;
  }
  .metric-label {
    font-size: 18px;
    font-weight: 600;
    letter-spacing: 0.5px;
    color: #cfd8dc;
  }
  .metric-val {
    font-size: 20px;
    font-weight: 800;
    font-family: monospace;
  }
  .team-delta .metric-val { color: var(--delta-blue); }
  .team-omega .metric-val { color: var(--omega-orange); }

  .bar-rail {
    height: 16px;
    background: rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    overflow: hidden;
    position: relative;
  }
  .bar-fill {
    height: 100%;
    border-radius: 8px;
    transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
  }
  .team-delta .bar-fill {
    background: linear-gradient(90deg, #0088cc, var(--delta-blue));
    box-shadow: 0 0 12px var(--delta-glow);
  }
  .team-omega .bar-fill {
    background: linear-gradient(90deg, #d35400, var(--omega-orange));
    box-shadow: 0 0 12px var(--omega-glow);
  }

  /* Offline indicator */
  .offline-notice {
    font-size: 13px;
    padding: 6px 12px;
    border-radius: 4px;
    background: rgba(244, 67, 54, 0.15);
    color: #f44336;
    border: 1px solid rgba(244, 67, 54, 0.3);
    margin-top: 12px;
    display: inline-block;
  }

  /* Discreet Footer & Admin Trigger */
  footer {
    height: 36px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 24px;
    font-size: 12px;
    color: #455a64;
  }
  .secret-dot {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    cursor: pointer;
    background: transparent;
    transition: background 0.2s;
  }
  .secret-dot:hover { background: rgba(255, 255, 255, 0.1); }

  /* Hidden Admin Modal & Scored Audit Dashboard */
  .modal-backdrop {
    display: none;
    position: fixed;
    top: 0; left: 0; width: 100vw; height: 100vh;
    background: rgba(0, 0, 0, 0.88);
    backdrop-filter: blur(12px);
    z-index: 1000;
    align-items: center;
    justify-content: center;
    padding: 20px;
    box-sizing: border-box;
  }
  .modal-box {
    background: #0d121a;
    border: 1px solid #1f2f40;
    border-radius: 14px;
    padding: 24px;
    width: 480px;
    max-width: 95vw;
    box-shadow: 0 25px 60px rgba(0,0,0,0.95);
    display: flex;
    flex-direction: column;
    min-height: 0;
    transition: width 0.3s ease, height 0.3s ease;
  }
  .modal-box.expanded {
    width: 1200px;
    max-width: 96vw;
    height: 92vh;
    max-height: 92vh;
    overflow: hidden;
  }

  /* Auth Screen */
  .auth-view h3 { margin-bottom: 12px; font-size: 18px; color: #fff; }
  .auth-view p { font-size: 13px; color: #78909c; margin-bottom: 20px; line-height: 1.4; }
  .modal-row { margin-bottom: 18px; display: flex; flex-direction: column; gap: 8px; }
  .modal-row label { font-size: 13px; color: #90a4ae; font-weight: 600; }
  .modal-box input, .modal-box select {
    background: #070a0f; border: 1px solid #2a3b4c; border-radius: 6px; padding: 10px 14px; color: #fff; font-size: 14px; outline: none;
  }
  .modal-box input:focus { border-color: #00c3ff; }
  .modal-actions { display: flex; gap: 12px; margin-top: 16px; }
  .btn {
    padding: 10px 18px; border-radius: 6px; font-weight: 700; font-size: 13px; cursor: pointer; border: none; transition: opacity 0.2s, background 0.2s;
  }
  .btn-primary { background: #0091ea; color: #fff; }
  .btn-reset { background: #c62828; color: #fff; }
  .btn-complete { background: #2e7d32; color: #fff; }
  .btn-close { background: #263238; color: #cfd8dc; }
  .btn:hover { opacity: 0.88; }
  .status-msg { margin-top: 12px; font-size: 13px; text-align: center; font-weight: 600; }

  /* Audit Dashboard UI */
  .audit-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 14px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
  }
  .audit-header-title {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 18px;
    font-weight: 800;
    color: #fff;
  }
  .badge-instructor {
    background: #283593;
    color: #8c9eff;
    font-size: 11px;
    font-weight: 800;
    padding: 3px 8px;
    border-radius: 4px;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    border: 1px solid rgba(140, 158, 255, 0.3);
  }
  .audit-header-btns {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .btn-sm {
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    border: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: all 0.2s;
  }
  .btn-icon-close {
    background: transparent;
    color: #90a4ae;
    font-size: 20px;
    border: none;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
  }
  .btn-icon-close:hover { color: #fff; background: rgba(255,255,255,0.1); }

  /* Team Selector & Filter Bar */
  .audit-nav-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    margin: 14px 0 12px 0;
  }
  .team-toggle-group {
    display: flex;
    background: #06090e;
    border: 1px solid #1c2b3a;
    border-radius: 8px;
    padding: 3px;
    gap: 4px;
  }
  .team-tab-btn {
    padding: 8px 18px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    border: none;
    background: transparent;
    color: #78909c;
    transition: all 0.2s;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .team-tab-btn.active.delta {
    background: #0088cc;
    color: #fff;
    box-shadow: 0 0 12px var(--delta-glow);
  }
  .team-tab-btn.active.omega {
    background: #d35400;
    color: #fff;
    box-shadow: 0 0 12px var(--omega-glow);
  }

  .filter-group {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .filter-pill {
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid #263238;
    background: #10161f;
    color: #90a4ae;
    transition: all 0.2s;
  }
  .filter-pill.active {
    background: #263238;
    color: #eceff1;
    border-color: #546e7a;
  }
  .search-input {
    background: #070a0f;
    border: 1px solid #263238;
    border-radius: 6px;
    padding: 6px 12px;
    color: #fff;
    font-size: 12px;
    width: 200px;
    outline: none;
  }
  .search-input:focus { border-color: #00c3ff; }

  /* Summary Stat Cards */
  .audit-summary-row {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 14px;
  }
  .summary-stat-card {
    background: #070b10;
    border: 1px solid #1c2b3a;
    border-radius: 8px;
    padding: 10px 14px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .summary-stat-label { font-size: 11px; font-weight: 700; color: #78909c; text-transform: uppercase; letter-spacing: 0.5px; }
  .summary-stat-val { font-size: 18px; font-weight: 800; font-family: monospace; color: #fff; }

  /* Audit List Container */
  .audit-scroll-area {
    flex: 1 1 0;
    min-height: 0;
    overflow-y: scroll;
    overflow-x: auto;
    padding-right: 10px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    scrollbar-width: thin;
    scrollbar-color: #00c3ff #101620;
  }
  .audit-scroll-area::-webkit-scrollbar {
    width: 10px;
    height: 10px;
  }
  .audit-scroll-area::-webkit-scrollbar-track {
    background: #090e15;
    border-radius: 5px;
  }
  .audit-scroll-area::-webkit-scrollbar-thumb {
    background: #1e3a5f;
    border-radius: 5px;
    border: 2px solid #090e15;
  }
  .audit-scroll-area::-webkit-scrollbar-thumb:hover {
    background: #00c3ff;
  }

  .audit-category-block {
    background: #080c12;
    border: 1px solid #1a2634;
    border-radius: 10px;
    overflow: hidden;
  }
  .audit-category-header {
    background: rgba(255,255,255,0.02);
    padding: 10px 16px;
    border-bottom: 1px solid #1a2634;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .audit-category-title {
    font-size: 13px;
    font-weight: 700;
    color: #cfd8dc;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .audit-category-score { font-size: 13px; font-weight: 700; color: #00e676; font-family: monospace; }

  /* Items Table */
  .audit-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  .audit-table th {
    text-align: left;
    padding: 8px 12px;
    background: rgba(0,0,0,0.3);
    color: #607d8b;
    font-weight: 600;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 0.5px;
  }
  .audit-table td {
    padding: 10px 12px;
    border-bottom: 1px solid rgba(255,255,255,0.03);
    vertical-align: middle;
    color: #eceff1;
  }
  .audit-table tr:hover { background: rgba(255,255,255,0.02); }

  /* Status Pills */
  .pill-status {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
  }
  .pill-earned { background: rgba(0, 230, 118, 0.15); color: #00e676; border: 1px solid rgba(0, 230, 118, 0.3); }
  .pill-missing { background: rgba(244, 67, 54, 0.15); color: #f44336; border: 1px solid rgba(244, 67, 54, 0.3); }

  .points-badge {
    font-weight: 800;
    font-family: monospace;
    font-size: 12px;
    padding: 2px 6px;
    border-radius: 4px;
    text-align: right;
    display: inline-block;
  }
  .points-full { color: #00e676; background: rgba(0, 230, 118, 0.1); }
  .points-part { color: #ffb300; background: rgba(255, 179, 0, 0.1); }
  .points-zero { color: #f44336; background: rgba(244, 67, 54, 0.1); }

  /* Footer Controls Bar */
  .audit-footer-controls {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 14px;
    margin-top: 8px;
    border-top: 1px solid rgba(255,255,255,0.08);
    flex-wrap: wrap;
    gap: 10px;
  }
  .remote-control-group {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .select-target {
    background: #070a0f;
    border: 1px solid #37474f;
    border-radius: 6px;
    padding: 6px 10px;
    color: #fff;
    font-size: 12px;
    outline: none;
  }
</style>
</head>
<body>

<header>
  <div class="title-area">
    <span class="title-badge">MALCOLM / NETBOX</span>
    <h1>Know Your Environment — Day 1 Live Scoring</h1>
  </div>
  <div class="sync-status">
    <div class="pulse-dot"></div>
    <span>Auto-Refresh: <strong id="countdown">30s</strong></span>
    <span>Last Sync: <span id="sync-time">--:--:--</span></span>
  </div>
</header>

<div class="arena">
  <!-- Team Delta -->
  <div class="team-panel team-delta">
    <div class="team-header">
      <div class="team-name">Team Delta</div>
      <div class="team-score-hero">
        <span class="score-num" id="delta-total">0</span>
        <span class="score-max">/ 75</span>
      </div>
    </div>
    <div id="delta-offline" class="offline-notice" style="display:none;">Offline / Connecting to NetBox...</div>

    <div class="metrics-box">
      <div class="metric-card">
        <div class="metric-top">
          <span class="metric-label">Corrected Data</span>
          <span class="metric-val" id="delta-m1">0 / 18</span>
        </div>
        <div class="bar-rail"><div class="bar-fill" id="delta-b1" style="width: 0%;"></div></div>
      </div>

      <div class="metric-card">
        <div class="metric-top">
          <span class="metric-label">Missing Entries</span>
          <span class="metric-val" id="delta-m2">0 / 18</span>
        </div>
        <div class="bar-rail"><div class="bar-fill" id="delta-b2" style="width: 0%;"></div></div>
      </div>

      <div class="metric-card">
        <div class="metric-top">
          <span class="metric-label">Missing DataFlow</span>
          <span class="metric-val" id="delta-m3">0 / 39</span>
        </div>
        <div class="bar-rail"><div class="bar-fill" id="delta-b3" style="width: 0%;"></div></div>
      </div>
    </div>
  </div>

  <!-- Team Omega -->
  <div class="team-panel team-omega">
    <div class="team-header">
      <div class="team-name">Team Omega</div>
      <div class="team-score-hero">
        <span class="score-num" id="omega-total">0</span>
        <span class="score-max">/ 75</span>
      </div>
    </div>
    <div id="omega-offline" class="offline-notice" style="display:none;">Offline / Connecting to NetBox...</div>

    <div class="metrics-box">
      <div class="metric-card">
        <div class="metric-top">
          <span class="metric-label">Corrected Data</span>
          <span class="metric-val" id="omega-m1">0 / 18</span>
        </div>
        <div class="bar-rail"><div class="bar-fill" id="omega-b1" style="width: 0%;"></div></div>
      </div>

      <div class="metric-card">
        <div class="metric-top">
          <span class="metric-label">Missing Entries</span>
          <span class="metric-val" id="omega-m2">0 / 18</span>
        </div>
        <div class="bar-rail"><div class="bar-fill" id="omega-b2" style="width: 0%;"></div></div>
      </div>

      <div class="metric-card">
        <div class="metric-top">
          <span class="metric-label">Missing DataFlow</span>
          <span class="metric-val" id="omega-m3">0 / 39</span>
        </div>
        <div class="bar-rail"><div class="bar-fill" id="omega-b3" style="width: 0%;"></div></div>
      </div>
    </div>
  </div>
</div>

<footer>
  <span>KYE Industrial Range Exercise</span>
  <div class="secret-dot" id="adminTrigger" title="Instructor Console"></div>
</footer>

<!-- Discrete Admin Modal -->
<div class="modal-backdrop" id="adminModal">
  <div class="modal-box" id="adminBox">
    
    <!-- 1. Passcode Screen (Shown if locked) -->
    <div id="adminAuthView" class="auth-view">
      <h3>Instructor Control & Scored Points Audit</h3>
      <p>Enter the Instructor PIN to access the item-by-item scoring audit and remote NetBox controls.</p>
      <div class="modal-row">
        <label>Instructor Passcode</label>
        <input type="password" id="adminPinInput" placeholder="Enter PIN" onkeydown="if(event.key==='Enter')submitPin()">
      </div>
      <div class="modal-actions">
        <button class="btn btn-primary" onclick="submitPin()">Unlock Console</button>
        <button class="btn btn-close" onclick="closeAdmin()">Cancel</button>
      </div>
      <div class="status-msg" id="authStatus"></div>
    </div>

    <!-- 2. Interactive Scored Audit Dashboard (Shown once unlocked) -->
    <div id="adminAuditView" style="display:none; flex: 1; flex-direction: column; overflow: hidden;">
      <div class="audit-header">
        <div class="audit-header-title">
          <span>Instructor Scored Points Audit</span>
          <span class="badge-instructor">Instructor Mode</span>
        </div>
        <div class="audit-header-btns">
          <button class="btn-sm btn-primary" onclick="refreshAudit(true)">⟳ Refresh Scores</button>
          <button class="btn-icon-close" onclick="closeAdmin()">&times;</button>
        </div>
      </div>

      <!-- Navigation & Filters -->
      <div class="audit-nav-bar">
        <div class="team-toggle-group">
          <button class="team-tab-btn delta active" id="tabDeltaBtn" onclick="selectTeam('delta')">
            <span>Team Delta</span>
            <span id="tabDeltaScore">0/75</span>
          </button>
          <button class="team-tab-btn omega" id="tabOmegaBtn" onclick="selectTeam('omega')">
            <span>Team Omega</span>
            <span id="tabOmegaScore">0/75</span>
          </button>
        </div>

        <div class="filter-group">
          <button class="filter-pill active" id="filterAll" onclick="setFilter('all')">All (28)</button>
          <button class="filter-pill" id="filterMissing" onclick="setFilter('missing')">✗ Missing / Incomplete</button>
          <button class="filter-pill" id="filterAccounted" onclick="setFilter('accounted')">✓ Accounted For</button>
          <input type="text" class="search-input" id="auditSearchInput" placeholder="🔍 Filter items..." oninput="filterItems()">
        </div>
      </div>

      <!-- Summary Stat Cards -->
      <div class="audit-summary-row">
        <div class="summary-stat-card">
          <span class="summary-stat-label">Total Score</span>
          <span class="summary-stat-val" id="statTotalScore">0 / 75 pts (0%)</span>
        </div>
        <div class="summary-stat-card">
          <span class="summary-stat-label">Part 1: Redacted Assets</span>
          <span class="summary-stat-val" id="statPart1">0 / 9 (0 / 18 pts)</span>
        </div>
        <div class="summary-stat-card">
          <span class="summary-stat-label">Part 2: Missing DataFlows</span>
          <span class="summary-stat-val" id="statPart2">0 / 13 (0 / 39 pts)</span>
        </div>
        <div class="summary-stat-card">
          <span class="summary-stat-label">Part 3: Tampered Devices</span>
          <span class="summary-stat-val" id="statPart3">0 / 6 (0 / 18 pts)</span>
        </div>
      </div>

      <!-- Scrollable Tables -->
      <div class="audit-scroll-area" id="auditScrollArea">
        
        <!-- Category 1: Part 3 Tampered Devices -->
        <div class="audit-category-block" id="blockPart3">
          <div class="audit-category-header">
            <span class="audit-category-title">🍅 Part 3: Tampered Devices (6 Items &times; 3 pts = 18 pts max)</span>
            <span class="audit-category-score" id="hdrPart3Score">0 / 18 pts</span>
          </div>
          <table class="audit-table">
            <thead>
              <tr>
                <th>Device</th>
                <th>Real Expected IPv4</th>
                <th>Seeded Bogus IP</th>
                <th>Current NetBox IP</th>
                <th>Status</th>
                <th style="text-align:right;">Points</th>
              </tr>
            </thead>
            <tbody id="tbodyPart3"></tbody>
          </table>
        </div>

        <!-- Category 2: Part 1 Redacted Assets -->
        <div class="audit-category-block" id="blockPart1">
          <div class="audit-category-header">
            <span class="audit-category-title">🔍 Part 1: Redacted Devices &amp; IPs (9 Items &times; 2 pts = 18 pts max)</span>
            <span class="audit-category-score" id="hdrPart1Score">0 / 18 pts</span>
          </div>
          <table class="audit-table">
            <thead>
              <tr>
                <th>Asset / Canonical</th>
                <th>Expected IPv4</th>
                <th>IP in IPAM (+1 pt)</th>
                <th>Device Bound (+1 pt)</th>
                <th>Matched In NetBox</th>
                <th style="text-align:right;">Points</th>
              </tr>
            </thead>
            <tbody id="tbodyPart1"></tbody>
          </table>
        </div>

        <!-- Category 3: Part 2 Missing Industrial Dataflows -->
        <div class="audit-category-block" id="blockPart2">
          <div class="audit-category-header">
            <span class="audit-category-title">⚡ Part 2: Missing Industrial DataFlows (13 Items &times; 3 pts = 39 pts max)</span>
            <span class="audit-category-score" id="hdrPart2Score">0 / 39 pts</span>
          </div>
          <table class="audit-table">
            <thead>
              <tr>
                <th>App</th>
                <th>Flow Name</th>
                <th>Endpoints &amp; Port</th>
                <th>Flow Record (+1 pt)</th>
                <th>Src Resolved (+1 pt)</th>
                <th>Dst Resolved (+1 pt)</th>
                <th style="text-align:right;">Points</th>
              </tr>
            </thead>
            <tbody id="tbodyPart2"></tbody>
          </table>
        </div>

      </div>

      <!-- Remote Control Bar -->
      <div class="audit-footer-controls">
        <div class="remote-control-group">
          <span style="font-size:12px; font-weight:600; color:#90a4ae;">Remote Action Target:</span>
          <select id="adminTarget" class="select-target">
            <option value="both">Both Teams (Delta &amp; Omega)</option>
            <option value="delta">Team Delta Only</option>
            <option value="omega">Team Omega Only</option>
          </select>
          <button class="btn btn-reset" onclick="triggerAction('reset')">Reset to KYE Start</button>
          <button class="btn btn-complete" onclick="triggerAction('complete')">Complete CTF Inventory</button>
        </div>
        <div class="status-msg" id="adminStatus" style="margin:0;"></div>
      </div>
    </div>

  </div>
</div>

<script>
  let timer = 30;
  let adminPin = sessionStorage.getItem('kye_admin_pin') || '';
  let auditData = null;
  let activeTeam = 'delta';
  let activeFilter = 'all';

  async function updateScores() {
    try {
      const res = await fetch('/api/scores');
      const data = await res.json();
      
      document.getElementById('sync-time').innerText = data.last_updated || '--:--:--';

      // Delta UI
      const d = data.delta || {};
      const dCats = d.categories || {};
      const dm1 = dCats.corrected_data ? dCats.corrected_data.points : 0;
      const dm2 = dCats.missing_entries ? dCats.missing_entries.points : 0;
      const dm3 = dCats.missing_dataflow ? dCats.missing_dataflow.points : 0;

      document.getElementById('delta-total').innerText = d.total_score || 0;
      document.getElementById('delta-m1').innerText = dm1 + ' / 18';
      document.getElementById('delta-b1').style.width = ((dm1 / 18) * 100) + '%';
      document.getElementById('delta-m2').innerText = dm2 + ' / 18';
      document.getElementById('delta-b2').style.width = ((dm2 / 18) * 100) + '%';
      document.getElementById('delta-m3').innerText = dm3 + ' / 39';
      document.getElementById('delta-b3').style.width = ((dm3 / 39) * 100) + '%';
      document.getElementById('delta-offline').style.display = data.delta_online ? 'none' : 'block';

      // Omega UI
      const o = data.omega || {};
      const oCats = o.categories || {};
      const om1 = oCats.corrected_data ? oCats.corrected_data.points : 0;
      const om2 = oCats.missing_entries ? oCats.missing_entries.points : 0;
      const om3 = oCats.missing_dataflow ? oCats.missing_dataflow.points : 0;

      document.getElementById('omega-total').innerText = o.total_score || 0;
      document.getElementById('omega-m1').innerText = om1 + ' / 18';
      document.getElementById('omega-b1').style.width = ((om1 / 18) * 100) + '%';
      document.getElementById('omega-m2').innerText = om2 + ' / 18';
      document.getElementById('omega-b2').style.width = ((om2 / 18) * 100) + '%';
      document.getElementById('omega-m3').innerText = om3 + ' / 39';
      document.getElementById('omega-b3').style.width = ((om3 / 39) * 100) + '%';
      document.getElementById('omega-offline').style.display = data.omega_online ? 'none' : 'block';

      // If audit dashboard is open, update its numbers too
      if (document.getElementById('adminAuditView').style.display === 'flex') {
        auditData = data;
        renderAudit();
      }
    } catch(e) {
      console.error('Score sync error:', e);
    }
  }

  setInterval(() => {
    timer--;
    if (timer <= 0) {
      timer = 30;
      updateScores();
    }
    document.getElementById('countdown').innerText = timer + 's';
  }, 1000);

  updateScores();

  // Admin Hotkey (Ctrl + Shift + A) or secret-dot click
  document.getElementById('adminTrigger').addEventListener('click', openAdmin);
  window.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey && (e.code === 'KeyA' || e.key === 'A' || e.key === 'a')) {
      e.preventDefault();
      openAdmin();
    }
  });

  function openAdmin() {
    document.getElementById('adminModal').style.display = 'flex';
    document.getElementById('adminStatus').innerText = '';
    if (adminPin) {
      showAuditDashboard();
    } else {
      showAuthScreen();
    }
  }

  function closeAdmin() {
    document.getElementById('adminModal').style.display = 'none';
  }

  function showAuthScreen() {
    const box = document.getElementById('adminBox');
    box.classList.remove('expanded');
    document.getElementById('adminAuthView').style.display = 'block';
    document.getElementById('adminAuditView').style.display = 'none';
    document.getElementById('authStatus').innerText = '';
    setTimeout(() => document.getElementById('adminPinInput').focus(), 100);
  }

  function showAuditDashboard() {
    const box = document.getElementById('adminBox');
    box.classList.add('expanded');
    document.getElementById('adminAuthView').style.display = 'none';
    document.getElementById('adminAuditView').style.display = 'flex';
    refreshAudit(false);
  }

  async function submitPin() {
    const pin = document.getElementById('adminPinInput').value.trim();
    const statusEl = document.getElementById('authStatus');
    statusEl.style.color = '#ffb300';
    statusEl.innerText = 'Verifying passcode...';

    try {
      const res = await fetch('/api/admin/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: pin })
      });
      if (res.ok) {
        adminPin = pin;
        sessionStorage.setItem('kye_admin_pin', pin);
        statusEl.innerText = '';
        auditData = await res.json();
        showAuditDashboard();
      } else {
        statusEl.style.color = '#f44336';
        statusEl.innerText = 'Incorrect passcode. Access denied.';
      }
    } catch(e) {
      statusEl.style.color = '#f44336';
      statusEl.innerText = 'Error connecting to server.';
    }
  }

  async function refreshAudit(force = false) {
    const statusEl = document.getElementById('adminStatus');
    if (force) {
      statusEl.style.color = '#ffb300';
      statusEl.innerText = 'Querying live NetBox instances...';
    }
    try {
      const res = await fetch('/api/admin/audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: adminPin, refresh: force })
      });
      if (res.ok) {
        auditData = await res.json();
        renderAudit();
        if (force) {
          statusEl.style.color = '#00e676';
          statusEl.innerText = 'Scores refreshed at ' + (auditData.last_updated || new Date().toLocaleTimeString());
          setTimeout(() => { statusEl.innerText = ''; }, 3000);
        }
      } else if (res.status === 403) {
        sessionStorage.removeItem('kye_admin_pin');
        adminPin = '';
        showAuthScreen();
      }
    } catch(e) {
      statusEl.style.color = '#f44336';
      statusEl.innerText = 'Error loading audit data.';
    }
  }

  function selectTeam(team) {
    activeTeam = team;
    document.getElementById('tabDeltaBtn').className = 'team-tab-btn delta' + (team === 'delta' ? ' active' : '');
    document.getElementById('tabOmegaBtn').className = 'team-tab-btn omega' + (team === 'omega' ? ' active' : '');
    renderAudit();
  }

  function setFilter(filt) {
    activeFilter = filt;
    ['filterAll', 'filterMissing', 'filterAccounted'].forEach(id => {
      document.getElementById(id).classList.remove('active');
    });
    if (filt === 'all') document.getElementById('filterAll').classList.add('active');
    if (filt === 'missing') document.getElementById('filterMissing').classList.add('active');
    if (filt === 'accounted') document.getElementById('filterAccounted').classList.add('active');
    renderAudit();
  }

  function filterItems() {
    renderAudit();
  }

  function renderAudit() {
    if (!auditData) return;

    const deltaScore = (auditData.delta && auditData.delta.total_score) || 0;
    const omegaScore = (auditData.omega && auditData.omega.total_score) || 0;
    document.getElementById('tabDeltaScore').innerText = deltaScore + '/75';
    document.getElementById('tabOmegaScore').innerText = omegaScore + '/75';

    const currentTeam = auditData[activeTeam] || {};
    const cats = currentTeam.categories || {};
    const p3 = cats.corrected_data || { points: 0, max: 18, count: 0, total: 6, details: [] };
    const p1 = cats.missing_entries || { points: 0, max: 18, count: 0, total: 9, details: [] };
    const p2 = cats.missing_dataflow || { points: 0, max: 39, count: 0, total: 13, details: [] };

    // Update Stat Cards
    const totalPts = currentTeam.total_score || 0;
    const pct = currentTeam.percentage || 0;
    document.getElementById('statTotalScore').innerText = totalPts + ' / 75 pts (' + pct + '%)';
    document.getElementById('statPart1').innerText = p1.count + ' / ' + p1.total + ' (' + p1.points + ' / 18 pts)';
    document.getElementById('statPart2').innerText = p2.count + ' / ' + p2.total + ' (' + p2.points + ' / 39 pts)';
    document.getElementById('statPart3').innerText = p3.count + ' / ' + p3.total + ' (' + p3.points + ' / 18 pts)';

    document.getElementById('hdrPart1Score').innerText = p1.points + ' / 18 pts';
    document.getElementById('hdrPart2Score').innerText = p2.points + ' / 39 pts';
    document.getElementById('hdrPart3Score').innerText = p3.points + ' / 18 pts';

    const q = (document.getElementById('auditSearchInput').value || '').toLowerCase().trim();

    // 1. Render Part 3: Tampered Devices (6 Items)
    const tbodyP3 = document.getElementById('tbodyPart3');
    tbodyP3.innerHTML = '';
    (p3.details || []).forEach(item => {
      const isComplete = item.is_corrected;
      if (activeFilter === 'missing' && isComplete) return;
      if (activeFilter === 'accounted' && !isComplete) return;

      const txtMatch = (item.device + ' ' + item.real_ip + ' ' + item.wrong_ip + ' ' + (item.current_ip || '')).toLowerCase();
      if (q && !txtMatch.includes(q)) return;

      const tr = document.createElement('tr');
      const stPill = isComplete 
        ? '<span class="pill-status pill-earned">✓ Restored to ' + item.real_ip + '</span>'
        : '<span class="pill-status pill-missing">✗ Tampered (current: ' + (item.current_ip || 'None') + ')</span>';

      const ptBadge = isComplete
        ? '<span class="points-badge points-full">3 / 3</span>'
        : '<span class="points-badge points-zero">0 / 3</span>';

      tr.innerHTML = `
        <td style="font-weight:700;">${item.device}</td>
        <td><code>${item.real_ip}</code></td>
        <td style="color:#78909c;"><code>${item.wrong_ip}</code></td>
        <td><code>${item.current_ip || '<span style="color:#607d8b;">None</span>'}</code></td>
        <td>${stPill}</td>
        <td style="text-align:right;">${ptBadge}</td>
      `;
      tbodyP3.appendChild(tr);
    });

    // 2. Render Part 1: Redacted Assets (9 Items)
    const tbodyP1 = document.getElementById('tbodyPart1');
    tbodyP1.innerHTML = '';
    (p1.details || []).forEach(item => {
      const isComplete = item.points === 2;
      if (activeFilter === 'missing' && isComplete) return;
      if (activeFilter === 'accounted' && !isComplete) return;

      const txtMatch = (item.canonical + ' ' + item.ip + ' ' + (item.found_dev_name || '')).toLowerCase();
      if (q && !txtMatch.includes(q)) return;

      const tr = document.createElement('tr');
      const ipPill = item.ip_found
        ? '<span class="pill-status pill-earned">✓ Found in IPAM</span>'
        : '<span class="pill-status pill-missing">✗ Missing IP</span>';

      const devPill = item.device_bound
        ? '<span class="pill-status pill-earned">✓ Bound to Device</span>'
        : '<span class="pill-status pill-missing">✗ Unbound</span>';

      let ptBadge = '<span class="points-badge points-zero">0 / 2</span>';
      if (item.points === 2) ptBadge = '<span class="points-badge points-full">2 / 2</span>';
      else if (item.points === 1) ptBadge = '<span class="points-badge points-part">1 / 2</span>';

      tr.innerHTML = `
        <td style="font-weight:700;">${item.canonical}</td>
        <td><code>${item.ip}</code></td>
        <td>${ipPill}</td>
        <td>${devPill}</td>
        <td style="color:#cfd8dc;">${item.found_dev_name || '<span style="color:#546e7a;">—</span>'}</td>
        <td style="text-align:right;">${ptBadge}</td>
      `;
      tbodyP1.appendChild(tr);
    });

    // 3. Render Part 2: Missing DataFlows (13 Items)
    const tbodyP2 = document.getElementById('tbodyPart2');
    tbodyP2.innerHTML = '';
    (p2.details || []).forEach(item => {
      const isComplete = item.points === 3;
      if (activeFilter === 'missing' && isComplete) return;
      if (activeFilter === 'accounted' && !isComplete) return;

      const txtMatch = (item.app + ' ' + item.name + ' ' + item.src_ip + ' ' + item.dst_ip + ' ' + item.port).toLowerCase();
      if (q && !txtMatch.includes(q)) return;

      const tr = document.createElement('tr');
      const flowPill = item.flow_found
        ? '<span class="pill-status pill-earned">✓ Created</span>'
        : '<span class="pill-status pill-missing">✗ Missing</span>';

      const srcPill = item.src_ok
        ? '<span class="pill-status pill-earned">✓ Resolved</span>'
        : '<span class="pill-status pill-missing">✗ Missing</span>';

      const dstPill = item.dst_ok
        ? '<span class="pill-status pill-earned">✓ Resolved</span>'
        : '<span class="pill-status pill-missing">✗ Missing</span>';

      let ptBadge = '<span class="points-badge points-zero">0 / 3</span>';
      if (item.points === 3) ptBadge = '<span class="points-badge points-full">3 / 3</span>';
      else if (item.points === 2) ptBadge = '<span class="points-badge points-part">2 / 3</span>';
      else if (item.points === 1) ptBadge = '<span class="points-badge points-part">1 / 3</span>';

      tr.innerHTML = `
        <td><span style="font-weight:800; color:#ffb300;">${item.app}</span></td>
        <td style="font-weight:600;">${item.name}</td>
        <td style="color:#90a4ae;"><code>${item.src_ip} &rarr; ${item.dst_ip}:${item.port}</code></td>
        <td>${flowPill}</td>
        <td>${srcPill}</td>
        <td>${dstPill}</td>
        <td style="text-align:right;">${ptBadge}</td>
      `;
      tbodyP2.appendChild(tr);
    });
  }

  async function triggerAction(action) {
    const target = document.getElementById('adminTarget').value;
    const statusEl = document.getElementById('adminStatus');

    statusEl.style.color = '#ffb300';
    statusEl.innerText = 'Executing ' + action + ' on ' + target + '...';

    try {
      const res = await fetch('/api/admin/' + action, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: adminPin, target: target })
      });
      const data = await res.json();
      if (res.ok) {
        statusEl.style.color = '#00e676';
        statusEl.innerText = 'Success: ' + (data.message || 'Operation complete.');
        setTimeout(() => refreshAudit(true), 1500);
      } else {
        statusEl.style.color = '#f44336';
        statusEl.innerText = 'Failed: ' + (data.error || 'Unauthorized / Error');
      }
    } catch(e) {
      statusEl.style.color = '#f44336';
      statusEl.innerText = 'Network error executing action.';
    }
  }
</script>
</body>
</html>
"""


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
        elif self.path == "/api/scores":
            with CACHE_LOCK:
                resp = json.dumps(LATEST_DATA)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resp.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if payload.get("pin") != ADMIN_PIN:
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid PIN"}).encode("utf-8"))
            return

        # Audit breakdown query
        if self.path == "/api/admin/audit":
            if payload.get("refresh"):
                try:
                    refresh_scores()
                except Exception as e:
                    print(f"Error during refresh: {e}")
            with CACHE_LOCK:
                resp = json.dumps({
                    "delta": LATEST_DATA["delta"],
                    "omega": LATEST_DATA["omega"],
                    "delta_online": LATEST_DATA["delta_online"],
                    "omega_online": LATEST_DATA["omega_online"],
                    "last_updated": LATEST_DATA["last_updated"],
                })
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resp.encode("utf-8"))
            return

        target = payload.get("target", "both")
        teams = []
        if target in ("delta", "both"):
            teams.append("delta")
        if target in ("omega", "both"):
            teams.append("omega")

        if self.path == "/api/admin/reset":
            # Reset to KYE start: wipe dta-v2, then seed partial_day1.json
            for tm in teams:
                try:
                    run_reset(apply=True, team=tm, show_progress=False)
                    run_seed(PARTIAL_DAY1, apply=True, team=tm, show_progress=False)
                except Exception as e:
                    print(f"Error resetting {tm}: {e}")
            threading.Thread(target=refresh_scores, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"message": f"Reset {target} to KYE Day 1 state."}).encode("utf-8"))

        elif self.path == "/api/admin/complete":
            # Push 100% CTF Master
            for tm in teams:
                try:
                    run_seed(MASTER_JSON, apply=True, team=tm, show_progress=False)
                except Exception as e:
                    print(f"Error completing {tm}: {e}")
            threading.Thread(target=refresh_scores, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"message": f"Completed 100% CTF inventory for {target}."}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress spammy log output
        pass


def run_dashboard_server(host: str = "0.0.0.0", port: int = 8080):
    # Kick off background poller thread
    t = threading.Thread(target=background_poller, args=(30,), daemon=True)
    t.start()

    server = socketserver.ThreadingTCPServer((host, port), DashboardHandler)
    print(f"\n[+] KYE Split-Screen Classroom Dashboard running at:")
    print(f"    👉 http://localhost:{port}/")
    print(f"    (Delta: Blue fonts | Omega: Orange fonts)")
    print(f"    (Instructor audit dashboard & controls: press Ctrl+Shift+A)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[+] Dashboard stopped.")


if __name__ == "__main__":
    p = 8080
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        p = int(sys.argv[1])
    run_dashboard_server(port=p)
