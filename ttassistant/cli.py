"""Typer CLI application entrypoint for ttassistant."""

import os
import sys
from pathlib import Path
from typing import Optional

import click
import typer
from rich.table import Table

from ttassistant import __version__
from ttassistant.adapters.catalog_adapter import JsonResourceCatalogAdapter
from ttassistant.adapters.fs_adapter import DiskFileSystemAdapter
from ttassistant.adapters.standards_adapter import MarkdownStandardsAdapter
from ttassistant.adapters.terminal_adapter import RichTerminalAdapter
from ttassistant.domain.exceptions import MissingStandardsError, TTAssistantError
from ttassistant.domain.standards import StandardsEngine


def version_callback(value: bool) -> None:
    """Print package version and exit."""
    if value:
        typer.echo(f"ttassistant {__version__}")
        raise typer.Exit(code=0)


def resolve_standards(
    standards_dir: Optional[Path] = None,
) -> tuple[Path, StandardsEngine]:
    """Discover standards directory and initialize StandardsEngine.

    Searches:
    1. Explicit standards_dir parameter (from --standards-dir or TT_STANDARDS_DIR)
    2. Ascending search from current working directory to filesystem root for 'common_standards/'

    Raises:
        MissingStandardsError: If standards directory cannot be found or is empty.
        InvalidStandardsError: If standards files are invalid or malformed.
    """
    if standards_dir is not None:
        target_dir = Path(standards_dir).resolve()
        if not target_dir.exists():
            raise MissingStandardsError(
                f"Specified standards directory does not exist: '{target_dir}'",
                details="Please verify the path provided to --standards-dir or TT_STANDARDS_DIR.",
            )
        if not target_dir.is_dir():
            raise MissingStandardsError(
                f"Specified standards path is not a directory: '{target_dir}'",
                details="Expected a directory containing corporate standards markdown files.",
            )
    else:
        # Runtime discovery: walk up from current working directory
        current = Path.cwd().resolve()
        found_dir: Optional[Path] = None
        for candidate_parent in [current, *current.parents]:
            candidate = candidate_parent / "common_standards"
            if candidate.is_dir():
                found_dir = candidate
                break
        if found_dir is None:
            raise MissingStandardsError(
                "Corporate standards directory 'common_standards/' not found in workspace or ancestor paths.",
                details="Please pull corporate standards into 'common_standards/' or specify --standards-dir (or set TT_STANDARDS_DIR).",
            )
        target_dir = found_dir

    adapter = MarkdownStandardsAdapter()
    bundle = adapter.load_standards(target_dir)
    engine = StandardsEngine(bundle)
    return target_dir, engine


class TTAssistantCLI(typer.Typer):
    """Custom Typer subclass providing top-level error formatting and graceful handling."""

    def __call__(self, *args, **kwargs):
        standalone = kwargs.pop("standalone_mode", True)
        if standalone:
            try:
                ret = super().__call__(*args, standalone_mode=False, **kwargs)
                if isinstance(ret, int) and ret != 0:
                    sys.exit(ret)
                return ret
            except (click.ClickException, typer.exceptions.TyperException) as exc:
                if hasattr(exc, "show") and callable(getattr(exc, "show")):
                    exc.show()
                elif str(exc):
                    terminal = RichTerminalAdapter()
                    terminal.print_error(str(exc))
                exit_code = getattr(exc, "exit_code", 1)
                sys.exit(exit_code)
            except typer.Exit as exc:
                sys.exit(exc.exit_code)
            except typer.Abort:
                terminal = RichTerminalAdapter()
                terminal.print_warning("Aborted.")
                sys.exit(130)
            except TTAssistantError as exc:
                if "--debug" in sys.argv or "-d" in sys.argv:
                    raise
                terminal = RichTerminalAdapter()
                terminal.print_error(exc.message)
                if exc.details:
                    terminal.print(f"Details: {exc.details}", stderr=True)
                sys.exit(1)
            except Exception as exc:
                if "--debug" in sys.argv or "-d" in sys.argv:
                    raise
                terminal = RichTerminalAdapter()
                terminal.print_error(f"Unexpected error: {exc}")
                sys.exit(1)
        return super().__call__(*args, standalone_mode=False, **kwargs)


app = TTAssistantCLI(
    name="ttassistant",
    help="Enterprise terminal CLI copilot for Azure Terraform development.",
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    standards_dir: Optional[Path] = typer.Option(
        None,
        "--standards-dir",
        "-s",
        help="Path to corporate standards directory containing markdown specifications.",
        envvar="TT_STANDARDS_DIR",
    ),
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show package version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        "-d",
        help="Enable debug mode with detailed exception traces.",
    ),
) -> None:
    """Enterprise terminal CLI copilot for Azure Terraform development."""
    # Resolve standards engine at startup (fail-fast policy)
    try:
        resolved_dir, standards_engine = resolve_standards(standards_dir)
        ctx.ensure_object(dict)
        ctx.obj["standards_dir"] = resolved_dir
        ctx.obj["standards_engine"] = standards_engine
        ctx.obj["standards_bundle"] = standards_engine.bundle
    except MissingStandardsError:
        if ctx.invoked_subcommand in ("scan", "catalog", "remediate") and standards_dir is None:
            ctx.ensure_object(dict)
            ctx.obj["standards_dir"] = None
            ctx.obj["standards_engine"] = None
            ctx.obj["standards_bundle"] = None
        else:
            raise

    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command("new")
def new_command(
    ctx: typer.Context,
    subscription: Optional[str] = typer.Option(
        None,
        "--subscription",
        "-sub",
        help="Target Azure subscription identifier.",
    ),
    resource_type: Optional[str] = typer.Option(
        None,
        "--resource-type",
        "-r",
        help="Azure resource type (e.g. azurerm_storage_account).",
    ),
    workload: Optional[str] = typer.Option(
        None,
        "--workload",
        "-w",
        help="Workload name.",
    ),
    env: Optional[str] = typer.Option(
        None,
        "--env",
        "-e",
        help="Target deployment environment (e.g. dev, prod).",
    ),
    subnet: Optional[str] = typer.Option(
        None,
        "--subnet",
        "-snet",
        help="Target candidate subnet name or identifier.",
    ),
    public_network_access: bool = typer.Option(
        False,
        "--public-network-access",
        help="Enable public network access on Tier 1 PaaS resource (requires explicit confirmation).",
    ),
    confirm_public_network_access: bool = typer.Option(
        False,
        "--confirm-public-network-access",
        help="Explicit confirmation override for public network access in non-interactive/headless environments.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip interactive confirmation and commit scaffolding to disk immediately.",
    ),
) -> None:
    """Guided provisioning dialogue for new Azure Terraform workloads."""
    standards_engine: StandardsEngine = ctx.obj["standards_engine"]
    terminal = RichTerminalAdapter()
    fs = DiskFileSystemAdapter()
    catalog = JsonResourceCatalogAdapter()

    from ttassistant.adapters.hcl_adapter import ReadOnlyHclAdapter
    from ttassistant.adapters.tweak_adapter import DeterministicTweakParserAdapter
    from ttassistant.application.provisioning_flow import ProvisioningFlow
    from ttassistant.application.tweak_handler import TweakHandler

    standards_patterns = None
    if standards_engine:
        net_rule = standards_engine.resolve_networking_policy(resource_type or "default")
        if net_rule and net_rule.subnet_patterns:
            standards_patterns = net_rule.subnet_patterns

    hcl_parser = ReadOnlyHclAdapter(standards_patterns=standards_patterns)
    tweak_parser = DeterministicTweakParserAdapter(catalog=catalog)
    tweak_handler = TweakHandler(parser=tweak_parser, catalog=catalog)

    flow = ProvisioningFlow(
        terminal=terminal,
        standards=standards_engine,
        fs=fs,
        hcl_parser=hcl_parser,
        catalog=catalog,
        tweak_handler=tweak_handler,
    )
    try:
        flow.run(
            subscription=subscription,
            resource_type=resource_type,
            workload_name=workload,
            environment=env,
            subnet=subnet,
            auto_approve=yes,
            public_network_access=public_network_access,
            confirm_public_network_access=confirm_public_network_access,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc))


@app.command("scan")
def scan_command(
    ctx: typer.Context,
    path: Path = typer.Argument(
        Path("."),
        help="Monorepo root or directory to scan for candidate Terraform files.",
    ),
    subscription: Optional[str] = typer.Option(
        None,
        "--subscription",
        "-sub",
        help="Filter discovered candidates by target subscription.",
    ),
    resource_type: Optional[str] = typer.Option(
        None,
        "--resource-type",
        "-r",
        help="Filter discovered candidates by resource type (e.g. azurerm_subnet).",
    ),
    ast: bool = typer.Option(
        False,
        "--ast",
        help="Perform Phase 2 AST extraction to discover and display subnets, VNets, and resource groups.",
    ),
) -> None:
    """Diagnostic scan of repository topology and candidate Terraform files."""
    terminal = RichTerminalAdapter()
    target_path = Path(path).resolve()
    if not target_path.exists():
        terminal.print_error(f"Directory does not exist: '{target_path}'")
        raise typer.Exit(code=1)
    if not target_path.is_dir():
        terminal.print_error(f"Specified path is not a directory: '{target_path}'")
        raise typer.Exit(code=1)

    fs = DiskFileSystemAdapter(base_dir=target_path)

    target_types = {resource_type} if resource_type else None
    index = fs.build_topology_index(target_path, target_types=target_types)

    candidates = index.candidates if not subscription else index.get_candidates_for_subscription(subscription)

    terminal.print_info(
        f"Topology Discovery: scanned {index.total_files_scanned} .tf files in {index.duration_seconds:.3f}s."
    )

    if not candidates:
        terminal.print("No candidate dependency files discovered.")
        return

    if ast:
        from rich.table import Table
        from ttassistant.adapters.hcl_adapter import ReadOnlyHclAdapter

        standards_patterns = None
        if ctx.obj and ctx.obj.get("standards_engine"):
            target_policy_type = resource_type or "default"
            net_rule = ctx.obj["standards_engine"].resolve_networking_policy(target_policy_type)
            if net_rule and net_rule.subnet_patterns:
                standards_patterns = net_rule.subnet_patterns

        adapter = ReadOnlyHclAdapter(standards_patterns=standards_patterns)
        topology = adapter.parse_topology_candidates(candidates)

        # 1. Subnets Table
        if topology.subnets:
            subnets_table = Table(
                title=f"Discovered Subnets ({len(topology.subnets)} total, {len(topology.get_private_endpoint_subnets())} Private Endpoint candidates)",
                show_header=True,
                header_style="bold cyan",
            )
            subnets_table.add_column("Subnet Name", style="bold green", overflow="fold")
            subnets_table.add_column("CIDR Prefixes", style="yellow", overflow="fold")
            subnets_table.add_column("Virtual Network", style="magenta", overflow="fold")
            subnets_table.add_column("Resource Group", style="blue", overflow="fold")
            subnets_table.add_column("Type", style="dim", overflow="fold")
            subnets_table.add_column("PE Candidate", style="bold", overflow="fold")
            subnets_table.add_column("Subscription", style="cyan", overflow="fold")

            for s in topology.subnets:
                cidr_str = ", ".join(s.address_prefixes) if s.address_prefixes else "-"
                vnet_str = s.virtual_network_name or "-"
                rg_str = s.resource_group_name or "-"
                type_str = "Data Source" if s.is_data_source else ("Inline" if s.is_inline else "Standalone")
                pe_str = "[green]Yes[/green]" if s.is_private_endpoint_candidate else "[dim]No[/dim]"
                sub_str = s.subscription or "unassigned"
                subnets_table.add_row(s.name, cidr_str, vnet_str, rg_str, type_str, pe_str, sub_str)

            terminal.console.print(subnets_table)

        # 2. Virtual Networks Table
        if topology.virtual_networks:
            vnets_table = Table(
                title=f"Discovered Virtual Networks ({len(topology.virtual_networks)} total)",
                show_header=True,
                header_style="bold magenta",
            )
            vnets_table.add_column("VNet Name", style="bold magenta", overflow="fold")
            vnets_table.add_column("Resource Group", style="blue", overflow="fold")
            vnets_table.add_column("Address Space", style="yellow", overflow="fold")
            vnets_table.add_column("Inline Subnets", style="green", overflow="fold")
            vnets_table.add_column("Location", style="dim", overflow="fold")
            vnets_table.add_column("Subscription", style="cyan", overflow="fold")

            for vn in topology.virtual_networks:
                space_str = ", ".join(vn.address_space) if vn.address_space else "-"
                rg_str = vn.resource_group_name or "-"
                loc_str = vn.location or "-"
                sub_str = vn.subscription or "unassigned"
                vnets_table.add_row(vn.name, rg_str, space_str, str(len(vn.subnets)), loc_str, sub_str)

            terminal.console.print(vnets_table)

        # 3. Resource Groups Table
        if topology.resource_groups:
            rgs_table = Table(
                title=f"Discovered Resource Groups ({len(topology.resource_groups)} total)",
                show_header=True,
                header_style="bold blue",
            )
            rgs_table.add_column("Resource Group Name", style="bold blue", overflow="fold")
            rgs_table.add_column("Location", style="dim", overflow="fold")
            rgs_table.add_column("Tags", style="yellow", overflow="fold")
            rgs_table.add_column("Type", style="dim", overflow="fold")
            rgs_table.add_column("Subscription", style="cyan", overflow="fold")

            for rg in topology.resource_groups:
                tags_str = ", ".join(f"{k}={v}" for k, v in sorted(rg.tags.items())) if rg.tags else "-"
                type_str = "Data Source" if rg.is_data_source else "Resource"
                loc_str = rg.location or "-"
                sub_str = rg.subscription or "unassigned"
                rgs_table.add_row(rg.name, loc_str, tags_str, type_str, sub_str)

            terminal.console.print(rgs_table)

        # Warnings / Parse Errors
        if topology.parse_errors:
            for err in topology.parse_errors:
                terminal.print_warning(f"AST Parse Warning: {err}")

        terminal.print_success(
            f"Phase 2 AST Extraction Complete: {len(topology.subnets)} subnets, {len(topology.virtual_networks)} VNets, {len(topology.resource_groups)} resource groups."
        )
        return

    from rich.table import Table

    table = Table(
        title="Discovered Dependency Candidates",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("File Path", style="dim", overflow="fold")
    table.add_column("Subscription", style="green")
    table.add_column("Detected Resource Types", style="yellow")

    for cand in candidates:
        try:
            rel = Path(cand.path).relative_to(target_path)
            display_path = str(rel)
        except ValueError:
            display_path = cand.path
        types_str = ", ".join(sorted(cand.detected_types))
        sub_str = cand.subscription or "unassigned"
        table.add_row(display_path, sub_str, types_str)

    terminal.console.print(table)
    terminal.print_success(
        f"Indexed {len(candidates)} candidate files in {index.duration_seconds:.3f}s."
    )


@app.command("remediate")
def remediate_command(
    ctx: typer.Context,
    path: Path = typer.Argument(
        Path("."),
        help="Target directory to inspect and remediate.",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        "-c",
        help="Audit mode: return exit code 1 if non-compliance violations exist.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation gate and commit surgical remediation to disk immediately.",
    ),
) -> None:
    """Inspect an existing directory and diagnose compliance violations against corporate standards."""
    standards_engine: Optional[StandardsEngine] = (
        ctx.obj.get("standards_engine") if ctx.obj else None
    )
    terminal = RichTerminalAdapter()
    fs = DiskFileSystemAdapter()
    from ttassistant.adapters.hcl_adapter import ReadOnlyHclAdapter
    from ttassistant.application.remediation_flow import RemediationFlow

    hcl_parser = ReadOnlyHclAdapter()
    flow = RemediationFlow(
        terminal=terminal,
        standards=standards_engine,
        fs=fs,
        hcl_parser=hcl_parser,
    )

    try:
        report, exit_code = flow.run_remediation(target_dir=path, check=check, auto_approve=yes)
    except typer.Abort:
        terminal.print_warning("Remediation cancelled. Disk left untouched.")
        return

    if exit_code != 0:
        raise typer.Exit(code=exit_code)


# --- Schema Catalog Subcommands ---

catalog_app = typer.Typer(
    name="catalog",
    help="Explore offline bundled AzureRM provider schema catalog.",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
)
app.add_typer(catalog_app, name="catalog")


@catalog_app.command("list")
def catalog_list_command(
    ctx: typer.Context,
    tier: Optional[str] = typer.Option(
        None,
        "--tier",
        "-t",
        help="Filter resources by tier (1 for Guided PaaS/Foundation, 2 for Universal).",
    ),
    prefix: Optional[str] = typer.Option(
        None,
        "--prefix",
        "-p",
        help="Filter resources by name prefix (e.g. azurerm_mssql).",
    ),
    catalog_path: Optional[Path] = typer.Option(
        None,
        "--catalog-path",
        help="Custom path to azurerm_schema.json (defaults to bundled catalog).",
    ),
) -> None:
    """List Azure resources in offline catalog with tier and prefix filtering."""
    terminal = RichTerminalAdapter()
    adapter = JsonResourceCatalogAdapter(catalog_path=catalog_path)

    resources = adapter.list_resources(filter_prefix=prefix, tier=tier)
    summary = adapter.get_summary()

    if not resources:
        terminal.print_info("No resources found matching the specified criteria.")
        return

    table = Table(
        title=f"AzureRM Schema Catalog ({len(resources)} resources)",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Resource Type", style="bold green", no_wrap=True)
    table.add_column("Classification Tier", style="cyan", no_wrap=True)
    table.add_column("Description", style="dim", overflow="fold")

    for res_name in resources:
        schema = adapter.get_resource_schema(res_name)
        tier_display = (
            "[bold green]Tier 1 (Guided PaaS)[/bold green]"
            if schema and schema.is_tier_1
            else "[dim]Tier 2 (Universal)[/dim]"
        )
        desc = schema.description if schema else ""
        table.add_row(res_name, tier_display, desc)

    terminal.console.print(table)
    terminal.print_success(
        f"Listed {len(resources)} resources (Catalog Total: {summary.total_resources}, Tier 1: {summary.tier_1_count}, Tier 2: {summary.tier_2_count})."
    )


@catalog_app.command("info")
def catalog_info_command(
    ctx: typer.Context,
    resource_type: str = typer.Argument(
        ...,
        help="Azure resource type to inspect (e.g. azurerm_storage_account).",
    ),
    catalog_path: Optional[Path] = typer.Option(
        None,
        "--catalog-path",
        help="Custom path to azurerm_schema.json (defaults to bundled catalog).",
    ),
) -> None:
    """Display schema, tier, and argument details for an Azure resource."""
    terminal = RichTerminalAdapter()
    adapter = JsonResourceCatalogAdapter(catalog_path=catalog_path)

    schema = adapter.get_resource_schema(resource_type)
    if schema is None:
        terminal.print_error(f"Resource '{resource_type}' not found in offline catalog.")
        raise typer.Exit(code=1)

    tier_label = (
        "[bold green]Tier 1 (Guided PaaS & Foundation)[/bold green]"
        if schema.is_tier_1
        else "[dim]Tier 2 (Universal Long-Tail)[/dim]"
    )

    terminal.console.print(f"[bold cyan]Resource:[/bold cyan] [bold white]{schema.resource_type}[/bold white]")
    terminal.console.print(f"[bold cyan]Tier:[/bold cyan] {tier_label}")
    if schema.description:
        terminal.console.print(f"[bold cyan]Description:[/bold cyan] {schema.description}\n")

    table = Table(
        title=f"Schema Arguments for {schema.resource_type}",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Argument", style="bold", no_wrap=True)
    table.add_column("Type", style="yellow", no_wrap=True)
    table.add_column("Required", style="bold", no_wrap=True)
    table.add_column("Default", style="magenta", no_wrap=True)
    table.add_column("Description", style="dim", overflow="fold")

    sorted_args = sorted(
        schema.arguments.values(),
        key=lambda a: (0 if a.required else 1, a.name),
    )

    for arg in sorted_args:
        req_str = "[bold red]Yes[/bold red]" if arg.required else "[dim]No[/dim]"
        arg_name_str = f"[bold green]{arg.name}[/bold green]" if arg.required else arg.name
        def_str = str(arg.default) if arg.default is not None else "-"
        table.add_row(arg_name_str, arg.type, req_str, def_str, arg.description)

    terminal.console.print(table)
    terminal.print_success(
        f"{schema.resource_type}: {len(schema.required_argument_names)} required, {len(schema.optional_argument_names)} optional arguments."
    )


if __name__ == "__main__":
    app()

