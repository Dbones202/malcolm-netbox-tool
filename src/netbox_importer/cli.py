"""Command Line Interface (CLI) entry point for NetBox Excel Device Importer."""
import sys
import argparse
from pathlib import Path
from rich.console import Console

from .template_generator import create_template_excel
from .validator import validate_excel_file
from .importer import NetBoxDeviceImporter

console = Console()


def main():
    parser = argparse.ArgumentParser(
        prog="netbox-excel-importer",
        description="Packaged CLI to validate and import devices, interfaces, and primary IPs into NetBox from Excel."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Subcommand: import
    import_parser = subparsers.add_parser("import", help="Validate and import devices from an Excel file into NetBox.")
    import_parser.add_argument("excel_file", help="Path to input Excel spreadsheet (.xlsx)")
    import_parser.add_argument("--dry-run", action="store_true", help="Perform pre-flight validation and dry run without writing changes to NetBox.")

    # Subcommand: validate
    validate_parser = subparsers.add_parser("validate", help="Run pre-flight validation on an Excel file without connecting to NetBox.")
    validate_parser.add_argument("excel_file", help="Path to input Excel spreadsheet (.xlsx)")

    # Subcommand: generate-template
    template_parser = subparsers.add_parser("generate-template", help="Generate a sample 2-sheet Excel file with test devices and config template.")
    template_parser.add_argument("output_path", nargs="?", default="netbox_test_devices.xlsx", help="Destination path for generated Excel file (default: netbox_test_devices.xlsx)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "generate-template":
        try:
            out_file = create_template_excel(args.output_path)
            console.print(f"[bold green]✓ Template generated successfully at:[/bold green] [cyan]{out_file}[/cyan]")
            sys.exit(0)
        except Exception as e:
            console.print(f"[bold red]✗ Failed to generate template:[/bold red] {str(e)}")
            sys.exit(1)

    elif args.command == "validate":
        res = validate_excel_file(args.excel_file)
        console.print(f"[bold blue]Pre-Flight Validation Report for '{args.excel_file}'[/bold blue]")
        for wrn in res.warnings:
            console.print(f"  [yellow]WARNING:[/yellow] {wrn}")

        if res.is_valid:
            console.print(f"  [bold green]✓ PASSED:[/bold green] {len(res.devices)} valid device rows found.")
            console.print("\n[bold white]Parsed Configuration:[/bold white]")
            for k, v in res.config.items():
                if "TOKEN" in k and v:
                    display_v = v[:4] + "..." + v[-4:]
                else:
                    display_v = v
                console.print(f"  {k}: [cyan]{display_v}[/cyan]")
            sys.exit(0)
        else:
            console.print(f"  [bold red]✗ FAILED:[/bold red] Found {len(res.errors)} validation error(s):")
            for err in res.errors:
                console.print(f"    [red]• {err}[/red]")
            sys.exit(1)

    elif args.command == "import":
        importer = NetBoxDeviceImporter(args.excel_file, dry_run=args.dry_run)
        success = importer.run()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
