"""Unit and integration tests for Story 2.3: Collaborative Subnet Selection & Missing Dependency Scaffolding."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import typer
from typer.testing import CliRunner

from ttassistant.adapters.fs_adapter import DiskFileSystemAdapter
from ttassistant.adapters.standards_adapter import MarkdownStandardsAdapter
from ttassistant.adapters.terminal_adapter import RichTerminalAdapter
from ttassistant.application.provisioning_flow import ProvisioningFlow
from ttassistant.cli import app
from ttassistant.domain.diff import compute_workspace_diff
from ttassistant.domain.exceptions import FileSystemError
from ttassistant.domain.models import (
    ProvisioningParameters,
    StagedFile,
    StagedWorkspace,
)
from ttassistant.domain.scaffold import ScaffoldEngine
from ttassistant.domain.standards import StandardsEngine
from ttassistant.domain.topology import (
    DiscoveredTopology,
    SubnetCandidate,
    VirtualNetworkCandidate,
)
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
    return terminal


def test_scaffold_subnet_synthesizes_compliant_files(scaffold_engine: ScaffoldEngine):
    """Verify scaffold_subnet creates compliant main.tf, data.tf, and backend.tf in azurerm_subnet/<subprod>/."""
    files = scaffold_engine.scaffold_subnet(
        subscription="sub-prod",
        subnet_name="snet-pe-01",
        address_prefixes=["10.0.1.0/24"],
        vnet_name="vnet-corporate-prod",
        environment="prod",
    )

    assert len(files) == 3
    paths = {f.path for f in files}
    assert "azurerm_subnet/sub-prod/main.tf" in paths
    assert "azurerm_subnet/sub-prod/data.tf" in paths
    assert "azurerm_subnet/sub-prod/backend.tf" in paths

    main_file = next(f for f in files if f.filename == "main.tf")
    assert 'resource "azurerm_subnet" "primary"' in main_file.content
    assert 'name                 = "snet-pe-01"' in main_file.content
    assert "resource_group_name  = data.azurerm_resource_group.primary.name" in main_file.content
    assert "virtual_network_name = data.azurerm_virtual_network.primary.name" in main_file.content
    assert 'address_prefixes     = ["10.0.1.0/24"]' in main_file.content
    assert "tags" not in main_file.content
    assert "location" not in main_file.content

    data_file = next(f for f in files if f.filename == "data.tf")
    assert 'data "azurerm_resource_group" "primary"' in data_file.content
    assert 'data "azurerm_virtual_network" "primary"' in data_file.content
    assert '"vnet-corporate-prod"' in data_file.content

    backend_file = next(f for f in files if f.filename == "backend.tf")
    assert 'backend "azurerm"' in backend_file.content
    assert 'key                  = "sub-prod/azurerm_subnet.tfstate"' in backend_file.content


def test_scaffold_subnet_validates_naming_convention(scaffold_engine: ScaffoldEngine):
    """Verify scaffold_subnet rejects non-compliant subnet names against corporate naming rules."""
    with pytest.raises(ValueError, match="does not match naming pattern"):
        scaffold_engine.scaffold_subnet(
            subscription="sub-prod",
            subnet_name="INVALID_NAME_WITH_CAPS",
            address_prefixes=["10.0.1.0/24"],
        )


def test_multiple_candidate_subnets_selection_and_recommended_default(
    mock_terminal, standards_engine
):
    """Verify Scenario 1: Multiple candidate subnets prioritize and recommend matching subnet."""
    s1 = SubnetCandidate(
        name="snet-workload-01",
        address_prefixes=["10.0.2.0/24"],
        virtual_network_name="vnet-prod",
        resource_group_name="rg-prod",
        subscription="sub-prod",
        is_private_endpoint_candidate=False,
    )
    s2 = SubnetCandidate(
        name="snet-paas-01",
        address_prefixes=["10.0.1.0/24"],
        virtual_network_name="vnet-prod",
        resource_group_name="rg-prod",
        subscription="sub-prod",
        is_private_endpoint_candidate=True,
    )
    s3 = SubnetCandidate(
        name="snet-mgmt-01",
        address_prefixes=["10.0.3.0/24"],
        virtual_network_name="vnet-prod",
        resource_group_name="rg-prod",
        subscription="sub-prod",
        is_private_endpoint_candidate=False,
    )

    topology = DiscoveredTopology(subnets=[s1, s2, s3])
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )

    # When prompted, user accepts the default recommendation (s2)
    def fake_prompt_select_subnet(prompt, choices, default=None):
        assert default is not None
        assert "snet-paas-01" in default
        assert "(Recommended)" in default
        # Verify recommended choice is first in choices list
        assert choices[0] == default
        return default

    mock_terminal.prompt_select_subnet.side_effect = fake_prompt_select_subnet

    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )

    assert params.selected_subnet == "snet-paas-01"
    assert params.network_action == "existing"


def test_multiple_candidate_subnets_user_aborts(mock_terminal, standards_engine):
    """Verify user aborting during candidate subnet selection raises typer.Abort."""
    s1 = SubnetCandidate(
        name="snet-paas-01",
        address_prefixes=["10.0.1.0/24"],
        subscription="sub-prod",
        is_private_endpoint_candidate=True,
    )
    topology = DiscoveredTopology(subnets=[s1])
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )

    mock_terminal.prompt_select_subnet.side_effect = typer.Abort()

    with pytest.raises(typer.Abort):
        flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="appdata",
        )


def test_single_candidate_subnet_with_custom_entry(mock_terminal, standards_engine):
    """Verify Scenario 2: Single candidate subnet presents choice with (Recommended) as default, and allows custom entry."""
    s1 = SubnetCandidate(
        name="snet-paas-single",
        address_prefixes=["10.0.1.0/24"],
        virtual_network_name="vnet-prod",
        resource_group_name="rg-prod",
        subscription="sub-prod",
        is_private_endpoint_candidate=True,
    )
    topology = DiscoveredTopology(subnets=[s1])
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )

    mock_terminal.prompt_select_subnet.return_value = "Other (Enter custom subnet name...)"
    mock_terminal.prompt_text.return_value = "snet-custom-01"

    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )

    assert params.selected_subnet == "snet-custom-01"
    assert params.network_action == "existing"


def test_pre_seeded_subnet_flag_bypasses_prompt(mock_terminal, standards_engine):
    """Verify Scenario 3: Pre-seeded subnet flag (--subnet) bypasses interactive prompt."""
    s1 = SubnetCandidate(
        name="snet-pe-01",
        address_prefixes=["10.0.1.0/24"],
        subscription="sub-prod",
        is_private_endpoint_candidate=True,
    )
    topology = DiscoveredTopology(subnets=[s1])
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

    mock_terminal.prompt_select_subnet.assert_not_called()
    assert params.selected_subnet == "snet-pe-01"
    assert params.network_action == "existing"


def test_pre_seeded_subnet_not_found_warns_and_binds(mock_terminal, standards_engine):
    """Verify Scenario 3: Pre-seeded subnet not in discovered topology prints warning and binds cleanly."""
    s1 = SubnetCandidate(
        name="snet-existing-01",
        address_prefixes=["10.0.1.0/24"],
        subscription="sub-prod",
    )
    topology = DiscoveredTopology(subnets=[s1])
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )

    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        subnet="snet-external-01",
        auto_approve=True,
    )

    mock_terminal.print_warning.assert_called()
    assert "snet-external-01" in mock_terminal.print_warning.call_args[0][0]
    assert params.selected_subnet == "snet-external-01"
    assert params.network_action == "existing"


def test_no_candidate_subnets_scaffold_option_stages_both_directories(
    mock_terminal, standards_engine
):
    """Verify Scenario 4: 0 subnets in subscription with Scaffold choice synthesizes azurerm_subnet and stages both directories."""
    topology = DiscoveredTopology(subnets=[])
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )

    # 1. Action prompt -> Scaffold missing subnet
    # 2. Text prompt -> Subnet Name: snet-pe-01
    # 3. Text prompt -> Subnet CIDR: 10.0.5.0/24
    # 4. Text prompt -> Target VNet Name: vnet-corporate-prod
    mock_terminal.prompt_select.return_value = "Scaffold missing subnet in this subscription"
    mock_terminal.prompt_text.side_effect = ["snet-pe-01", "10.0.5.0/24", "vnet-corporate-prod"]

    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )

    assert params.selected_subnet == "snet-pe-01"
    assert params.network_action == "scaffold"

    # Workspace should contain 6 files across 2 directory hierarchies:
    # azurerm_storage_account/sub-prod/ (main.tf, data.tf, backend.tf)
    # azurerm_subnet/sub-prod/ (main.tf, data.tf, backend.tf)
    assert workspace.file_count == 6
    assert "main.tf" in workspace
    assert "data.tf" in workspace
    assert "backend.tf" in workspace
    assert "azurerm_subnet/sub-prod/main.tf" in workspace
    assert "azurerm_subnet/sub-prod/data.tf" in workspace
    assert "azurerm_subnet/sub-prod/backend.tf" in workspace

    subnet_main = workspace["azurerm_subnet/sub-prod/main.tf"]
    assert 'name                 = "snet-pe-01"' in subnet_main.content
    assert 'address_prefixes     = ["10.0.5.0/24"]' in subnet_main.content
    subnet_data = workspace["azurerm_subnet/sub-prod/data.tf"]
    assert '"vnet-corporate-prod"' in subnet_data.content



def test_no_candidate_subnets_cross_subscription_option(
    mock_terminal, standards_engine
):
    """Verify Scenario 5: 0 subnets in subscription with Cross-Subscription choice binds parameters."""
    topology = DiscoveredTopology(subnets=[])
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )

    # 1. Action prompt -> Cross-subscription lookup
    # 2. Text prompt -> Source subscription: core-networking
    # 3. Text prompt -> Shared subnet name: snet-shared-pe-01
    mock_terminal.prompt_select.return_value = "Configure cross-subscription shared network lookup"
    mock_terminal.prompt_text.side_effect = ["core-networking", "snet-shared-pe-01"]

    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )

    assert params.selected_subnet == "snet-shared-pe-01"
    assert params.network_action == "cross_subscription"
    assert params.cross_sub_source == "core-networking"
    # Target directory remains storage account only (3 files)
    assert workspace.file_count == 3


def test_multi_directory_atomic_commit_happy_path(tmp_path: Path, standards_engine):
    """Verify Scenario 6: StagedWorkspace containing files across 2 directories commits atomically with unified diff."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)
    ws = StagedWorkspace(target_dir="azurerm_storage_account/sub-prod/")

    # Directory 1 files
    ws.add_file(
        StagedFile(
            path="main.tf",
            content='resource "azurerm_storage_account" "primary" {\n  name = "stappdataprod"\n}\n',
            is_new=True,
        )
    )
    ws.add_file(
        StagedFile(
            path="data.tf",
            content='data "azurerm_resource_group" "primary" {\n  name = "rg-sub-prod"\n}\n',
            is_new=True,
        )
    )
    # Directory 2 files
    ws.add_file(
        StagedFile(
            path="azurerm_subnet/sub-prod/main.tf",
            content='resource "azurerm_subnet" "primary" {\n  name = "snet-pe-01"\n}\n',
            is_new=True,
        )
    )
    ws.add_file(
        StagedFile(
            path="azurerm_subnet/sub-prod/backend.tf",
            content='terraform {\n  backend "azurerm" {\n    key = "sub-prod/azurerm_subnet.tfstate"\n  }\n}\n',
            is_new=True,
        )
    )

    # 1. Diff preview contains files from both directories
    diff = compute_workspace_diff(ws)
    assert diff.has_changes is True
    assert "azurerm_storage_account/sub-prod/main.tf" in diff.diff_text
    assert "azurerm_subnet/sub-prod/main.tf" in diff.diff_text

    # 2. Atomic commit writes both directories to disk
    committed = adapter.commit_workspace(ws)
    assert len(committed) == 4

    dir1_file = tmp_path / "azurerm_storage_account" / "sub-prod" / "main.tf"
    dir2_file = tmp_path / "azurerm_subnet" / "sub-prod" / "main.tf"

    assert dir1_file.is_file()
    assert dir2_file.is_file()
    assert "stappdataprod" in dir1_file.read_text(encoding="utf-8")
    assert "snet-pe-01" in dir2_file.read_text(encoding="utf-8")


def test_multi_directory_atomic_commit_rollback_on_failure(tmp_path: Path):
    """Verify Scenario 6: Failure during atomic swap across multi-directory workspace rolls back all directories."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)
    ws = StagedWorkspace(target_dir="azurerm_storage_account/sub-prod/")

    ws.add_file(
        StagedFile(
            path="main.tf",
            content='resource "azurerm_storage_account" "primary" {}\n',
            is_new=True,
        )
    )
    ws.add_file(
        StagedFile(
            path="azurerm_subnet/sub-prod/main.tf",
            content='resource "azurerm_subnet" "primary" {}\n',
            is_new=True,
        )
    )

    real_replace = __import__("os").replace
    replace_count = 0

    def fail_on_second_swap(src, dst):
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("Injected disk atomic swap failure on second directory")
        return real_replace(src, dst)

    with patch("os.replace", side_effect=fail_on_second_swap):
        with pytest.raises(FileSystemError, match="swap failure"):
            adapter.commit_workspace(ws)

    # Neither directory should contain files after rollback
    dir1 = tmp_path / "azurerm_storage_account" / "sub-prod"
    dir2 = tmp_path / "azurerm_subnet" / "sub-prod"

    assert not (dir1 / "main.tf").exists()
    assert not (dir2 / "main.tf").exists()


def test_non_tty_prompt_select_subnet_with_recommended_default(tmp_path: Path):
    """Verify Scenario 7: Non-TTY environment chooses (Recommended) default on empty line input."""
    import io

    stdout = io.StringIO()
    stderr = io.StringIO()
    # Empty enter to accept default selection
    stdin = io.StringIO("\n")

    adapter = RichTerminalAdapter(stdout=stdout, stderr=stderr, stdin=stdin)
    choices = [
        "snet-paas-01 [10.0.1.0/24] (vnet-prod / rg-prod) - Private Endpoint (Recommended)",
        "snet-workload-01 [10.0.2.0/24] (vnet-prod / rg-prod) - Workload",
    ]

    selected = adapter.prompt_select_subnet("Select Target Subnet:", choices=choices)

    assert selected == choices[0]
    out = stdout.getvalue()
    assert "Select Target Subnet:" in out
    assert "1) [*] snet-paas-01" in out


def test_cli_new_with_subnet_flag_e2e(tmp_path: Path):
    """Verify CLI ttassistant new accepts --subnet option in automated pipeline execution."""
    import shutil

    try:
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "new",
                "--subscription",
                "sub-prod",
                "--resource-type",
                "azurerm_storage_account",
                "--workload",
                "appdata",
                "--subnet",
                "snet-pe-01",
                "--yes",
            ],
        )
        assert result.exit_code == 0
        assert "Subnet:        snet-pe-01" in result.output
        assert "Network Action: existing" in result.output
    finally:
        shutil.rmtree("azurerm_storage_account", ignore_errors=True)
        shutil.rmtree("azurerm_subnet", ignore_errors=True)


def test_resource_group_bypasses_subnet_selection(mock_terminal, standards_engine):
    """Verify azurerm_resource_group bypasses subnet prompt completely."""
    s1 = SubnetCandidate(
        name="snet-pe-01",
        address_prefixes=["10.0.1.0/24"],
        subscription="sub-prod",
    )
    topology = DiscoveredTopology(subnets=[s1])
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )
    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_resource_group",
        workload_name="appdata",
        auto_approve=True,
    )
    mock_terminal.prompt_select_subnet.assert_not_called()
    assert params.selected_subnet is None
    assert params.network_action is None


def test_strict_cidr_validation_rejects_host_bits(scaffold_engine: ScaffoldEngine):
    """Verify scaffold_subnet rejects CIDR with host bits set (strict=True)."""
    with pytest.raises(ValueError, match="Invalid subnet CIDR prefix"):
        scaffold_engine.scaffold_subnet(
            subscription="sub-prod",
            subnet_name="snet-pe-01",
            address_prefixes=["10.0.1.5/24"],
        )


def test_pre_seeded_subnet_flag_validation(mock_terminal, standards_engine):
    """Verify pre-seeded subnet flag rejects empty string or naming convention violations."""
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=DiscoveredTopology(),
    )
    # Empty string
    with pytest.raises(ValueError, match="Subnet name cannot be empty"):
        flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="appdata",
            subnet="   ",
            auto_approve=True,
        )

    # Naming convention violation
    with pytest.raises(ValueError, match="does not match naming pattern"):
        flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="appdata",
            subnet="INVALID_SUBNET_CAPS",
            auto_approve=True,
        )


def test_cross_subscription_rejects_self_referential(mock_terminal, standards_engine):
    """Verify cross-subscription selection rejects choosing target subscription as source."""
    topology = DiscoveredTopology(subnets=[])
    flow = ProvisioningFlow(
        terminal=mock_terminal,
        standards=standards_engine,
        discovered_topology=topology,
    )

    validator_captured = None

    def fake_prompt_text(prompt, default=None, validate=None, completer=None):
        nonlocal validator_captured
        if "Enter Source Subscription" in prompt:
            validator_captured = validate
            return "core-networking"
        return "snet-shared-01"

    mock_terminal.prompt_select.return_value = "Configure cross-subscription shared network lookup"
    mock_terminal.prompt_text.side_effect = fake_prompt_text

    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )

    assert validator_captured is not None
    res = validator_captured("sub-prod")
    assert res == "Source subscription cannot be the same as target subscription"
    assert validator_captured("core-networking") is True

