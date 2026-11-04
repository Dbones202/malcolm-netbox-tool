"""CLI entry point for the NetBox v2 importer.

Available now:
  discover      Read-only API introspection -> saved report (needs a real .env token).

Planned (built after discovery + day-1 materials are in hand):
  build-master  Assemble/validate the master YAML (optionally from white-cell export).
  seed          Full seed of the complete environment from the master.
  seed-partial  Seed an incomplete 'starting' environment from the master.
  score         Diff a live (blue-team) NetBox against the master -> gap/score report.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console

from .version import __version__

console = Console()
PLANNED = {
    "score": "Diff a live NetBox against the master -> gap/score report.",
}


def _print_discovery_summary(rep: dict) -> None:
    console.print(f"\n[bold blue]NetBox API Discovery[/bold blue]  (netbox v{rep.get('netbox_version')})")
    console.print(f"  API: [cyan]{rep['connection']['api_url']}[/cyan]  verify_ssl={rep['connection']['verify_ssl']}")

    plugins = rep.get("installed_plugins") or {}
    if plugins:
        names = ", ".join(sorted(plugins.keys())) if isinstance(plugins, dict) else str(plugins)
        console.print(f"  [white]Plugins:[/white] {names}")

    mac = rep.get("mac_model", {})
    console.print("\n[bold white]MAC model:[/bold white]")
    console.print(f"  first-class mac-addresses objects: [cyan]{mac.get('first_class_mac_objects')}[/cyan]")
    console.print(f"  interface.primary_mac_address: [cyan]{mac.get('interface_has_primary_mac_address')}[/cyan] | "
                  f"legacy mac_address: [cyan]{mac.get('interface_has_legacy_mac_field')}[/cyan]")
    console.print(f"  -> [green]{mac.get('recommended_approach')}[/green]")

    df = rep.get("dataflows", {})
    console.print("\n[bold white]netbox-data-flows plugin:[/bold white]")
    if df.get("installed"):
        eps = ", ".join(sorted((df.get("endpoints") or {}).keys()))
        console.print(f"  [green]installed[/green] at /api/{df.get('base')}  endpoints: {eps}")
    else:
        console.print(f"  [yellow]not detected[/yellow] — {df.get('note')}")

    console.print("\n[bold white]Current object counts:[/bold white]")
    for ep, c in (rep.get("counts") or {}).items():
        console.print(f"  {ep}: [cyan]{c}[/cyan]")

    svc = rep.get("service_fields", {})
    if svc.get("protocol", {}).get("choices"):
        console.print(f"\n[white]ipam/services protocol choices:[/white] {svc['protocol']['choices']}")


def cmd_discover(args) -> int:
    from .discover import run_discovery
    try:
        rep = run_discovery(env_file=args.env_file)
    except Exception as e:
        console.print(f"[bold red]Discovery failed:[/bold red] {e}")
        return 1

    _print_discovery_summary(rep)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_file = out_dir / f"discovery-{stamp}.json"
    out_file.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    console.print(f"\n[bold green]Full report written to:[/bold green] [cyan]{out_file}[/cyan]")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="netbox-v2",
        description="NetBox v2 importer — master-driven seeding and scoring.",
    )
    parser.add_argument("--version", action="version", version=f"netbox-importer-v2 {__version__}")
    sub = parser.add_subparsers(dest="command")

    d = sub.add_parser("discover", help="Read-only API introspection -> saved report.")
    d.add_argument("--env-file", default=None, help="Path to .env (default: auto-detect repo .env).")
    d.add_argument("--out", default="v2_reports", help="Directory for the JSON report (default: v2_reports/).")

    du = sub.add_parser("dump", help="Read-only export of existing NetBox objects -> instance_inventory.json.")
    du.add_argument("--env-file", default=None)
    du.add_argument("--out", default="v2_reports/instance_inventory.json")

    rs = sub.add_parser("reset", help="Wipe NetBox objects (plan by default; --apply to delete).")
    rs.add_argument("--env-file", default=None)
    rs.add_argument("--apply", action="store_true", help="Actually delete (otherwise dry-run plan).")

    se = sub.add_parser("seed", help="Seed NetBox from a master file (plan by default; --apply to write).")
    se.add_argument("--master", default="v2_reports/master.json", help="master.json or a partial_*.json")
    se.add_argument("--env-file", default=None)
    se.add_argument("--apply", action="store_true", help="Actually write (otherwise dry-run plan).")

    for name, desc in PLANNED.items():
        sub.add_parser(name, help=f"(planned) {desc}")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "discover":
        sys.exit(cmd_discover(args))
    elif args.command == "dump":
        from .dump_instance import run_dump
        import json as _json
        try:
            inv = run_dump(env_file=args.env_file)
        except Exception as e:
            console.print(f"[bold red]Dump failed:[/bold red] {e}"); sys.exit(1)
        import os as _os
        _os.makedirs(_os.path.dirname(args.out) or ".", exist_ok=True)
        _json.dump(inv, open(args.out, "w"), indent=2)
        console.print(f"[green]Wrote[/green] {args.out}  (sites={len(inv.get('sites',[]))}, devices={len(inv.get('devices',[]))}, dataflows={len(inv.get('df_dataflows',[]))})")
        sys.exit(0)
    elif args.command == "reset":
        from .seeder import run_reset
        if args.apply:
            console.print("[bold red]APPLY: deleting objects from NetBox...[/bold red]")
        s = run_reset(apply=args.apply, env_file=args.env_file)
        sys.exit(0 if not s.errors else 1)
    elif args.command == "seed":
        from .seeder import run_seed
        console.print(f"[white]Seeding from[/white] [cyan]{args.master}[/cyan] "
                      + ("[bold red](APPLY)[/bold red]" if args.apply else "[yellow](plan / dry-run)[/yellow]"))
        s = run_seed(args.master, apply=args.apply, env_file=args.env_file)
        if s.errors:
            console.print(f"[red]{len(s.errors)} errors[/red] - see v2_reports/seed_result.json")
        sys.exit(0 if not s.errors else 1)
    elif args.command in PLANNED:
        console.print(f"[yellow]'{args.command}' is planned but not built yet.[/yellow]")
        console.print("It will be implemented after API discovery and review of the day-1 materials.")
        sys.exit(2)


if __name__ == "__main__":
    main()
