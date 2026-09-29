"""Unit, edge-case, and SLA benchmark tests for the air-gapped deterministic tweak engine (Story 4.1)."""

import socket
import time
from typing import Any
import pytest
import hcl2

from ttassistant.adapters.catalog_adapter import JsonResourceCatalogAdapter
from ttassistant.adapters.tweak_adapter import DeterministicTweakParserAdapter
from ttassistant.application.tweak_handler import TweakHandler
from ttassistant.domain.exceptions import TweakParseError
from ttassistant.domain.models import ProvisioningParameters, StagedFile, StagedWorkspace
from ttassistant.domain.tweak import (
    mutate_hcl_attribute,
    mutate_hcl_tag,
    normalize_attribute_value,
    resolve_attribute_alias,
)
from ttassistant.ports.tweak_parser import TweakAction


STORAGE_HCL = """# Infrastructure configuration
resource "azurerm_storage_account" "sa" {
  name                     = "stmyworkloaddev"
  resource_group_name      = "rg-myworkload-dev"
  location                 = "westeurope"
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_0"

  # Enterprise mandatory compliance tags
  tags = {
    Environment = "dev"
    ManagedBy   = "ttassistant"
  }
}
"""

MSSQL_HCL = """resource "azurerm_mssql_server" "sql" {
  name                         = "sql-myworkload-dev"
  resource_group_name          = "rg-myworkload-dev"
  location                     = "westeurope"
  version                      = "12.0"
  administrator_login          = "sqladmin"
  administrator_login_password = "ChangeMe123!"
  minimum_tls_version          = "1.0"
  public_network_access_enabled = true

  tags = {
    Environment = "dev"
  }
}
"""

ACR_HCL = """resource "azurerm_container_registry" "acr" {
  name                = "carmyworkloaddev"
  resource_group_name = "rg-myworkload-dev"
  location            = "westeurope"
  sku                 = "Basic"
  admin_enabled       = false

  tags = {
    Environment = "dev"
  }
}
"""


def _create_workspace(hcl_content: str, resource_type: str = "azurerm_storage_account") -> StagedWorkspace:
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type=resource_type,
        workload_name="myworkload",
        environment="dev",
        resource_name="myres",
        tags={"Environment": "dev", "ManagedBy": "ttassistant"},
        public_network_access=False,
    )
    ws = StagedWorkspace(
        target_dir=f"{resource_type}/sub-prod/",
        parameters=params,
    )
    ws.add_file(
        StagedFile(
            path="main.tf",
            content=hcl_content,
            is_new=True,
            metadata={"resource_type": resource_type},
        )
    )
    return ws


class TestAttributeAliasResolution:
    """Test resolution of colloquial terms into AzureRM attributes."""

    def test_resolve_tls_aliases(self) -> None:
        assert resolve_attribute_alias("tls", "azurerm_storage_account") == "min_tls_version"
        assert resolve_attribute_alias("minimum TLS version", "azurerm_storage_account") == "min_tls_version"
        assert resolve_attribute_alias("min_tls_version", "azurerm_storage_account") == "min_tls_version"
        assert resolve_attribute_alias("tls", "azurerm_mssql_server") == "minimum_tls_version"
        assert resolve_attribute_alias("minimum TLS version", "azurerm_mssql_server") == "minimum_tls_version"

    def test_resolve_replication_aliases(self) -> None:
        assert resolve_attribute_alias("replication") == "account_replication_type"
        assert resolve_attribute_alias("account replication type") == "account_replication_type"
        assert resolve_attribute_alias("repl") == "account_replication_type"

    def test_resolve_tier_and_sku_aliases(self) -> None:
        assert resolve_attribute_alias("tier") == "account_tier"
        assert resolve_attribute_alias("account tier") == "account_tier"
        assert resolve_attribute_alias("sku", "azurerm_container_registry") == "sku"
        assert resolve_attribute_alias("sku", "azurerm_key_vault") == "sku_name"

    def test_resolve_public_access_aliases(self) -> None:
        assert resolve_attribute_alias("public access") == "public_network_access_enabled"
        assert resolve_attribute_alias("public network access") == "public_network_access_enabled"

    def test_unresolvable_term_raises(self) -> None:
        with pytest.raises(TweakParseError):
            resolve_attribute_alias("??? bad term !!!")


class TestValueNormalization:
    """Test value normalization across different types and resource conventions."""

    def test_normalize_tls_storage(self) -> None:
        assert normalize_attribute_value("min_tls_version", "1.2", "azurerm_storage_account") == "TLS1_2"
        assert normalize_attribute_value("min_tls_version", "TLS1_2", "azurerm_storage_account") == "TLS1_2"
        assert normalize_attribute_value("min_tls_version", "1.0", "azurerm_storage_account") == "TLS1_0"

    def test_normalize_tls_mssql(self) -> None:
        assert normalize_attribute_value("minimum_tls_version", "1.2", "azurerm_mssql_server") == "1.2"
        assert normalize_attribute_value("minimum_tls_version", "TLS1_2", "azurerm_mssql_server") == "1.2"

    def test_normalize_replication(self) -> None:
        assert normalize_attribute_value("account_replication_type", "grs") == "GRS"
        assert normalize_attribute_value("account_replication_type", "LRS") == "LRS"
        assert normalize_attribute_value("account_replication_type", "ragrs") == "RAGRS"

    def test_normalize_booleans(self) -> None:
        assert normalize_attribute_value("public_network_access_enabled", "false") is False
        assert normalize_attribute_value("public_network_access_enabled", "true") is True
        assert normalize_attribute_value("public_network_access_enabled", "disable") is False
        assert normalize_attribute_value("public_network_access_enabled", "enable") is True


class TestDeterministicTweakParserAdapter:
    """Test the parser adapter across colloquial and structured phrases."""

    @pytest.fixture
    def parser(self) -> DeterministicTweakParserAdapter:
        catalog = JsonResourceCatalogAdapter()
        return DeterministicTweakParserAdapter(catalog=catalog)

    def test_parse_tls_tweak(self, parser: DeterministicTweakParserAdapter) -> None:
        parsed = parser.parse("Set minimum TLS version to 1.2", "azurerm_storage_account")
        assert parsed.action == TweakAction.SET_ATTRIBUTE
        assert parsed.attribute_name == "min_tls_version"
        assert parsed.value == "TLS1_2"

    def test_parse_replication_tweak(self, parser: DeterministicTweakParserAdapter) -> None:
        parsed = parser.parse("Change replication to GRS", "azurerm_storage_account")
        assert parsed.action == TweakAction.SET_ATTRIBUTE
        assert parsed.attribute_name == "account_replication_type"
        assert parsed.value == "GRS"

    def test_parse_tier_tweak(self, parser: DeterministicTweakParserAdapter) -> None:
        parsed = parser.parse("Set tier to Premium", "azurerm_storage_account")
        assert parsed.action == TweakAction.SET_ATTRIBUTE
        assert parsed.attribute_name == "account_tier"
        assert parsed.value == "Premium"

    def test_parse_sku_tweak_acr(self, parser: DeterministicTweakParserAdapter) -> None:
        parsed = parser.parse("Change sku to Standard", "azurerm_container_registry")
        assert parsed.action == TweakAction.SET_ATTRIBUTE
        assert parsed.attribute_name == "sku"
        assert parsed.value == "Standard"

    def test_parse_tag_addition(self, parser: DeterministicTweakParserAdapter) -> None:
        parsed = parser.parse("Add tag team=core")
        assert parsed.action == TweakAction.SET_TAG
        assert parsed.attribute_name == "team"
        assert parsed.value == "core"

    def test_parse_tag_removal(self, parser: DeterministicTweakParserAdapter) -> None:
        parsed = parser.parse("Remove tag ManagedBy")
        assert parsed.action == TweakAction.REMOVE_TAG
        assert parsed.attribute_name == "ManagedBy"
        assert parsed.value is None

    def test_parse_toggle_public_access(self, parser: DeterministicTweakParserAdapter) -> None:
        parsed_deny = parser.parse("Disable public network access")
        assert parsed_deny.action == TweakAction.TOGGLE_BOOLEAN
        assert parsed_deny.attribute_name == "public_network_access_enabled"
        assert parsed_deny.value is False

        parsed_allow = parser.parse("Enable public access")
        assert parsed_allow.action == TweakAction.TOGGLE_BOOLEAN
        assert parsed_allow.attribute_name == "public_network_access_enabled"
        assert parsed_allow.value is True

    def test_parse_direct_assignment(self, parser: DeterministicTweakParserAdapter) -> None:
        parsed = parser.parse('account_replication_type = "ZRS"', "azurerm_storage_account")
        assert parsed.attribute_name == "account_replication_type"
        assert parsed.value == "ZRS"

    def test_parse_invalid_instruction_raises(self, parser: DeterministicTweakParserAdapter) -> None:
        with pytest.raises(TweakParseError):
            parser.parse("Make it faster please", "azurerm_storage_account")

    def test_parse_unknown_attribute_with_catalog_raises(self, parser: DeterministicTweakParserAdapter) -> None:
        with pytest.raises(TweakParseError) as exc_info:
            parser.parse("Set invalid_attr to foo", "azurerm_storage_account")
        assert "not a valid argument" in str(exc_info.value)


class TestTweakHandlerApplication:
    """Test full in-memory workspace mutation via TweakHandler."""

    @pytest.fixture
    def handler(self) -> TweakHandler:
        catalog = JsonResourceCatalogAdapter()
        parser = DeterministicTweakParserAdapter(catalog=catalog)
        return TweakHandler(parser=parser, catalog=catalog)

    def test_apply_replication_tweak_storage(self, handler: TweakHandler) -> None:
        ws = _create_workspace(STORAGE_HCL, "azurerm_storage_account")
        res = handler.apply_tweak(ws, "Change replication to GRS")

        assert res.success is True
        assert res.elapsed_ms <= 10.0
        content = ws["main.tf"].content
        assert 'account_replication_type = "GRS"' in content
        assert "# Infrastructure configuration" in content  # comment preserved
        assert "# Enterprise mandatory compliance tags" in content  # comment preserved

        # HCL AST syntax check
        parsed = hcl2.loads(content)
        assert parsed is not None

    def test_apply_tls_tweak_storage(self, handler: TweakHandler) -> None:
        ws = _create_workspace(STORAGE_HCL, "azurerm_storage_account")
        res = handler.apply_tweak(ws, "Set minimum TLS version to 1.2")

        assert res.success is True
        assert res.elapsed_ms <= 10.0
        content = ws["main.tf"].content
        assert 'min_tls_version          = "TLS1_2"' in content or 'min_tls_version = "TLS1_2"' in content

        parsed = hcl2.loads(content)
        assert parsed is not None

    def test_apply_tls_tweak_mssql(self, handler: TweakHandler) -> None:
        ws = _create_workspace(MSSQL_HCL, "azurerm_mssql_server")
        res = handler.apply_tweak(ws, "Change TLS to 1.2")

        assert res.success is True
        assert res.elapsed_ms <= 10.0
        content = ws["main.tf"].content
        assert 'minimum_tls_version          = "1.2"' in content or 'minimum_tls_version = "1.2"' in content

        parsed = hcl2.loads(content)
        assert parsed is not None

    def test_apply_add_tag(self, handler: TweakHandler) -> None:
        ws = _create_workspace(STORAGE_HCL, "azurerm_storage_account")
        res = handler.apply_tweak(ws, "Add tag team=core")

        assert res.success is True
        content = ws["main.tf"].content
        assert 'team = "core"' in content or '"team" = "core"' in content
        assert ws.parameters.tags.get("team") == "core"

        parsed = hcl2.loads(content)
        assert parsed is not None

    def test_apply_update_tag(self, handler: TweakHandler) -> None:
        ws = _create_workspace(STORAGE_HCL, "azurerm_storage_account")
        res = handler.apply_tweak(ws, "Set tag Environment=staging")

        assert res.success is True
        content = ws["main.tf"].content
        assert 'Environment = "staging"' in content
        assert ws.parameters.tags.get("Environment") == "staging"

        parsed = hcl2.loads(content)
        assert parsed is not None

    def test_apply_remove_tag(self, handler: TweakHandler) -> None:
        ws = _create_workspace(STORAGE_HCL, "azurerm_storage_account")
        res = handler.apply_tweak(ws, "Remove tag ManagedBy")

        assert res.success is True
        content = ws["main.tf"].content
        assert "ManagedBy" not in content
        assert "ManagedBy" not in ws.parameters.tags

        parsed = hcl2.loads(content)
        assert parsed is not None

    def test_apply_disable_public_access(self, handler: TweakHandler) -> None:
        ws = _create_workspace(MSSQL_HCL, "azurerm_mssql_server")
        ws.parameters.public_network_access = True

        res = handler.apply_tweak(ws, "Disable public network access")

        assert res.success is True
        content = ws["main.tf"].content
        assert "public_network_access_enabled = false" in content
        assert ws.parameters.public_network_access is False

        parsed = hcl2.loads(content)
        assert parsed is not None

    def test_apply_missing_attribute_insertion(self, handler: TweakHandler) -> None:
        """When an attribute is not yet in HCL, it should be inserted cleanly before tags."""
        base_hcl = """resource "azurerm_storage_account" "sa" {
  name                = "stmyworkloaddev"
  resource_group_name = "rg-dev"
  location            = "westeurope"
  account_tier        = "Standard"

  tags = {
    Environment = "dev"
  }
}
"""
        ws = _create_workspace(base_hcl, "azurerm_storage_account")
        res = handler.apply_tweak(ws, "Set replication to GRS")

        assert res.success is True
        content = ws["main.tf"].content
        assert 'account_replication_type = "GRS"' in content
        parsed = hcl2.loads(content)
        assert parsed is not None

    def test_apply_invalid_tweak_returns_failure(self, handler: TweakHandler) -> None:
        ws = _create_workspace(STORAGE_HCL, "azurerm_storage_account")
        res = handler.apply_tweak(ws, "Invalid gibberish instruction")

        assert res.success is False
        assert res.error_message is not None
        assert ws["main.tf"].content == STORAGE_HCL  # workspace untouched


class TestAirGappedLatencyBenchmark:
    """Benchmark tests to verify <=10ms latency and zero network access (NFR-4, NFR-5)."""

    def test_100_consecutive_tweaks_latency_sla(self) -> None:
        catalog = JsonResourceCatalogAdapter()
        parser = DeterministicTweakParserAdapter(catalog=catalog)
        handler = TweakHandler(parser=parser, catalog=catalog)
        ws = _create_workspace(STORAGE_HCL, "azurerm_storage_account")

        instructions = [
            "Change replication to GRS",
            "Set minimum TLS version to 1.2",
            "Set tier to Premium",
            "Add tag team=core",
            "Set tag Environment=staging",
            "account_replication_type = LRS",
            "min_tls_version = TLS1_2",
            "Disable public network access",
            "Enable public access",
            "Remove tag ManagedBy",
        ]

        timings: list[float] = []

        for i in range(100):
            instruction = instructions[i % len(instructions)]
            res = handler.apply_tweak(ws, instruction)
            assert res.success is True
            timings.append(res.elapsed_ms)
            # Strict NFR-4 SLA: each individual tweak must execute in <= 10.0 milliseconds
            assert res.elapsed_ms <= 10.0, f"Tweak #{i} '{instruction}' took {res.elapsed_ms:.2f}ms (>10ms)"

        avg_ms = sum(timings) / len(timings)
        max_ms = max(timings)
        assert avg_ms < 2.0, f"Average execution time {avg_ms:.3f}ms exceeded 2ms target"
        print(f"\n100 tweaks completed: avg={avg_ms:.3f}ms, max={max_ms:.3f}ms")

    def test_zero_network_calls_during_tweak(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify that tweak execution makes zero socket/network calls (air-gapped operation)."""
        def forbid_socket(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("Network call attempted during air-gapped tweak execution!")

        monkeypatch.setattr(socket, "socket", forbid_socket)

        catalog = JsonResourceCatalogAdapter()
        parser = DeterministicTweakParserAdapter(catalog=catalog)
        handler = TweakHandler(parser=parser, catalog=catalog)
        ws = _create_workspace(STORAGE_HCL, "azurerm_storage_account")

        # Must execute cleanly without triggering socket.socket
        res1 = handler.apply_tweak(ws, "Set minimum TLS version to 1.2")
        assert res1.success is True

        res2 = handler.apply_tweak(ws, "Change replication to GRS")
        assert res2.success is True

        res3 = handler.apply_tweak(ws, "Add tag env=prod")
        assert res3.success is True
