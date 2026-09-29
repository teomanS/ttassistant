"""Unit tests for pure-Python HCL serialization in domain/hcl.py."""

import hcl2
import pytest

from ttassistant.domain.hcl import (
    HclBlock,
    HclReference,
    build_backend_block,
    build_data_block,
    build_resource_block,
    format_hcl_value,
    render_hcl_document,
)


def test_hcl_reference_rendering():
    """Verify HclReference renders without quotation marks and supports equality check."""
    ref = HclReference("data.azurerm_resource_group.primary.name")
    assert str(ref) == "data.azurerm_resource_group.primary.name"
    assert ref == HclReference("data.azurerm_resource_group.primary.name")
    assert ref != HclReference("data.azurerm_resource_group.other.name")
    assert format_hcl_value(ref) == "data.azurerm_resource_group.primary.name"


def test_format_hcl_value_primitives():
    """Verify string escaping, boolean lowercase, and integer/float formatting."""
    assert format_hcl_value("standard") == '"standard"'
    assert format_hcl_value('with"quotes"and\\backslash') == '"with\\"quotes\\"and\\\\backslash"'
    assert format_hcl_value("name_${env}_%{if true}ok") == '"name_$${env}_%%{if true}ok"'
    assert format_hcl_value(True) == "true"
    assert format_hcl_value(False) == "false"
    assert format_hcl_value(42) == "42"
    assert format_hcl_value(3.14) == "3.14"
    assert format_hcl_value(None) == "null"


def test_format_hcl_map_alignment():
    """Verify map keys are sorted and equals signs align to the longest key."""
    tags = {
        "CostCenter": "CC-1001",
        "Environment": "prod",
        "Owner": "cloud-platform@corporate.com",
    }
    rendered = format_hcl_value(tags, indent_level=0)
    lines = rendered.splitlines()

    assert lines[0] == "{"
    assert lines[-1] == "}"
    # Keys should be sorted: CostCenter, Environment, Owner
    # Longest key is Environment (11 chars)
    assert '  CostCenter  = "CC-1001"' in lines
    assert '  Environment = "prod"' in lines
    assert '  Owner       = "cloud-platform@corporate.com"' in lines


def test_format_hcl_quoted_map_key_alignment():
    """Verify map keys with special characters requiring quotes align equals signs to the quoted key width."""
    mapping = {
        "simple": "val1",
        "key with spaces": "val2",
    }
    rendered = format_hcl_value(mapping, indent_level=0)
    lines = rendered.splitlines()

    # "key with spaces" is quoted -> '"key with spaces"' (17 chars)
    # "simple" is unquoted -> 'simple           ' (17 chars)
    assert '  "key with spaces" = "val2"' in lines
    assert '  simple            = "val1"' in lines


def test_format_hcl_empty_collections():
    """Verify empty dict, list, tuple, and set format compactly."""
    assert format_hcl_value({}) == "{}"
    assert format_hcl_value([]) == "[]"
    assert format_hcl_value(()) == "[]"
    assert format_hcl_value(set()) == "[]"


def test_format_hcl_list_inline_and_multiline():
    """Verify short primitive lists format inline while long lists format multi-line."""
    short_list = ["10.0.0.0/16", "10.1.0.0/16"]
    assert format_hcl_value(short_list) == '["10.0.0.0/16", "10.1.0.0/16"]'

    # Multi-line with > 3 items
    multiline_items = ["a", "b", "c", "d"]
    rendered = format_hcl_value(multiline_items, indent_level=0)
    lines = rendered.splitlines()
    assert lines[0] == "["
    assert lines[-1] == "]"
    assert len(lines) == 6
    assert '  "a",' in lines

    # Multi-line with long strings (> 30 chars)
    long_items = ["a-very-long-attribute-string-exceeding-thirty-characters"]
    rendered_long = format_hcl_value(long_items, indent_level=0)
    assert rendered_long.startswith("[\n")


def test_format_hcl_tuple_and_set_formatting():
    """Verify tuple and set types are formatted cleanly."""
    tup = ("10.0.0.0/16", "10.1.0.0/16")
    assert format_hcl_value(tup) == '["10.0.0.0/16", "10.1.0.0/16"]'

    st = {"alpha", "beta"}
    rendered_st = format_hcl_value(st)
    assert rendered_st in ('["alpha", "beta"]', '["beta", "alpha"]')



def test_hcl_block_attribute_alignment():
    """Verify attributes in HclBlock are aligned based on longest scalar key."""
    block = build_resource_block(
        resource_type="azurerm_storage_account",
        name="primary",
        attributes={
            "name": "stappdataprod",
            "resource_group_name": HclReference("data.azurerm_resource_group.primary.name"),
            "location": HclReference("data.azurerm_resource_group.primary.location"),
            "account_tier": "Standard",
            "account_replication_type": "LRS",
        },
    )
    rendered = block.render(0)
    lines = rendered.splitlines()

    assert lines[0] == 'resource "azurerm_storage_account" "primary" {'
    assert lines[-1] == "}"

    # Longest scalar is account_replication_type (24 chars)
    assert '  account_replication_type = "LRS"' in lines
    assert '  account_tier             = "Standard"' in lines
    assert '  location                 = data.azurerm_resource_group.primary.location' in lines
    assert '  name                     = "stappdataprod"' in lines
    assert '  resource_group_name      = data.azurerm_resource_group.primary.name' in lines


def test_hcl_block_with_tags_map():
    """Verify block with scalar attributes and tags map separates map with blank line and renders valid HCL."""
    block = build_resource_block(
        resource_type="azurerm_storage_account",
        name="primary",
        attributes={
            "name": "stappdataprod",
            "tags": {
                "CostCenter": "CC-1001",
                "Environment": "prod",
            },
        },
    )
    rendered = block.render(0)
    assert 'resource "azurerm_storage_account" "primary" {' in rendered
    assert '  name = "stappdataprod"' in rendered
    assert "  tags = {" in rendered
    assert '    CostCenter  = "CC-1001"' in rendered
    assert '    Environment = "prod"' in rendered


def test_build_backend_block_rendering():
    """Verify build_backend_block creates nested terraform { backend "azurerm" { ... } } structure."""
    block = build_backend_block(
        backend_type="azurerm",
        resource_group_name="rg-tfstate-prod",
        storage_account_name="sttfstateprod",
        container_name="tfstate",
        key="prod/azurerm_storage_account.tfstate",
    )
    rendered = block.render(0)
    lines = rendered.splitlines()

    assert lines[0] == "terraform {"
    assert lines[1] == '  backend "azurerm" {'
    assert '    resource_group_name  = "rg-tfstate-prod"' in lines
    assert '    storage_account_name = "sttfstateprod"' in lines
    assert '    container_name       = "tfstate"' in lines
    assert '    key                  = "prod/azurerm_storage_account.tfstate"' in lines
    assert lines[-2] == "  }"
    assert lines[-1] == "}"


def test_render_hcl_document_multiple_blocks_and_hcl2_parse():
    """Verify render_hcl_document joins multiple blocks with double newlines and passes hcl2 parser."""
    data_blk = build_data_block(
        data_type="azurerm_resource_group",
        name="primary",
        attributes={"name": "rg-tfstate-prod"},
    )
    res_blk = build_resource_block(
        resource_type="azurerm_storage_account",
        name="primary",
        attributes={
            "name": "stappdataprod",
            "resource_group_name": HclReference("data.azurerm_resource_group.primary.name"),
            "location": HclReference("data.azurerm_resource_group.primary.location"),
            "tags": {"Environment": "prod"},
        },
    )
    doc = render_hcl_document([data_blk, res_blk])

    assert doc.endswith("\n")
    assert '\n\nresource "azurerm_storage_account" "primary" {' in doc

    # Validate with python-hcl2
    parsed = hcl2.loads(doc)
    assert "data" in parsed
    assert "resource" in parsed
    assert parsed["data"][0]['"azurerm_resource_group"']['"primary"']["name"] == '"rg-tfstate-prod"'
