"""Core Importer Engine connecting to NetBox REST API via pynetbox."""
import sys
import urllib3
from typing import Dict, Any, List
import pynetbox
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .validator import validate_excel_file, ValidationResult

console = Console()


def _slugify(text: str) -> str:
    """Converts a string into a valid NetBox slug."""
    clean = "".join(c.lower() if c.isalnum() else "-" for c in text.strip())
    while "--" in clean:
        clean = clean.replace("--", "-")
    return clean.strip("-") or "default"


class NetBoxDeviceImporter:
    def __init__(self, excel_path: str, dry_run: bool = False):
        self.excel_path = excel_path
        self.dry_run = dry_run
        self.validation: ValidationResult = None
        self.nb: Any = None
        self.site_obj: Any = None
        self.role_obj: Any = None
        self.manufacturer_obj: Any = None
        self.device_type_obj: Any = None

    def run(self) -> bool:
        """Executes full validation and device import process."""
        console.print(Panel.fit("[bold blue]NetBox Excel Device Importer[/bold blue]", border_style="blue"))
        
        # Step 1: Pre-flight Spreadsheet Validation
        console.print(f"[bold white]1. Performing Pre-Flight Spreadsheet Validation...[/bold white] ({self.excel_path})")
        self.validation = validate_excel_file(self.excel_path)

        for wrn in self.validation.warnings:
            console.print(f"  [yellow]WARNING:[/yellow] {wrn}")

        if not self.validation.is_valid:
            console.print("\n[bold red]PRE-FLIGHT VALIDATION FAILED![/bold red] Please fix the following errors:")
            for err in self.validation.errors:
                console.print(f"  [bold red]✗[/bold red] {err}")
            return False

        console.print(f"  [green]✓ Spreadsheet validation passed![/green] ({len(self.validation.devices)} valid device entries found)")

        cfg = self.validation.config
        netbox_url = cfg["NETBOX_URL"]
        token = cfg["NETBOX_TOKEN"]
        verify_ssl = cfg["VERIFY_SSL"].lower() == "true"
        interface_name = cfg["INTERFACE_NAME"]

        if self.dry_run:
            console.print("\n[bold yellow]*** RUNNING IN DRY-RUN MODE (NO CHANGES WILL BE WRITTEN TO NETBOX) ***[/bold yellow]")

        # Step 2: Initialize NetBox Connection
        console.print(f"\n[bold white]2. Connecting to NetBox API at:[/bold white] [cyan]{netbox_url}[/cyan]")
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        try:
            self.nb = pynetbox.api(netbox_url, token=token)
            if not verify_ssl:
                self.nb.http_session.verify = False

            if not self.dry_run:
                # Test API responsiveness
                status = self.nb.status()
                netbox_version = status.get("netbox-version", "Unknown")
                console.print(f"  [green]✓ Successfully connected to NetBox v{netbox_version}![/green]")
            else:
                console.print("  [cyan]✓ Dry-run connection check passed.[/cyan]")
        except Exception as e:
            console.print(f"  [bold red]✗ Failed to connect to NetBox API at {netbox_url}: {str(e)}[/bold red]")
            return False

        # Step 3: Ensure Prerequisites (Site, Manufacturer, Device Type, Device Role)
        if not self._ensure_prerequisites():
            return False

        # Step 4: Process IPAM Subnet Prefixes (if present)
        if self.validation.prefixes:
            self._process_prefixes()

        # Step 5: Import Devices Loop
        console.print("\n[bold white]4. Processing Device Imports...[/bold white]")
        
        summary_table = Table(title="Device Import Results", show_header=True, header_style="bold magenta")
        summary_table.add_column("Device Name", style="cyan")
        summary_table.add_column("IP Address", style="yellow")
        summary_table.add_column("Status / Action", style="green")
        summary_table.add_column("Details", style="white")

        success_count = 0
        skip_count = 0
        fail_count = 0

        for dev in self.validation.devices:
            name = dev["name"]
            cidr_ip = dev["cidr_ip"]
            ip_only = dev["ip_address"]
            overwrite = dev.get("overwrite", False)

            try:
                action, detail = self._process_single_device(name, cidr_ip, ip_only, interface_name, overwrite=overwrite)
                if "Skipped" in action or "Exists" in action:
                    skip_count += 1
                    summary_table.add_row(name, cidr_ip, f"[yellow]{action}[/yellow]", detail)
                elif "Overwritten" in action or "Reassigned" in action:
                    success_count += 1
                    summary_table.add_row(name, cidr_ip, f"[bold green]{action}[/bold green]", detail)
                else:
                    success_count += 1
                    summary_table.add_row(name, cidr_ip, f"[green]{action}[/green]", detail)
            except Exception as e:
                fail_count += 1
                summary_table.add_row(name, cidr_ip, "[red]Failed[/red]", str(e))
                console.print(f"  [red]✗ Error processing device '{name}': {str(e)}[/red]")

        console.print("\n", summary_table)
        console.print(Panel(
            f"[bold]Summary:[/bold] Total: {len(self.validation.devices)} | Created/Configured: [green]{success_count}[/green] | Skipped: [yellow]{skip_count}[/yellow] | Failed: [red]{fail_count}[/red]",
            border_style="cyan"
        ))

        return fail_count == 0

    def _ensure_prerequisites(self) -> bool:
        """Verifies or auto-creates required Site, Manufacturer, Device Type, and Device Role."""
        cfg = self.validation.config
        site_name = cfg["SITE_NAME"]
        role_name = cfg["DEVICE_ROLE"]
        manu_name = cfg["MANUFACTURER"]
        dt_name = cfg["DEVICE_TYPE"]

        console.print("  [white]Checking NetBox prerequisite objects...[/white]")
        if self.dry_run:
            console.print("    [cyan]✓ Prerequisites verified (Dry-run mode).[/cyan]")
            return True

        try:
            # 1. Site
            site = self.nb.dcim.sites.get(name=site_name)
            if not site:
                site = self.nb.dcim.sites.create(name=site_name, slug=_slugify(site_name))
                console.print(f"    [green]+ Created missing Site:[/green] '{site_name}'")
            self.site_obj = site

            # 2. Manufacturer
            manu = self.nb.dcim.manufacturers.get(name=manu_name)
            if not manu:
                manu = self.nb.dcim.manufacturers.create(name=manu_name, slug=_slugify(manu_name))
                console.print(f"    [green]+ Created missing Manufacturer:[/green] '{manu_name}'")
            self.manufacturer_obj = manu

            # 3. Device Type
            dt = self.nb.dcim.device_types.get(model=dt_name)
            if not dt:
                dt = self.nb.dcim.device_types.create(
                    model=dt_name,
                    slug=_slugify(dt_name),
                    manufacturer=self.manufacturer_obj.id
                )
                console.print(f"    [green]+ Created missing Device Type:[/green] '{dt_name}'")
            self.device_type_obj = dt

            # 4. Device Role
            role = self.nb.dcim.device_roles.get(name=role_name)
            if not role:
                role = self.nb.dcim.device_roles.create(
                    name=role_name,
                    slug=_slugify(role_name),
                    color="9e9e9e"
                )
                console.print(f"    [green]+ Created missing Device Role:[/green] '{role_name}'")
            self.role_obj = role
            return True
        except Exception as e:
            console.print(f"  [bold red]✗ Failed to ensure prerequisites in NetBox: {str(e)}[/bold red]")
            return False

    def _process_prefixes(self):
        """Creates or verifies IPAM subnet prefixes defined in the Prefixes sheet."""
        console.print("\n[bold white]3. Processing IPAM Subnet Prefixes...[/bold white]")
        prefix_table = Table(title="IPAM Subnet Prefixes", show_header=True, header_style="bold cyan")
        prefix_table.add_column("Subnet Prefix", style="yellow")
        prefix_table.add_column("Description", style="white")
        prefix_table.add_column("Site", style="cyan")
        prefix_table.add_column("Status", style="green")

        for pref in self.validation.prefixes:
            cidr_prefix = pref["prefix"]
            desc = pref["description"]
            site_name = pref["site"]
            status_val = pref["status"]

            if self.dry_run:
                prefix_table.add_row(cidr_prefix, desc, site_name, "[yellow]Dry Run OK[/yellow]")
                continue

            try:
                # Find site object ID if specified
                site_id = None
                if site_name:
                    site_obj = self.nb.dcim.sites.get(name=site_name)
                    if site_obj:
                        site_id = site_obj.id

                prefix_obj = self.nb.ipam.prefixes.get(prefix=cidr_prefix)
                if not prefix_obj:
                    prefix_payload = {
                        "prefix": cidr_prefix,
                        "status": status_val or "active",
                        "description": desc,
                    }
                    if site_id:
                        prefix_payload["site"] = site_id

                    prefix_obj = self.nb.ipam.prefixes.create(**prefix_payload)
                    prefix_table.add_row(cidr_prefix, desc, site_name, "[green]Created[/green]")
                else:
                    prefix_table.add_row(cidr_prefix, desc, site_name, "[yellow]Updated/Exists[/yellow]")
            except Exception as e:
                prefix_table.add_row(cidr_prefix, desc, site_name, f"[red]Failed: {str(e)}[/red]")
                console.print(f"  [red]✗ Error processing IPAM prefix '{cidr_prefix}': {str(e)}[/red]")

        console.print(prefix_table)

    def _process_single_device(self, name: str, cidr_ip: str, ip_only: str, interface_name: str, overwrite: bool = False) -> tuple:
        """Handles idempotent creation of device, interface (1000base-t), IP assignment, and primary IP, with forced overwrite support."""
        if self.dry_run:
            ow_note = " (Overwrite enabled)" if overwrite else ""
            return f"Dry Run OK{ow_note}", "Validation passed; device and IP would be verified/configured."

        # 1. Check or Create Device
        device = self.nb.dcim.devices.get(name=name)
        device_created = False
        if not device:
            device = self.nb.dcim.devices.create(
                name=name,
                device_type=self.device_type_obj.id,
                role=self.role_obj.id,
                site=self.site_obj.id,
                status="active"
            )
            device_created = True

        # 2. Check or Create Interface (type: 1000base-t)
        interface = self.nb.dcim.interfaces.get(device_id=device.id, name=interface_name)
        if not interface:
            interface = self.nb.dcim.interfaces.create(
                device=device.id,
                name=interface_name,
                type="1000base-t"
            )

        # 3. Check or Create IP Address in IPAM
        ip_obj = self.nb.ipam.ip_addresses.get(address=cidr_ip)
        if not ip_obj:
            ip_obj = self.nb.ipam.ip_addresses.create(
                address=cidr_ip,
                status="active"
            )

        # 4. Handle IP Assignment & Overwrite Logic
        was_overwritten = False
        if ip_obj.assigned_object_id:
            if ip_obj.assigned_object_id != interface.id:
                if overwrite:
                    # Attempt to clear primary IP on old device if applicable
                    try:
                        old_iface = self.nb.dcim.interfaces.get(id=ip_obj.assigned_object_id)
                        if old_iface and hasattr(old_iface, "device") and old_iface.device:
                            old_dev = self.nb.dcim.devices.get(id=old_iface.device.id)
                            if old_dev and old_dev.primary_ip4 and old_dev.primary_ip4.id == ip_obj.id:
                                old_dev.primary_ip4 = None
                                old_dev.save()
                                console.print(f"  [bold yellow]OVERWRITE:[/bold yellow] Unset primary IPv4 on former device '{old_dev.name}'.")
                    except Exception as ex:
                        console.print(f"  [yellow]Notice during overwrite cleanup:[/yellow] {str(ex)}")

                    # Rebind IP to target interface
                    ip_obj.assigned_object_type = "dcim.interface"
                    ip_obj.assigned_object_id = interface.id
                    ip_obj.save()
                    was_overwritten = True
                    console.print(f"  [bold green]OVERWRITE:[/bold green] Reassigned IP {cidr_ip} to device '{name}' interface '{interface_name}'.")
                else:
                    console.print(f"  [bold yellow]WARNING:[/bold yellow] IP address {cidr_ip} is already assigned to object ID {ip_obj.assigned_object_id}. Skipping re-assignment (set Overwrite=TRUE to force).")
        else:
            # Bind IP to device interface
            ip_obj.assigned_object_type = "dcim.interface"
            ip_obj.assigned_object_id = interface.id
            ip_obj.save()

        # 5. Set as Primary IPv4 on Device
        if not device.primary_ip4 or device.primary_ip4.id != ip_obj.id:
            device.primary_ip4 = ip_obj.id
            device.save()

        if was_overwritten:
            return "Overwritten", f"Forced IP reassignment of {cidr_ip} to '{name}' ({interface_name})."
        elif device_created:
            return "Created", f"Interface '{interface_name}' attached, Primary IP {cidr_ip} set."
        else:
            return "Updated/Exists", f"Verified interface '{interface_name}' and Primary IP {cidr_ip}."
