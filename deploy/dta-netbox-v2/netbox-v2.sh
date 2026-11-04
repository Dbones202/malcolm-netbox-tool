#!/usr/bin/env bash
# Run the v2 importer tools against the live NetBox from this repo on the Mac.
# Usage: ./netbox-v2.sh discover|seed|seed-partial|score  [args]
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
PYTHONPATH="$HERE/src" "$PY" -m netbox_importer_v2.cli "$@"
