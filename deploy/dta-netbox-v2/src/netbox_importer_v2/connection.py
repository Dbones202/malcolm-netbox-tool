"""NetBox connection helpers for the v2 tools.

Shares credentials with v1 by reading the repo ``.env`` (or an explicit
``--env-file``). Supports either an explicit ``NETBOX_URL`` or a Malcolm-style
host/path/port/scheme construction, mirroring v1's validator logic.

``.env`` is loaded via python-dotenv when available, otherwise via a small
built-in parser — so the v2 tools work even on an air-gapped host that doesn't
have python-dotenv installed.

Exposes a thin wrapper over ``requests`` so the discovery stage can make raw
GET/OPTIONS calls (OPTIONS field/choice introspection isn't surfaced by
pynetbox).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

try:
    from dotenv import load_dotenv as _dotenv_load
except Exception:  # python-dotenv not installed
    _dotenv_load = None

PLACEHOLDER_TOKENS = {"", "your_api_token_here", "<api_token>"}


def _find_dotenv() -> Optional[Path]:
    """Walk up from this file to locate a repo-root ``.env``."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    return None


def _parse_env_file(path: Path) -> dict:
    """Minimal KEY=VALUE .env parser (fallback when python-dotenv is absent)."""
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
    """Load .env into os.environ without overriding already-set vars."""
    path = Path(env_file) if env_file else _find_dotenv()
    if not path or not Path(path).exists():
        return
    if _dotenv_load is not None:
        _dotenv_load(path, override=False)
        return
    for key, val in _parse_env_file(Path(path)).items():
        os.environ.setdefault(key, val)


def _build_base_url() -> str:
    """Return the NetBox base URL (no trailing ``/api``)."""
    explicit = os.environ.get("NETBOX_URL")
    if explicit:
        return explicit.rstrip("/")

    # Default: run ON the Malcolm host and talk to its local NetBox (no IP needed).
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
    base_url: str   # e.g. https://host/netbox      (no trailing /api)
    api_url: str    # e.g. https://host/netbox/api
    token: str
    verify_ssl: bool
    session: requests.Session

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return self.api_url.rstrip("/") + "/" + path.lstrip("/")

    def get(self, path: str, *, timeout: int = 30, **kw) -> requests.Response:
        return self.session.get(self._url(path), timeout=timeout, **kw)

    def options(self, path: str, *, timeout: int = 30, **kw) -> requests.Response:
        return self.session.options(self._url(path), timeout=timeout, **kw)


def get_connection(env_file: Optional[str] = None) -> NetBoxConn:
    """Build a read-ready NetBox connection from env/.env.

    Raises RuntimeError if the token is missing or still a placeholder.
    """
    _load_env(env_file)

    base_url = _build_base_url()
    api_url = base_url + "/api"
    token = (os.environ.get("NETBOX_TOKEN") or "").strip()

    verify_raw = (
        os.environ.get("NETBOX_VERIFY_SSL")
        or os.environ.get("VERIFY_SSL")
        or "False"
    ).strip().lower()
    verify_ssl = verify_raw in ("true", "1", "yes", "t")

    if token in PLACEHOLDER_TOKENS:
        raise RuntimeError(
            "NETBOX_TOKEN is not set (still a placeholder). Put a real token in "
            f".env (resolved NetBox base: {base_url}) before running v2 tools."
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
    )
