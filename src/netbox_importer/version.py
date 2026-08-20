"""Version information for netbox-excel-importer."""
from pathlib import Path

VERSION_FILE = Path(__file__).parent.parent.parent / "VERSION"

if VERSION_FILE.exists():
    __version__ = VERSION_FILE.read_text(encoding="utf-8").strip()
else:
    __version__ = "1.3.0"
