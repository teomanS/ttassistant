"""Unit, integration, and CLI tests for the offline AzureRM provider schema catalog."""

import json
from pathlib import Path
import time
import pytest
from typer.testing import CliRunner

from ttassistant.adapters.catalog_adapter import JsonResourceCatalogAdapter
from ttassistant.cli import app
from ttassistant.domain.catalog import (
    TIER_1_RESOURCES,
    CatalogSummary,
    ResourceArgumentSchema,
    ResourceSchema,
    ResourceTier,
    is_tier_1,
    is_tier_1_resource,
)
from ttassistant.domain.exceptions import (
    CatalogError,
    InvalidCatalogError,
    MissingCatalogError,
    TTAssistantError,
)
from ttassistant.ports.catalog import ResourceCatalogPort

runner = CliRunner()


@pytest.fixture
def catalog_adapter() -> JsonResourceCatalogAdapter:
    """Fixture providing a freshly loaded JsonResourceCatalogAdapter."""
    return JsonResourceCatalogAdapter()


def test_catalog_implements_resource_catalog_port(catalog_adapter: JsonResourceCatalogAdapter):
    """Verify JsonResourceCatalogAdapter satisfies the ResourceCatalogPort Protocol."""
    assert isinstance(catalog_adapter, ResourceCatalogPort)


def test_query_tier_1_storage_account_schema(catalog_adapter: JsonResourceCatalogAdapter):
    """Verify querying azurerm_storage_account returns Tier 1 schema with required arguments."""
    schema = catalog_adapter.get_resource_schema("azurerm_storage_account")
    assert schema is not None
    assert schema.resource_type == "azurerm_storage_account"
    assert schema.tier == ResourceTier.TIER_1
    assert schema.is_tier_1 is True
    assert schema.is_tier_2 is False

    # Required arguments per matrix: name, resource_group_name, location, account_tier, account_replication_type
    required_names = schema.required_argument_names
    assert "name" in required_names
    assert "resource_group_name" in required_names
    assert "location" in required_names
    assert "account_tier" in required_names
    assert "account_replication_type" in required_names
    assert len(required_names) == 5

    # Check argument lookups
    name_arg = schema.get_argument("name")
    assert name_arg is not None
    assert name_arg.required is True
    assert name_arg.type == "string"
    assert name_arg.description != ""

    tier_arg = schema.get_argument("account_tier")
    assert tier_arg is not None
    assert tier_arg.default == "Standard"

    # Optional arguments check
    assert "min_tls_version" in schema.optional_argument_names
    assert "public_network_access_enabled" in schema.optional_argument_names

    # Dict-like and list-like properties on required_arguments
    assert "name" in schema.required_arguments
    assert schema.required_arguments["name"].type == "string"


def test_query_tier_2_cognitive_account_schema(catalog_adapter: JsonResourceCatalogAdapter):
    """Verify querying azurerm_cognitive_account returns Tier 2 schema with required arguments."""
    schema = catalog_adapter.get_resource_schema("azurerm_cognitive_account")
    assert schema is not None
    assert schema.resource_type == "azurerm_cognitive_account"
    assert schema.tier == ResourceTier.TIER_2
    assert schema.is_tier_1 is False
    assert schema.is_tier_2 is True

    required_names = schema.required_argument_names
    assert "name" in required_names
    assert "resource_group_name" in required_names
    assert "location" in required_names
    assert "kind" in required_names
    assert "sku_name" in required_names


def test_tier_1_classification_checks(catalog_adapter: JsonResourceCatalogAdapter):
    """Verify is_tier_1 correctly differentiates Tier 1 PaaS from Tier 2 long-tail."""
    # Key Vault is Tier 1
    assert catalog_adapter.is_tier_1("azurerm_key_vault") is True
    assert is_tier_1("azurerm_key_vault") is True
    assert is_tier_1_resource("azurerm_key_vault") is True

    # Log Analytics Workspace is Tier 2
    assert catalog_adapter.is_tier_1("azurerm_log_analytics_workspace") is False
    assert is_tier_1("azurerm_log_analytics_workspace") is False
    assert is_tier_1_resource("azurerm_log_analytics_workspace") is False

    # All 12 Tier 1 canonical resources
    expected_tier_1 = {
        "azurerm_storage_account",
        "azurerm_key_vault",
        "azurerm_mssql_server",
        "azurerm_cosmosdb_account",
        "azurerm_eventhub_namespace",
        "azurerm_postgresql_flexible_server",
        "azurerm_mysql_flexible_server",
        "azurerm_redis_cache",
        "azurerm_linux_web_app",
        "azurerm_virtual_network",
        "azurerm_subnet",
        "azurerm_resource_group",
    }
    assert TIER_1_RESOURCES == expected_tier_1
    for res in expected_tier_1:
        assert catalog_adapter.is_tier_1(res) is True, f"{res} should be Tier 1"

    # Tier 2 checks
    assert catalog_adapter.is_tier_2("azurerm_cognitive_account") is True
    assert catalog_adapter.is_tier_2("azurerm_key_vault") is False
    assert catalog_adapter.is_tier_2("azurerm_nonexistent_service") is False
    assert catalog_adapter.is_tier_2("") is False

    # Bool equality guard check
    assert ResourceTier.TIER_1 != True
    assert ResourceTier.TIER_2 != False
    assert ResourceTier.TIER_1 != False
    assert ResourceTier.TIER_2 != True


def test_query_unknown_resource(catalog_adapter: JsonResourceCatalogAdapter):
    """Verify querying unknown resource returns None and is_known_resource returns False without exceptions."""
    schema = catalog_adapter.get_resource_schema("azurerm_nonexistent_service")
    assert schema is None

    assert catalog_adapter.is_known_resource("azurerm_nonexistent_service") is False
    assert catalog_adapter.is_known_resource("") is False
    assert catalog_adapter.get_resource_schema("") is None


def test_list_resources_filtering(catalog_adapter: JsonResourceCatalogAdapter):
    """Verify list_resources supports filter_prefix and tier filtering."""
    # Prefix filtering
    mssql_resources = catalog_adapter.list_resources(filter_prefix="azurerm_mssql")
    assert "azurerm_mssql_server" in mssql_resources
    assert "azurerm_mssql_database" in mssql_resources
    for r in mssql_resources:
        assert r.startswith("azurerm_mssql")

    # Non-existent prefix returns empty list
    assert catalog_adapter.list_resources(filter_prefix="azurerm_nonexistent") == []

    # Tier 1 filtering
    tier_1_list = catalog_adapter.list_resources(tier=ResourceTier.TIER_1)
    assert len(tier_1_list) == 12
    for r in tier_1_list:
        assert catalog_adapter.is_tier_1(r) is True

    # Tier filtering via integer and string values
    assert catalog_adapter.list_resources(tier=1) == tier_1_list
    assert catalog_adapter.list_resources(tier="1") == tier_1_list
    assert catalog_adapter.list_resources(tier="tier_1") == tier_1_list

    # Invalid tier filtering returns empty list
    assert catalog_adapter.list_resources(tier="invalid") == []
    assert catalog_adapter.list_resources(tier=999) == []

    # Tier 2 filtering
    tier_2_list = catalog_adapter.list_resources(tier=ResourceTier.TIER_2)
    assert len(tier_2_list) > 0
    assert "azurerm_cognitive_account" in tier_2_list
    assert "azurerm_log_analytics_workspace" in tier_2_list
    assert "azurerm_storage_account" not in tier_2_list


def test_search_resources(catalog_adapter: JsonResourceCatalogAdapter):
    """Verify substring and description search."""
    results = catalog_adapter.search("storage")
    assert "azurerm_storage_account" in results

    results = catalog_adapter.search("redis")
    assert "azurerm_redis_cache" in results

    results = catalog_adapter.search("")
    assert len(results) == len(catalog_adapter.list_resources())


def test_catalog_summary(catalog_adapter: JsonResourceCatalogAdapter):
    """Verify get_summary returns accurate metadata and counts."""
    summary = catalog_adapter.get_summary()
    assert isinstance(summary, CatalogSummary)
    assert summary.total_resources >= 30
    assert summary.tier_1_count == 12
    assert summary.tier_2_count == summary.total_resources - 12
    assert summary.provider_version == "3.116.0"
    assert len(summary.resource_types) == summary.total_resources


def test_missing_catalog_file_raises_catalog_error(tmp_path: Path):
    """Verify non-existent catalog file raises MissingCatalogError inheriting CatalogError and TTAssistantError."""
    missing_file = tmp_path / "does_not_exist.json"
    with pytest.raises(MissingCatalogError) as exc_info:
        JsonResourceCatalogAdapter(catalog_path=missing_file)

    err = exc_info.value
    assert isinstance(err, CatalogError)
    assert isinstance(err, TTAssistantError)
    assert "not found" in err.message.lower()
    assert err.details is not None


def test_corrupt_catalog_file_raises_catalog_error(tmp_path: Path):
    """Verify corrupt catalog JSON raises InvalidCatalogError inheriting CatalogError."""
    corrupt_file = tmp_path / "corrupt_schema.json"
    corrupt_file.write_text("{ this is not valid JSON :(", encoding="utf-8")

    with pytest.raises(InvalidCatalogError) as exc_info:
        JsonResourceCatalogAdapter(catalog_path=corrupt_file)

    err = exc_info.value
    assert isinstance(err, CatalogError)
    assert isinstance(err, TTAssistantError)
    assert "corrupt or malformed" in err.message.lower()


def test_invalid_catalog_structure_raises_catalog_error(tmp_path: Path):
    """Verify JSON without 'resources' key raises InvalidCatalogError."""
    invalid_file = tmp_path / "invalid_schema.json"
    invalid_file.write_text(json.dumps({"provider": "azurerm"}), encoding="utf-8")

    with pytest.raises(InvalidCatalogError) as exc_info:
        JsonResourceCatalogAdapter(catalog_path=invalid_file)

    err = exc_info.value
    assert "invalid catalog structure" in err.message.lower()

    # Null or non-dict arguments in resource
    null_args_file = tmp_path / "null_args.json"
    null_args_file.write_text(
        json.dumps({"resources": {"azurerm_test": {"description": "test", "arguments": None}}}),
        encoding="utf-8",
    )
    with pytest.raises(InvalidCatalogError) as exc_info2:
        JsonResourceCatalogAdapter(catalog_path=null_args_file)
    assert "arguments" in exc_info2.value.message.lower()


def test_schema_argument_validation():
    """Verify ResourceSchema.validate_arguments detects missing required arguments."""
    adapter = JsonResourceCatalogAdapter()
    schema = adapter.get_resource_schema("azurerm_storage_account")
    assert schema is not None

    # Valid arguments provided
    valid_args = {
        "name": "sttestappprod01",
        "resource_group_name": "rg-core-prod",
        "location": "westeurope",
        "account_tier": "Standard",
        "account_replication_type": "LRS",
    }
    is_valid, missing = schema.validate_arguments(valid_args)
    assert is_valid is True
    assert missing == []

    # Missing arguments
    incomplete_args = {
        "name": "sttestappprod01",
        "location": "westeurope",
    }
    is_valid, missing = schema.validate_arguments(incomplete_args)
    assert is_valid is False
    assert "resource_group_name" in missing
    assert "account_tier" in missing
    assert "account_replication_type" in missing

    # None arguments check
    is_valid_none, missing_none = schema.validate_arguments(None)
    assert is_valid_none is False
    assert set(missing_none) == set(schema.required_argument_names)


def test_catalog_load_latency_under_50ms():
    """Verify catalog loading completes well under the 50ms requirement."""
    start = time.perf_counter()
    adapter = JsonResourceCatalogAdapter()
    duration = time.perf_counter() - start

    assert duration < 0.050, f"Catalog load took {duration*1000:.2f}ms (must be < 50ms)"


def test_cli_catalog_list_tier_1():
    """Verify 'ttassistant catalog list --tier 1' exits 0 and lists Tier 1 resources."""
    result = runner.invoke(app, ["catalog", "list", "--tier", "1"])
    assert result.exit_code == 0
    assert "azurerm_storage_account" in result.output
    assert "azurerm_key_vault" in result.output
    assert "Tier 1 (Guided PaaS)" in result.output
    assert "Listed 12 resources" in result.output


def test_cli_catalog_list_prefix_filter():
    """Verify 'ttassistant catalog list --prefix azurerm_mssql' filters correctly."""
    result = runner.invoke(app, ["catalog", "list", "--prefix", "azurerm_mssql"])
    assert result.exit_code == 0
    assert "azurerm_mssql_server" in result.output
    assert "azurerm_mssql_database" in result.output
    assert "azurerm_storage_account" not in result.output


def test_cli_catalog_list_no_matches():
    """Verify CLI catalog list with non-matching criteria outputs guidance and exits 0."""
    result = runner.invoke(app, ["catalog", "list", "--prefix", "azurerm_nonexistent_xyz"])
    assert result.exit_code == 0
    assert "No resources found" in result.output


def test_cli_catalog_info_tier_1_storage():
    """Verify 'ttassistant catalog info azurerm_storage_account' renders Rich arguments table."""
    result = runner.invoke(app, ["catalog", "info", "azurerm_storage_account"])
    assert result.exit_code == 0
    assert "azurerm_storage_account" in result.output
    assert "Tier 1 (Guided PaaS & Foundation)" in result.output
    assert "account_replication_type" in result.output
    assert "account_tier" in result.output
    assert "resource_group_name" in result.output
    assert "5 required" in result.output


def test_cli_catalog_info_tier_2_cognitive():
    """Verify 'ttassistant catalog info azurerm_cognitive_account' renders Tier 2 details."""
    result = runner.invoke(app, ["catalog", "info", "azurerm_cognitive_account"])
    assert result.exit_code == 0
    assert "azurerm_cognitive_account" in result.output
    assert "Tier 2 (Universal Long-Tail)" in result.output
    assert "kind" in result.output
    assert "sku_name" in result.output


def test_cli_catalog_info_unknown_resource():
    """Verify 'ttassistant catalog info azurerm_nonexistent_service' exits with code 1."""
    result = runner.invoke(app, ["catalog", "info", "azurerm_nonexistent_service"])
    assert result.exit_code == 1
    assert "not found in offline catalog" in result.output


def test_cli_catalog_without_common_standards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Verify CLI catalog commands execute with exit code 0 in a workspace without common_standards/."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["catalog", "list", "--tier", "1"])
    assert result.exit_code == 0
    assert "azurerm_storage_account" in result.output

    result_info = runner.invoke(app, ["catalog", "info", "azurerm_storage_account"])
    assert result_info.exit_code == 0
    assert "Tier 1 (Guided PaaS & Foundation)" in result_info.output
