"""CLI entry point for the NetBox v2 importer, scorer, and dashboard.

Commands:
  discover      Read-only API introspection -> saved report.
  dump          Read-only export of existing NetBox objects -> instance_inventory.json.
  seed          Seed NetBox from master or partial Day 1.
  reset         Wipe NetBox objects (plan by default; --apply to delete).
  score         Grade a live instance against the 75-point rubric.
  dashboard     Run live split-screen classroom dashboard server for Delta & Omega.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from rich.console import Console

from .version import __version__

console = Console()
PLANNED = {}


def _resolve_team_and_localhost(args) -> Tuple[Optional[str], bool]:
    """Helper to resolve team name and localhost flag from CLI arguments.
    Supports:
      --localhost delta   -> team='delta', localhost=True
      --localhost omega   -> team='omega', localhost=True
      --localhost         -> team=args.team or None, localhost=True
      --team delta        -> team='delta', localhost=False
    """
    localhost_arg = getattr(args, "localhost", None)
    team_arg = getattr(args, "team", None)

    is_localhost = localhost_arg is not None
    if localhost_arg in ("delta", "omega"):
        team = localhost_arg
    elif team_arg:
        team = team_arg
    else:
        team = None
    return team, is_localhost


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
    team, localhost = _resolve_team_and_localhost(args)
    try:
        rep = run_discovery(env_file=args.env_file, team=team, localhost=localhost)
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


def cmd_score(args) -> int:
    from .scorer import NetBoxScorer
    from rich.table import Table
    from rich.panel import Panel

    team, localhost = _resolve_team_and_localhost(args)
    target_desc = f"Team {team.capitalize()}" if team else "Default"
    if localhost:
        target_desc += " (localhost)"

    console.print(Panel.fit(f"[bold blue]KYE Day 1 NetBox Challenge Scorer[/bold blue] (Target: {target_desc})", border_style="cyan"))
    scorer = NetBoxScorer(env_file=args.env_file, team=team, localhost=localhost)
    try:
        res = scorer.score()
    except Exception as e:
        console.print(f"[bold red]Scoring failed:[/bold red] {e}")
        return 1

    cats = res["categories"]
    m1 = cats["corrected_data"]
    m2 = cats["missing_entries"]
    m3 = cats["missing_dataflow"]

    table = Table(title="Score Breakdown", show_header=True, header_style="bold magenta")
    table.add_column("Category", style="white", width=24)
    table.add_column("Progress", style="cyan", width=18)
    table.add_column("Points Earned", style="green", justify="right")
    table.add_column("Max Possible", style="yellow", justify="right")

    table.add_row("Corrected Data", f"{m1['count']} / {m1['total']} devices", f"{m1['points']} pts", f"{m1['max']} pts")
    table.add_row("Missing Entries", f"{m2['count']} / {m2['total']} items", f"{m2['points']} pts", f"{m2['max']} pts")
    table.add_row("Missing DataFlow", f"{m3['count']} / {m3['total']} flows", f"{m3['points']} pts", f"{m3['max']} pts")
    table.add_section()
    table.add_row("[bold]TOTAL SCORE[/bold]", f"[bold]{res['percentage']}% Complete[/bold]", f"[bold green]{res['total_score']} pts[/bold green]", f"[bold]{res['max_score']} pts[/bold]")

    console.print(table)

    if getattr(args, "details", False):
        # 1. Part 1: Redacted Assets
        t1 = Table(title="\nPart 1: Redacted Assets & IPs (9 Items - 18 pts max)", show_header=True, header_style="bold blue")
        t1.add_column("Canonical Name", style="white")
        t1.add_column("Expected IPv4", style="cyan")
        t1.add_column("IP in IPAM", style="magenta")
        t1.add_column("Device Bound", style="magenta")
        t1.add_column("Matched Name", style="white")
        t1.add_column("Points", style="green", justify="right")
        for item in m2.get("details", []):
            ip_st = "[green]✓ Found[/green]" if item.get("ip_found") else "[red]✗ Missing[/red]"
            dev_st = "[green]✓ Bound[/green]" if item.get("device_bound") else "[red]✗ Unbound[/red]"
            pts = f"{item.get('points', 0)} / 2"
            t1.add_row(item.get("canonical", ""), item.get("ip", ""), ip_st, dev_st, item.get("found_dev_name") or "-", pts)
        console.print(t1)

        # 2. Part 2: Missing DataFlows
        t2 = Table(title="\nPart 2: Missing Industrial DataFlows (13 Items - 39 pts max)", show_header=True, header_style="bold cyan")
        t2.add_column("App", style="yellow", width=6)
        t2.add_column("Flow Name", style="white")
        t2.add_column("Endpoints & Port", style="dim")
        t2.add_column("Flow Record", style="magenta")
        t2.add_column("Src Resolved", style="magenta")
        t2.add_column("Dst Resolved", style="magenta")
        t2.add_column("Points", style="green", justify="right")
        for item in m3.get("details", []):
            f_st = "[green]✓ Created[/green]" if item.get("flow_found") else "[red]✗ Missing[/red]"
            s_st = "[green]✓ OK[/green]" if item.get("src_ok") else "[red]✗ Missing[/red]"
            d_st = "[green]✓ OK[/green]" if item.get("dst_ok") else "[red]✗ Missing[/red]"
            ep = f"{item.get('src_ip')} → {item.get('dst_ip')} ({item.get('port')})"
            pts = f"{item.get('points', 0)} / 3"
            t2.add_row(item.get("app", ""), item.get("name", ""), ep, f_st, s_st, d_st, pts)
        console.print(t2)

        # 3. Part 3: Tampered Devices
        t3 = Table(title="\nPart 3: Tampered Devices (6 Items - 18 pts max)", show_header=True, header_style="bold yellow")
        t3.add_column("Device", style="white")
        t3.add_column("Real Expected IPv4", style="green")
        t3.add_column("Bogus Starting IP", style="dim")
        t3.add_column("Current NetBox IP", style="cyan")
        t3.add_column("Status", style="magenta")
        t3.add_column("Points", style="green", justify="right")
        for item in m1.get("details", []):
            st = "[green]✓ Corrected[/green]" if item.get("is_corrected") else "[red]✗ Tampered[/red]"
            pts = f"{item.get('points', 0)} / 3"
            t3.add_row(item.get("device", ""), item.get("real_ip", ""), item.get("wrong_ip", ""), item.get("current_ip") or "[dim]None[/dim]", st, pts)
        console.print(t3)

    return 0


def cmd_dashboard(args) -> int:
    from .dashboard_server import run_dashboard_server
    run_dashboard_server(host=args.host, port=args.port)
    return 0


def cmd_perms(args) -> int:
    from .connection import get_connection
    from .permissions import fix_student_permissions

    team, localhost = _resolve_team_and_localhost(args)
    conn = get_connection(env_file=args.env_file, team=team, localhost=localhost)
    summary = fix_student_permissions(
        conn=conn,
        usernames=args.users,
        group_name=args.group,
        apply=args.apply,
    )
    return 0 if not summary.get("errors") else 1


def _add_connection_args(parser: argparse.ArgumentParser) -> None:
    """Adds common connection flags (--team and --localhost) across subcommands."""
    parser.add_argument(
        "--team",
        choices=["delta", "omega"],
        default=None,
        help="Target remote team NetBox instance (delta or omega).",
    )
    parser.add_argument(
        "--localhost",
        nargs="?",
        const="default",
        choices=["delta", "omega", "default"],
        default=None,
        help="Target local loopback (127.0.0.1) on Malcolm VM. E.g. --localhost delta or --localhost omega.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="netbox-v2",
        description="NetBox v2 importer — master-driven seeding, scoring, and live classroom dashboard.",
    )
    parser.add_argument("--version", action="version", version=f"netbox-importer-v2 {__version__}")
    sub = parser.add_subparsers(dest="command")

    d = sub.add_parser("discover", help="Read-only API introspection -> saved report.")
    d.add_argument("--env-file", default=None, help="Path to .env (default: auto-detect repo .env).")
    d.add_argument("--out", default="v2_reports", help="Directory for the JSON report (default: v2_reports/).")
    _add_connection_args(d)

    du = sub.add_parser("dump", help="Read-only export of existing NetBox objects -> instance_inventory.json.")
    du.add_argument("--env-file", default=None)
    du.add_argument("--out", default="v2_reports/instance_inventory.json")
    _add_connection_args(du)

    rs = sub.add_parser("reset", help="Wipe NetBox objects (plan by default; --apply to delete).")
    rs.add_argument("--env-file", default=None)
    rs.add_argument("--apply", action="store_true", help="Actually delete (otherwise dry-run plan).")
    _add_connection_args(rs)

    se = sub.add_parser("seed", help="Seed NetBox from a master file (plan by default; --apply to write).")
    se.add_argument("--master", default="v2_reports/master.json", help="master.json or a partial_*.json")
    se.add_argument("--env-file", default=None)
    se.add_argument("--apply", action="store_true", help="Actually write (otherwise dry-run plan).")
    _add_connection_args(se)

    sc = sub.add_parser("score", help="Score a live instance against the 75-pt KYE Day 1 rubric.")
    sc.add_argument("--env-file", default=None)
    sc.add_argument("--details", "--audit", action="store_true", help="Print item-by-item breakdown of all 28 scorable points.")
    _add_connection_args(sc)

    dash = sub.add_parser("dashboard", help="Start the live split-screen classroom dashboard.")
    dash.add_argument("--host", default="0.0.0.0", help="Binding host (default: 0.0.0.0)")
    dash.add_argument("--port", type=int, default=8080, help="HTTP port (default: 8080)")

    p = sub.add_parser("perms", help="Re-assign and define student permissions (revoke superuser, restrict changelog).")
    p.add_argument("--env-file", default=None)
    p.add_argument("--apply", action="store_true", help="Actually apply permission changes (otherwise dry-run plan).")
    p.add_argument("--users", nargs="+", default=None, help="Usernames to fix (default: delta-user omega-user).")
    p.add_argument("--group", default="student", help="Target student group name (default: student).")
    _add_connection_args(p)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "discover":
        sys.exit(cmd_discover(args))
    elif args.command == "dump":
        from .dump_instance import run_dump
        import os as _os
        team, localhost = _resolve_team_and_localhost(args)
        try:
            inv = run_dump(env_file=args.env_file, team=team, localhost=localhost)
        except Exception as e:
            console.print(f"[bold red]Dump failed:[/bold red] {e}")
            sys.exit(1)
        _os.makedirs(_os.path.dirname(args.out) or ".", exist_ok=True)
        json.dump(inv, open(args.out, "w"), indent=2)
        console.print(f"[green]Wrote[/green] {args.out}  (sites={len(inv.get('sites',[]))}, devices={len(inv.get('devices',[]))}, dataflows={len(inv.get('df_dataflows',[]))})")
        sys.exit(0)
    elif args.command == "reset":
        from .seeder import run_reset
        team, localhost = _resolve_team_and_localhost(args)
        if args.apply:
            console.print("[bold red]APPLY: deleting objects from NetBox...[/bold red]")
        s = run_reset(apply=args.apply, env_file=args.env_file, team=team, localhost=localhost)
        sys.exit(0 if not s.errors else 1)
    elif args.command == "seed":
        from .seeder import run_seed
        team, localhost = _resolve_team_and_localhost(args)
        console.print(f"[white]Seeding from[/white] [cyan]{args.master}[/cyan] "
                      + ("[bold red](APPLY)[/bold red]" if args.apply else "[yellow](plan / dry-run)[/yellow]"))
        s = run_seed(args.master, apply=args.apply, env_file=args.env_file, team=team, localhost=localhost)
        if s.errors:
            console.print(f"[red]{len(s.errors)} errors[/red] - see v2_reports/seed_result.json")
        sys.exit(0 if not s.errors else 1)
    elif args.command == "score":
        sys.exit(cmd_score(args))
    elif args.command == "dashboard":
        sys.exit(cmd_dashboard(args))
    elif args.command == "perms":
        sys.exit(cmd_perms(args))


if __name__ == "__main__":
    main()
