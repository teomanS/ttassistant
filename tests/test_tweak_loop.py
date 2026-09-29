"""Unit and integration tests for the interactive tweak loop and dynamic diff re-rendering (Story 4.2)."""

import io
from pathlib import Path
import re
from unittest.mock import MagicMock, patch
import pytest
import typer

from ttassistant.adapters.catalog_adapter import JsonResourceCatalogAdapter
from ttassistant.adapters.terminal_adapter import RichTerminalAdapter
from ttassistant.adapters.tweak_adapter import DeterministicTweakParserAdapter
from ttassistant.application.provisioning_flow import ProvisioningFlow
from ttassistant.application.tweak_handler import TweakHandler
from ttassistant.domain.models import StagedWorkspace
from ttassistant.domain.standards import StandardsEngine
from ttassistant.ports.filesystem import FileSystemPort
from ttassistant.ports.terminal import TerminalUIPort


@pytest.fixture
def catalog():
    return JsonResourceCatalogAdapter()


@pytest.fixture
def tweak_handler(catalog):
    parser = DeterministicTweakParserAdapter(catalog=catalog)
    return TweakHandler(parser=parser)


from ttassistant.adapters.standards_adapter import MarkdownStandardsAdapter


@pytest.fixture
def standards_engine() -> StandardsEngine:
    standards_dir = Path(__file__).resolve().parent.parent / "common_standards"
    adapter = MarkdownStandardsAdapter()
    bundle = adapter.load_standards(standards_dir)
    return StandardsEngine(bundle)


class TestPromptConfirmationGate:
    """Test the prompt_confirmation_gate method on RichTerminalAdapter."""

    def test_nontty_confirmation_gate_commit(self) -> None:
        stdin = io.StringIO("y\n")
        stdout = io.StringIO()
        adapter = RichTerminalAdapter(stdin=stdin, stdout=stdout)

        choice = adapter.prompt_confirmation_gate()
        assert choice == "commit"

    def test_nontty_confirmation_gate_default_commit(self) -> None:
        stdin = io.StringIO("\n")
        stdout = io.StringIO()
        adapter = RichTerminalAdapter(stdin=stdin, stdout=stdout)

        choice = adapter.prompt_confirmation_gate()
        assert choice == "commit"

    def test_nontty_confirmation_gate_cancel(self) -> None:
        stdin = io.StringIO("n\n")
        stdout = io.StringIO()
        adapter = RichTerminalAdapter(stdin=stdin, stdout=stdout)

        choice = adapter.prompt_confirmation_gate()
        assert choice == "cancel"

    def test_nontty_confirmation_gate_tweak(self) -> None:
        stdin = io.StringIO("t\n")
        stdout = io.StringIO()
        adapter = RichTerminalAdapter(stdin=stdin, stdout=stdout)

        choice = adapter.prompt_confirmation_gate()
        assert choice == "tweak"

    def test_nontty_confirmation_gate_eof_aborts(self) -> None:
        stdin = io.StringIO("")
        stdout = io.StringIO()
        adapter = RichTerminalAdapter(stdin=stdin, stdout=stdout)

        with pytest.raises(typer.Abort):
            adapter.prompt_confirmation_gate()

    def test_interactive_confirmation_gate(self) -> None:
        adapter = RichTerminalAdapter()
        with patch.object(adapter, "is_interactive", return_value=True), \
             patch.object(adapter, "is_term_dumb", return_value=False), \
             patch("questionary.select") as mock_select:
            mock_select.return_value.ask.return_value = "tweak"
            choice = adapter.prompt_confirmation_gate("Action:")
            assert choice == "tweak"

    def test_interactive_confirmation_gate_abort_on_none(self) -> None:
        adapter = RichTerminalAdapter()
        with patch.object(adapter, "is_interactive", return_value=True), \
             patch.object(adapter, "is_term_dumb", return_value=False), \
             patch("questionary.select") as mock_select:
            mock_select.return_value.ask.return_value = None
            with pytest.raises(typer.Abort):
                adapter.prompt_confirmation_gate("Action:")

    def test_interactive_confirmation_gate_keyboard_interrupt(self) -> None:
        adapter = RichTerminalAdapter()
        with patch.object(adapter, "is_interactive", return_value=True), \
             patch.object(adapter, "is_term_dumb", return_value=False), \
             patch("questionary.select") as mock_select:
            mock_select.return_value.ask.side_effect = KeyboardInterrupt
            with pytest.raises(typer.Abort):
                adapter.prompt_confirmation_gate("Action:")

    def test_clear_screen_on_interactive_adapter(self) -> None:
        adapter = RichTerminalAdapter()
        with patch.object(adapter, "is_interactive", return_value=True), \
             patch.object(adapter.console, "clear") as mock_clear:
            adapter.clear_screen()
            mock_clear.assert_called_once()


class TestProvisioningFlowTweakLoop:
    """Test dynamic tweak loop in ProvisioningFlow.run()."""

    def test_single_tweak_then_commit(
        self,
        standards_engine: StandardsEngine,
        catalog: JsonResourceCatalogAdapter,
        tweak_handler: TweakHandler,
    ) -> None:
        mock_terminal = MagicMock(spec=TerminalUIPort)
        mock_terminal.prompt_confirmation_gate.side_effect = ["tweak", "commit"]
        mock_terminal.prompt_text.return_value = "Change replication to GRS"

        mock_fs = MagicMock(spec=FileSystemPort)
        mock_fs.read_workspace_existing_files.return_value = {}
        mock_fs.commit_workspace.return_value = ["azurerm_storage_account/sub-prod/main.tf"]

        flow = ProvisioningFlow(
            terminal=mock_terminal,
            standards=standards_engine,
            fs=mock_fs,
            catalog=catalog,
            tweak_handler=tweak_handler,
        )

        params, workspace = flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="mydata",
            environment="dev",
            subnet=None,
            auto_approve=False,
        )

        assert workspace.metadata.get("committed") is True
        main_content = workspace["main.tf"].content
        assert re.search(r'account_replication_type\s*=\s*"GRS"', main_content)
        # Verify diff was displayed at least twice (initial + post-tweak)
        assert mock_terminal.display_diff.call_count >= 2
        post_tweak_diff = mock_terminal.display_diff.call_args_list[1][0][0]
        assert "account_replication_type" in post_tweak_diff and '"GRS"' in post_tweak_diff

    def test_multiple_consecutive_tweaks_then_commit(
        self,
        standards_engine: StandardsEngine,
        catalog: JsonResourceCatalogAdapter,
        tweak_handler: TweakHandler,
    ) -> None:
        mock_terminal = MagicMock(spec=TerminalUIPort)
        # Sequence: tweak (replication) -> tweak (TLS) -> tweak (add tag) -> commit
        mock_terminal.prompt_confirmation_gate.side_effect = ["tweak", "tweak", "tweak", "commit"]
        mock_terminal.prompt_text.side_effect = [
            "Change replication to GRS",
            "Set minimum TLS version to 1.2",
            "Add tag team=core",
        ]

        mock_fs = MagicMock(spec=FileSystemPort)
        mock_fs.read_workspace_existing_files.return_value = {}
        mock_fs.commit_workspace.return_value = ["azurerm_storage_account/sub-prod/main.tf"]

        flow = ProvisioningFlow(
            terminal=mock_terminal,
            standards=standards_engine,
            fs=mock_fs,
            catalog=catalog,
            tweak_handler=tweak_handler,
        )

        params, workspace = flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="mydata",
            environment="dev",
            auto_approve=False,
        )

        assert workspace.metadata.get("committed") is True
        main_content = workspace["main.tf"].content
        assert re.search(r'account_replication_type\s*=\s*"GRS"', main_content)
        assert re.search(r'min_tls_version\s*=\s*"TLS1_2"', main_content)
        assert 'team = "core"' in main_content or '"team" = "core"' in main_content
        assert workspace.parameters.tags.get("team") == "core"

        # Diff re-rendered on each turn
        assert mock_terminal.display_diff.call_count >= 4
        final_diff = mock_terminal.display_diff.call_args_list[-1][0][0]
        assert "account_replication_type" in final_diff and '"GRS"' in final_diff
        assert "min_tls_version" in final_diff and '"TLS1_2"' in final_diff
        assert "team" in final_diff and "core" in final_diff

    def test_tweak_error_recovery_in_loop(
        self,
        standards_engine: StandardsEngine,
        catalog: JsonResourceCatalogAdapter,
        tweak_handler: TweakHandler,
    ) -> None:
        mock_terminal = MagicMock(spec=TerminalUIPort)
        # Tweak fails first with gibberish, then user commits
        mock_terminal.prompt_confirmation_gate.side_effect = ["tweak", "commit"]
        mock_terminal.prompt_text.return_value = "Make it fast please"

        mock_fs = MagicMock(spec=FileSystemPort)
        mock_fs.read_workspace_existing_files.return_value = {}
        mock_fs.commit_workspace.return_value = ["azurerm_storage_account/sub-prod/main.tf"]

        flow = ProvisioningFlow(
            terminal=mock_terminal,
            standards=standards_engine,
            fs=mock_fs,
            catalog=catalog,
            tweak_handler=tweak_handler,
        )

        params, workspace = flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="mydata",
            environment="dev",
            auto_approve=False,
        )

        assert workspace.metadata.get("committed") is True
        # Verify error printed
        error_calls = [c[0][0] for c in mock_terminal.print_error.call_args_list]
        assert any("Refinement failed" in msg for msg in error_calls)

    def test_cancel_after_tweak_does_not_commit(
        self,
        standards_engine: StandardsEngine,
        catalog: JsonResourceCatalogAdapter,
        tweak_handler: TweakHandler,
    ) -> None:
        mock_terminal = MagicMock(spec=TerminalUIPort)
        # Tweak once, then cancel
        mock_terminal.prompt_confirmation_gate.side_effect = ["tweak", "cancel"]
        mock_terminal.prompt_text.return_value = "Change replication to GRS"

        mock_fs = MagicMock(spec=FileSystemPort)
        mock_fs.read_workspace_existing_files.return_value = {}

        flow = ProvisioningFlow(
            terminal=mock_terminal,
            standards=standards_engine,
            fs=mock_fs,
            catalog=catalog,
            tweak_handler=tweak_handler,
        )

        params, workspace = flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="mydata",
            environment="dev",
            auto_approve=False,
        )

        assert workspace.metadata.get("committed") is False
        mock_fs.commit_workspace.assert_not_called()
        mock_terminal.print.assert_any_call("Scaffolding cancelled. No files written to disk.")

    def test_auto_approve_bypasses_tweak_loop(
        self,
        standards_engine: StandardsEngine,
        catalog: JsonResourceCatalogAdapter,
        tweak_handler: TweakHandler,
    ) -> None:
        mock_terminal = MagicMock(spec=TerminalUIPort)
        mock_fs = MagicMock(spec=FileSystemPort)
        mock_fs.read_workspace_existing_files.return_value = {}
        mock_fs.commit_workspace.return_value = ["azurerm_storage_account/sub-prod/main.tf"]

        flow = ProvisioningFlow(
            terminal=mock_terminal,
            standards=standards_engine,
            fs=mock_fs,
            catalog=catalog,
            tweak_handler=tweak_handler,
        )

        params, workspace = flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="mydata",
            environment="dev",
            auto_approve=True,
        )

        assert workspace.metadata.get("committed") is True
        mock_terminal.prompt_confirmation_gate.assert_not_called()
        mock_terminal.confirm.assert_not_called()
        mock_fs.commit_workspace.assert_called_once()

    def test_immediate_commit_gate(
        self,
        standards_engine: StandardsEngine,
        catalog: JsonResourceCatalogAdapter,
        tweak_handler: TweakHandler,
    ) -> None:
        mock_terminal = MagicMock(spec=TerminalUIPort)
        mock_terminal.prompt_confirmation_gate.return_value = "commit"
        mock_fs = MagicMock(spec=FileSystemPort)
        mock_fs.read_workspace_existing_files.return_value = {}
        mock_fs.commit_workspace.return_value = ["azurerm_storage_account/sub-prod/main.tf"]

        flow = ProvisioningFlow(
            terminal=mock_terminal,
            standards=standards_engine,
            fs=mock_fs,
            catalog=catalog,
            tweak_handler=tweak_handler,
        )

        params, workspace = flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="mydata",
            environment="dev",
            auto_approve=False,
        )

        assert workspace.metadata.get("committed") is True
        mock_terminal.prompt_confirmation_gate.assert_called_once()
        mock_fs.commit_workspace.assert_called_once()

    def test_immediate_cancel_gate(
        self,
        standards_engine: StandardsEngine,
        catalog: JsonResourceCatalogAdapter,
        tweak_handler: TweakHandler,
    ) -> None:
        mock_terminal = MagicMock(spec=TerminalUIPort)
        mock_terminal.prompt_confirmation_gate.return_value = "cancel"
        mock_fs = MagicMock(spec=FileSystemPort)
        mock_fs.read_workspace_existing_files.return_value = {}

        flow = ProvisioningFlow(
            terminal=mock_terminal,
            standards=standards_engine,
            fs=mock_fs,
            catalog=catalog,
            tweak_handler=tweak_handler,
        )

        params, workspace = flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="mydata",
            environment="dev",
            auto_approve=False,
        )

        assert workspace.metadata.get("committed") is False
        mock_terminal.prompt_confirmation_gate.assert_called_once()
        mock_fs.commit_workspace.assert_not_called()

    def test_empty_tweak_instruction_recovery(
        self,
        standards_engine: StandardsEngine,
        catalog: JsonResourceCatalogAdapter,
        tweak_handler: TweakHandler,
    ) -> None:
        mock_terminal = MagicMock(spec=TerminalUIPort)
        # First tweak has empty string, then valid instruction, then commit
        mock_terminal.prompt_confirmation_gate.side_effect = ["tweak", "tweak", "commit"]
        mock_terminal.prompt_text.side_effect = ["   ", "Change replication to GRS"]
        mock_fs = MagicMock(spec=FileSystemPort)
        mock_fs.read_workspace_existing_files.return_value = {}
        mock_fs.commit_workspace.return_value = ["azurerm_storage_account/sub-prod/main.tf"]

        flow = ProvisioningFlow(
            terminal=mock_terminal,
            standards=standards_engine,
            fs=mock_fs,
            catalog=catalog,
            tweak_handler=tweak_handler,
        )

        params, workspace = flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="mydata",
            environment="dev",
            auto_approve=False,
        )

        assert workspace.metadata.get("committed") is True
        mock_terminal.print_info.assert_any_call("No refinement instruction entered.")
        main_content = workspace["main.tf"].content
        assert re.search(r'account_replication_type\s*=\s*"GRS"', main_content)

    def test_clear_screen_called_in_provisioning_flow(
        self,
        standards_engine: StandardsEngine,
        catalog: JsonResourceCatalogAdapter,
        tweak_handler: TweakHandler,
    ) -> None:
        mock_terminal = MagicMock(spec=TerminalUIPort)
        mock_terminal.prompt_confirmation_gate.side_effect = ["tweak", "commit"]
        mock_terminal.prompt_text.return_value = "Change replication to GRS"
        mock_fs = MagicMock(spec=FileSystemPort)
        mock_fs.read_workspace_existing_files.return_value = {}
        mock_fs.commit_workspace.return_value = ["azurerm_storage_account/sub-prod/main.tf"]

        flow = ProvisioningFlow(
            terminal=mock_terminal,
            standards=standards_engine,
            fs=mock_fs,
            catalog=catalog,
            tweak_handler=tweak_handler,
        )

        flow.run(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="mydata",
            environment="dev",
            auto_approve=False,
        )

        # clear_screen must be called on loop iteration > 0
        mock_terminal.clear_screen.assert_called_once()
