"""Comprehensive unit and integration test suite for Story 2.4: Decoupled Data Source Generator.

Verifies:
- Scaffolding data.tf with decoupled upstream data sources (RG, VNet, Subnet).
- Single-subscription, cross-subscription, and greenfield/skipped network flows.
- Strictly zero terraform_remote_state data blocks.
- Deterministic alphabetical attribute ordering.
- Proper HCL reference types.
- Remote subscription, VNet, RG, and Subnet naming validations.
- python-hcl2 syntax parsing across all outputs.
- Integration with ProvisioningFlow and DiscoveredTopology.
- Zero local binaries (terraform, az) invoked.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import hcl2
import pytest

from ttassistant.adapters.standards_adapter import MarkdownStandardsAdapter
from ttassistant.application.provisioning_flow import ProvisioningFlow
from ttassistant.domain.models import (
    ProvisioningParameters,
    StagedWorkspace,
)
from ttassistant.domain.scaffold import ScaffoldEngine
from ttassistant.domain.standards import StandardsEngine
from ttassistant.domain.topology import DiscoveredTopology, SubnetCandidate
from ttassistant.ports.terminal import TerminalUIPort


@pytest.fixture
def standards_engine() -> StandardsEngine:
    """Load real standards engine from workspace common_standards."""
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
# Domain Unit Tests: ScaffoldEngine.synthesize_data
# ==============================================================================


def test_data_tf_with_selected_subnet_single_subscription(scaffold_engine: ScaffoldEngine):
    """Verify workload with selected subnet and VNet emits RG, VNet, and Subnet data sources with zero remote state."""
    params = ProvisioningParameters(
        subscription="sub-prod",
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
    assert "data.tf" in workspace
    data_file = workspace["data.tf"]
    data_content = data_file.content

    # Zero remote state enforcement (AD-3, FR-7)
    assert "terraform_remote_state" not in data_content

    # No hardcoded Azure IDs
    assert "/subscriptions/" not in data_content
    assert "00000000-0000-0000-0000-000000000000" not in data_content

    # Emits data "azurerm_resource_group" "primary"
    assert 'data "azurerm_resource_group" "primary" {' in data_content
    assert 'name = "rg-tfstate-default"' in data_content

    # Emits data "azurerm_virtual_network" "primary"
    assert 'data "azurerm_virtual_network" "primary" {' in data_content
    assert 'name                = "vnet-prod"' in data_content
    assert "resource_group_name = data.azurerm_resource_group.primary.name" in data_content

    # Emits data "azurerm_subnet" "primary"
    assert 'data "azurerm_subnet" "primary" {' in data_content
    assert 'name                 = "snet-pe-01"' in data_content
    assert "resource_group_name  = data.azurerm_virtual_network.primary.resource_group_name" in data_content
    assert "virtual_network_name = data.azurerm_virtual_network.primary.name" in data_content

    # Attribute ordering: deterministic alphabetical
    # In VNet: name before resource_group_name
    vnet_pos = data_content.find('data "azurerm_virtual_network" "primary"')
    snet_pos = data_content.find('data "azurerm_subnet" "primary"')
    assert vnet_pos > 0
    assert snet_pos > vnet_pos

    vnet_snippet = data_content[vnet_pos:snet_pos]
    assert vnet_snippet.find("name") < vnet_snippet.find("resource_group_name")

    snet_snippet = data_content[snet_pos:]
    name_idx = snet_snippet.find("name")
    rg_idx = snet_snippet.find("resource_group_name")
    vnet_idx = snet_snippet.find("virtual_network_name")
    assert name_idx < rg_idx < vnet_idx

    # HCL AST validity via python-hcl2
    parsed = hcl2.loads(data_content)
    assert parsed is not None
    assert "data" in parsed
    assert len(parsed["data"]) == 4

    # Metadata validation
    assert data_file.metadata["subnet"] == "snet-pe-01"
    assert data_file.metadata["vnet"] == "vnet-prod"


def test_data_tf_with_selected_subnet_custom_rg(scaffold_engine: ScaffoldEngine):
    """Verify workload with selected subnet and custom RG emits explicit RG string reference on VNet."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-pe-01",
        selected_vnet="vnet-prod",
        selected_subnet_rg="rg-networking-prod",
        network_action="existing",
    )
    workspace = scaffold_engine.scaffold(params)
    data_content = workspace["data.tf"].content

    assert 'resource_group_name = "rg-networking-prod"' in data_content
    assert "resource_group_name  = data.azurerm_virtual_network.primary.resource_group_name" in data_content
    parsed = hcl2.loads(data_content)
    assert parsed is not None


def test_data_tf_inferred_vnet_name(scaffold_engine: ScaffoldEngine):
    """Verify workload with selected subnet but unspecified VNet infers vnet-<subscription>."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-pe-01",
        selected_vnet=None,
        network_action="existing",
    )
    workspace = scaffold_engine.scaffold(params)
    data_content = workspace["data.tf"].content

    assert 'name                = "vnet-sub-prod"' in data_content
    assert "resource_group_name = data.azurerm_resource_group.primary.name" in data_content
    assert "resource_group_name  = data.azurerm_virtual_network.primary.resource_group_name" in data_content
    assert "virtual_network_name = data.azurerm_virtual_network.primary.name" in data_content

    parsed = hcl2.loads(data_content)
    assert parsed is not None


def test_data_tf_cross_subscription_shared_subnet(scaffold_engine: ScaffoldEngine):
    """Verify cross-subscription shared subnet emits provider reference and remote hub coordinates."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-shared-01",
        network_action="cross_subscription",
        cross_sub_source="sub-hub",
    )
    workspace = scaffold_engine.scaffold(params)
    data_content = workspace["data.tf"].content

    # Zero remote state
    assert "terraform_remote_state" not in data_content

    # Target workload RG remains in target subscription
    assert 'data "azurerm_resource_group" "primary" {' in data_content
    assert 'name = "rg-tfstate-default"' in data_content

    # VNet data source has remote hub coordinates and provider alias
    assert 'data "azurerm_virtual_network" "primary" {' in data_content
    assert 'name                = "vnet-sub-hub"' in data_content
    assert "provider            = azurerm.sub_hub" in data_content
    assert 'resource_group_name = "rg-sub-hub"' in data_content

    # Subnet data source has provider alias and VNet references
    assert 'data "azurerm_subnet" "primary" {' in data_content
    assert 'name                 = "snet-shared-01"' in data_content
    assert "provider             = azurerm.sub_hub" in data_content
    assert "resource_group_name  = data.azurerm_virtual_network.primary.resource_group_name" in data_content
    assert "virtual_network_name = data.azurerm_virtual_network.primary.name" in data_content

    # Alphabetical attribute order: name < provider < resource_group_name
    vnet_pos = data_content.find('data "azurerm_virtual_network" "primary"')
    snet_pos = data_content.find('data "azurerm_subnet" "primary"')
    vnet_snippet = data_content[vnet_pos:snet_pos]
    assert vnet_snippet.find("name") < vnet_snippet.find("provider") < vnet_snippet.find("resource_group_name")

    snet_snippet = data_content[snet_pos:]
    assert (
        snet_snippet.find("name")
        < snet_snippet.find("provider")
        < snet_snippet.find("resource_group_name")
        < snet_snippet.find("virtual_network_name")
    )

    parsed = hcl2.loads(data_content)
    assert parsed is not None
    assert len(parsed["data"]) == 4


def test_data_tf_cross_subscription_remote_alias_action(scaffold_engine: ScaffoldEngine):
    """Verify network_action='remote' is treated as cross-subscription."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-hub-pe",
        selected_vnet="vnet-core-hub",
        selected_subnet_rg="rg-core-networking",
        network_action="remote",
        cross_sub_source="core-hub",
    )
    workspace = scaffold_engine.scaffold(params)
    data_content = workspace["data.tf"].content

    assert "provider            = azurerm.core_hub" in data_content
    assert 'name                = "vnet-core-hub"' in data_content
    assert 'resource_group_name = "rg-core-networking"' in data_content

    parsed = hcl2.loads(data_content)
    assert parsed is not None


def test_data_tf_skipped_network_configuration(scaffold_engine: ScaffoldEngine):
    """Verify greenfield / skipped network configuration emits only resource group data source."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet=None,
        network_action="none",
    )
    workspace = scaffold_engine.scaffold(params)
    assert "data.tf" in workspace
    data_content = workspace["data.tf"].content

    assert 'data "azurerm_resource_group" "primary" {' in data_content
    assert 'data "azurerm_virtual_network"' not in data_content
    assert 'data "azurerm_subnet"' not in data_content
    assert "terraform_remote_state" not in data_content

    parsed = hcl2.loads(data_content)
    assert parsed is not None
    assert len(parsed["data"]) == 1


def test_data_tf_omitted_for_resource_group_workload(scaffold_engine: ScaffoldEngine):
    """Verify scaffolding azurerm_resource_group omits data.tf completely."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_resource_group",
        workload_name="network",
        environment="prod",
        resource_name="rg-network-prod",
        tags={"Environment": "prod"},
    )
    workspace = scaffold_engine.scaffold(params)
    assert "data.tf" not in workspace
    assert "main.tf" in workspace
    assert "backend.tf" in workspace


# ==============================================================================
# Validation & Error Handling Tests
# ==============================================================================


def test_data_tf_rejects_invalid_remote_subscription_format(scaffold_engine: ScaffoldEngine):
    """Verify cross-subscription synthesis rejects invalid source subscription format."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-pe-01",
        network_action="cross_subscription",
        cross_sub_source="invalid sub!@#$",
    )
    with pytest.raises(ValueError, match="Invalid remote subscription format"):
        scaffold_engine.synthesize_data(params)


def test_data_tf_rejects_self_referential_remote_subscription(scaffold_engine: ScaffoldEngine):
    """Verify cross-subscription synthesis rejects source subscription matching target subscription."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-pe-01",
        network_action="cross_subscription",
        cross_sub_source="sub-prod",
    )
    with pytest.raises(ValueError, match="Remote subscription cannot be the same"):
        scaffold_engine.synthesize_data(params)


def test_data_tf_rejects_invalid_vnet_name(scaffold_engine: ScaffoldEngine):
    """Verify synthesis validates parent VNet name against naming conventions."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-pe-01",
        selected_vnet="invalid_vnet_name!",
        network_action="existing",
    )
    with pytest.raises(ValueError, match="does not match naming pattern"):
        scaffold_engine.synthesize_data(params)


def test_data_tf_rejects_invalid_subnet_name(scaffold_engine: ScaffoldEngine):
    """Verify synthesis validates selected Subnet name against naming conventions."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="invalid_subnet!",
        selected_vnet="vnet-prod",
        network_action="existing",
    )
    with pytest.raises(ValueError, match="does not match naming pattern"):
        scaffold_engine.synthesize_data(params)


def test_data_tf_rejects_invalid_subnet_rg_name(scaffold_engine: ScaffoldEngine):
    """Verify synthesis validates custom subnet RG name against naming conventions."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-pe-01",
        selected_vnet="vnet-prod",
        selected_subnet_rg="invalid_rg!@#",
        network_action="existing",
    )
    with pytest.raises(ValueError, match="does not match naming pattern"):
        scaffold_engine.synthesize_data(params)


# ==============================================================================
# Integration Tests: ProvisioningFlow Wiring
# ==============================================================================


def test_provisioning_flow_wires_candidate_vnet_and_rg_into_data_tf(
    mock_terminal: MagicMock,
    standards_engine: StandardsEngine,
):
    """Verify candidate subnet selection passes parent VNet and RG metadata into ProvisioningParameters and data.tf."""
    candidate = SubnetCandidate(
        name="snet-pe-prod",
        address_prefixes=["10.0.2.0/24"],
        virtual_network_name="vnet-corporate-prod",
        resource_group_name="rg-network-prod",
        subscription="sub-prod",
        is_private_endpoint_candidate=True,
    )
    topology = DiscoveredTopology(subnets=[candidate])
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )

    mock_terminal.prompt_select_subnet.return_value = (
        "snet-pe-prod [10.0.2.0/24] (vnet-corporate-prod / rg-network-prod) - Private Endpoint (Recommended)"
    )

    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )

    # ProvisioningParameters metadata wired
    assert params.selected_subnet == "snet-pe-prod"
    assert params.selected_vnet == "vnet-corporate-prod"
    assert params.selected_subnet_rg == "rg-network-prod"
    assert params.network_action == "existing"

    # data.tf populated with decoupled data sources
    assert "data.tf" in workspace
    data_content = workspace["data.tf"].content

    assert 'data "azurerm_resource_group" "primary"' in data_content
    assert 'data "azurerm_virtual_network" "primary"' in data_content
    assert 'name                = "vnet-corporate-prod"' in data_content
    assert 'resource_group_name = "rg-network-prod"' in data_content
    assert 'data "azurerm_subnet" "primary"' in data_content
    assert 'name                 = "snet-pe-prod"' in data_content
    assert "resource_group_name  = data.azurerm_virtual_network.primary.resource_group_name" in data_content
    assert "virtual_network_name = data.azurerm_virtual_network.primary.name" in data_content
    assert "terraform_remote_state" not in data_content

    # python-hcl2 valid
    parsed = hcl2.loads(data_content)
    assert parsed is not None


def test_provisioning_flow_missing_subnet_scaffold_wires_data_tf(
    mock_terminal: MagicMock,
    standards_engine: StandardsEngine,
):
    """Verify scaffolding a missing subnet updates workload data.tf with generated subnet and VNet."""
    topology = DiscoveredTopology(subnets=[])
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )

    mock_terminal.prompt_select.return_value = "Scaffold missing subnet in this subscription"
    mock_terminal.prompt_text.side_effect = ["snet-pe-01", "10.0.5.0/24", "vnet-prod"]

    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )

    assert params.selected_subnet == "snet-pe-01"
    assert params.selected_vnet == "vnet-prod"
    assert params.network_action == "scaffold"

    # Workload data.tf references scaffolded network
    workload_data = workspace["data.tf"].content
    assert 'name                = "vnet-prod"' in workload_data
    assert 'name                 = "snet-pe-01"' in workload_data
    assert "virtual_network_name = data.azurerm_virtual_network.primary.name" in workload_data
    assert "terraform_remote_state" not in workload_data

    parsed = hcl2.loads(workload_data)
    assert parsed is not None


def test_provisioning_flow_cross_subscription_wires_data_tf(
    mock_terminal: MagicMock,
    standards_engine: StandardsEngine,
):
    """Verify cross-subscription selection in flow wires provider and coordinates into data.tf."""
    topology = DiscoveredTopology(subnets=[])
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )

    mock_terminal.prompt_select.return_value = "Configure cross-subscription shared network lookup"
    mock_terminal.prompt_text.side_effect = ["core-networking", "snet-shared-01"]

    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )

    assert params.selected_subnet == "snet-shared-01"
    assert params.network_action == "cross_subscription"
    assert params.cross_sub_source == "core-networking"

    workload_data = workspace["data.tf"].content
    assert "provider            = azurerm.core_networking" in workload_data
    assert 'name                = "vnet-core-networking"' in workload_data
    assert 'resource_group_name = "rg-core-networking"' in workload_data
    assert "provider             = azurerm.core_networking" in workload_data
    assert 'name                 = "snet-shared-01"' in workload_data
    assert "terraform_remote_state" not in workload_data

    parsed = hcl2.loads(workload_data)
    assert parsed is not None


# ==============================================================================
# Security & Air-Gap Verification: Zero External Binaries
# ==============================================================================


def test_data_source_synthesis_never_invokes_external_binaries(
    scaffold_engine: ScaffoldEngine,
):
    """Verify data source synthesis and AST validation execute purely in Python without external binaries."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-pe-01",
        selected_vnet="vnet-prod",
        network_action="existing",
    )
    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen, patch("os.system") as mock_sys:
        workspace = scaffold_engine.scaffold(params)
        data_content = workspace["data.tf"].content
        parsed = hcl2.loads(data_content)

        assert parsed is not None
        assert mock_run.call_count == 0
        assert mock_popen.call_count == 0
        assert mock_sys.call_count == 0


def test_provisioning_flow_pre_seeded_subnet_wires_candidate_vnet_and_rg_into_data_tf(
    mock_terminal: MagicMock,
    standards_engine: StandardsEngine,
):
    """Verify pre-seeded subnet flag wires candidate VNet and RG metadata into data.tf."""
    candidate = SubnetCandidate(
        name="snet-pe-01",
        address_prefixes=["10.0.1.0/24"],
        virtual_network_name="vnet-corporate-prod",
        resource_group_name="rg-network-prod",
        subscription="sub-prod",
        is_private_endpoint_candidate=True,
    )
    topology = DiscoveredTopology(subnets=[candidate])
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )

    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        subnet="snet-pe-01",
        auto_approve=True,
    )

    assert params.selected_subnet == "snet-pe-01"
    assert params.selected_vnet == "vnet-corporate-prod"
    assert params.selected_subnet_rg == "rg-network-prod"
    assert params.network_action == "existing"

    data_content = workspace["data.tf"].content
    assert 'name                = "vnet-corporate-prod"' in data_content
    assert 'resource_group_name = "rg-network-prod"' in data_content
    assert 'name                 = "snet-pe-01"' in data_content
    assert "virtual_network_name = data.azurerm_virtual_network.primary.name" in data_content

    mock_terminal.prompt_select_subnet.assert_not_called()


def test_provisioning_flow_non_interactive_auto_approve_selects_recommended_subnet_and_wires_data_tf(
    mock_terminal: MagicMock,
    standards_engine: StandardsEngine,
):
    """Verify non-interactive auto-approve selects recommended subnet and wires candidate VNet and RG."""
    c1 = SubnetCandidate(
        name="snet-general-01",
        address_prefixes=["10.0.0.0/24"],
        virtual_network_name="vnet-general-prod",
        resource_group_name="rg-general-prod",
        subscription="sub-prod",
        is_private_endpoint_candidate=False,
    )
    c2 = SubnetCandidate(
        name="snet-pe-recommended",
        address_prefixes=["10.0.1.0/24"],
        virtual_network_name="vnet-corporate-prod",
        resource_group_name="rg-network-prod",
        subscription="sub-prod",
        is_private_endpoint_candidate=True,
    )
    topology = DiscoveredTopology(subnets=[c1, c2])
    mock_terminal.is_interactive.return_value = False

    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )

    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )

    assert params.selected_subnet == "snet-pe-recommended"
    assert params.selected_vnet == "vnet-corporate-prod"
    assert params.selected_subnet_rg == "rg-network-prod"
    assert params.network_action == "existing"

    data_content = workspace["data.tf"].content
    assert 'name                = "vnet-corporate-prod"' in data_content
    assert 'resource_group_name = "rg-network-prod"' in data_content
    assert 'name                 = "snet-pe-recommended"' in data_content

    mock_terminal.prompt_select_subnet.assert_not_called()


def test_data_tf_rejects_invalid_parent_resource_group_name(scaffold_engine: ScaffoldEngine):
    """Verify synthesis rejects parent resource group name violating corporate naming conventions."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
    )
    with patch.object(
        scaffold_engine.standards,
        "resolve_backend",
        return_value={"resource_group_name": "INVALID_RG!@#"},
    ):
        with pytest.raises(ValueError, match="does not match naming pattern"):
            scaffold_engine.synthesize_data(params)


def test_data_tf_cross_subscription_numeric_and_uuid_provider_alias(scaffold_engine: ScaffoldEngine):
    """Verify numeric or UUID cross-subscription source generates valid HCL identifier with sub_ prefix."""
    params_numeric = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-shared-01",
        network_action="cross_subscription",
        cross_sub_source="123-prod",
    )
    ws_numeric = scaffold_engine.scaffold(params_numeric)
    content_numeric = ws_numeric["data.tf"].content
    assert "provider            = azurerm.sub_123_prod" in content_numeric
    assert "provider             = azurerm.sub_123_prod" in content_numeric
    assert hcl2.loads(content_numeric) is not None

    params_uuid = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet="snet-shared-01",
        network_action="cross_subscription",
        cross_sub_source="00000000-0000-0000-0000-000000000000",
    )
    ws_uuid = scaffold_engine.scaffold(params_uuid)
    content_uuid = ws_uuid["data.tf"].content
    assert "provider            = azurerm.sub_00000000_0000_0000_0000_000000000000" in content_uuid
    assert hcl2.loads(content_uuid) is not None


@pytest.mark.parametrize(
    "reserved_name",
    ["GatewaySubnet", "AzureBastionSubnet", "AzureFirewallSubnet", "RouteServerSubnet"],
)
def test_data_tf_azure_reserved_subnets_allowed(scaffold_engine: ScaffoldEngine, reserved_name: str):
    """Verify Azure-reserved subnets pass validation without requiring snet- prefix."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        selected_subnet=reserved_name,
        selected_vnet="vnet-prod",
        network_action="existing",
    )
    workspace = scaffold_engine.scaffold(params)
    data_content = workspace["data.tf"].content
    assert f'name                 = "{reserved_name}"' in data_content
    assert hcl2.loads(data_content) is not None
