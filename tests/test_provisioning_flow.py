"""Unit tests for ProvisioningFlow application orchestrator with mock terminal."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
import typer

from ttassistant.adapters.standards_adapter import MarkdownStandardsAdapter
from ttassistant.application.provisioning_flow import OTHER_SUBSCRIPTION_CHOICE, ProvisioningFlow
from ttassistant.domain.models import ProvisioningParameters, StagedWorkspace
from ttassistant.domain.standards import StandardsEngine
from ttassistant.ports.terminal import TerminalUIPort


@pytest.fixture
def standards_engine() -> StandardsEngine:
    """Load standards engine from workspace common_standards."""
    standards_dir = Path(__file__).resolve().parent.parent / "common_standards"
    adapter = MarkdownStandardsAdapter()
    bundle = adapter.load_standards(standards_dir)
    return StandardsEngine(bundle)


@pytest.fixture
def mock_terminal() -> MagicMock:
    """Create a mock TerminalUIPort instance."""
    terminal = MagicMock(spec=TerminalUIPort)
    return terminal


def test_provisioning_flow_happy_path(mock_terminal, standards_engine):
    """Verify happy path parameter collection for storage account produces stappdataprod and StagedWorkspace."""
    # Terminal interactions:
    # 1. prompt_select for subscription: return "workload-prod"
    # 2. prompt_select for resource type: return "azurerm_storage_account"
    # 3. prompt_text for workload: return "appdata"
    mock_terminal.prompt_select.side_effect = ["workload-prod", "azurerm_storage_account"]
    mock_terminal.prompt_text.return_value = "appdata"

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    params, workspace = flow.run()

    assert isinstance(params, ProvisioningParameters)
    assert params.subscription == "workload-prod"
    assert params.resource_type == "azurerm_storage_account"
    assert params.workload_name == "appdata"
    assert params.environment == "prod"
    assert params.resource_name == "stappdataprod"
    assert params.tags["Environment"] == "prod"
    assert "Owner" in params.tags
    assert "CostCenter" in params.tags

    assert isinstance(workspace, StagedWorkspace)
    assert workspace.target_dir == "azurerm_storage_account/workload-prod/"
    assert workspace.file_count == 3
    assert "main.tf" in workspace
    assert "data.tf" in workspace
    assert "backend.tf" in workspace
    assert workspace.parameters == params


def test_provisioning_flow_custom_subscription_entry(mock_terminal, standards_engine):
    """Verify selecting 'Other (Enter custom...)' prompts for custom subscription name and stages workspace."""
    mock_terminal.prompt_select.side_effect = [OTHER_SUBSCRIPTION_CHOICE, "azurerm_key_vault"]
    mock_terminal.prompt_text.side_effect = ["custom-sub-dev", "mysecret"]

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    params, workspace = flow.run()

    assert params.subscription == "custom-sub-dev"
    assert params.resource_type == "azurerm_key_vault"
    assert params.workload_name == "mysecret"
    assert params.environment == "dev"
    assert params.resource_name == "kv-mysecret-dev"

    assert workspace.target_dir == "azurerm_key_vault/custom-sub-dev/"
    assert "main.tf" in workspace


def test_provisioning_flow_workload_validator_rejects_invalid_chars(mock_terminal, standards_engine):
    """Verify inline workload validator rejects uppercase and special characters for storage account."""
    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    validator = flow._make_workload_validator("azurerm_storage_account", "prod")

    res = validator("App-Data!")
    assert res == "Invalid name: must match ^[a-z0-9]+$"

    # Valid name passes
    assert validator("appdata") is True


def test_provisioning_flow_workload_validator_rejects_length_violation(mock_terminal, standards_engine):
    """Verify inline workload validator rejects names exceeding maximum length (24 chars for storage)."""
    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    validator = flow._make_workload_validator("azurerm_storage_account", "prod")

    # 30 characters
    long_name = "abcdefghijklmnopqrstuvwxyz1234"
    res = validator(long_name)
    assert res == "Name exceeds maximum length of 24 characters"


def test_provisioning_flow_workload_validator_hyphen_allowed_for_resource_group(mock_terminal, standards_engine):
    """Verify workload validator permits hyphens for azurerm_resource_group."""
    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    validator = flow._make_workload_validator("azurerm_resource_group", "prod")

    assert validator("app-data") is True
    res_bad = validator("App@Data!")
    assert res_bad == "Invalid name: must match ^[a-z0-9-]+$"


def test_provisioning_flow_pre_seeded_flags_bypass_prompts(mock_terminal, standards_engine):
    """Verify pre-seeded flags bypass terminal prompts and construct valid ProvisioningParameters and StagedWorkspace."""
    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
    )

    assert mock_terminal.prompt_select.call_count == 0
    assert mock_terminal.prompt_text.call_count == 0
    assert params.subscription == "sub-prod"
    assert params.resource_name == "stappdataprod"
    assert workspace.target_dir == "azurerm_storage_account/sub-prod/"
    assert "main.tf" in workspace


def test_provisioning_flow_invalid_pre_seeded_workload_raises_value_error(mock_terminal, standards_engine):
    """Verify invalid pre-seeded workload flag raises ValueError."""
    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    with pytest.raises(ValueError, match="Invalid name"):
        flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="App-Data!",
        )


def test_provisioning_flow_invalid_pre_seeded_resource_type_raises_value_error(mock_terminal, standards_engine):
    """Verify invalid pre-seeded resource type raises ValueError."""
    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    with pytest.raises(ValueError, match="Unknown resource type"):
        flow.run(
            subscription="sub-prod",
            resource_type="invalid_resource_type",
            workload_name="appdata",
        )


def test_provisioning_flow_abort_on_cancel(mock_terminal, standards_engine):
    """Verify typer.Abort raised by terminal UI propagates up."""
    mock_terminal.prompt_select.side_effect = typer.Abort()

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    with pytest.raises(typer.Abort):
        flow.run()


def test_provisioning_flow_explicit_environment_override(mock_terminal, standards_engine):
    """Verify explicit environment parameter overrides environment inferred from subscription."""
    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    params, workspace = flow.run(
        subscription="workload-dev",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
    )
    assert params.environment == "prod"
    assert params.resource_name == "stappdataprod"
    assert params.tags["Environment"] == "prod"
    assert workspace.target_dir == "azurerm_storage_account/workload-dev/"


def test_provisioning_flow_invalid_environment_raises_value_error(mock_terminal, standards_engine):
    """Verify unapproved environment raises ValueError against tagging baseline."""
    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    with pytest.raises(ValueError, match="Invalid environment"):
        flow.run(
            subscription="workload-dev",
            resource_type="azurerm_storage_account",
            workload_name="appdata",
            environment="invalid_env",
        )


def test_provisioning_flow_invalid_pre_seeded_subscription_raises_value_error(mock_terminal, standards_engine):
    """Verify invalid subscription characters or empty subscription raises ValueError."""
    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    with pytest.raises(ValueError, match="Subscription name"):
        flow.run(
            subscription="bad sub!@#",
            resource_type="azurerm_storage_account",
            workload_name="appdata",
        )


def test_provisioning_flow_diff_preview_and_confirm_commit(mock_terminal, standards_engine):
    """Verify diff preview is displayed, confirmation requested, and workspace committed on [Y]."""
    from ttassistant.ports.filesystem import FileSystemPort

    mock_fs = MagicMock(spec=FileSystemPort)
    mock_fs.read_workspace_existing_files.return_value = {}
    mock_fs.commit_workspace.return_value = [Path("main.tf"), Path("data.tf"), Path("backend.tf")]
    mock_terminal.confirm.return_value = True

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine, fs=mock_fs)
    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
    )

    # Verify diff display was called with /dev/null headers
    mock_terminal.display_diff.assert_called_once()
    diff_arg = mock_terminal.display_diff.call_args[0][0]
    assert "--- /dev/null" in diff_arg
    assert "azurerm_storage_account/sub-prod/main.tf" in diff_arg

    # Verify confirmation gate was presented
    mock_terminal.confirm.assert_called_once_with("Commit changes to disk?", default=False)

    # Verify workspace was committed
    mock_fs.commit_workspace.assert_called_once_with(workspace)
    assert workspace.metadata["committed"] is True


def test_provisioning_flow_rejection_cancels_without_commit(mock_terminal, standards_engine):
    """Verify selecting [N] cancels scaffolding, prints cancellation message, and does not commit."""
    from ttassistant.ports.filesystem import FileSystemPort

    mock_fs = MagicMock(spec=FileSystemPort)
    mock_fs.read_workspace_existing_files.return_value = {}
    mock_terminal.confirm.return_value = False

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine, fs=mock_fs)
    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
    )

    mock_terminal.confirm.assert_called_once_with("Commit changes to disk?", default=False)
    mock_fs.commit_workspace.assert_not_called()
    assert workspace.metadata["committed"] is False
    mock_terminal.print.assert_any_call("Scaffolding cancelled. No files written to disk.")


def test_provisioning_flow_auto_approve_yes_flag(mock_terminal, standards_engine):
    """Verify auto_approve=True bypasses confirmation prompt and commits to filesystem."""
    from ttassistant.ports.filesystem import FileSystemPort

    mock_fs = MagicMock(spec=FileSystemPort)
    mock_fs.read_workspace_existing_files.return_value = {}
    mock_fs.commit_workspace.return_value = [Path("main.tf")]

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine, fs=mock_fs)
    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )

    mock_terminal.confirm.assert_not_called()
    mock_fs.commit_workspace.assert_called_once_with(workspace)
    assert workspace.metadata["committed"] is True


def test_provisioning_flow_diff_preview_with_existing_files_on_disk(mock_terminal, standards_engine):
    """Verify diff preview compares against existing disk files when present."""
    from ttassistant.ports.filesystem import FileSystemPort

    mock_fs = MagicMock(spec=FileSystemPort)
    old_content = '# Pre-existing main file\nresource "azurerm_storage_account" "old" {}\n'
    mock_fs.read_workspace_existing_files.return_value = {
        "azurerm_storage_account/sub-prod/main.tf": old_content,
    }
    mock_fs.commit_workspace.return_value = [Path("main.tf")]

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine, fs=mock_fs)
    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )

    mock_terminal.display_diff.assert_called_once()
    diff_text = mock_terminal.display_diff.call_args[0][0]
    assert "--- azurerm_storage_account/sub-prod/main.tf" in diff_text
    assert "-# Pre-existing main file" in diff_text
    assert '+resource "azurerm_storage_account" "primary"' in diff_text


def test_provisioning_flow_empty_diff_identical_files_displays_info(mock_terminal, standards_engine):
    """Verify that when workspace files match existing disk files exactly, informative message is displayed."""
    from ttassistant.ports.filesystem import FileSystemPort
    from ttassistant.domain.scaffold import ScaffoldEngine
    from ttassistant.domain.models import ProvisioningParameters

    scaffold_engine = ScaffoldEngine(standards_engine)
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
    )
    ws = scaffold_engine.scaffold(params)
    existing = {f"azurerm_storage_account/sub-prod/{f.filename}": f.content for f in ws}

    mock_fs = MagicMock(spec=FileSystemPort)
    mock_fs.read_workspace_existing_files.return_value = existing

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine, fs=mock_fs)
    flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
    )

    mock_terminal.print_info.assert_any_call("Files on disk are already identical. No changes to apply.")
