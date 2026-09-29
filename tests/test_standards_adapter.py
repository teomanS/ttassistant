"""Unit tests for MarkdownStandardsAdapter."""

import time
from pathlib import Path
import pytest

from ttassistant.adapters.standards_adapter import MarkdownStandardsAdapter
from ttassistant.domain.exceptions import (
    InvalidStandardsError,
    MissingStandardsError,
)
from ttassistant.ports.standards_source import StandardsSourcePort


@pytest.fixture
def adapter():
    return MarkdownStandardsAdapter()


@pytest.fixture
def canonical_standards_dir():
    root = Path(__file__).resolve().parent.parent
    return root / "common_standards"


def test_adapter_implements_protocol(adapter):
    """Verify MarkdownStandardsAdapter satisfies StandardsSourcePort protocol."""
    assert isinstance(adapter, StandardsSourcePort)


def test_load_canonical_standards_success(adapter, canonical_standards_dir):
    """Verify canonical repository standards load cleanly into a StandardsBundle."""
    bundle = adapter.load_standards(canonical_standards_dir)

    # Naming rules
    assert "azurerm_resource_group" in bundle.naming_rules
    assert "azurerm_storage_account" in bundle.naming_rules
    assert bundle.naming_rules["azurerm_resource_group"].max_length == 90
    assert bundle.naming_rules["azurerm_storage_account"].max_length == 24

    # Tag rules
    assert "Environment" in bundle.tag_rules
    assert bundle.tag_rules["Environment"].required is True
    assert "dev" in bundle.tag_rules["Environment"].allowed_values

    # Backend rules
    assert len(bundle.backend_rules) >= 4
    core_net = bundle.get_backend_rule("core-networking")
    assert core_net is not None
    assert core_net.storage_account_name == "sttfstatenetworking"

    # Networking rules
    assert "azurerm_storage_account" in bundle.networking_rules
    assert (
        bundle.networking_rules["azurerm_storage_account"].private_dns_zone_name
        == "privatelink.blob.core.windows.net"
    )
    assert "*snet-paas*" in bundle.networking_rules["azurerm_storage_account"].subnet_patterns
    assert "*private*" in bundle.networking_rules["azurerm_storage_account"].subnet_patterns

    # Metadata
    assert "naming_conventions" in bundle.metadata
    assert bundle.metadata["naming_conventions"].get("version") == "1.0.0"


def test_load_standards_performance_budget(adapter, canonical_standards_dir):
    """Verify standards engine parsing overhead is <= 200ms."""
    start = time.perf_counter()
    bundle = adapter.load_standards(canonical_standards_dir)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert bundle is not None
    assert elapsed_ms <= 200.0, f"Standards parsing took {elapsed_ms:.2f}ms (budget <= 200ms)"


def test_missing_standards_directory(adapter, tmp_path):
    """Verify missing standards directory raises MissingStandardsError."""
    non_existent = tmp_path / "does_not_exist"
    with pytest.raises(MissingStandardsError) as exc_info:
        adapter.load_standards(non_existent)
    assert "Standards directory not found" in exc_info.value.message


def test_standards_path_is_file_not_dir(adapter, tmp_path):
    """Verify pointing to a file instead of directory raises MissingStandardsError."""
    test_file = tmp_path / "some_file.txt"
    test_file.write_text("not a dir")
    with pytest.raises(MissingStandardsError) as exc_info:
        adapter.load_standards(test_file)
    assert "Standards path is not a directory" in exc_info.value.message


def test_empty_standards_directory(adapter, tmp_path):
    """Verify empty standards directory raises MissingStandardsError."""
    empty_dir = tmp_path / "empty_standards"
    empty_dir.mkdir()
    with pytest.raises(MissingStandardsError) as exc_info:
        adapter.load_standards(empty_dir)
    assert "is empty" in exc_info.value.message


def test_missing_required_standards_file(adapter, tmp_path):
    """Verify missing required files raises MissingStandardsError."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text("# Naming")
    # Missing tagging_baseline.md and backend_mapping.md

    with pytest.raises(MissingStandardsError) as exc_info:
        adapter.load_standards(standards_dir)
    assert "Missing required standard file" in exc_info.value.message


def test_unclosed_frontmatter_raises_invalid_standards(adapter, tmp_path):
    """Verify unclosed frontmatter raises InvalidStandardsError."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text("---\ntitle: unclosed\n# Missing close delimiter")
    (standards_dir / "tagging_baseline.md").write_text("# Tags")
    (standards_dir / "backend_mapping.md").write_text("# Backend")

    with pytest.raises(InvalidStandardsError) as exc_info:
        adapter.load_standards(standards_dir)
    assert "unclosed '---' delimiter" in exc_info.value.message


def test_malformed_yaml_frontmatter_raises_invalid_standards(adapter, tmp_path):
    """Verify invalid YAML syntax in frontmatter raises InvalidStandardsError."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text("---\ntitle: [unclosed list\n---\n# Content")
    (standards_dir / "tagging_baseline.md").write_text("# Tags")
    (standards_dir / "backend_mapping.md").write_text("# Backend")

    with pytest.raises(InvalidStandardsError) as exc_info:
        adapter.load_standards(standards_dir)
    assert "Malformed YAML frontmatter" in exc_info.value.message


def test_frontmatter_not_mapping_raises_invalid_standards(adapter, tmp_path):
    """Verify frontmatter that is a string/scalar raises InvalidStandardsError."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text("---\njust a string\n---\n# Content")
    (standards_dir / "tagging_baseline.md").write_text("# Tags")
    (standards_dir / "backend_mapping.md").write_text("# Backend")

    with pytest.raises(InvalidStandardsError) as exc_info:
        adapter.load_standards(standards_dir)
    assert "expected mapping" in exc_info.value.message


def test_naming_conventions_missing_headers(adapter, tmp_path):
    """Verify table with missing required headers raises InvalidStandardsError."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text(
        "| Resource Type | Description |\n|---|---|\n| azurerm_resource_group | Resource Group |\n"
    )
    (standards_dir / "tagging_baseline.md").write_text("# Tags")
    (standards_dir / "backend_mapping.md").write_text("# Backend")

    with pytest.raises(InvalidStandardsError) as exc_info:
        adapter.load_standards(standards_dir)
    assert "missing required headers" in exc_info.value.message


def test_naming_conventions_invalid_max_length_integer(adapter, tmp_path):
    """Verify non-integer Max Length raises InvalidStandardsError."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n"
        "|---|---|---|---|\n"
        "| azurerm_resource_group | ^rg-[a-z]+$ | Lowercase | ninety |\n"
    )
    (standards_dir / "tagging_baseline.md").write_text("# Tags")
    (standards_dir / "backend_mapping.md").write_text("# Backend")

    with pytest.raises(InvalidStandardsError) as exc_info:
        adapter.load_standards(standards_dir)
    assert "invalid integer for 'Max Length'" in exc_info.value.message


def test_naming_conventions_invalid_regex_pattern(adapter, tmp_path):
    """Verify invalid regex pattern raises InvalidStandardsError."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n"
        "|---|---|---|---|\n"
        "| azurerm_resource_group | ^rg-[a-z0-9-(unclosed$ | Lowercase | 90 |\n"
    )
    (standards_dir / "tagging_baseline.md").write_text("# Tags")
    (standards_dir / "backend_mapping.md").write_text("# Backend")

    with pytest.raises(InvalidStandardsError) as exc_info:
        adapter.load_standards(standards_dir)
    assert "Pydantic schema validation error" in exc_info.value.message


def test_corrupted_table_columns_raises_invalid_standards(adapter, tmp_path):
    """Verify broken row columns in markdown table raises InvalidStandardsError."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n"
        "|---|---|---|---|\n"
        "| azurerm_resource_group | ^rg-[a-z]+$ | Lowercase | 90 |\n"
        "| azurerm_storage_account | ^st[a-z]+$ |\n"  # missing pipes/columns
    )
    (standards_dir / "tagging_baseline.md").write_text("# Tags")
    (standards_dir / "backend_mapping.md").write_text("# Backend")

    with pytest.raises(InvalidStandardsError) as exc_info:
        adapter.load_standards(standards_dir)
    assert "corrupted column count" in exc_info.value.message or "column count mismatch" in exc_info.value.message


def test_tagging_baseline_bullet_list_parsing(adapter, tmp_path):
    """Verify tagging_baseline.md can be parsed from bullet lists if no table is present."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n"
        "|---|---|---|---|\n"
        "| azurerm_resource_group | ^rg-[a-z]+$ | Lowercase | 90 |\n"
    )
    (standards_dir / "tagging_baseline.md").write_text(
        "# Tag Baseline\n\n"
        "- `Environment` (Required): Allowed values: dev, test, prod. Default: dev. Target environment.\n"
        "- `Owner` (Required): Default: platform-team. Responsible owner.\n"
        "- `CostCenter` (Optional): Default: CC-001.\n"
    )
    (standards_dir / "backend_mapping.md").write_text(
        "| Subscription | Storage Account | Container | Key Pattern |\n"
        "|---|---|---|---|\n"
        "| workload-dev | sttfstatedev | tfstate | dev/{resource_type}.tfstate |\n"
    )

    bundle = adapter.load_standards(standards_dir)
    assert "Environment" in bundle.tag_rules
    assert bundle.tag_rules["Environment"].required is True
    assert bundle.tag_rules["Environment"].allowed_values == ["dev", "test", "prod"]
    assert bundle.tag_rules["Environment"].default_value == "dev"
    assert "Owner" in bundle.tag_rules
    assert "CostCenter" in bundle.tag_rules
    assert bundle.tag_rules["CostCenter"].required is False


def test_malformed_networking_policy_missing_headers(adapter, tmp_path):
    """Verify networking_policy.md missing Resource Type header raises InvalidStandardsError."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n"
        "|---|---|---|---|\n"
        "| azurerm_resource_group | ^rg-[a-z]+$ | Lowercase | 90 |\n"
    )
    (standards_dir / "tagging_baseline.md").write_text(
        "| Tag Key | Required |\n|---|---|\n| Env | Yes |\n"
    )
    (standards_dir / "backend_mapping.md").write_text(
        "| Subscription | Storage Account |\n|---|---|\n| dev | stdev |\n"
    )
    (standards_dir / "networking_policy.md").write_text(
        "| Invalid Col | Private DNS Zone ID |\n|---|---|\n| storage | /sub/hub |\n"
    )

    with pytest.raises(InvalidStandardsError) as exc_info:
        adapter.load_standards(standards_dir)
    assert "missing required 'Resource Type' header" in exc_info.value.message


def test_malformed_networking_policy_column_mismatch(adapter, tmp_path):
    """Verify networking_policy.md with column count mismatch raises InvalidStandardsError."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n"
        "|---|---|---|---|\n"
        "| azurerm_resource_group | ^rg-[a-z]+$ | Lowercase | 90 |\n"
    )
    (standards_dir / "tagging_baseline.md").write_text(
        "| Tag Key | Required |\n|---|---|\n| Env | Yes |\n"
    )
    (standards_dir / "backend_mapping.md").write_text(
        "| Subscription | Storage Account |\n|---|---|\n| dev | stdev |\n"
    )
    (standards_dir / "networking_policy.md").write_text(
        "| Resource Type | Private DNS Zone ID |\n"
        "|---|---|\n"
        "| azurerm_storage_account | /sub/hub | extra_col |\n"
    )

    with pytest.raises(InvalidStandardsError) as exc_info:
        adapter.load_standards(standards_dir)
    assert "column count mismatch" in exc_info.value.message or "corrupted column count" in exc_info.value.message


def test_standards_utf8_bom_handling(adapter, tmp_path):
    """Verify standards files starting with UTF-8 BOM are stripped and parsed correctly."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_bytes(
        "\ufeff---\ntitle: BOM Test\n---\n\n| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n|---|---|---|---|\n| azurerm_resource_group | ^rg-[a-z]+$ | Lowercase | 90 |\n".encode("utf-8")
    )
    (standards_dir / "tagging_baseline.md").write_text(
        "| Tag Key | Required |\n|---|---|\n| Env | Yes |\n"
    )
    (standards_dir / "backend_mapping.md").write_text(
        "| Subscription | Storage Account |\n|---|---|\n| dev | stdev |\n"
    )

    bundle = adapter.load_standards(standards_dir)
    assert "azurerm_resource_group" in bundle.naming_rules
    assert bundle.metadata["naming_conventions"].get("title") == "BOM Test"


def test_naming_conventions_extracts_min_length(adapter, tmp_path):
    """Verify Min Length column in naming_conventions table is extracted."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Min Length | Max Length |\n"
        "|---|---|---|---|---|\n"
        "| azurerm_storage_account | ^st[a-z0-9]+$ | Lowercase | 3 | 24 |\n"
    )
    (standards_dir / "tagging_baseline.md").write_text(
        "| Tag Key | Required |\n|---|---|\n| Env | Yes |\n"
    )
    (standards_dir / "backend_mapping.md").write_text(
        "| Subscription | Storage Account |\n|---|---|\n| dev | stdev |\n"
    )

    bundle = adapter.load_standards(standards_dir)
    rule = bundle.naming_rules["azurerm_storage_account"]
    assert rule.min_length == 3
    assert rule.max_length == 24


def test_escaped_pipe_in_table_cell(adapter, tmp_path):
    """Verify escaped pipes and backticked pipes in table cells do not corrupt column counting."""
    standards_dir = tmp_path / "standards"
    standards_dir.mkdir()
    (standards_dir / "naming_conventions.md").write_text(
        "| Resource Type | Naming Pattern | Allowed Characters | Max Length |\n"
        "|---|---|---|---|\n"
        "| azurerm_resource_group | ^rg-[a-z]+$ | Lowercase \\| hyphen | 90 |\n"
    )
    (standards_dir / "tagging_baseline.md").write_text(
        "| Tag Key | Required | Allowed Values |\n|---|---|---|\n| Env | Yes | `a | b` |\n"
    )
    (standards_dir / "backend_mapping.md").write_text(
        "| Subscription | Storage Account |\n|---|---|\n| dev | stdev |\n"
    )

    bundle = adapter.load_standards(standards_dir)
    assert "azurerm_resource_group" in bundle.naming_rules
    assert "hyphen" in bundle.naming_rules["azurerm_resource_group"].allowed_characters
