"""NetBox connection helpers for the v2 tools with adaptive latency and rate limiting.

Features:
  - Unified Delta & Omega environment support via a single .env configuration.
  - Support for --localhost execution directly on the Malcolm VM host.
  - Adaptive pacing between API calls to prevent Gunicorn/Docker worker exhaustion on Malcolm.
  - Automatic retry with exponential backoff on timeouts, connection resets, and HTTP 429/502/503/504.
  - Pre-flight ping/latency check.
  - Configurable timeouts and pacing via environment variables.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple

import requests

try:
    from dotenv import load_dotenv as _dotenv_load
except Exception:
    _dotenv_load = None

PLACEHOLDER_TOKENS = {"", "your_api_token_here", "<api_token>", "your_delta_api_token_here", "your_omega_api_token_here"}


def _find_dotenv() -> Optional[Path]:
    here = Path(__file__).parent.resolve()
    for parent in [here, here.parent, *here.parents]:
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    return None


def _parse_env_file(path: Path) -> dict:
    data: dict = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.lower().startswith("export "):
                line = line[7:]
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                data[key] = val
    except Exception:
        pass
    return data


def _load_env(env_file: Optional[str]) -> None:
    path = Path(env_file) if env_file else _find_dotenv()
    if not path or not Path(path).exists():
        return
    if _dotenv_load is not None:
        _dotenv_load(path, override=False)
        return
    for key, val in _parse_env_file(Path(path)).items():
        os.environ.setdefault(key, val)


def _build_base_url() -> str:
    explicit = os.environ.get("NETBOX_URL")
    if explicit:
        return explicit.rstrip("/")

    host = os.environ.get("NETBOX_HOST") or "127.0.0.1"
    scheme = os.environ.get("NETBOX_SCHEME") or "https"
    port = os.environ.get("NETBOX_PORT") or ("443" if scheme == "https" else "80")
    path_prefix = (os.environ.get("NETBOX_PATH") or "netbox").strip("/")
    seg = f"/{path_prefix}" if path_prefix else ""
    default_port = (scheme == "https" and port == "443") or (scheme == "http" and port == "80")
    host_part = host if default_port else f"{host}:{port}"
    return f"{scheme}://{host_part}{seg}".rstrip("/")


@dataclass
class NetBoxConn:
    base_url: str   # e.g. https://host/netbox (no trailing /api)
    api_url: str    # e.g. https://host/netbox/api
    token: str
    verify_ssl: bool
    session: requests.Session
    pace_delay: float = 0.05    # Delay in seconds between write operations
    max_retries: int = 4        # Retries on 429/502/503/504 or network drops
    timeout_sec: int = 45       # Per-request read timeout

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return self.api_url.rstrip("/") + "/" + path.lstrip("/")

    def request(self, method: str, path: str, *, timeout: Optional[int] = None, **kw) -> requests.Response:
        """Adaptive request execution with pacing, exponential backoff, and retry."""
        url = self._url(path)
        to = timeout or self.timeout_sec

        # Apply write pacing delay between mutating calls to prevent Malcolm worker exhaustion
        if method.upper() in ("POST", "PATCH", "PUT", "DELETE") and self.pace_delay > 0:
            time.sleep(self.pace_delay)

        backoff = 0.5
        last_resp = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(method, url, timeout=to, **kw)
                last_resp = resp

                # Success or client validation error (don't retry 400/404)
                if resp.status_code < 400 or resp.status_code in (400, 404):
                    return resp

                # Rate limited or server transient errors (429, 502, 503, 504)
                if resp.status_code in (429, 502, 503, 504):
                    if attempt < self.max_retries:
                        retry_after = resp.headers.get("Retry-After")
                        sleep_time = float(retry_after) if retry_after and retry_after.isdigit() else backoff
                        time.sleep(sleep_time)
                        backoff *= 2.0
                        # Auto-tune pace delay upward if encountering rate limits
                        self.pace_delay = min(self.pace_delay * 1.5, 0.5)
                        continue
                return resp

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as ex:
                if attempt < self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2.0
                    self.pace_delay = min(self.pace_delay * 1.5, 0.5)
                    continue
                raise ex

        return last_resp  # type: ignore

    def get(self, path: str, **kw) -> requests.Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw) -> requests.Response:
        return self.request("POST", path, **kw)

    def patch(self, path: str, **kw) -> requests.Response:
        return self.request("PATCH", path, **kw)

    def delete(self, path: str, **kw) -> requests.Response:
        return self.request("DELETE", path, **kw)

    def options(self, path: str, **kw) -> requests.Response:
        return self.request("OPTIONS", path, **kw)

    def ping(self) -> Tuple[bool, float, str]:
        """Performs a lightweight health check to measure latency and availability.
        Returns: (success, latency_seconds, status_or_version_message)
        """
        t0 = time.time()
        try:
            r = self.session.get(self._url("status/"), timeout=4)
            elapsed = time.time() - t0
            if r.status_code == 200:
                ver = r.json().get("netbox-version", "Unknown")
                return True, elapsed, f"NetBox v{ver} (Latency: {elapsed*1000:.0f}ms)"
            return False, elapsed, f"HTTP {r.status_code}"
        except Exception as e:
            return False, time.time() - t0, str(e)


def get_connection(
    env_file: Optional[str] = None,
    team: Optional[str] = None,
    localhost: bool = False,
) -> NetBoxConn:
    """Build a read-ready NetBox connection from env/.env.

    Parameters:
      env_file: Path to specific env file (optional, defaults to repo .env).
      team: 'delta' or 'omega' to select team credentials from unified .env.
      localhost: If True, connects via 127.0.0.1 on the Malcolm VM host.
    """
    _load_env(env_file)

    team_str = (team or "").strip().lower() or None

    # Resolve Token:
    token = ""
    if team_str:
        token = (os.environ.get(f"{team_str.upper()}_NETBOX_TOKEN") or "").strip()
    if not token:
        token = (os.environ.get("NETBOX_TOKEN") or "").strip()

    # Resolve Base URL:
    if localhost:
        base_url = (os.environ.get("NETBOX_LOCAL_URL") or "https://127.0.0.1/netbox").rstrip("/")
    elif team_str:
        team_url = (os.environ.get(f"{team_str.upper()}_NETBOX_URL") or "").strip()
        base_url = team_url.rstrip("/") if team_url else _build_base_url()
    else:
        base_url = _build_base_url()

    api_url = base_url + "/api"

    verify_raw = (
        os.environ.get("NETBOX_VERIFY_SSL")
        or os.environ.get("VERIFY_SSL")
        or "False"
    ).strip().lower()
    verify_ssl = verify_raw in ("true", "1", "yes", "t")

    # Read pacing & timeout overrides from environment if provided
    try:
        pace_ms = float(os.environ.get("NETBOX_PACE_MS", 75))
        pace_delay = max(pace_ms / 1000.0, 0.0)
    except Exception:
        pace_delay = 0.075

    try:
        timeout_sec = int(os.environ.get("NETBOX_TIMEOUT", 45))
    except Exception:
        timeout_sec = 45

    if token in PLACEHOLDER_TOKENS:
        target_name = f"Team {team_str.capitalize()}" if team_str else "default instance"
        env_var_name = f"{team_str.upper()}_NETBOX_TOKEN" if team_str else "NETBOX_TOKEN"
        raise RuntimeError(
            f"NetBox token for {target_name} is not configured (or is still a placeholder). "
            f"Please set {env_var_name} in your .env file (resolved URL: {base_url})."
        )

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    session.verify = verify_ssl
    if not verify_ssl:
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass

    return NetBoxConn(
        base_url=base_url,
        api_url=api_url,
        token=token,
        verify_ssl=verify_ssl,
        session=session,
        pace_delay=pace_delay,
        timeout_sec=timeout_sec,
    )
