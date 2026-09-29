"""Comprehensive unit and integration test suite for surgical remediation staging and comment preservation (Story 4.4)."""

import os
from pathlib import Path
import re
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from ttassistant.adapters.fs_adapter import DiskFileSystemAdapter
from ttassistant.adapters.hcl_adapter import ReadOnlyHclAdapter
from ttassistant.adapters.terminal_adapter import RichTerminalAdapter
from ttassistant.application.remediation_flow import RemediationFlow
from ttassistant.cli import app
from ttassistant.domain.compliance import (
    ComplianceReport,
    ComplianceSeverity,
    ComplianceViolation,
    ComplianceViolationType,
)
from ttassistant.domain.patcher import (
    _strip_strings_and_comments,
    find_resource_block_lines,
    generate_companion_private_endpoint,
    patch_public_network_access,
    patch_tags,
)


# ==============================================================================
# Domain Patcher Unit Tests (AD-1, AD-2, AD-5)
# ==============================================================================


class TestDomainPatcherCommentPreservation:
    """Verify 100% comment, formatting, and indentation preservation during surgical patching."""

    def test_strip_strings_and_comments(self):
        line = '  name = "foo {bar} baz" # comment with {brace}'
        cleaned = _strip_strings_and_comments(line)
        assert "{" not in cleaned
        assert "}" not in cleaned
        assert "comment" not in cleaned

        line2 = '  /* block comment {inside} */ tags = {'
        cleaned2 = _strip_strings_and_comments(line2)
        assert cleaned2.strip() == "tags = {"

        line3 = '  foo = true // inline slash comment {here}'
        cleaned3 = _strip_strings_and_comments(line3)
        assert "{" not in cleaned3
        assert "//" not in cleaned3

    def test_find_resource_block_lines_nested_blocks(self):
        hcl = """# Header comment
// Top level comment
resource "azurerm_storage_account" "primary" {
  name                     = "stcorp001"
  account_tier             = "Standard"

  network_rules {
    default_action = "Deny"
    ip_rules       = ["10.0.0.1"]
  } # end network_rules

  tags = {
    Owner = "team"
  }
}

# Footer comment
resource "azurerm_resource_group" "rg" {
  name = "rg-main"
}
"""
        lines = hcl.splitlines(keepends=True)
        span = find_resource_block_lines(lines, "azurerm_storage_account", "primary")
        assert span is not None
        start, end = span
        assert lines[start].startswith('resource "azurerm_storage_account" "primary"')
        assert lines[end].strip() == "}"
        assert start == 2
        assert end == 14

    def test_find_resource_block_lines_not_found(self):
        lines = ['resource "azurerm_storage_account" "primary" {\n', "}\n"]
        span = find_resource_block_lines(lines, "azurerm_mssql_server", "sql")
        assert span is None

    def test_patch_public_network_access_inplace_replacement_preserves_comments(self):
        hcl = """# File header comment
resource "azurerm_storage_account" "sa" {
  name                          = "stmain01"
  public_network_access_enabled = true # Temporary waiver approved by SecOps (Ticket #1234)
  account_tier                  = "Standard"
}
"""
        patched = patch_public_network_access(hcl, "azurerm_storage_account", "sa", enabled=False)

        assert "# File header comment" in patched
        assert "public_network_access_enabled = false # Temporary waiver approved by SecOps (Ticket #1234)" in patched
        assert 'name                          = "stmain01"' in patched
        assert 'account_tier                  = "Standard"' in patched

    def test_patch_public_network_access_inplace_slash_comment(self):
        hcl = """resource "azurerm_storage_account" "sa" {
  public_network_access_enabled = true // double slash note
}
"""
        patched = patch_public_network_access(hcl, "azurerm_storage_account", "sa", enabled=False)
        assert "public_network_access_enabled = false // double slash note" in patched

    def test_patch_public_network_access_omitted_insertion(self):
        hcl = """# Header
resource "azurerm_storage_account" "sa" {
    name = "sttest01"
    account_tier = "Standard"
}
"""
        patched = patch_public_network_access(hcl, "azurerm_storage_account", "sa", enabled=False)

        assert "# Header" in patched
        assert "    public_network_access_enabled = false\n" in patched
        assert "    name = \"sttest01\"" in patched

    def test_patch_tags_append_to_existing_multiline_block(self):
        hcl = """resource "azurerm_storage_account" "sa" {
  name = "st01"

  tags = {
    Owner       = "dev-team@corp.com" # primary contact
    Environment = "prod"
  } # end tags
}
"""
        missing = {
            "CostCenter": "CC-9999",
            "Project": "CorePlatform",
        }
        patched = patch_tags(hcl, "azurerm_storage_account", "sa", missing)

        assert 'Owner       = "dev-team@corp.com" # primary contact' in patched
        assert 'Environment = "prod"' in patched
        assert 'CostCenter = "CC-9999"' in patched
        assert 'Project = "CorePlatform"' in patched
        assert "} # end tags" in patched

    def test_patch_tags_updates_empty_values_inplace(self):
        hcl = """resource "azurerm_storage_account" "sa" {
  name = "st01"

  tags = {
    Owner       = "dev-team@corp.com"
    Environment = "" # Needs to be populated
  }
}
"""
        missing = {
            "Environment": "dev",
            "CostCenter": "CC-1001",
        }
        patched = patch_tags(hcl, "azurerm_storage_account", "sa", missing)

        assert 'Environment = "dev" # Needs to be populated' in patched
        assert 'CostCenter = "CC-1001"' in patched
        # Ensure Environment was not duplicated
        assert patched.count("Environment =") == 1

    def test_patch_tags_single_line_tags_block(self):
        hcl = """resource "azurerm_storage_account" "sa" {
  name = "st01"
  tags = {} # empty tag block
}
"""
        missing = {
            "Owner": "platform@corp.com",
            "Environment": "dev",
        }
        patched = patch_tags(hcl, "azurerm_storage_account", "sa", missing)

        assert "tags = { # empty tag block" in patched
        assert 'Owner = "platform@corp.com"' in patched
        assert 'Environment = "dev"' in patched

    def test_patch_tags_creates_new_block_when_absent(self):
        hcl = """# Storage component
resource "azurerm_storage_account" "sa" {
  name         = "st01"
  account_tier = "Standard"
}
"""
        missing = {
            "CostCenter": "CC-101",
            "Owner": "infra@corp.com",
        }
        patched = patch_tags(hcl, "azurerm_storage_account", "sa", missing)

        assert "  tags = {" in patched
        assert '    CostCenter = "CC-101"' in patched
        assert '    Owner = "infra@corp.com"' in patched
        assert "# Storage component" in patched

    def test_patch_no_op_when_missing_tags_empty(self):
        hcl = """resource "azurerm_storage_account" "sa" {\n  name = "st01"\n}\n"""
        assert patch_tags(hcl, "azurerm_storage_account", "sa", {}) == hcl


class TestCompanionPrivateEndpointGeneration:
    """Verify generation of companion azurerm_private_endpoint blocks with DNS zone groups."""

    def test_generate_companion_private_endpoint_storage(self):
        block = generate_companion_private_endpoint(
            resource_type="azurerm_storage_account",
            resource_name="primary_sa",
            location="northeurope",
            resource_group_name="rg-data",
        )

        assert 'resource "azurerm_private_endpoint" "pe_primary_sa"' in block
        assert 'name                = "pe-primary_sa"' in block
        assert 'location            = "northeurope"' in block
        assert 'resource_group_name = "rg-data"' in block
        assert 'private_connection_resource_id = azurerm_storage_account.primary_sa.id' in block
        assert 'subresource_names              = ["blob"]' in block
        assert 'private_dns_zone_group {' in block
        assert "privatelink.blob.core.windows.net" in block

    def test_generate_companion_private_endpoint_mssql(self):
        block = generate_companion_private_endpoint(
            resource_type="azurerm_mssql_server",
            resource_name="sql_server",
        )

        assert 'resource "azurerm_private_endpoint" "pe_sql_server"' in block
        assert 'private_connection_resource_id = azurerm_mssql_server.sql_server.id' in block
        assert 'subresource_names              = ["sqlServer"]' in block
        assert "privatelink.database.windows.net" in block

    def test_generate_companion_private_endpoint_with_tags(self):
        block = generate_companion_private_endpoint(
            resource_type="azurerm_key_vault",
            resource_name="kv",
            tags={"Environment": "prod", "CostCenter": "CC-001"},
        )

        assert "tags = {" in block
        assert 'CostCenter = "CC-001"' in block
        assert 'Environment = "prod"' in block
        assert "privatelink.vaultcore.azure.net" in block


# ==============================================================================
# RemediationFlow Staging & Execution Integration Tests
# ==============================================================================


class TestRemediationFlowStaging:
    """Verify StagedWorkspace staging, unified diff computation, and atomic commit."""

    def test_stage_remediation_modifies_only_non_compliant_resources(self, tmp_path: Path):
        work_dir = tmp_path / "stage_test"
        work_dir.mkdir()

        tf_file = work_dir / "main.tf"
        tf_file.write_text(
            """# Legacy storage account
resource "azurerm_storage_account" "sa" {
  name                          = "ststage001"
  account_tier                  = "Standard"
  public_network_access_enabled = true
}

# Unmanaged network security rule - should be untouched
resource "azurerm_network_security_rule" "nsg_rule" {
  name = "allow_ssh"
}
""",
            encoding="utf-8",
        )

        terminal = RichTerminalAdapter()
        fs = DiskFileSystemAdapter()
        hcl_parser = ReadOnlyHclAdapter()
        flow = RemediationFlow(terminal=terminal, standards=None, fs=fs, hcl_parser=hcl_parser)

        report = flow.inspect_directory(work_dir)
        workspace = flow.stage_remediation(work_dir, report=report)

        # Target file on disk must remain 100% UNTOUCHED before commit
        disk_content = tf_file.read_text(encoding="utf-8")
        assert "public_network_access_enabled = true" in disk_content

        # Staged workspace has modified file
        assert len(workspace.files) == 1
        staged_content = list(workspace.files.values())[0].content

        assert "# Legacy storage account" in staged_content
        assert "public_network_access_enabled = false" in staged_content
        assert 'name                          = "ststage001"' in staged_content
        assert "tags = {" in staged_content
        assert 'resource "azurerm_private_endpoint" "pe_sa"' in staged_content
        assert 'resource "azurerm_network_security_rule" "nsg_rule"' in staged_content

    def test_stage_remediation_zero_changes_on_compliant_folder(self, tmp_path: Path):
        work_dir = tmp_path / "compliant_stage"
        work_dir.mkdir()

        (work_dir / "main.tf").write_text(
            """resource "azurerm_storage_account" "sa" {
  name                          = "stcomp001"
  public_network_access_enabled = false
  tags = {
    CostCenter  = "CC-100"
    Environment = "dev"
    ManagedBy   = "Terraform"
    Owner       = "platform@corp.com"
    Project     = "Core"
  }
}

resource "azurerm_private_endpoint" "pe_sa" {
  name = "pe-sa"
  private_service_connection {
    name                           = "psc-sa"
    private_connection_resource_id = azurerm_storage_account.sa.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = ["/subscriptions/.../privatelink.blob.core.windows.net"]
  }
}
""",
            encoding="utf-8",
        )

        terminal = RichTerminalAdapter()
        flow = RemediationFlow(terminal=terminal, standards=None, fs=None, hcl_parser=ReadOnlyHclAdapter())

        report = flow.inspect_directory(work_dir)
        assert report.is_compliant

        workspace = flow.stage_remediation(work_dir, report=report)
        assert len(workspace.files) == 0

    def test_run_remediation_auto_approve_commits_to_disk(self, tmp_path: Path):
        work_dir = tmp_path / "auto_commit_dir"
        work_dir.mkdir()
        tf_file = work_dir / "main.tf"
        tf_file.write_text(
            """resource "azurerm_storage_account" "sa" {
  name                          = "stauto01"
  public_network_access_enabled = true
}
""",
            encoding="utf-8",
        )

        terminal = RichTerminalAdapter()
        fs = DiskFileSystemAdapter()
        flow = RemediationFlow(terminal=terminal, standards=None, fs=fs, hcl_parser=ReadOnlyHclAdapter())

        report, exit_code = flow.run_remediation(work_dir, auto_approve=True)

        assert exit_code == 0
        disk_content = tf_file.read_text(encoding="utf-8")
        assert "public_network_access_enabled = false" in disk_content
        assert "tags = {" in disk_content
        assert 'resource "azurerm_private_endpoint" "pe_sa"' in disk_content

    def test_run_remediation_user_confirm_commits_to_disk(self, tmp_path: Path):
        work_dir = tmp_path / "confirm_commit_dir"
        work_dir.mkdir()
        tf_file = work_dir / "main.tf"
        tf_file.write_text(
            """resource "azurerm_storage_account" "sa" {
  name                          = "stconfirm01"
  public_network_access_enabled = true
}
""",
            encoding="utf-8",
        )

        mock_terminal = MagicMock()
        mock_terminal.confirm.return_value = True
        mock_terminal.is_color_supported.return_value = False

        fs = DiskFileSystemAdapter()
        flow = RemediationFlow(terminal=mock_terminal, standards=None, fs=fs, hcl_parser=ReadOnlyHclAdapter())

        report, exit_code = flow.run_remediation(work_dir, auto_approve=False)

        assert exit_code == 0
        mock_terminal.confirm.assert_called_once()
        mock_terminal.print_success.assert_called()

        disk_content = tf_file.read_text(encoding="utf-8")
        assert "public_network_access_enabled = false" in disk_content

    def test_run_remediation_user_cancel_leaves_disk_untouched(self, tmp_path: Path):
        work_dir = tmp_path / "cancel_commit_dir"
        work_dir.mkdir()
        original_content = """# Keep this intact
resource "azurerm_storage_account" "sa" {
  name                          = "stcancel01"
  public_network_access_enabled = true
}
"""
        tf_file = work_dir / "main.tf"
        tf_file.write_text(original_content, encoding="utf-8")

        mock_terminal = MagicMock()
        mock_terminal.confirm.return_value = False
        mock_terminal.is_color_supported.return_value = False

        fs = DiskFileSystemAdapter()
        flow = RemediationFlow(terminal=mock_terminal, standards=None, fs=fs, hcl_parser=ReadOnlyHclAdapter())

        report, exit_code = flow.run_remediation(work_dir, auto_approve=False)

        assert exit_code == 0
        mock_terminal.confirm.assert_called_once()
        mock_terminal.print_warning.assert_called_with("Remediation cancelled. Disk left untouched.")

        # Verify disk is 100% untouched
        disk_content = tf_file.read_text(encoding="utf-8")
        assert disk_content == original_content


# ==============================================================================
# CLI Remediation Integration Tests
# ==============================================================================


class TestRemediateCLIStory44:
    """Verify CLI interactive, auto-approve, and check behaviors for Story 4.4."""

    def test_cli_remediate_with_yes_flag(self, tmp_path: Path):
        target_dir = tmp_path / "cli_yes"
        target_dir.mkdir()
        tf_file = target_dir / "main.tf"
        tf_file.write_text(
            """# Legacy comment
resource "azurerm_storage_account" "legacy" {
  name                          = "stcliyes01"
  public_network_access_enabled = true
}
""",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(app, ["remediate", str(target_dir), "--yes"])

        assert result.exit_code == 0
        assert "Successfully committed surgical remediation" in result.output
        updated = tf_file.read_text(encoding="utf-8")
        assert "# Legacy comment" in updated
        assert "public_network_access_enabled = false" in updated
        assert "azurerm_private_endpoint" in updated

    def test_cli_remediate_interactive_yes_input(self, tmp_path: Path):
        target_dir = tmp_path / "cli_interactive_yes"
        target_dir.mkdir()
        tf_file = target_dir / "main.tf"
        tf_file.write_text(
            """resource "azurerm_storage_account" "legacy" {
  name                          = "stintyes"
  public_network_access_enabled = true
}
""",
            encoding="utf-8",
        )

        runner = CliRunner()
        # Feed "y" to interactive prompt
        result = runner.invoke(app, ["remediate", str(target_dir)], input="y\n")

        assert result.exit_code == 0
        assert "Successfully committed surgical remediation" in result.output
        updated = tf_file.read_text(encoding="utf-8")
        assert "public_network_access_enabled = false" in updated

    def test_cli_remediate_interactive_no_input_cancels(self, tmp_path: Path):
        target_dir = tmp_path / "cli_interactive_no"
        target_dir.mkdir()
        tf_file = target_dir / "main.tf"
        original = """resource "azurerm_storage_account" "legacy" {
  name                          = "stintno"
  public_network_access_enabled = true
}
"""
        tf_file.write_text(original, encoding="utf-8")

        runner = CliRunner()
        # Feed "n" to interactive prompt
        result = runner.invoke(app, ["remediate", str(target_dir)], input="n\n")

        assert result.exit_code == 0
        assert "Remediation cancelled. Disk left untouched." in result.output
        assert tf_file.read_text(encoding="utf-8") == original

    def test_cli_remediate_check_mode_does_not_remediate(self, tmp_path: Path):
        target_dir = tmp_path / "cli_check_only"
        target_dir.mkdir()
        tf_file = target_dir / "main.tf"
        original = """resource "azurerm_storage_account" "legacy" {
  name                          = "stcheck"
  public_network_access_enabled = true
}
"""
        tf_file.write_text(original, encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(app, ["remediate", str(target_dir), "--check"])

        assert result.exit_code == 1
        assert "CRITICAL" in result.output
        assert tf_file.read_text(encoding="utf-8") == original

    def test_cli_remediate_already_compliant(self, tmp_path: Path):
        target_dir = tmp_path / "cli_compliant"
        target_dir.mkdir()
        (target_dir / "main.tf").write_text(
            """resource "azurerm_resource_group" "rg" {
  name     = "rg-sample"
  location = "westeurope"
  tags = {
    CostCenter  = "CC-101"
    Environment = "dev"
    ManagedBy   = "Terraform"
    Owner       = "infra@corp.com"
    Project     = "Core"
  }
}
""",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(app, ["remediate", str(target_dir)])

        assert result.exit_code == 0
        assert "100% compliant with corporate standards" in result.output


# ==============================================================================
# Edge-Cases and Architectural Isolation Tests
# ==============================================================================


class TestRemediationEdgeCasesAndArchitecture:
    """Verify architectural boundaries and subtle edge cases."""

    def test_domain_patcher_architectural_isolation_ad1(self):
        """Verify ttassistant.domain.patcher has zero forbidden external or adapter imports."""
        patcher_path = Path("ttassistant/domain/patcher.py")
        content = patcher_path.read_text(encoding="utf-8")

        forbidden = [
            "typer",
            "rich",
            "questionary",
            "hcl2",
            "ttassistant.adapters",
            "ttassistant.application",
            "ttassistant.cli",
        ]
        for f in forbidden:
            assert f not in content, f"Forbidden import '{f}' found in domain/patcher.py (AD-1 violation)"

    def test_patch_multiple_paas_resources_in_single_file(self):
        hcl = """# Multi-resource file
resource "azurerm_storage_account" "sa1" {
  name                          = "st01"
  public_network_access_enabled = true
}

resource "azurerm_mssql_server" "sql" {
  name                          = "sql01"
  public_network_access_enabled = true
}
"""
        patched = patch_public_network_access(hcl, "azurerm_storage_account", "sa1", enabled=False)
        patched = patch_public_network_access(patched, "azurerm_mssql_server", "sql", enabled=False)

        assert patched.count("public_network_access_enabled = false") == 2
        assert "# Multi-resource file" in patched

    def test_patch_tags_with_special_characters_and_comments(self):
        hcl = """resource "azurerm_storage_account" "sa" {
  name = "st01"
  /* Block comment before tags */
  tags = {
    # Custom note
    Existing = "Value" // inline comment
  }
}
"""
        missing = {"CostCenter": "CC-900"}
        patched = patch_tags(hcl, "azurerm_storage_account", "sa", missing)

        assert "/* Block comment before tags */" in patched
        assert "# Custom note" in patched
        assert 'Existing = "Value" // inline comment' in patched
        assert 'CostCenter = "CC-900"' in patched

    def test_stage_remediation_omitted_public_network_access_attribute(self, tmp_path: Path):
        """Verify RemediationFlow stages PNA denial when attribute is completely omitted."""
        work_dir = tmp_path / "omitted_pna_dir"
        work_dir.mkdir()
        (work_dir / "main.tf").write_text(
            """resource "azurerm_storage_account" "sa_omitted" {
  name         = "stomitted01"
  account_tier = "Standard"
}
""",
            encoding="utf-8",
        )

        flow = RemediationFlow(
            terminal=RichTerminalAdapter(),
            standards=None,
            fs=DiskFileSystemAdapter(),
            hcl_parser=ReadOnlyHclAdapter(),
        )
        report = flow.inspect_directory(work_dir)
        # Verify violation was detected
        assert any(
            v.violation_type == ComplianceViolationType.MISSING_PUBLIC_NETWORK_ACCESS_DENIAL
            for v in report.violations
        )

        workspace = flow.stage_remediation(work_dir, report=report)
        assert len(workspace.files) == 1
        staged_text = list(workspace.files.values())[0].content
        assert "public_network_access_enabled = false" in staged_text

    def test_stage_remediation_handles_invalid_tag_value(self, tmp_path: Path):
        """Verify RemediationFlow stages in-place tag updates for INVALID_TAG_VALUE violations."""
        work_dir = tmp_path / "invalid_tag_dir"
        work_dir.mkdir()
        (work_dir / "main.tf").write_text(
            """resource "azurerm_storage_account" "sa_empty_tag" {
  name = "stinvtag01"
  tags = {
    Environment = ""
    Owner       = "team@corp.com"
  }
}
""",
            encoding="utf-8",
        )

        flow = RemediationFlow(
            terminal=RichTerminalAdapter(),
            standards=None,
            fs=DiskFileSystemAdapter(),
            hcl_parser=ReadOnlyHclAdapter(),
        )
        report = flow.inspect_directory(work_dir)
        assert any(
            v.violation_type == ComplianceViolationType.INVALID_TAG_VALUE
            for v in report.violations
        )

        workspace = flow.stage_remediation(work_dir, report=report)
        assert len(workspace.files) == 1
        staged_text = list(workspace.files.values())[0].content
        assert 'Environment = "..."' in staged_text
        assert staged_text.count("Environment =") == 1

    def test_single_line_resource_block_expansion(self):
        """Verify single-line resource declarations are expanded cleanly without syntax errors."""
        hcl = 'resource "azurerm_storage_account" "sa" { name = "st01" }'
        pna_patched = patch_public_network_access(hcl, "azurerm_storage_account", "sa", enabled=False)
        assert "public_network_access_enabled = false" in pna_patched
        assert pna_patched.strip().endswith("}")

        tag_patched = patch_tags(hcl, "azurerm_storage_account", "sa", {"Environment": "dev"})
        assert "tags = {" in tag_patched
        assert 'Environment = "dev"' in tag_patched
        assert tag_patched.strip().endswith("}")

    def test_multi_line_comment_with_braces(self):
        """Verify multi-line C-style comments containing braces do not confuse block line tracking."""
        hcl = """/*
  This is a block comment
  { with unbalanced curly brace
*/
resource "azurerm_storage_account" "sa" {
  name = "st01"
  account_tier = "Standard"
}
"""
        span = find_resource_block_lines(hcl.splitlines(keepends=True), "azurerm_storage_account", "sa")
        assert span is not None
        start, end = span
        assert start == 4

        patched = patch_public_network_access(hcl, "azurerm_storage_account", "sa", enabled=False)
        assert "public_network_access_enabled = false" in patched

    def test_dynamic_tags_variable_reference_not_overwritten(self):
        """Verify dynamic tag assignment via variable or function is not corrupted with a duplicate tags block."""
        hcl = """resource "azurerm_storage_account" "sa" {
  name = "st01"
  tags = var.custom_tags
}
"""
        patched = patch_tags(hcl, "azurerm_storage_account", "sa", {"Environment": "dev"})
        # Must not inject a conflicting tags = { ... } block
        assert patched.count("tags =") == 1
        assert patched == hcl

    def test_quoted_tag_keys_with_trailing_commas(self):
        """Verify quoted tag keys with trailing commas are updated in-place preserving style."""
        hcl = """resource "azurerm_storage_account" "sa" {
  name = "st01"
  tags = {
    "Environment" = "", // inline comment
    "Owner"       = "ops@corp.com",
  }
}
"""
        missing = {"Environment": "prod"}
        patched = patch_tags(hcl, "azurerm_storage_account", "sa", missing)
        assert '"Environment" = "prod",' in patched
        assert "// inline comment" in patched
        assert patched.count('"Environment" =') == 1

    def test_companion_private_endpoint_resource_generation_valid(self):
        """Verify companion PE resource labels and attributes are generated properly."""
        pe_sa = generate_companion_private_endpoint("azurerm_storage_account", "sa_blob")
        pe_kv = generate_companion_private_endpoint("azurerm_key_vault", "kv_secrets")

        assert 'resource "azurerm_private_endpoint" "pe_sa_blob"' in pe_sa
        assert 'resource "azurerm_private_endpoint" "pe_kv_secrets"' in pe_kv

    def test_remediation_flow_missing_hcl_parser_raises(self, tmp_path: Path):
        """Verify RemediationFlow raises RuntimeError if hcl_parser is not provided."""
        (tmp_path / "main.tf").write_text('resource "azurerm_storage_account" "sa" {}')
        flow = RemediationFlow(terminal=RichTerminalAdapter(), standards=None, fs=None, hcl_parser=None)
        with pytest.raises(RuntimeError, match="HCL parser port is required"):
            flow.inspect_directory(tmp_path)

    def test_remediation_flow_missing_fs_on_commit_raises(self, tmp_path: Path):
        """Verify RemediationFlow raises RuntimeError if fs is None when committing."""
        (tmp_path / "main.tf").write_text('resource "azurerm_storage_account" "sa" { public_network_access_enabled = true }')
        flow = RemediationFlow(
            terminal=RichTerminalAdapter(),
            standards=None,
            fs=None,
            hcl_parser=ReadOnlyHclAdapter(),
        )
        with pytest.raises(RuntimeError, match="FileSystem port is required"):
            flow.run_remediation(tmp_path, auto_approve=True)


