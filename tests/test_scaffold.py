"""Unit tests for ScaffoldEngine in domain/scaffold.py."""

from pathlib import Path
import hcl2
import pytest

from ttassistant.adapters.standards_adapter import MarkdownStandardsAdapter
from ttassistant.domain.exceptions import StandardsError
from ttassistant.domain.models import ProvisioningParameters, StandardsBundle
from ttassistant.domain.scaffold import ScaffoldEngine
from ttassistant.domain.standards import StandardsEngine


@pytest.fixture
def standards_engine() -> StandardsEngine:
    """Load real corporate standards from common_standards/."""
    standards_dir = Path(__file__).resolve().parent.parent / "common_standards"
    adapter = MarkdownStandardsAdapter()
    bundle = adapter.load_standards(standards_dir)
    return StandardsEngine(bundle)


@pytest.fixture
def scaffold_engine(standards_engine: StandardsEngine) -> ScaffoldEngine:
    """Initialize ScaffoldEngine with corporate standards."""
    return ScaffoldEngine(standards=standards_engine)


def test_scaffold_storage_account_greenfield(scaffold_engine: ScaffoldEngine):
    """Verify scaffolding azurerm_storage_account creates workspace in azurerm_storage_account/sub-prod/."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
    )
    workspace = scaffold_engine.scaffold(params)

    assert workspace.target_dir == "azurerm_storage_account/sub-prod/"
    assert workspace.file_count == 3
    assert "main.tf" in workspace
    assert "data.tf" in workspace
    assert "backend.tf" in workspace

    # Verify explicit backend.tf configuration attributes
    backend_content = workspace["backend.tf"].content
    assert 'resource_group_name  = "rg-tfstate-default"' in backend_content
    assert 'storage_account_name = "sttfstatedefault"' in backend_content
    assert 'container_name       = "tfstate"' in backend_content
    assert 'key                  = "sub-prod/azurerm_storage_account.tfstate"' in backend_content

    # Verify python-hcl2 parses all generated files
    for filename in ["main.tf", "data.tf", "backend.tf"]:
        content = workspace[filename].content
        assert content.endswith("\n")
        parsed = hcl2.loads(content)
        assert parsed is not None


def test_backend_tf_state_isolation(scaffold_engine: ScaffoldEngine):
    """Verify backend.tf isolates state key paths between subscriptions."""
    params_prod = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
    )
    params_nonprod = ProvisioningParameters(
        subscription="sub-nonprod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="dev",
        resource_name="stappdatadev",
        tags={"Environment": "dev"},
    )

    ws_prod = scaffold_engine.scaffold(params_prod)
    ws_nonprod = scaffold_engine.scaffold(params_nonprod)

    backend_prod = ws_prod["backend.tf"].content
    backend_nonprod = ws_nonprod["backend.tf"].content

    assert 'key                  = "sub-prod/azurerm_storage_account.tfstate"' in backend_prod
    assert 'key                  = "sub-nonprod/azurerm_storage_account.tfstate"' in backend_nonprod
    assert backend_prod != backend_nonprod


def test_data_tf_resource_group_wiring(scaffold_engine: ScaffoldEngine):
    """Verify data.tf emits decoupled data.azurerm_resource_group.primary referencing backend RG."""
    params = ProvisioningParameters(
        subscription="workload-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
    )
    workspace = scaffold_engine.scaffold(params)
    data_content = workspace["data.tf"].content

    assert 'data "azurerm_resource_group" "primary" {' in data_content
    # In backend_mapping.md, workload-prod has rg-tfstate-prod
    assert 'name = "rg-tfstate-prod"' in data_content
    assert "terraform_remote_state" not in data_content


def test_data_tf_decoupled_networking_sources(scaffold_engine: ScaffoldEngine):
    """Verify data.tf emits decoupled VNet and Subnet data sources with zero remote state when subnet selected."""
    params = ProvisioningParameters(
        subscription="workload-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-pe-01",
        selected_vnet="vnet-prod",
        network_action="existing",
    )
    workspace = scaffold_engine.scaffold(params)
    data_content = workspace["data.tf"].content

    assert 'data "azurerm_resource_group" "primary" {' in data_content
    assert 'name = "rg-tfstate-prod"' in data_content
    assert 'data "azurerm_virtual_network" "primary" {' in data_content
    assert 'name                = "vnet-prod"' in data_content
    assert "resource_group_name = data.azurerm_resource_group.primary.name" in data_content
    assert 'data "azurerm_subnet" "primary" {' in data_content
    assert 'name                 = "snet-pe-01"' in data_content
    assert "resource_group_name  = data.azurerm_virtual_network.primary.resource_group_name" in data_content
    assert "virtual_network_name = data.azurerm_virtual_network.primary.name" in data_content
    assert 'data "azurerm_private_dns_zone" "hub" {' in data_content
    assert 'name                = "privatelink.blob.core.windows.net"' in data_content
    assert 'resource_group_name = "rg-hub-dns"' in data_content
    assert "terraform_remote_state" not in data_content

    parsed = hcl2.loads(data_content)
    assert parsed is not None
    assert len(parsed["data"]) == 4

    # Verify companion private endpoint bundled in main.tf (AD-7, FR-13)
    main_content = workspace["main.tf"].content
    assert 'resource "azurerm_private_endpoint" "primary" {' in main_content
    assert 'name                = "pe-stappdataprod"' in main_content
    assert "subnet_id           = data.azurerm_subnet.primary.id" in main_content
    assert 'private_service_connection {' in main_content
    assert 'subresource_names              = ["blob"]' in main_content
    assert 'private_dns_zone_group {' in main_content


def test_main_tf_references_data_source_and_mandatory_tags(scaffold_engine: ScaffoldEngine):
    """Verify main.tf references data source attributes and populates mandatory corporate tags."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
    )
    workspace = scaffold_engine.scaffold(params)
    main_content = workspace["main.tf"].content

    # Primary resource block
    assert 'resource "azurerm_storage_account" "primary" {' in main_content
    assert 'name                          = "stappdataprod"' in main_content
    assert "resource_group_name           = data.azurerm_resource_group.primary.name" in main_content
    assert "location                      = data.azurerm_resource_group.primary.location" in main_content
    assert 'account_tier                  = "Standard"' in main_content
    assert 'account_replication_type      = "LRS"' in main_content
    assert 'public_network_access_enabled = false' in main_content

    # Mandatory tags from tagging_baseline.md (Environment, Owner, Project, CostCenter)
    assert 'CostCenter  = "CC-1001"' in main_content
    assert 'Environment = "prod"' in main_content
    assert 'Owner       = "cloud-platform@corporate.com"' in main_content
    assert 'Project     = "CorePlatform"' in main_content


def test_scaffold_resource_group_hyphenated_naming(scaffold_engine: ScaffoldEngine):
    """Verify scaffolding azurerm_resource_group uses hyphenated name and omits redundant data.tf."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_resource_group",
        workload_name="appdata",
        environment="prod",
        resource_name="rg-appdata-prod",
        tags={"Environment": "prod"},
    )
    workspace = scaffold_engine.scaffold(params)
    assert workspace.file_count == 2
    assert "main.tf" in workspace
    assert "backend.tf" in workspace
    assert "data.tf" not in workspace

    main_content = workspace["main.tf"].content

    assert 'resource "azurerm_resource_group" "primary" {' in main_content
    assert 'name     = "rg-appdata-prod"' in main_content
    # Resource group specifies its own location
    assert 'location = "westeurope"' in main_content
    # Should not have resource_group_name pointing to itself
    assert "resource_group_name" not in main_content
    assert "public_network_access_enabled" not in main_content


def test_scaffold_key_vault_defaults(scaffold_engine: ScaffoldEngine):
    """Verify scaffolding azurerm_key_vault synthesizes sku_name and tenant_id defaults with data.tf."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_key_vault",
        workload_name="appsecrets",
        environment="prod",
        resource_name="kv-appsecrets-prod",
        tags={"Environment": "prod"},
    )
    workspace = scaffold_engine.scaffold(params)
    assert workspace.file_count == 3
    assert "main.tf" in workspace
    assert "data.tf" in workspace
    assert "backend.tf" in workspace

    main_content = workspace["main.tf"].content
    assert 'name                          = "kv-appsecrets-prod"' in main_content
    assert 'sku_name                      = "standard"' in main_content
    assert 'tenant_id                     = "00000000-0000-0000-0000-000000000000"' in main_content
    assert "resource_group_name           = data.azurerm_resource_group.primary.name" in main_content
    assert "location                      = data.azurerm_resource_group.primary.location" in main_content
    assert 'public_network_access_enabled = false' in main_content


def test_scaffold_subnet_omits_location(scaffold_engine: ScaffoldEngine):
    """Verify azurerm_subnet scaffolding omits location attribute and public_network_access_enabled."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_subnet",
        workload_name="appdata",
        environment="prod",
        resource_name="snet-appdata-prod",
        tags={"Environment": "prod"},
    )
    workspace = scaffold_engine.scaffold(params)
    main_content = workspace["main.tf"].content
    assert "resource_group_name = data.azurerm_resource_group.primary.name" in main_content
    assert "location" not in main_content
    assert "public_network_access_enabled" not in main_content


def test_scaffold_raises_standards_error_when_no_backend_rule():
    """Verify StandardsError is raised when subscription matches no backend rules."""
    # Bundle with no matching backend rule and no wildcard
    empty_bundle = StandardsBundle(
        backend_rules=[],
    )
    engine = StandardsEngine(empty_bundle)
    scaffold = ScaffoldEngine(engine)

    params = ProvisioningParameters(
        subscription="unmapped-subscription",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
    )
    with pytest.raises(StandardsError, match="No remote state backend mapping found"):
        scaffold.scaffold(params)


def test_scaffold_paas_resource_with_public_network_access_enabled(scaffold_engine: ScaffoldEngine):
    """Verify that explicitly setting public_network_access=True synthesizes public_network_access_enabled = true on PaaS resources."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        public_network_access=True,
    )
    workspace = scaffold_engine.scaffold(params)
    main_content = workspace["main.tf"].content

    assert 'resource "azurerm_storage_account" "primary" {' in main_content
    assert "public_network_access_enabled = true" in main_content

    parsed = hcl2.loads(main_content)
    assert parsed is not None
    res_block = parsed["resource"][0]['"azurerm_storage_account"']['"primary"']
    assert res_block["public_network_access_enabled"] is True
