"""Comprehensive test suite for Automated Private Endpoint & Hub Private DNS Zone Group Bundling (Story 3.3).

Validates:
- FR-13: Automated companion azurerm_private_endpoint and nested private_dns_zone_group bundling in main.tf
- FR-7 & AD-3: Decoupled data "azurerm_private_dns_zone" "hub" in data.tf with zero terraform_remote_state
- AD-1: Domain boundary isolation (pure domain logic in scaffold.py, standards.py, catalog.py)
- AD-7: Enterprise Security Triad guardrails for all Tier 1 PaaS services
- Canonical subresource names and Hub DNS zone resolution across all 9 Tier 1 PaaS services
- Foundation resource omission (resource group, vnet, subnet never scaffold private endpoint)
- Tier 1 PaaS without subnet omission
- Cross-subscription subnet binding
- Strict HCL AST syntax validity via python-hcl2
"""

from pathlib import Path
from unittest.mock import MagicMock
import hcl2
import pytest

from ttassistant.adapters.standards_adapter import MarkdownStandardsAdapter
from ttassistant.application.provisioning_flow import ProvisioningFlow
from ttassistant.domain.catalog import (
    PAAS_DEFAULT_DNS_ZONES,
    PAAS_SUBRESOURCE_NAMES,
    TIER_1_FOUNDATION_RESOURCES,
    TIER_1_PAAS_RESOURCES,
    get_paas_default_dns_zone,
    get_paas_subresource_names,
    is_tier_1_paas,
)
from ttassistant.domain.models import ProvisioningParameters
from ttassistant.domain.scaffold import ScaffoldEngine
from ttassistant.domain.standards import StandardsEngine
from ttassistant.ports.terminal import TerminalUIPort


@pytest.fixture
def standards_engine() -> StandardsEngine:
    """Load corporate standards engine from workspace common_standards/."""
    standards_dir = Path(__file__).resolve().parent.parent / "common_standards"
    adapter = MarkdownStandardsAdapter()
    bundle = adapter.load_standards(standards_dir)
    return StandardsEngine(bundle)


@pytest.fixture
def scaffold_engine(standards_engine: StandardsEngine) -> ScaffoldEngine:
    """Initialize ScaffoldEngine with corporate standards."""
    return ScaffoldEngine(standards=standards_engine)


@pytest.fixture
def mock_terminal() -> MagicMock:
    """Create a mock TerminalUIPort instance."""
    terminal = MagicMock(spec=TerminalUIPort)
    terminal.is_interactive.return_value = True
    return terminal


# ==============================================================================
# 1. Canonical Tier 1 PaaS Catalog Mappings
# ==============================================================================


def test_paas_catalog_has_all_tier_1_paas_services():
    """Verify that catalog subresource names and default DNS zones cover all 9 Tier 1 PaaS services."""
    assert len(TIER_1_PAAS_RESOURCES) == 9
    for resource_type in TIER_1_PAAS_RESOURCES:
        assert resource_type in PAAS_SUBRESOURCE_NAMES
        assert resource_type in PAAS_DEFAULT_DNS_ZONES
        assert len(get_paas_subresource_names(resource_type)) > 0
        assert get_paas_default_dns_zone(resource_type) is not None


# ==============================================================================
# 2. Storage Account Private Endpoint Bundling
# ==============================================================================


def test_storage_account_private_endpoint_bundling(scaffold_engine: ScaffoldEngine):
    """Verify scaffolding azurerm_storage_account with selected subnet bundles private endpoint and Hub DNS data source."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-data-prod",
        selected_vnet="vnet-prod",
        network_action="existing",
    )
    workspace = scaffold_engine.scaffold(params)
    assert workspace.target_dir == "azurerm_storage_account/sub-prod/"

    # --- Verify main.tf ---
    main_content = workspace["main.tf"].content
    assert 'resource "azurerm_storage_account" "primary" {' in main_content
    assert 'public_network_access_enabled = false' in main_content

    # Companion private endpoint block
    assert 'resource "azurerm_private_endpoint" "primary" {' in main_content
    assert 'name                = "pe-stappdataprod"' in main_content
    assert "location            = data.azurerm_resource_group.primary.location" in main_content
    assert "resource_group_name = data.azurerm_resource_group.primary.name" in main_content
    assert "subnet_id           = data.azurerm_subnet.primary.id" in main_content

    # Mandatory tags applied to private endpoint
    assert 'CostCenter  = "CC-1001"' in main_content
    assert 'Environment = "prod"' in main_content

    # Nested private_service_connection block
    assert "private_service_connection {" in main_content
    assert 'name                           = "psc-stappdataprod"' in main_content
    assert "private_connection_resource_id = azurerm_storage_account.primary.id" in main_content
    assert "is_manual_connection           = false" in main_content
    assert 'subresource_names              = ["blob"]' in main_content

    # Nested private_dns_zone_group block
    assert "private_dns_zone_group {" in main_content
    assert 'name                 = "default"' in main_content
    assert "data.azurerm_private_dns_zone.hub.id" in main_content

    # --- Verify data.tf ---
    data_content = workspace["data.tf"].content
    assert 'data "azurerm_resource_group" "primary" {' in data_content
    assert 'data "azurerm_virtual_network" "primary" {' in data_content
    assert 'data "azurerm_subnet" "primary" {' in data_content

    # Hub Private DNS zone data source
    assert 'data "azurerm_private_dns_zone" "hub" {' in data_content
    assert 'name                = "privatelink.blob.core.windows.net"' in data_content
    assert 'resource_group_name = "rg-hub-dns"' in data_content

    # Zero remote state
    assert "terraform_remote_state" not in data_content
    assert "terraform_remote_state" not in main_content

    # Verify python-hcl2 parses cleanly
    parsed_main = hcl2.loads(main_content)
    assert parsed_main is not None
    assert len(parsed_main["resource"]) == 2

    pe_block = parsed_main["resource"][1]['"azurerm_private_endpoint"']['"primary"']
    assert pe_block["name"] == '"pe-stappdataprod"'
    assert pe_block["subnet_id"] == "${data.azurerm_subnet.primary.id}"
    psc = pe_block["private_service_connection"][0]
    assert psc["name"] == '"psc-stappdataprod"'
    assert psc["subresource_names"] == ['"blob"']
    assert psc["is_manual_connection"] is False
    assert psc["private_connection_resource_id"] == "${azurerm_storage_account.primary.id}"

    pdz = pe_block["private_dns_zone_group"][0]
    assert pdz["name"] == '"default"'
    assert pdz["private_dns_zone_ids"] == ["${data.azurerm_private_dns_zone.hub.id}"]

    parsed_data = hcl2.loads(data_content)
    assert parsed_data is not None
    assert len(parsed_data["data"]) == 4


# ==============================================================================
# 3. Key Vault Private Endpoint Bundling
# ==============================================================================


def test_key_vault_private_endpoint_bundling(scaffold_engine: ScaffoldEngine):
    """Verify scaffolding azurerm_key_vault with selected subnet bundles private endpoint with vault subresource and vaultcore DNS zone."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_key_vault",
        workload_name="appsecrets",
        environment="prod",
        resource_name="kv-appsecrets-prod",
        tags={"Environment": "prod"},
        selected_subnet="snet-sec-prod",
        selected_vnet="vnet-prod",
        network_action="existing",
    )
    workspace = scaffold_engine.scaffold(params)

    main_content = workspace["main.tf"].content
    assert 'resource "azurerm_private_endpoint" "primary" {' in main_content
    assert 'name                = "pe-kv-appsecrets-prod"' in main_content
    assert 'name                           = "psc-kv-appsecrets-prod"' in main_content
    assert "private_connection_resource_id = azurerm_key_vault.primary.id" in main_content
    assert 'subresource_names              = ["vault"]' in main_content

    data_content = workspace["data.tf"].content
    assert 'data "azurerm_private_dns_zone" "hub" {' in data_content
    assert 'name                = "privatelink.vaultcore.azure.net"' in data_content
    assert 'resource_group_name = "rg-hub-dns"' in data_content

    # Strict AST validation
    parsed_main = hcl2.loads(main_content)
    assert parsed_main is not None
    pe = parsed_main["resource"][1]['"azurerm_private_endpoint"']['"primary"']
    assert pe["private_service_connection"][0]["subresource_names"] == ['"vault"']

    parsed_data = hcl2.loads(data_content)
    assert parsed_data is not None
    assert len(parsed_data["data"]) == 4


# ==============================================================================
# 4. Parameterized Test for All 9 Tier 1 PaaS Services
# ==============================================================================


@pytest.mark.parametrize(
    "resource_type,expected_subresource,expected_dns_zone",
    [
        ("azurerm_storage_account", ["blob"], "privatelink.blob.core.windows.net"),
        ("azurerm_key_vault", ["vault"], "privatelink.vaultcore.azure.net"),
        ("azurerm_mssql_server", ["sqlServer"], "privatelink.database.windows.net"),
        ("azurerm_cosmosdb_account", ["Sql"], "privatelink.documents.azure.com"),
        ("azurerm_eventhub_namespace", ["namespace"], "privatelink.servicebus.windows.net"),
        ("azurerm_postgresql_flexible_server", ["postgresqlServer"], "privatelink.postgres.database.azure.com"),
        ("azurerm_mysql_flexible_server", ["mysqlServer"], "privatelink.mysql.database.azure.com"),
        ("azurerm_redis_cache", ["redisCache"], "privatelink.redis.cache.windows.net"),
        ("azurerm_linux_web_app", ["sites"], "privatelink.azurewebsites.net"),
    ],
)
def test_all_tier_1_paas_synthesize_correct_subresource_and_hub_dns(
    scaffold_engine: ScaffoldEngine,
    resource_type: str,
    expected_subresource: list[str],
    expected_dns_zone: str,
):
    """Verify that every Tier 1 PaaS service scaffolds its canonical subresource name and matching Hub DNS zone."""
    assert is_tier_1_paas(resource_type) is True

    clean_name = resource_type.replace("azurerm_", "").replace("_", "")[:12]
    res_name = f"{clean_name}prod"

    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type=resource_type,
        workload_name="testapp",
        environment="prod",
        resource_name=res_name,
        tags={"Environment": "prod"},
        selected_subnet="snet-paas-prod",
        selected_vnet="vnet-prod",
        network_action="existing",
    )

    workspace = scaffold_engine.scaffold(params)
    main_content = workspace["main.tf"].content
    data_content = workspace["data.tf"].content

    # main.tf assertions
    assert f'resource "{resource_type}" "primary" {{' in main_content
    assert 'resource "azurerm_private_endpoint" "primary" {' in main_content
    assert f'name                = "pe-{res_name}"' in main_content
    assert f"private_connection_resource_id = {resource_type}.primary.id" in main_content
    assert f'subresource_names              = ["{expected_subresource[0]}"]' in main_content
    assert "private_dns_zone_group {" in main_content

    # data.tf assertions
    assert 'data "azurerm_private_dns_zone" "hub" {' in data_content
    assert f'name                = "{expected_dns_zone}"' in data_content
    assert 'resource_group_name = "rg-hub-dns"' in data_content

    # Parse validity
    parsed_main = hcl2.loads(main_content)
    assert parsed_main is not None
    pe = parsed_main["resource"][1]['"azurerm_private_endpoint"']['"primary"']
    assert pe["private_service_connection"][0]["subresource_names"] == [f'"{expected_subresource[0]}"']

    parsed_data = hcl2.loads(data_content)
    assert parsed_data is not None
    assert len(parsed_data["data"]) == 4


# ==============================================================================
# 5. Non-PaaS Foundation Resources Omission
# ==============================================================================


@pytest.mark.parametrize("foundation_type", sorted(TIER_1_FOUNDATION_RESOURCES))
def test_foundation_resources_omit_private_endpoint_and_dns(
    scaffold_engine: ScaffoldEngine, foundation_type: str
):
    """Verify foundation resources (resource group, vnet, subnet) never scaffold private endpoint or DNS zone."""
    assert is_tier_1_paas(foundation_type) is False

    clean_name = foundation_type.replace("azurerm_", "").replace("_", "-")
    res_name = f"{clean_name}-prod"

    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type=foundation_type,
        workload_name="corenet",
        environment="prod",
        resource_name=res_name,
        tags={"Environment": "prod"},
        selected_subnet="snet-existing-01" if foundation_type != "azurerm_resource_group" else None,
        network_action="existing",
    )

    workspace = scaffold_engine.scaffold(params)
    main_content = workspace["main.tf"].content

    assert "azurerm_private_endpoint" not in main_content
    assert "private_service_connection" not in main_content
    assert "private_dns_zone_group" not in main_content

    if "data.tf" in workspace:
        data_content = workspace["data.tf"].content
        assert "azurerm_private_dns_zone" not in data_content

    parsed_main = hcl2.loads(main_content)
    assert parsed_main is not None
    assert len(parsed_main["resource"]) == 1


# ==============================================================================
# 6. Tier 1 PaaS Without Subnet Omission
# ==============================================================================


def test_paas_resource_without_subnet_omits_private_endpoint(scaffold_engine: ScaffoldEngine):
    """Verify Tier 1 PaaS without selected subnet omits private endpoint and Hub DNS data source."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet=None,
    )
    workspace = scaffold_engine.scaffold(params)

    main_content = workspace["main.tf"].content
    assert 'resource "azurerm_storage_account" "primary" {' in main_content
    assert "azurerm_private_endpoint" not in main_content

    data_content = workspace["data.tf"].content
    assert "azurerm_private_dns_zone" not in data_content

    parsed_main = hcl2.loads(main_content)
    assert parsed_main is not None
    assert len(parsed_main["resource"]) == 1


# ==============================================================================
# 7. Cross-Subscription Subnet Binding
# ==============================================================================


def test_cross_subscription_subnet_binding_private_endpoint(scaffold_engine: ScaffoldEngine):
    """Verify cross-subscription subnet binding wires private endpoint to data.azurerm_subnet.primary.id referencing remote VNet."""
    params = ProvisioningParameters(
        subscription="sub-workload-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-hub-pe",
        selected_vnet="vnet-hub-core",
        selected_subnet_rg="rg-hub-network",
        network_action="cross_subscription",
        cross_sub_source="sub-hub",
    )
    workspace = scaffold_engine.scaffold(params)

    main_content = workspace["main.tf"].content
    data_content = workspace["data.tf"].content

    # Private endpoint references primary subnet
    assert 'resource "azurerm_private_endpoint" "primary" {' in main_content
    assert "subnet_id           = data.azurerm_subnet.primary.id" in main_content

    # data.tf has cross-sub provider on subnet and VNet, plus Hub DNS data source
    assert 'data "azurerm_virtual_network" "primary" {' in data_content
    assert "provider            = azurerm.sub_hub" in data_content
    assert 'data "azurerm_subnet" "primary" {' in data_content
    assert "provider             = azurerm.sub_hub" in data_content

    assert 'data "azurerm_private_dns_zone" "hub" {' in data_content
    assert 'name                = "privatelink.blob.core.windows.net"' in data_content
    assert 'resource_group_name = "rg-hub-dns"' in data_content

    # Strict HCL parsing
    parsed_main = hcl2.loads(main_content)
    assert parsed_main is not None
    assert len(parsed_main["resource"]) == 2

    parsed_data = hcl2.loads(data_content)
    assert parsed_data is not None
    assert len(parsed_data["data"]) == 4


# ==============================================================================
# 8. ProvisioningFlow Integration & Terminal Display
# ==============================================================================


def test_provisioning_flow_displays_private_endpoint_summary(mock_terminal, standards_engine):
    """Verify ProvisioningFlow outputs Private Endpoint and Hub DNS summary when subnet is selected."""
    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        subnet="snet-data-prod",
        auto_approve=True,
    )

    assert params.selected_subnet == "snet-data-prod"
    assert "main.tf" in workspace
    assert "azurerm_private_endpoint" in workspace["main.tf"].content
    assert "azurerm_private_dns_zone" in workspace["data.tf"].content

    # Check terminal print calls for PE summary
    print_calls = [call[0][0] for call in mock_terminal.print.call_args_list if call[0]]
    assert any("Private Endpoint: Enabled (pe-stappdataprod)" in c for c in print_calls)
    assert any("Hub DNS Zone:  privatelink.blob.core.windows.net" in c for c in print_calls)


def test_network_action_none_suppresses_private_endpoint_and_dns(scaffold_engine: ScaffoldEngine):
    """Verify that network_action='none' suppresses private endpoint and DNS zone blocks even if subnet is provided."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-data-prod",
        network_action="none",
    )
    workspace = scaffold_engine.scaffold(params)
    main_content = workspace["main.tf"].content
    assert "azurerm_private_endpoint" not in main_content
    data_content = workspace["data.tf"].content
    assert "azurerm_private_dns_zone" not in data_content


def test_provisioning_flow_warning_when_subnet_is_none(mock_terminal, standards_engine):
    """Verify ProvisioningFlow prints a warning when Tier 1 PaaS has no subnet selected."""
    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )
    assert params.selected_subnet is None
    assert "azurerm_private_endpoint" not in workspace["main.tf"].content
    assert "azurerm_private_dns_zone" not in workspace["data.tf"].content

    # Verify terminal print_warning was called with PE omitted message
    warning_calls = [call[0][0] for call in mock_terminal.print_warning.call_args_list if call[0]]
    assert any("Private Endpoint: Omitted (no subnet selected)" in c for c in warning_calls)


def test_scaffold_raises_standards_error_when_zone_name_empty():
    """Verify StandardsError is raised in synthesize_data if DNS zone cannot be resolved."""
    from ttassistant.domain.exceptions import StandardsError
    from ttassistant.domain.models import BackendMappingRule, StandardsBundle

    empty_bundle = StandardsBundle(
        backend_rules=[
            BackendMappingRule(
                subscription="*",
                storage_account_name="stdefault",
                resource_group_name="rg-default",
            )
        ],
        networking_rules={},
    )
    engine = StandardsEngine(empty_bundle)
    engine.resolve_hub_dns_zone = lambda rt: {"name": "", "resource_group_name": "rg-hub"}
    scaffold = ScaffoldEngine(engine)
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        selected_subnet="snet-test",
        network_action="existing",
    )
    with pytest.raises(StandardsError, match="No Private DNS Zone resolved"):
        scaffold.synthesize_data(params)


def test_scaffold_validates_pe_name_against_naming_rule(standards_engine):
    """Verify ValueError is raised if synthesized pe_name violates azurerm_private_endpoint naming rules."""
    scaffold = ScaffoldEngine(standards_engine)
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        # Resource name with underscore will yield pe-invalid_name which violates ^pe-[a-z0-9-]+$
        resource_name="invalid_name_with_underscores",
        selected_subnet="snet-test",
        network_action="existing",
    )
    with pytest.raises(ValueError, match="Invalid private endpoint name|does not match naming pattern"):
        scaffold.synthesize_main(params)
