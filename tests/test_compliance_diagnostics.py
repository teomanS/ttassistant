"""Unit and integration tests for existing directory compliance inspection and diagnostics (Story 4.3, AD-1, AD-7)."""

from pathlib import Path
import pytest
from typer.testing import CliRunner

from ttassistant.adapters.hcl_adapter import ReadOnlyHclAdapter
from ttassistant.adapters.terminal_adapter import RichTerminalAdapter
from ttassistant.application.remediation_flow import RemediationFlow
from ttassistant.cli import app
from ttassistant.domain.compliance import (
    ComplianceReport,
    ComplianceSeverity,
    ComplianceViolation,
    ComplianceViolationType,
    ParsedResource,
    audit_paas_security_triad,
    audit_resource_tags,
)
from ttassistant.domain.standards import (
    NamingRule,
    NetworkingPolicyRule,
    StandardsBundle,
    StandardsEngine,
    TagRule,
)
from ttassistant.ports.terminal import TerminalUIPort


class MockTerminalAdapter(TerminalUIPort):
    """In-memory recording terminal adapter for testing."""

    def __init__(self, interactive: bool = True) -> None:
        self.messages: list[str] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.successes: list[str] = []
        self.infos: list[str] = []
        self.tables: list[tuple[str, list[str], list[list[str]]]] = []
        self._interactive = interactive

    @property
    def is_interactive(self) -> bool:
        return self._interactive

    def print(self, message: str = "", stderr: bool = False) -> None:
        self.messages.append(message)

    def print_error(self, message: str) -> None:
        self.errors.append(message)

    def print_warning(self, message: str) -> None:
        self.warnings.append(message)

    def print_success(self, message: str) -> None:
        self.successes.append(message)

    def print_info(self, message: str) -> None:
        self.infos.append(message)

    def prompt_text(self, prompt: str, default: str | None = None) -> str:
        return default or ""

    def prompt_select(self, prompt: str, choices: list[str], default: str | None = None) -> str:
        return choices[0] if choices else ""

    def prompt_confirm(self, prompt: str, default: bool = True) -> bool:
        return default

    def display_diff(self, old_content: str, new_content: str, title: str | None = None) -> None:
        pass

    def display_table(self, title: str, headers: list[str], rows: list[list[str]]) -> None:
        self.tables.append((title, headers, rows))


@pytest.fixture
def mock_standards() -> StandardsEngine:
    bundle = StandardsBundle(
        naming_rules={
            "azurerm_storage_account": NamingRule(
                resource_type="azurerm_storage_account",
                pattern=r"^st[a-z0-9]{1,22}$",
                max_length=24,
            )
        },
        tag_rules={
            "Environment": TagRule(key="Environment", required=True, allowed_values=["dev", "prod"]),
            "Owner": TagRule(key="Owner", required=True),
            "CostCenter": TagRule(key="CostCenter", required=True, default_value="CC-1000"),
            "ManagedBy": TagRule(key="ManagedBy", required=True, default_value="Terraform"),
            "OptionalTag": TagRule(key="OptionalTag", required=False),
        },
        networking_rules={
            "default": NetworkingPolicyRule(
                resource_type="default",
                subnet_patterns=["*snet*", "*pe*"],
            )
        },
    )
    return StandardsEngine(bundle)


class TestComplianceDomain:
    """Tests for pure domain compliance auditing functions and models."""

    def test_audit_resource_tags_all_present(self):
        res = ParsedResource(
            resource_type="azurerm_storage_account",
            resource_name="main",
            file_path="main.tf",
            tags={"Environment": "dev", "Owner": "platform-team", "CostCenter": "CC-1000"},
        )
        violations = audit_resource_tags(
            resource=res,
            required_tags=["Environment", "Owner", "CostCenter"],
        )
        assert len(violations) == 0

    def test_audit_resource_tags_missing_tags(self):
        res = ParsedResource(
            resource_type="azurerm_storage_account",
            resource_name="main",
            file_path="main.tf",
            tags={"Environment": "dev"},
        )
        violations = audit_resource_tags(
            resource=res,
            required_tags=["Environment", "Owner", "CostCenter"],
            standards_defaults={"CostCenter": "CC-1000"},
        )
        assert len(violations) == 2
        assert all(v.severity == ComplianceSeverity.HIGH for v in violations)
        assert all(v.violation_type == ComplianceViolationType.MISSING_TAG for v in violations)

        owner_v = next(v for v in violations if "Owner" in v.message)
        assert "Owner" in owner_v.remediation_hint

        cc_v = next(v for v in violations if "CostCenter" in v.message)
        assert "CC-1000" in cc_v.remediation_hint

    def test_audit_paas_security_triad_public_access_true(self):
        primary = ParsedResource(
            resource_type="azurerm_storage_account",
            resource_name="main",
            file_path="main.tf",
            attributes={"public_network_access_enabled": True},
        )
        violations = audit_paas_security_triad(primary_resource=primary, all_resources=[primary])
        crit = next((v for v in violations if v.violation_type == ComplianceViolationType.PUBLIC_NETWORK_ACCESS_ENABLED), None)
        assert crit is not None
        assert crit.severity == ComplianceSeverity.CRITICAL
        assert "public_network_access_enabled = false" in crit.remediation_hint

    def test_audit_paas_security_triad_public_access_omitted(self):
        primary = ParsedResource(
            resource_type="azurerm_key_vault",
            resource_name="vault",
            file_path="main.tf",
            attributes={},
        )
        violations = audit_paas_security_triad(primary_resource=primary, all_resources=[primary])
        crit = next((v for v in violations if v.violation_type == ComplianceViolationType.MISSING_PUBLIC_NETWORK_ACCESS_DENIAL), None)
        assert crit is not None
        assert crit.severity == ComplianceSeverity.CRITICAL

    def test_audit_paas_security_triad_missing_private_endpoint(self):
        primary = ParsedResource(
            resource_type="azurerm_storage_account",
            resource_name="main",
            file_path="main.tf",
            attributes={"public_network_access_enabled": False},
        )
        violations = audit_paas_security_triad(primary_resource=primary, all_resources=[primary])
        pe_v = next((v for v in violations if v.violation_type == ComplianceViolationType.MISSING_PRIVATE_ENDPOINT), None)
        assert pe_v is not None
        assert pe_v.severity == ComplianceSeverity.HIGH

    def test_audit_paas_security_triad_missing_dns_zone_group(self):
        primary = ParsedResource(
            resource_type="azurerm_storage_account",
            resource_name="main",
            file_path="main.tf",
            attributes={"public_network_access_enabled": False},
        )
        pe = ParsedResource(
            resource_type="azurerm_private_endpoint",
            resource_name="pe",
            file_path="private_endpoint.tf",
            attributes={"private_connection_resource_id": "azurerm_storage_account.main.id"},
            nested_blocks={},  # Missing private_dns_zone_group
        )
        violations = audit_paas_security_triad(primary_resource=primary, all_resources=[primary, pe])
        dns_v = next((v for v in violations if v.violation_type == ComplianceViolationType.MISSING_DNS_ZONE_GROUP), None)
        assert dns_v is not None
        assert dns_v.severity == ComplianceSeverity.MEDIUM

    def test_audit_paas_security_triad_fully_compliant(self):
        primary = ParsedResource(
            resource_type="azurerm_storage_account",
            resource_name="main",
            file_path="main.tf",
            attributes={"public_network_access_enabled": False},
        )
        pe = ParsedResource(
            resource_type="azurerm_private_endpoint",
            resource_name="pe",
            file_path="private_endpoint.tf",
            attributes={"private_connection_resource_id": "azurerm_storage_account.main.id"},
            nested_blocks={"private_dns_zone_group": {"name": "default"}},
        )
        violations = audit_paas_security_triad(primary_resource=primary, all_resources=[primary, pe])
        assert len(violations) == 0

    def test_audit_paas_security_triad_ignores_tier_2_or_infra(self):
        rg = ParsedResource(
            resource_type="azurerm_resource_group",
            resource_name="rg",
            file_path="main.tf",
            attributes={},
        )
        vnet = ParsedResource(
            resource_type="azurerm_virtual_network",
            resource_name="vnet",
            file_path="main.tf",
            attributes={},
        )
        assert len(audit_paas_security_triad(primary_resource=rg, all_resources=[rg])) == 0
        assert len(audit_paas_security_triad(primary_resource=vnet, all_resources=[vnet])) == 0

    def test_compliance_report_properties(self):
        violations = [
            ComplianceViolation(
                severity=ComplianceSeverity.CRITICAL,
                violation_type=ComplianceViolationType.PUBLIC_NETWORK_ACCESS_ENABLED,
                resource_type="azurerm_storage_account",
                resource_name="main",
                file_path="main.tf",
                message="Public network access is enabled.",
                remediation_hint="Disable public access.",
            ),
            ComplianceViolation(
                severity=ComplianceSeverity.HIGH,
                violation_type=ComplianceViolationType.MISSING_TAG,
                resource_type="azurerm_storage_account",
                resource_name="main",
                file_path="main.tf",
                message="Missing tag.",
                remediation_hint="Add tag.",
            ),
            ComplianceViolation(
                severity=ComplianceSeverity.MEDIUM,
                violation_type=ComplianceViolationType.MISSING_DNS_ZONE_GROUP,
                resource_type="azurerm_private_endpoint",
                resource_name="pe",
                file_path="pe.tf",
                message="Missing dns zone group.",
                remediation_hint="Add dns zone group.",
            ),
        ]
        report = ComplianceReport(
            target_dir="/test",
            violations=violations,
        )
        assert not report.is_compliant
        assert report.critical_count == 1
        assert report.high_count == 1
        assert report.medium_count == 1
        assert report.low_count == 0


class TestHclResourceExtraction:
    """Tests for HCL parser resource extraction adapter."""

    def test_parse_resources_from_file(self, tmp_path: Path):
        tf_file = tmp_path / "main.tf"
        tf_file.write_text(
            """
resource "azurerm_storage_account" "sa" {
  name                     = "stappdev001"
  resource_group_name      = "rg-app-dev"
  location                 = "westeurope"
  account_tier             = "Standard"
  account_replication_type = "LRS"
  public_network_access_enabled = false

  tags = {
    Environment = "dev"
    Owner       = "devops"
  }
}

resource "azurerm_private_endpoint" "pe" {
  name                = "pe-stappdev001"
  location            = "westeurope"
  resource_group_name = "rg-app-dev"
  subnet_id           = "/subscriptions/000/subnets/snet-pe"

  private_service_connection {
    name                           = "psc-stappdev001"
    private_connection_resource_id = azurerm_storage_account.sa.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = ["/subscriptions/000/dnszones/privatelink.blob.core.windows.net"]
  }
}
""",
            encoding="utf-8",
        )
        adapter = ReadOnlyHclAdapter()
        resources, warnings = adapter.parse_resources_from_file(tf_file)
        assert len(warnings) == 0
        assert len(resources) == 2

        sa = next(r for r in resources if r.resource_type == "azurerm_storage_account")
        assert sa.resource_name == "sa"
        assert sa.attributes["public_network_access_enabled"] is False
        assert sa.tags["Environment"] == "dev"
        assert sa.tags["Owner"] == "devops"

        pe = next(r for r in resources if r.resource_type == "azurerm_private_endpoint")
        assert pe.resource_name == "pe"
        assert "private_dns_zone_group" in pe.nested_blocks

    def test_parse_resources_malformed_syntax_fallback(self, tmp_path: Path):
        tf_file = tmp_path / "broken.tf"
        tf_file.write_text(
            """
# Malformed HCL that fails strict AST parsing
resource "azurerm_storage_account" "broken_sa" {
  name = "stbroken001"
  missing_closing_brace =
""",
            encoding="utf-8",
        )
        adapter = ReadOnlyHclAdapter()
        resources, warnings = adapter.parse_resources_from_file(tf_file)
        # Should gracefully return with warning and fallback extraction
        assert len(warnings) > 0
        assert any(r.resource_type == "azurerm_storage_account" for r in resources)


class TestRemediationFlow:
    """Tests for RemediationFlow application service."""

    def test_inspect_directory_fully_compliant(self, tmp_path: Path, mock_standards: StandardsEngine):
        work_dir = tmp_path / "compliant"
        work_dir.mkdir()
        (work_dir / "main.tf").write_text(
            """
resource "azurerm_storage_account" "main" {
  name                     = "stvalid001"
  resource_group_name      = "rg-valid"
  location                 = "westeurope"
  public_network_access_enabled = false
  tags = {
    Environment = "dev"
    Owner       = "sre"
    CostCenter  = "CC-1000"
    ManagedBy   = "Terraform"
  }
}

resource "azurerm_private_endpoint" "pe" {
  name                = "pe-stvalid001"
  location            = "westeurope"
  resource_group_name = "rg-valid"
  private_dns_zone_group {
    name = "default"
  }
}
""",
            encoding="utf-8",
        )
        terminal = MockTerminalAdapter()
        flow = RemediationFlow(
            terminal=terminal,
            standards=mock_standards,
            hcl_parser=ReadOnlyHclAdapter(),
        )

        report, exit_code = flow.run_diagnostics(work_dir, check=True)
        assert report.is_compliant
        assert len(report.violations) == 0
        assert exit_code == 0
        assert any("100% compliant" in s for s in terminal.successes)

    def test_inspect_directory_multiple_violations(self, tmp_path: Path, mock_standards: StandardsEngine):
        work_dir = tmp_path / "non_compliant"
        work_dir.mkdir()
        (work_dir / "main.tf").write_text(
            """
resource "azurerm_storage_account" "legacy" {
  name                     = "stlegacy001"
  resource_group_name      = "rg-legacy"
  location                 = "westeurope"
  public_network_access_enabled = true
  tags = {
    Environment = "dev"
  }
}
""",
            encoding="utf-8",
        )
        terminal = MockTerminalAdapter()
        flow = RemediationFlow(
            terminal=terminal,
            standards=mock_standards,
            hcl_parser=ReadOnlyHclAdapter(),
        )

        report, exit_code = flow.run_diagnostics(work_dir, check=False)
        assert not report.is_compliant
        assert exit_code == 0  # check=False returns 0
        assert report.critical_count >= 1  # public access enabled
        assert report.high_count >= 2     # missing tags & missing PE
        assert len(terminal.tables) == 1

        # Now test with check=True
        report_check, exit_code_check = flow.run_diagnostics(work_dir, check=True)
        assert exit_code_check == 1

    def test_inspect_directory_empty_folder(self, tmp_path: Path, mock_standards: StandardsEngine):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        terminal = MockTerminalAdapter()
        flow = RemediationFlow(
            terminal=terminal,
            standards=mock_standards,
            hcl_parser=ReadOnlyHclAdapter(),
        )

        report, exit_code = flow.run_diagnostics(empty_dir, check=True)
        assert exit_code == 0
        assert len(report.violations) == 0
        assert any("No .tf files discovered" in w for w in terminal.warnings)

    def test_inspect_directory_non_existent(self, tmp_path: Path, mock_standards: StandardsEngine):
        invalid_dir = tmp_path / "does_not_exist"
        terminal = MockTerminalAdapter()
        flow = RemediationFlow(
            terminal=terminal,
            standards=mock_standards,
            hcl_parser=ReadOnlyHclAdapter(),
        )

        report, exit_code = flow.run_diagnostics(invalid_dir, check=True)
        assert exit_code == 1
        assert any("does not exist" in e for e in terminal.errors)


class TestRemediateCLI:
    """End-to-end tests for ttassistant remediate command."""

    def test_remediate_cli_help(self):
        runner = CliRunner()
        result = runner.invoke(app, ["remediate", "--help"])
        assert result.exit_code == 0
        assert "remediate" in result.output
        assert "--check" in result.output

    def test_remediate_cli_compliant_directory(self, tmp_path: Path):
        comp_dir = tmp_path / "compliant_cli"
        comp_dir.mkdir()
        (comp_dir / "main.tf").write_text(
            """
resource "azurerm_storage_account" "sa" {
  name                     = "stvalidcli"
  location                 = "westeurope"
  public_network_access_enabled = false
  tags = {
    CostCenter  = "CC-1000"
    Environment = "prod"
    ManagedBy   = "Terraform"
    Owner       = "secops"
    Project     = "Infra"
  }
}

resource "azurerm_private_endpoint" "pe" {
  name                = "pe-stvalidcli"
  location            = "westeurope"
  private_dns_zone_group {
    name = "default"
  }
}
""",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(app, ["remediate", str(comp_dir), "--check"])
        assert result.exit_code == 0
        assert "100% compliant" in result.output

    def test_remediate_cli_check_fails_on_violations(self, tmp_path: Path):
        bad_dir = tmp_path / "bad_cli"
        bad_dir.mkdir()
        (bad_dir / "main.tf").write_text(
            """
resource "azurerm_storage_account" "bad_sa" {
  name = "stbad001"
  public_network_access_enabled = true
}
""",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(app, ["remediate", str(bad_dir), "--check"])
        assert result.exit_code == 1
        assert "Non-Compliance Diagnostics" in result.output or "CRITICAL" in result.output

    def test_remediate_cli_without_check_exits_zero(self, tmp_path: Path):
        bad_dir = tmp_path / "bad_cli_no_check"
        bad_dir.mkdir()
        (bad_dir / "main.tf").write_text(
            """
resource "azurerm_storage_account" "bad_sa" {
  name = "stbad002"
}
""",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(app, ["remediate", str(bad_dir)])
        assert result.exit_code == 0
        assert "Non-Compliance Diagnostics" in result.output or "CRITICAL" in result.output

    def test_remediate_cli_non_existent_path(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(app, ["remediate", str(tmp_path / "ghost_path")])
        assert result.exit_code == 1
        assert "does not exist" in result.output


class TestReviewLensRegressions:
    """Regression tests covering edge cases and verification gaps identified during review."""

    def test_rich_terminal_adapter_display_table_color_supported(self, monkeypatch):
        """Verify display_table renders Rich Table without NameError when color is supported."""
        adapter = RichTerminalAdapter()
        monkeypatch.setattr(adapter, "is_color_supported", lambda: True)
        # Should not raise NameError: name 'Table' is not defined
        adapter.display_table(
            "Test Table",
            ["Severity", "Resource", "Remediation Hint"],
            [["CRITICAL", "azurerm_storage_account.main", "Fix public access"]],
        )

    def test_rich_terminal_adapter_display_table_plain_text(self, monkeypatch):
        """Verify display_table renders cleanly in plain text when color is not supported."""
        adapter = RichTerminalAdapter()
        monkeypatch.setattr(adapter, "is_color_supported", lambda: False)
        adapter.display_table(
            "Plain Table",
            ["Col1", "Col2"],
            [["Value1", "Value2\nwith newline"]],
        )

    def test_multiple_paas_resources_targeting_isolation(self):
        """When multiple PaaS resources exist, an unrelated PE must not satisfy another PaaS resource."""
        sa = ParsedResource(
            resource_type="azurerm_storage_account",
            resource_name="main",
            file_path="main.tf",
            attributes={"public_network_access_enabled": False},
        )
        kv = ParsedResource(
            resource_type="azurerm_key_vault",
            resource_name="vault",
            file_path="vault.tf",
            attributes={"public_network_access_enabled": False},
        )
        # PE explicitly targets storage account only
        pe_sa = ParsedResource(
            resource_type="azurerm_private_endpoint",
            resource_name="pe_sa",
            file_path="pe.tf",
            attributes={"private_connection_resource_id": "azurerm_storage_account.main.id"},
            nested_blocks={"private_dns_zone_group": {"name": "default"}},
        )

        # Storage account should be compliant
        sa_violations = audit_paas_security_triad(sa, [sa, kv, pe_sa])
        assert len(sa_violations) == 0

        # Key vault should fail with MISSING_PRIVATE_ENDPOINT
        kv_violations = audit_paas_security_triad(kv, [sa, kv, pe_sa])
        assert any(v.violation_type == ComplianceViolationType.MISSING_PRIVATE_ENDPOINT for v in kv_violations)

    def test_multiple_pes_dns_zone_group_individual_check(self):
        """When multiple PEs exist, each must be individually verified for private_dns_zone_group."""
        sa = ParsedResource(
            resource_type="azurerm_storage_account",
            resource_name="sa",
            file_path="sa.tf",
            attributes={"public_network_access_enabled": False},
        )
        pe_compliant = ParsedResource(
            resource_type="azurerm_private_endpoint",
            resource_name="pe_compliant",
            file_path="pe1.tf",
            attributes={"private_connection_resource_id": "azurerm_storage_account.sa.id"},
            nested_blocks={"private_dns_zone_group": {"name": "default"}},
        )
        pe_missing_dns = ParsedResource(
            resource_type="azurerm_private_endpoint",
            resource_name="pe_missing_dns",
            file_path="pe2.tf",
            attributes={"private_connection_resource_id": "azurerm_storage_account.sa.id"},
            nested_blocks={},
        )

        violations = audit_paas_security_triad(sa, [sa, pe_compliant, pe_missing_dns])
        dns_v = [v for v in violations if v.violation_type == ComplianceViolationType.MISSING_DNS_ZONE_GROUP]
        assert len(dns_v) == 1
        assert dns_v[0].resource_name == "pe_missing_dns"

    def test_public_access_strict_non_denial(self):
        """Non-boolean non-denial values (e.g. 'Enabled') trigger CRITICAL violation."""
        sa = ParsedResource(
            resource_type="azurerm_storage_account",
            resource_name="sa",
            file_path="sa.tf",
            attributes={"public_network_access_enabled": "Enabled"},
        )
        violations = audit_paas_security_triad(sa, [sa])
        crit = next((v for v in violations if v.violation_type == ComplianceViolationType.PUBLIC_NETWORK_ACCESS_ENABLED), None)
        assert crit is not None
        assert crit.severity == ComplianceSeverity.CRITICAL

    def test_empty_tag_value_emits_violation(self):
        """Empty or whitespace tag value emits INVALID_TAG_VALUE violation."""
        sa = ParsedResource(
            resource_type="azurerm_storage_account",
            resource_name="sa",
            file_path="sa.tf",
            tags={"Environment": "   "},
        )
        violations = audit_resource_tags(sa, required_tags=["Environment"])
        assert len(violations) == 1
        assert violations[0].violation_type == ComplianceViolationType.INVALID_TAG_VALUE
        assert violations[0].severity == ComplianceSeverity.HIGH

    def test_naming_convention_audit_in_remediation_flow(self, tmp_path: Path, mock_standards: StandardsEngine):
        """Resources violating corporate naming convention must emit INVALID_RESOURCE_NAME."""
        work_dir = tmp_path / "naming_test"
        work_dir.mkdir()
        (work_dir / "main.tf").write_text(
            """
resource "azurerm_storage_account" "INVALID_NAME_WITH_CAPS" {
  name = "INVALID_NAME_WITH_CAPS"
  public_network_access_enabled = false
  tags = {
    Environment = "dev"
    Owner       = "secops"
    CostCenter  = "CC-1000"
    ManagedBy   = "Terraform"
  }
}
""",
            encoding="utf-8",
        )
        terminal = MockTerminalAdapter()
        flow = RemediationFlow(
            terminal=terminal,
            standards=mock_standards,
            hcl_parser=ReadOnlyHclAdapter(),
        )

        report, exit_code = flow.run_diagnostics(work_dir, check=False)
        naming_v = [v for v in report.violations if v.violation_type == ComplianceViolationType.INVALID_RESOURCE_NAME]
        assert len(naming_v) >= 1
        assert naming_v[0].severity == ComplianceSeverity.MEDIUM

    def test_compliance_report_model_dump_computed_fields(self):
        """Verify computed_field properties are included when serialized to dict/json."""
        report = ComplianceReport(
            target_dir="/test",
            violations=[],
        )
        dump = report.model_dump()
        assert "is_compliant" in dump
        assert dump["is_compliant"] is True
        assert "critical_count" in dump
        assert dump["critical_count"] == 0

