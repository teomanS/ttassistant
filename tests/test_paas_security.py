"""Comprehensive test suite for Tier 1 PaaS Scaffolding with Mandatory Public Network Access Denial (Story 3.2).

Validates:
- FR-12: Mandatory Public Network Access Denial on Tier 1 PaaS resources
- AD-1: Domain boundary isolation (pure logic in domain/scaffold and domain/models)
- AD-7: Enterprise Security Triad guardrails
- High-visibility security warning banner & explicit interactive confirmation gate
- Confirmation rejection clean fallback to private-only configuration
- Headless automated safeguard: unconfirmed public access fails fast with exit code 1
- Full provider schema compliance and python-hcl2 syntax validity
"""

from pathlib import Path
from unittest.mock import MagicMock
import hcl2
import pytest
from typer.testing import CliRunner

from ttassistant.adapters.standards_adapter import MarkdownStandardsAdapter
from ttassistant.adapters.terminal_adapter import RichTerminalAdapter
from ttassistant.application.provisioning_flow import ProvisioningFlow
from ttassistant.cli import app
from ttassistant.domain.catalog import (
    TIER_1_FOUNDATION_RESOURCES,
    TIER_1_PAAS_RESOURCES,
    is_tier_1_paas,
)
from ttassistant.domain.exceptions import SecurityPolicyViolationError
from ttassistant.domain.models import ProvisioningParameters, StagedWorkspace
from ttassistant.domain.scaffold import ScaffoldEngine
from ttassistant.domain.standards import StandardsEngine
from ttassistant.ports.filesystem import FileSystemPort
from ttassistant.ports.terminal import TerminalUIPort

runner = CliRunner()


@pytest.fixture(autouse=True)
def cleanup_generated_dirs():
    """Ensure no test artifacts remain in workspace before or after test execution."""
    import shutil

    for d in [
        "azurerm_storage_account",
        "azurerm_key_vault",
        "azurerm_resource_group",
        "azurerm_virtual_network",
        "azurerm_subnet",
    ]:
        shutil.rmtree(d, ignore_errors=True)
    yield
    for d in [
        "azurerm_storage_account",
        "azurerm_key_vault",
        "azurerm_resource_group",
        "azurerm_virtual_network",
        "azurerm_subnet",
    ]:
        shutil.rmtree(d, ignore_errors=True)


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
# 1. Mandatory Public Network Denial by Default for All Tier 1 PaaS Resources
# ==============================================================================


def test_default_paas_denial_storage_account(scaffold_engine: ScaffoldEngine):
    """Verify default scaffolding of azurerm_storage_account explicitly sets public_network_access_enabled = false."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
        public_network_access=False,
    )
    workspace = scaffold_engine.scaffold(params)
    main_content = workspace["main.tf"].content

    assert "resource \"azurerm_storage_account\" \"primary\" {" in main_content
    assert "public_network_access_enabled = false" in main_content
    assert "account_tier                  = \"Standard\"" in main_content
    assert "account_replication_type      = \"LRS\"" in main_content

    # Validate HCL parsing
    parsed = hcl2.loads(main_content)
    assert parsed is not None
    res_block = parsed["resource"][0]["\"azurerm_storage_account\""]["\"primary\""]
    assert res_block["public_network_access_enabled"] is False


def test_default_paas_denial_key_vault(scaffold_engine: ScaffoldEngine):
    """Verify default scaffolding of azurerm_key_vault sets public_network_access_enabled = false with standard defaults."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_key_vault",
        workload_name="appsecrets",
        environment="prod",
        resource_name="kv-appsecrets-prod",
        tags={"Environment": "prod"},
        public_network_access=False,
    )
    workspace = scaffold_engine.scaffold(params)
    main_content = workspace["main.tf"].content

    assert "resource \"azurerm_key_vault\" \"primary\" {" in main_content
    assert "public_network_access_enabled = false" in main_content
    assert "sku_name                      = \"standard\"" in main_content
    assert "tenant_id                     = \"00000000-0000-0000-0000-000000000000\"" in main_content

    parsed = hcl2.loads(main_content)
    assert parsed is not None
    res_block = parsed["resource"][0]["\"azurerm_key_vault\""]["\"primary\""]
    assert res_block["public_network_access_enabled"] is False


@pytest.mark.parametrize("resource_type", sorted(TIER_1_PAAS_RESOURCES))
def test_all_tier_1_paas_resources_enforce_public_access_denial_by_default(
    scaffold_engine: ScaffoldEngine, resource_type: str
):
    """Verify that every canonical Tier 1 PaaS resource synthesizes public_network_access_enabled = false by default."""
    assert is_tier_1_paas(resource_type) is True

    clean_name = resource_type.replace("azurerm_", "").replace("_", "")[:12]
    resource_name = f"{clean_name}prod"

    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type=resource_type,
        workload_name="testapp",
        environment="prod",
        resource_name=resource_name,
        tags={"Environment": "prod"},
        public_network_access=False,
    )

    workspace = scaffold_engine.scaffold(params)
    main_content = workspace["main.tf"].content

    assert f"resource \"{resource_type}\" \"primary\" {{" in main_content
    assert "public_network_access_enabled = false" in main_content

    # Strict syntax check with python-hcl2
    parsed = hcl2.loads(main_content)
    assert parsed is not None
    res_block = parsed["resource"][0][f"\"{resource_type}\""]["\"primary\""]
    assert res_block["public_network_access_enabled"] is False


# ==============================================================================
# 2. Non-PaaS Foundation Resources Omit public_network_access_enabled
# ==============================================================================


@pytest.mark.parametrize("foundation_type", sorted(TIER_1_FOUNDATION_RESOURCES))
def test_foundation_resources_omit_public_network_access_denial(
    scaffold_engine: ScaffoldEngine, foundation_type: str
):
    """Verify foundation resources (resource group, vnet, subnet) do not configure public_network_access_enabled."""
    assert is_tier_1_paas(foundation_type) is False

    clean_name = foundation_type.replace("azurerm_", "").replace("_", "-")
    resource_name = f"{clean_name}-prod"

    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type=foundation_type,
        workload_name="foundation",
        environment="prod",
        resource_name=resource_name,
        tags={"Environment": "prod"},
        public_network_access=False,
    )

    workspace = scaffold_engine.scaffold(params)
    main_content = workspace["main.tf"].content

    assert f"resource \"{foundation_type}\" \"primary\" {{" in main_content
    assert "public_network_access_enabled" not in main_content

    parsed = hcl2.loads(main_content)
    assert parsed is not None
    res_block = parsed["resource"][0][f"\"{foundation_type}\""]["\"primary\""]
    assert "public_network_access_enabled" not in res_block


# ==============================================================================
# 3. Interactive Security Warning & Confirmation Gate
# ==============================================================================


def test_interactive_public_access_request_confirmed(mock_terminal, standards_engine):
    """Verify requesting public access interactively displays security warning and enables public access when confirmed."""
    mock_terminal.is_interactive.return_value = True
    # First confirm is the security warning confirmation gate [y/N]
    # Second confirm is the commit to disk confirmation
    mock_terminal.confirm.side_effect = [True, True]

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        public_network_access=True,
    )

    # Verify high-visibility warning was displayed
    mock_terminal.display_security_warning.assert_called_once()
    warning_kwargs = mock_terminal.display_security_warning.call_args[1]
    assert "azurerm_storage_account" in warning_kwargs["message"]

    # Verify security confirmation was requested with default=False [y/N]
    mock_terminal.confirm.assert_any_call(
        "Enable public network access despite corporate security policy violation?",
        default=False,
    )

    # Verify public access parameter is True and main.tf has public_network_access_enabled = true
    assert params.public_network_access is True
    main_content = workspace["main.tf"].content
    assert "public_network_access_enabled = true" in main_content

    parsed = hcl2.loads(main_content)
    res_block = parsed["resource"][0]["\"azurerm_storage_account\""]["\"primary\""]
    assert res_block["public_network_access_enabled"] is True


def test_interactive_public_access_request_rejected(mock_terminal, standards_engine):
    """Verify rejecting security confirmation gate reverts cleanly to private-only (public_network_access_enabled = false)."""
    mock_terminal.is_interactive.return_value = True
    # First confirm: security gate -> False (rejected)
    # Second confirm: commit to disk -> True
    mock_terminal.confirm.side_effect = [False, True]

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        public_network_access=True,
    )

    # Warning was displayed
    mock_terminal.display_security_warning.assert_called_once()

    # Rejection message was printed
    mock_terminal.print_info.assert_any_call(
        "Security confirmation rejected: reverting to secure private-only configuration (public_network_access_enabled = false)."
    )

    # Reverted to False
    assert params.public_network_access is False
    main_content = workspace["main.tf"].content
    assert "public_network_access_enabled = false" in main_content

    parsed = hcl2.loads(main_content)
    res_block = parsed["resource"][0]["\"azurerm_storage_account\""]["\"primary\""]
    assert res_block["public_network_access_enabled"] is False


def test_interactive_prompt_public_access_opt_in(mock_terminal, standards_engine):
    """Verify prompting for public access in interactive mode triggers security warning gate when user opts in."""
    mock_terminal.is_interactive.return_value = True
    # Prompt 1: "Enable public network access for this PaaS resource?" -> True
    # Prompt 2: Security gate confirmation -> True
    # Prompt 3: Commit to disk -> True
    mock_terminal.confirm.side_effect = [True, True, True]

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        prompt_public_access=True,
    )

    assert mock_terminal.confirm.call_count == 3
    mock_terminal.display_security_warning.assert_called_once()
    assert params.public_network_access is True
    assert "public_network_access_enabled = true" in workspace["main.tf"].content


# ==============================================================================
# 4. Headless Non-Interactive Safeguard & Security Policy Enforcement
# ==============================================================================


def test_headless_unconfirmed_public_access_raises_policy_violation(mock_terminal, standards_engine):
    """Verify headless execution requesting public access without confirmation override raises SecurityPolicyViolationError."""
    mock_terminal.is_interactive.return_value = False

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)

    with pytest.raises(SecurityPolicyViolationError, match="Security policy violation"):
        flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="appdata",
            auto_approve=True,
            public_network_access=True,
            confirm_public_network_access=False,
        )


def test_headless_confirmed_public_access_override_succeeds(mock_terminal, standards_engine):
    """Verify headless execution with explicit confirm_public_network_access override succeeds without prompt."""
    mock_terminal.is_interactive.return_value = False

    flow = ProvisioningFlow(terminal=mock_terminal, standards=standards_engine)
    params, workspace = flow.run(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        auto_approve=True,
        public_network_access=True,
        confirm_public_network_access=True,
    )

    # Zero interactive prompts
    mock_terminal.confirm.assert_not_called()
    assert params.public_network_access is True
    assert "public_network_access_enabled = true" in workspace["main.tf"].content


# ==============================================================================
# 5. CLI Integration Tests for --public-network-access
# ==============================================================================


def test_cli_new_help_displays_public_network_access_options():
    """Verify ttassistant new --help documents --public-network-access option."""
    wide_runner = CliRunner(env={"COLUMNS": "160"})
    result = wide_runner.invoke(app, ["new", "--help"])
    assert result.exit_code == 0
    assert "--public-network-access" in result.output
    assert "--confirm-public-network-access" in result.output


def test_cli_headless_unconfirmed_public_access_exits_code_1():
    """Verify running ttassistant new with --public-network-access without confirmation fails fast with exit code 1."""
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
            "--yes",
            "--public-network-access",
        ],
    )
    assert result.exit_code == 1
    assert "Security policy violation" in result.output or "Security policy violation" in str(result.exception)


def test_cli_headless_confirmed_public_access_succeeds(tmp_path):
    """Verify running ttassistant new with --public-network-access and --confirm-public-network-access succeeds."""
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
            "--yes",
            "--public-network-access",
            "--confirm-public-network-access",
        ],
    )
    assert result.exit_code == 0
    assert "Provisioning parameters collected successfully." in result.output
    assert "Public Access: Enabled (Public)" in result.output


# ==============================================================================
# 6. Terminal Adapter Security Warning Formatting
# ==============================================================================


def test_rich_terminal_adapter_display_security_warning_dumb_mode():
    """Verify RichTerminalAdapter renders security warning banner in dumb/non-color terminal mode."""
    import io

    out = io.StringIO()
    adapter = RichTerminalAdapter(stdout=out, stderr=out)
    adapter.is_color_supported = lambda: False
    adapter.display_security_warning(
        message="Test security policy violation message",
        details=["Detail line 1", "Detail line 2"],
        title="CRITICAL SECURITY WARNING",
    )
    rendered = out.getvalue()
    assert "=" * 70 in rendered
    assert "Test security policy violation message" in rendered
    assert "* Detail line 1" in rendered
    assert "* Detail line 2" in rendered
    assert "CRITICAL SECURITY WARNING" in rendered


def test_rich_terminal_adapter_display_security_warning_color_panel_mode():
    """Verify RichTerminalAdapter renders colored Rich Panel with title, border, message, and details."""
    import io

    out = io.StringIO()
    adapter = RichTerminalAdapter(stdout=out, stderr=out)
    adapter.is_color_supported = lambda: True
    adapter._init_consoles()
    adapter.display_security_warning(
        message="Test security policy violation message",
        details=["Detail line 1", "Detail line 2"],
        title="CRITICAL SECURITY WARNING",
    )
    rendered = out.getvalue()
    # Panel box drawing characters for border
    assert "╭" in rendered and "╮" in rendered
    assert "╰" in rendered and "╯" in rendered
    assert "CRITICAL SECURITY WARNING" in rendered
    assert "Test security policy violation message" in rendered
    assert "• Detail line 1" in rendered
    assert "• Detail line 2" in rendered


def test_rich_terminal_adapter_print_security_warning():
    """Verify print_security_warning delegates to display_security_warning."""
    import io

    out = io.StringIO()
    adapter = RichTerminalAdapter(stdout=out, stderr=out)
    adapter.print_security_warning("Direct warning message")
    rendered = out.getvalue()
    assert "Direct warning message" in rendered
    assert "SECURITY POLICY WARNING" in rendered
