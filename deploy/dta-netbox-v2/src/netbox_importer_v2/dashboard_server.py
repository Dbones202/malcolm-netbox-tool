"""Classroom Live Split-Screen Dashboard Server for KYE Day 1 NetBox Challenge.

Serves auto-updating split-screen dashboard for Team Delta (Blue) and Team Omega (Orange).
Polls NetBox APIs every 30 seconds or on demand.
Includes discrete, non-obvious Admin controls to Reset to Day 1 or Complete CTF Inventory.
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

from .scorer import NetBoxScorer
from .seeder import run_reset, run_seed

HERE = Path(__file__).parent.resolve()
ROOT_REPO = HERE.parent.parent

DELTA_ENV = str(HERE / "delta_env.txt")
OMEGA_ENV = str(HERE / "omega_env.txt")
PARTIAL_DAY1 = str(ROOT_REPO / "v2_reports" / "partial_day1.json")
MASTER_JSON = str(ROOT_REPO / "v2_reports" / "master.json")

ADMIN_PIN = "instructor"

# In-memory score cache
CACHE_LOCK = threading.Lock()
LATEST_DATA: Dict[str, Any] = {
    "delta": {"total_score": 0, "max_score": 75, "categories": {"corrected_data": {"points": 0, "max": 18}, "missing_entries": {"points": 0, "max": 18}, "missing_dataflow": {"points": 0, "max": 39}}},
    "omega": {"total_score": 0, "max_score": 75, "categories": {"corrected_data": {"points": 0, "max": 18}, "missing_entries": {"points": 0, "max": 18}, "missing_dataflow": {"points": 0, "max": 39}}},
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
            delta_res = {"error": str(e), "total_score": 0, "max_score": 75, "categories": {
                "corrected_data": {"points": 0, "max": 18}, "missing_entries": {"points": 0, "max": 18}, "missing_dataflow": {"points": 0, "max": 39}
            }}

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
            omega_res = {"error": str(e), "total_score": 0, "max_score": 75, "categories": {
                "corrected_data": {"points": 0, "max": 18}, "missing_entries": {"points": 0, "max": 18}, "missing_dataflow": {"points": 0, "max": 39}
            }}

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

  /* Hidden Modal */
  .modal-backdrop {
    display: none;
    position: fixed;
    top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(0, 0, 0, 0.85);
    backdrop-filter: blur(10px);
    z-index: 1000;
    align-items: center;
    justify-content: center;
  }
  .modal-box {
    background: #141b24;
    border: 1px solid #2a3b4c;
    border-radius: 12px;
    padding: 32px;
    width: 480px;
    box-shadow: 0 20px 40px rgba(0,0,0,0.8);
  }
  .modal-box h3 { margin-bottom: 16px; font-size: 18px; color: #fff; }
  .modal-row { margin-bottom: 20px; display: flex; flex-direction: column; gap: 8px; }
  .modal-row label { font-size: 13px; color: #90a4ae; }
  .modal-box input, .modal-box select {
    background: #0d1219; border: 1px solid #37474f; border-radius: 6px; padding: 10px 14px; color: #fff; font-size: 14px; outline: none;
  }
  .modal-actions { display: flex; gap: 12px; margin-top: 24px; }
  .btn {
    flex: 1; padding: 12px; border-radius: 6px; font-weight: 700; font-size: 14px; cursor: pointer; border: none; transition: opacity 0.2s;
  }
  .btn-reset { background: #d32f2f; color: #fff; }
  .btn-complete { background: #2e7d32; color: #fff; }
  .btn-close { background: #37474f; color: #fff; }
  .btn:hover { opacity: 0.85; }
  .status-msg { margin-top: 14px; font-size: 13px; text-align: center; }
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
  <div class="secret-dot" id="adminTrigger" title=""></div>
</footer>

<!-- Discrete Admin Modal -->
<div class="modal-backdrop" id="adminModal">
  <div class="modal-box">
    <h3>Instructor Control Console</h3>
    <div class="modal-row">
      <label>Passcode</label>
      <input type="password" id="adminPin" placeholder="Instructor PIN">
    </div>
    <div class="modal-row">
      <label>Target Environment</label>
      <select id="adminTarget">
        <option value="both">Both Teams (Delta & Omega)</option>
        <option value="delta">Team Delta Only</option>
        <option value="omega">Team Omega Only</option>
      </select>
    </div>
    <div class="modal-actions">
      <button class="btn btn-reset" onclick="triggerAction('reset')">Reset to KYE Start</button>
      <button class="btn btn-complete" onclick="triggerAction('complete')">Complete CTF Inventory</button>
    </div>
    <div style="margin-top: 12px; text-align: right;">
      <button class="btn btn-close" onclick="closeAdmin()">Close</button>
    </div>
    <div class="status-msg" id="adminStatus"></div>
  </div>
</div>

<script>
  let timer = 30;

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
    if (e.ctrlKey && e.shiftKey && e.code === 'KeyA') {
      openAdmin();
    }
  });

  function openAdmin() {
    document.getElementById('adminModal').style.display = 'flex';
    document.getElementById('adminStatus').innerText = '';
  }
  function closeAdmin() {
    document.getElementById('adminModal').style.display = 'none';
  }

  async function triggerAction(action) {
    const pin = document.getElementById('adminPin').value;
    const target = document.getElementById('adminTarget').value;
    const statusEl = document.getElementById('adminStatus');

    statusEl.style.color = '#ffb300';
    statusEl.innerText = 'Executing ' + action + ' on ' + target + '...';

    try {
      const res = await fetch('/api/admin/' + action, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: pin, target: target })
      });
      const data = await res.json();
      if (res.ok) {
        statusEl.style.color = '#00e676';
        statusEl.innerText = 'Success: ' + (data.message || 'Operation complete.');
        setTimeout(updateScores, 1500);
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
    print(f"    (Admin console hidden in bottom-right corner or press Ctrl+Shift+A)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[+] Dashboard stopped.")


if __name__ == "__main__":
    p = 8080
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        p = int(sys.argv[1])
    run_dashboard_server(port=p)

