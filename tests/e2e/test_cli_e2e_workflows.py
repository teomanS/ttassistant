"""End-to-End (E2E) automated CLI workflow test suite for ttassistant."""

from pathlib import Path
import shutil

import pytest
from typer.testing import CliRunner

from ttassistant.cli import app


@pytest.fixture
def enterprise_monorepo(tmp_path: Path) -> Path:
    """Fixture simulating a corporate Terraform monorepo with existing networking and real standards."""
    repo = tmp_path / "enterprise_monorepo"
    repo.mkdir()

    # 1. Copy real common_standards from project root
    shutil.copytree(Path("common_standards").resolve(), repo / "common_standards")

    # 2. Existing networking infrastructure folder in workload-prod
    net_dir = repo / "networking" / "workload-prod"
    net_dir.mkdir(parents=True)
    (net_dir / "main.tf").write_text(
        """resource "azurerm_resource_group" "rg_net" {
  name     = "rg-network-prod"
  location = "westeurope"
}

resource "azurerm_virtual_network" "vnet_hub" {
  name                = "vnet-prod-hub"
  resource_group_name = azurerm_resource_group.rg_net.name
  location            = azurerm_resource_group.rg_net.location
  address_space       = ["10.0.0.0/16"]
}

resource "azurerm_subnet" "snet_paas" {
  name                 = "snet-paas"
  resource_group_name  = azurerm_resource_group.rg_net.name
  virtual_network_name = azurerm_virtual_network.vnet_hub.name
  address_prefixes     = ["10.0.1.0/24"]
}
""",
        encoding="utf-8",
    )

    return repo


class TestEndToEndProvisioningWorkflows:
    """E2E Scenario Tests for Greenfield Provisioning (`ttassistant new`)."""

    def test_e2e_greenfield_tier_1_paas_scaffolding(
        self, enterprise_monorepo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """E2E Journey: Scaffold Tier 1 PaaS with subnet discovery, Enterprise Security Triad, and atomic commit."""
        monkeypatch.chdir(enterprise_monorepo)
        runner = CliRunner(env={"COLUMNS": "200"})
        result = runner.invoke(
            app,
            [
                "--standards-dir",
                str(enterprise_monorepo / "common_standards"),
                "new",
                "--subscription",
                "workload-prod",
                "--resource-type",
                "azurerm_storage_account",
                "--workload",
                "corpapp",
                "--env",
                "prod",
                "--subnet",
                "snet-paas",
                "--yes",
            ],
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert "Committed 3 files atomically to disk" in result.output

        target_dir = enterprise_monorepo / "azurerm_storage_account" / "workload-prod"
        assert target_dir.is_dir()

        # 1. Verify main.tf: Enterprise Security Triad & Tags
        main_tf = target_dir / "main.tf"
        assert main_tf.exists()
        main_content = main_tf.read_text(encoding="utf-8")

        # AD-7 / FR-12: Mandatory public network access denial
        assert "public_network_access_enabled = false" in main_content
        # FR-9: Mandatory compliance tags
        assert 'CostCenter  = "CC-1001"' in main_content
        assert 'Environment = "prod"' in main_content
        assert 'Owner       = "cloud-platform@corporate.com"' in main_content
        assert 'Project     = "CorePlatform"' in main_content
        # FR-13: Companion Private Endpoint & Hub DNS Zone Group
        assert 'resource "azurerm_private_endpoint" "primary"' in main_content
        assert "data.azurerm_private_dns_zone.hub.id" in main_content

        # 2. Verify data.tf: Decoupled data sources
        data_tf = target_dir / "data.tf"
        assert data_tf.exists()
        data_content = data_tf.read_text(encoding="utf-8")
        assert 'data "azurerm_resource_group" "primary"' in data_content
        assert 'data "azurerm_subnet" "primary"' in data_content
        assert "privatelink.blob.core.windows.net" in data_content
        assert "terraform_remote_state" not in data_content

        # 3. Verify backend.tf: State backend isolation
        backend_tf = target_dir / "backend.tf"
        assert backend_tf.exists()
        backend_content = backend_tf.read_text(encoding="utf-8")
        assert 'backend "azurerm"' in backend_content
        assert "sttfstateprod" in backend_content
        assert "prod/azurerm_storage_account.tfstate" in backend_content

    def test_e2e_greenfield_tier_2_universal_resource_scaffolding(
        self, enterprise_monorepo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """E2E Journey: Scaffold Tier 2 Universal long-tail resource with offline schema validation."""
        monkeypatch.chdir(enterprise_monorepo)
        runner = CliRunner(env={"COLUMNS": "200"})
        result = runner.invoke(
            app,
            [
                "--standards-dir",
                str(enterprise_monorepo / "common_standards"),
                "new",
                "--subscription",
                "workload-dev",
                "--resource-type",
                "azurerm_resource_group",
                "--workload",
                "analytics",
                "--env",
                "dev",
                "--yes",
            ],
        )

        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert "Committed 2 files atomically to disk" in result.output
        target_dir = enterprise_monorepo / "azurerm_resource_group" / "workload-dev"
        assert target_dir.is_dir()

        main_content = (target_dir / "main.tf").read_text(encoding="utf-8")
        assert 'resource "azurerm_resource_group" "primary"' in main_content
        assert 'name     = "rg-analytics-dev"' in main_content
        assert 'Environment = "dev"' in main_content
        assert 'Owner       = "cloud-platform@corporate.com"' in main_content


class TestEndToEndTopologyAndCatalogWorkflows:
    """E2E Scenario Tests for Monorepo Topology Discovery and Schema Catalog."""

    def test_e2e_monorepo_topology_scanning(self, enterprise_monorepo: Path):
        """E2E Journey: Recursively scan monorepo topology with fast lexical and AST extraction."""
        runner = CliRunner(env={"COLUMNS": "200"})
        result = runner.invoke(
            app,
            ["scan", str(enterprise_monorepo), "--ast"],
        )

        assert result.exit_code == 0
        assert "Discovered Subnets" in result.output
        assert "snet-paas" in result.output
        assert "vnet-prod-hub" in result.output
        assert "rg-network-prod" in result.output
        assert "Phase 2 AST Extraction Complete" in result.output

    def test_e2e_offline_schema_catalog_exploration(self):
        """E2E Journey: Inspect offline AzureRM schema catalog without network calls."""
        runner = CliRunner(env={"COLUMNS": "200"})

        # 1. List Tier 1 PaaS resources
        list_res = runner.invoke(app, ["catalog", "list", "--tier", "1"])
        assert list_res.exit_code == 0
        assert "AzureRM Schema Catalog" in list_res.output
        assert "azurerm_storage_account" in list_res.output
        assert "azurerm_key_vault" in list_res.output
        assert "Tier 1 (Guided PaaS)" in list_res.output

        # 2. Inspect specific resource argument schema
        info_res = runner.invoke(app, ["catalog", "info", "azurerm_storage_account"])
        assert info_res.exit_code == 0
        assert "Schema Arguments for azurerm_storage_account" in info_res.output
        assert "account_tier" in info_res.output
        assert "account_replication_type" in info_res.output


class TestEndToEndComplianceRemediationLifecycle:
    """E2E Scenario Tests for Audit, Non-Compliance Diagnostics, and Surgical Remediation."""

    def test_e2e_full_remediation_lifecycle(self, enterprise_monorepo: Path):
        """E2E Journey: Audit non-compliant legacy code -> fail CI gate -> surgically fix -> pass CI gate."""
        runner = CliRunner(env={"COLUMNS": "200"})
        standards_arg = ["--standards-dir", str(enterprise_monorepo / "common_standards")]

        # Setup legacy non-compliant workload with developer comments
        legacy_dir = enterprise_monorepo / "legacy_workload" / "workload-prod"
        legacy_dir.mkdir(parents=True)
        legacy_file = legacy_dir / "main.tf"
        legacy_file.write_text(
            """# Legacy storage account for payment processing
// Security waiver ticket SEC-8899 expired last quarter
resource "azurerm_storage_account" "payment" {
  name                          = "stpaymentprod"
  account_tier                  = "Standard"
  account_replication_type      = "LRS"
  public_network_access_enabled = true # Temporary waiver enabled
  /* Custom configuration block */
}
""",
            encoding="utf-8",
        )

        # Step 1: CI Audit with --check should fail with exit code 1
        audit_res = runner.invoke(app, [*standards_arg, "remediate", str(legacy_dir), "--check"])
        assert audit_res.exit_code == 1
        assert "Non-Compliance Diagnostics" in audit_res.output
        assert "CRITICAL" in audit_res.output
        assert "missing_tag" in audit_res.output
        assert "public_network_access_enabled" in audit_res.output

        # Step 2: Apply surgical remediation with --yes
        remediate_res = runner.invoke(app, [*standards_arg, "remediate", str(legacy_dir), "--yes"])
        assert remediate_res.exit_code == 0
        assert "Successfully committed surgical remediation" in remediate_res.output

        # Verify disk contents: surgical update with 100% comment preservation
        updated_content = legacy_file.read_text(encoding="utf-8")
        assert "# Legacy storage account for payment processing" in updated_content
        assert "// Security waiver ticket SEC-8899 expired last quarter" in updated_content
        assert "/* Custom configuration block */" in updated_content
        assert "public_network_access_enabled = false # Temporary waiver enabled" in updated_content
        assert "tags = {" in updated_content
        assert 'CostCenter = "CC-1001"' in updated_content
        assert 'Environment = "dev"' in updated_content
        assert 'resource "azurerm_private_endpoint" "pe_payment"' in updated_content

        # Step 3: Re-audit with --check: should pass cleanly with exit code 0
        recheck_res = runner.invoke(app, [*standards_arg, "remediate", str(legacy_dir), "--check"])
        assert recheck_res.exit_code == 0
        assert "100% compliant with corporate standards" in recheck_res.output
