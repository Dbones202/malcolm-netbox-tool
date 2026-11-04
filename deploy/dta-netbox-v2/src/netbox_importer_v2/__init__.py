"""NetBox Importer v2 — advanced, master-driven importer and scorer.

Sits alongside the v1 ``netbox_importer`` package and never modifies it.
v2 adds: multi-NIC devices, multiple IPs per interface, MAC addresses,
services derived from open ports, and data-flows (via the netbox-data-flows
plugin). A single declarative master definition drives three tools:
full seed, partial seed, and a live-vs-master scorer.
"""
from .version import __version__

__all__ = ["__version__"]
