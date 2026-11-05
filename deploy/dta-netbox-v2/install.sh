#!/usr/bin/env bash
# Offline installer. No internet. Prefers venv; falls back to ./vendor if venv/ensurepip absent.
set -euo pipefail
export PIP_DISABLE_PIP_VERSION_CHECK=1
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
echo "[*] Python: $(python3 --version 2>&1)  arch=$(uname -m)"
if python3 -c 'import ensurepip, venv' >/dev/null 2>&1; then
  echo "[*] venv available -> building ./venv"
  python3 -m venv venv
  ./venv/bin/python -m pip install --no-index --find-links wheels -r requirements.txt
  VERIFY_PY="./venv/bin/python"; VERIFY_ENV=""
else
  echo "[*] venv/ensurepip NOT available -> installing into ./vendor (no venv needed)"
  python3 -m pip install --no-index --find-links wheels --target vendor -r requirements.txt --root-user-action=ignore
  VERIFY_PY="python3"; VERIFY_ENV="$HERE/vendor"
fi
echo "[*] Verifying deps…"
PYTHONPATH="$VERIFY_ENV" "$VERIFY_PY" - <<'PY'
import importlib.metadata as m
import requests, rich  # import-check
print("    requests", m.version("requests"), "| rich", m.version("rich"), "-> OK")
PY
echo "[*] Install complete. Example:"
echo "    ./netbox-v2.sh dump  --env-file src/netbox_importer_v2/delta_env.txt"
echo "    ./netbox-v2.sh reset --apply --env-file src/netbox_importer_v2/delta_env.txt"
echo "    ./netbox-v2.sh seed  --apply --env-file src/netbox_importer_v2/delta_env.txt"
