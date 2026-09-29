"""Unit and integration tests for Tier 2 universal Azure long-tail resource scaffolding.

Tests Story 3.4 acceptance criteria and edge-case matrix:
- Cloud Adoption Framework (CAF) naming prefixes
- Lean file layout enforcement (main.tf, data.tf, backend.tf only)
- Required schema arguments and default values
- Complex nested child block synthesis (AKS node pool, NIC/Bastion IP config, Container App template)
- Subnet prompt suppression for Tier 2 resources
- Explicit pre-seeded subnet wiring
- All 21 Tier 2 AzureRM resources AST validation via python-hcl2
"""

from pathlib import Path
from unittest.mock import MagicMock
import hcl2
import pytest
import re
import subprocess
import sys

from ttassistant.adapters.catalog_adapter import JsonResourceCatalogAdapter
from ttassistant.adapters.standards_adapter import MarkdownStandardsAdapter
from ttassistant.application.provisioning_flow import ProvisioningFlow
from ttassistant.domain.catalog import TIER_2_RESOURCES, is_tier_2_resource
from ttassistant.domain.models import ProvisioningParameters
from ttassistant.domain.scaffold import ScaffoldEngine
from ttassistant.domain.standards import DEFAULT_RESOURCE_PREFIXES, StandardsEngine
from ttassistant.ports.terminal import TerminalUIPort


@pytest.fixture
def standards_engine() -> StandardsEngine:
    """Load corporate standards engine from common_standards/."""
    standards_dir = Path(__file__).resolve().parent.parent / "common_standards"
    adapter = MarkdownStandardsAdapter()
    bundle = adapter.load_standards(standards_dir)
    return StandardsEngine(bundle)


@pytest.fixture
def catalog_adapter() -> JsonResourceCatalogAdapter:
    """Load offline AzureRM provider schema catalog."""
    return JsonResourceCatalogAdapter()


@pytest.fixture
def scaffold_engine(
    standards_engine: StandardsEngine, catalog_adapter: JsonResourceCatalogAdapter
) -> ScaffoldEngine:
    """Initialize ScaffoldEngine with corporate standards and schema catalog."""
    return ScaffoldEngine(standards=standards_engine, catalog=catalog_adapter)


@pytest.fixture
def mock_terminal() -> MagicMock:
    """Create a mock TerminalUIPort instance."""
    terminal = MagicMock(spec=TerminalUIPort)
    terminal.is_interactive.return_value = True
    return terminal


# --- 1. CAF Resource Prefix Mappings ---


def test_caf_resource_prefix_mappings(standards_engine: StandardsEngine):
    """Verify all 13 standard CAF resource prefixes and fallbacks."""
    expected_mappings = {
        "azurerm_log_analytics_workspace": "law-appdata-dev",
        "azurerm_application_insights": "appi-appdata-dev",
        "azurerm_network_security_group": "nsg-appdata-dev",
        "azurerm_public_ip": "pip-appdata-dev",
        "azurerm_container_registry": "crappdatadev",
        "azurerm_kubernetes_cluster": "aks-appdata-dev",
        "azurerm_api_management": "apim-appdata-dev",
        "azurerm_firewall": "afw-appdata-dev",
        "azurerm_user_assigned_identity": "id-appdata-dev",
        "azurerm_bastion_host": "bas-appdata-dev",
        "azurerm_dns_zone": "dns-appdata-dev",
        "azurerm_service_plan": "asp-appdata-dev",
        "azurerm_servicebus_namespace": "sb-appdata-dev",
    }

    for res_type, expected_name in expected_mappings.items():
        computed = standards_engine.compute_resource_name(res_type, "appdata", "dev")
        assert computed == expected_name, f"Failed for {res_type}: expected {expected_name}, got {computed}"

    # Empty environment
    assert standards_engine.compute_resource_name("azurerm_log_analytics_workspace", "appdata", "") == "law-appdata"
    assert standards_engine.compute_resource_name("azurerm_container_registry", "appdata", "") == "crappdata"

    # Pre-existing prefix or environment suffix in workload
    assert standards_engine.compute_resource_name("azurerm_log_analytics_workspace", "law-appdata-dev", "dev") == "law-appdata-dev"
    assert standards_engine.compute_resource_name("azurerm_container_registry", "crappdata-dev", "dev") == "crappdatadev"

    # Fallback for unmapped resource without naming rule
    assert standards_engine.compute_resource_name("unknown_resource", "appdata", "dev") == "appdata-dev"
    assert standards_engine.compute_resource_name("unknown_resource", "appdata", "") == "appdata"
    assert standards_engine.compute_resource_name("azurerm_cognitive_account", "appdata", "dev") == "cog-appdata-dev"


# --- 2. Tier 2 Standard Long-Tail Resource ---


def test_tier_2_standard_long_tail_resource(
    scaffold_engine: ScaffoldEngine, standards_engine: StandardsEngine
):
    """Verify standard Tier 2 resource (azurerm_log_analytics_workspace) scaffolding."""
    res_type = "azurerm_log_analytics_workspace"
    res_name = standards_engine.compute_resource_name(res_type, "appdata", "dev")
    assert res_name == "law-appdata-dev"

    params = ProvisioningParameters(
        subscription="workload-dev",
        resource_type=res_type,
        workload_name="appdata",
        environment="dev",
        resource_name=res_name,
        tags=standards_engine.apply_default_tags({"Environment": "dev"}),
    )

    workspace = scaffold_engine.scaffold(params)

    # 1. Lean File Layout
    assert set(workspace.files.keys()) == {"main.tf", "data.tf", "backend.tf"}
    assert "variables.tf" not in workspace.files
    assert "outputs.tf" not in workspace.files

    # 2. main.tf content & AST
    main_hcl = workspace.files["main.tf"].content
    parsed_main = hcl2.loads(main_hcl)
    assert parsed_main is not None
    assert 'resource "azurerm_log_analytics_workspace" "primary"' in main_hcl
    assert 'name                = "law-appdata-dev"' in main_hcl
    assert "resource_group_name = data.azurerm_resource_group.primary.name" in main_hcl
    assert "location            = data.azurerm_resource_group.primary.location" in main_hcl
    assert "tags = {" in main_hcl
    assert 'Environment = "dev"' in main_hcl

    # 3. data.tf content & AST
    data_hcl = workspace.files["data.tf"].content
    parsed_data = hcl2.loads(data_hcl)
    assert parsed_data is not None
    assert 'data "azurerm_resource_group" "primary"' in data_hcl
    assert 'name = "rg-tfstate-dev"' in data_hcl
    assert "terraform_remote_state" not in data_hcl

    # 4. backend.tf content & AST
    backend_hcl = workspace.files["backend.tf"].content
    parsed_backend = hcl2.loads(backend_hcl)
    assert parsed_backend is not None
    assert 'key                  = "dev/azurerm_log_analytics_workspace.tfstate"' in backend_hcl
    assert 'storage_account_name = "sttfstatedev"' in backend_hcl


# --- 3. Tier 2 with Schema Defaults ---


def test_tier_2_with_schema_defaults(
    scaffold_engine: ScaffoldEngine, standards_engine: StandardsEngine
):
    """Verify Tier 2 resource populates schema default arguments (application_type = 'web')."""
    res_type = "azurerm_application_insights"
    res_name = standards_engine.compute_resource_name(res_type, "appdata", "dev")
    assert res_name == "appi-appdata-dev"

    params = ProvisioningParameters(
        subscription="workload-dev",
        resource_type=res_type,
        workload_name="appdata",
        environment="dev",
        resource_name=res_name,
        tags=standards_engine.apply_default_tags({"Environment": "dev"}),
    )

    workspace = scaffold_engine.scaffold(params)
    main_hcl = workspace.files["main.tf"].content

    parsed = hcl2.loads(main_hcl)
    assert parsed is not None
    assert 'application_type    = "web"' in main_hcl
    assert 'name                = "appi-appdata-dev"' in main_hcl
    assert "resource_group_name = data.azurerm_resource_group.primary.name" in main_hcl
    assert "location            = data.azurerm_resource_group.primary.location" in main_hcl


# --- 4. Tier 2 Without Location Attribute ---


def test_tier_2_without_location_attribute(
    scaffold_engine: ScaffoldEngine, standards_engine: StandardsEngine
):
    """Verify Tier 2 resources without location in schema cleanly omit location."""
    for res_type in ["azurerm_dns_zone", "azurerm_private_dns_zone", "azurerm_container_app"]:
        res_name = standards_engine.compute_resource_name(res_type, "appdata", "dev")
        params = ProvisioningParameters(
            subscription="workload-dev",
            resource_type=res_type,
            workload_name="appdata",
            environment="dev",
            resource_name=res_name,
            tags=standards_engine.apply_default_tags({"Environment": "dev"}),
        )

        workspace = scaffold_engine.scaffold(params)
        main_hcl = workspace.files["main.tf"].content
        parsed = hcl2.loads(main_hcl)
        assert parsed is not None

        assert "data.azurerm_resource_group.primary.name" in main_hcl
        assert "location" not in main_hcl, f"Expected no location in {res_type}, but found it"


def test_tier_2_mssql_database_omits_location_and_rg(
    scaffold_engine: ScaffoldEngine, standards_engine: StandardsEngine
):
    """Verify azurerm_mssql_database omits location and resource_group_name, populating server_id."""
    res_type = "azurerm_mssql_database"
    res_name = standards_engine.compute_resource_name(res_type, "appdata", "dev")
    params = ProvisioningParameters(
        subscription="workload-dev",
        resource_type=res_type,
        workload_name="appdata",
        environment="dev",
        resource_name=res_name,
        tags=standards_engine.apply_default_tags({"Environment": "dev"}),
    )

    workspace = scaffold_engine.scaffold(params)
    main_hcl = workspace.files["main.tf"].content
    parsed = hcl2.loads(main_hcl)
    assert parsed is not None

    assert "location" not in main_hcl
    assert "resource_group_name" not in main_hcl
    assert re.search(r'server_id\s+=\s+""', main_hcl)


# --- 5. Tier 2 Complex Nested Blocks ---


def test_tier_2_aks_nested_default_node_pool(
    scaffold_engine: ScaffoldEngine, standards_engine: StandardsEngine
):
    """Verify azurerm_kubernetes_cluster synthesizes dns_prefix and default_node_pool block."""
    res_type = "azurerm_kubernetes_cluster"
    res_name = standards_engine.compute_resource_name(res_type, "appdata", "dev")
    assert res_name == "aks-appdata-dev"

    params = ProvisioningParameters(
        subscription="workload-dev",
        resource_type=res_type,
        workload_name="appdata",
        environment="dev",
        resource_name=res_name,
        tags=standards_engine.apply_default_tags({"Environment": "dev"}),
    )

    workspace = scaffold_engine.scaffold(params)
    main_hcl = workspace.files["main.tf"].content
    parsed = hcl2.loads(main_hcl)
    assert parsed is not None

    assert 'dns_prefix          = "aks-appdata-dev"' in main_hcl
    assert "default_node_pool {" in main_hcl
    assert 'name       = "default"' in main_hcl
    assert "node_count = 1" in main_hcl
    assert 'vm_size    = "Standard_DS2_v2"' in main_hcl


def test_tier_2_container_app_nested_template(
    scaffold_engine: ScaffoldEngine, standards_engine: StandardsEngine
):
    """Verify azurerm_container_app synthesizes template and container nested blocks."""
    res_type = "azurerm_container_app"
    res_name = standards_engine.compute_resource_name(res_type, "appdata", "dev")

    params = ProvisioningParameters(
        subscription="workload-dev",
        resource_type=res_type,
        workload_name="appdata",
        environment="dev",
        resource_name=res_name,
        tags=standards_engine.apply_default_tags({"Environment": "dev"}),
    )

    workspace = scaffold_engine.scaffold(params)
    main_hcl = workspace.files["main.tf"].content
    parsed = hcl2.loads(main_hcl)
    assert parsed is not None

    assert "template {" in main_hcl
    assert "container {" in main_hcl
    assert 'name   = "app"' in main_hcl
    assert 'image  = "mcr.microsoft.com/azuredocs/aci-helloworld:latest"' in main_hcl


def test_tier_2_bastion_nested_ip_configuration(
    scaffold_engine: ScaffoldEngine, standards_engine: StandardsEngine
):
    """Verify azurerm_bastion_host synthesizes ip_configuration block."""
    res_type = "azurerm_bastion_host"
    res_name = standards_engine.compute_resource_name(res_type, "appdata", "dev")

    params = ProvisioningParameters(
        subscription="workload-dev",
        resource_type=res_type,
        workload_name="appdata",
        environment="dev",
        resource_name=res_name,
        tags=standards_engine.apply_default_tags({"Environment": "dev"}),
    )

    workspace = scaffold_engine.scaffold(params)
    main_hcl = workspace.files["main.tf"].content
    parsed = hcl2.loads(main_hcl)
    assert parsed is not None

    assert "ip_configuration {" in main_hcl
    assert 'name                 = "configuration"' in main_hcl


# --- 6. Subnet Prompt Suppression for Tier 2 ---


def test_tier_2_subnet_prompt_suppression(
    mock_terminal: MagicMock,
    standards_engine: StandardsEngine,
    catalog_adapter: JsonResourceCatalogAdapter,
):
    """Verify interactive ProvisioningFlow skips subnet discovery and prompts for Tier 2 resources."""
    mock_terminal.prompt_select.side_effect = ["workload-dev", "azurerm_log_analytics_workspace"]
    mock_terminal.prompt_text.return_value = "appdata"
    mock_terminal.confirm.return_value = True

    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        catalog=catalog_adapter,
        require_subnet=True,  # Even with require_subnet, Tier 2 skips subnet prompt
    )

    params, workspace = flow.run()

    assert params.resource_type == "azurerm_log_analytics_workspace"
    assert params.selected_subnet is None

    # Subnet prompt was NEVER called
    prompt_select_subnet = getattr(mock_terminal, "prompt_select_subnet", None)
    if prompt_select_subnet:
        prompt_select_subnet.assert_not_called()

    # None of the prompt_select calls asked about subnets or networking actions
    for call in mock_terminal.prompt_select.call_args_list:
        prompt_title = call.args[0] if call.args else call.kwargs.get("title", "")
        assert "Subnet" not in prompt_title
        assert "networking action" not in prompt_title

    # Diff preview was displayed and committed
    mock_terminal.display_diff.assert_called_once()
    assert workspace.metadata.get("committed") is True


# --- 7. Explicit Pre-Seeded Subnet Wiring ---


def test_tier_2_explicit_pre_seeded_subnet(
    mock_terminal: MagicMock,
    standards_engine: StandardsEngine,
    catalog_adapter: JsonResourceCatalogAdapter,
):
    """Verify Tier 2 resource with --subnet wires subnet_id into ip_configuration."""
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        catalog=catalog_adapter,
    )

    params, workspace = flow.run(
        subscription="workload-dev",
        resource_type="azurerm_network_interface",
        workload_name="appdata",
        environment="dev",
        subnet="snet-app-prod",
        auto_approve=True,
    )

    assert params.selected_subnet == "snet-app-prod"
    main_hcl = workspace.files["main.tf"].content
    data_hcl = workspace.files["data.tf"].content

    parsed_main = hcl2.loads(main_hcl)
    parsed_data = hcl2.loads(data_hcl)
    assert parsed_main is not None
    assert parsed_data is not None

    # Verify subnet_id in ip_configuration
    assert "subnet_id                     = data.azurerm_subnet.primary.id" in main_hcl
    assert 'data "azurerm_subnet" "primary"' in data_hcl
    assert 'name                 = "snet-app-prod"' in data_hcl

    # Tier 2 must never scaffold companion private endpoint or hub DNS zone
    assert "azurerm_private_endpoint" not in main_hcl
    assert "azurerm_private_dns_zone" not in data_hcl


# --- 8. Unknown Resource Type Validation ---


def test_unknown_resource_type_validation_error(
    mock_terminal: MagicMock,
    standards_engine: StandardsEngine,
    catalog_adapter: JsonResourceCatalogAdapter,
):
    """Verify unknown resource type raises ValueError with clear error details."""
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        catalog=catalog_adapter,
    )

    with pytest.raises(ValueError) as excinfo:
        flow.run(
            subscription="workload-dev",
            resource_type="azurerm_nonexistent_xyz",
            workload_name="appdata",
            environment="dev",
            auto_approve=True,
        )

    assert "Unknown resource type 'azurerm_nonexistent_xyz'" in str(excinfo.value)


def test_cli_new_unknown_resource_type_exits_code_2():
    """Verify CLI ttassistant new with unknown resource type exits with code 2."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ttassistant",
            "new",
            "-r",
            "azurerm_nonexistent_xyz",
            "-sub",
            "workload-dev",
            "-w",
            "appdata",
            "-e",
            "dev",
            "-y",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "Unknown resource type 'azurerm_nonexistent_xyz'" in proc.stderr or "Unknown resource type 'azurerm_nonexistent_xyz'" in proc.stdout


def test_cli_new_tier_2_resource_success(tmp_path: Path):
    """Verify CLI ttassistant new with a valid Tier 2 resource scaffolds cleanly and exits with code 0."""
    project_root = Path(__file__).resolve().parent.parent
    standards_dir = project_root / "common_standards"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ttassistant",
            "--standards-dir",
            str(standards_dir),
            "new",
            "-r",
            "azurerm_log_analytics_workspace",
            "-sub",
            "workload-dev",
            "-w",
            "appdata",
            "-e",
            "dev",
            "-y",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"CLI invocation failed: {proc.stderr}\n{proc.stdout}"
    assert "Provisioning parameters collected successfully." in proc.stdout
    target_dir = tmp_path / "azurerm_log_analytics_workspace" / "workload-dev"
    assert (target_dir / "main.tf").is_file()
    assert (target_dir / "data.tf").is_file()
    assert (target_dir / "backend.tf").is_file()
    assert not (target_dir / "variables.tf").exists()
    assert not (target_dir / "outputs.tf").exists()


# --- 9. Comprehensive Validation of All 21 Tier 2 Resources ---


@pytest.mark.parametrize("resource_type", sorted(TIER_2_RESOURCES))
def test_all_21_tier_2_resources_scaffolding_and_ast_validation(
    resource_type: str,
    scaffold_engine: ScaffoldEngine,
    standards_engine: StandardsEngine,
    catalog_adapter: JsonResourceCatalogAdapter,
):
    """Verify all 21 Tier 2 resources generate valid HCL AST, compliant naming, and lean layout."""
    # Confirm resource is classified as Tier 2
    assert is_tier_2_resource(resource_type)
    assert catalog_adapter.is_tier_2(resource_type)

    res_name = standards_engine.compute_resource_name(resource_type, "appdata", "dev")
    params = ProvisioningParameters(
        subscription="workload-dev",
        resource_type=resource_type,
        workload_name="appdata",
        environment="dev",
        resource_name=res_name,
        tags=standards_engine.apply_default_tags({"Environment": "dev"}),
    )

    workspace = scaffold_engine.scaffold(params)

    # 1. Lean File Layout: strictly main.tf, data.tf, backend.tf
    assert set(workspace.files.keys()) == {"main.tf", "data.tf", "backend.tf"}
    assert "variables.tf" not in workspace.files
    assert "outputs.tf" not in workspace.files

    # 2. Parse all generated files with python-hcl2 (zero syntax errors)
    for filename, staged in workspace.files.items():
        parsed = hcl2.loads(staged.content)
        assert parsed is not None, f"Failed to parse {filename} for {resource_type}"

    # 3. main.tf checks
    main_hcl = workspace.files["main.tf"].content
    assert f'resource "{resource_type}" "primary"' in main_hcl
    assert re.search(rf'name\s+=\s+"{re.escape(res_name)}"', main_hcl)
    assert "tags = {" in main_hcl
    assert 'Environment = "dev"' in main_hcl
    assert "terraform_remote_state" not in main_hcl

    # 4. data.tf checks
    data_hcl = workspace.files["data.tf"].content
    assert 'data "azurerm_resource_group" "primary"' in data_hcl
    assert "terraform_remote_state" not in data_hcl

    # 5. backend.tf checks
    backend_hcl = workspace.files["backend.tf"].content
    assert f'key                  = "dev/{resource_type}.tfstate"' in backend_hcl
    assert 'container_name       = "tfstate"' in backend_hcl

    # 6. Verify required schema arguments and child blocks are present
    schema = catalog_adapter.get_resource_schema(resource_type)
    assert schema is not None
    for req_arg in schema.required_argument_names:
        arg_schema = schema.arguments[req_arg]
        if arg_schema.type == "object" or arg_schema.type.startswith("list(object)"):
            assert f"{req_arg} {{" in main_hcl, f"Missing required nested block '{req_arg}' in {resource_type}"
        else:
            assert re.search(rf"\b{re.escape(req_arg)}\s*=", main_hcl), f"Missing required argument '{req_arg}' in {resource_type}"
