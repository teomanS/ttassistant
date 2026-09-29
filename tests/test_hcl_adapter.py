"""Unit tests for ReadOnlyHclAdapter AST extraction (AD-1, AD-2)."""

import os
from pathlib import Path
import pytest

from ttassistant.adapters.hcl_adapter import ReadOnlyHclAdapter
from ttassistant.domain.topology import (
    CandidateFile,
    DiscoveredTopology,
    ResourceGroupCandidate,
    SubnetCandidate,
    VirtualNetworkCandidate,
    is_private_endpoint_subnet,
)


@pytest.fixture
def adapter() -> ReadOnlyHclAdapter:
    """Fixture providing ReadOnlyHclAdapter instance with default standards."""
    return ReadOnlyHclAdapter(standards_patterns=["*snet-paas*", "*private*", "*pe*"])


def test_empty_candidate_list(adapter: ReadOnlyHclAdapter):
    """Verify empty candidate list returns empty DiscoveredTopology immediately."""
    result = adapter.parse_topology_candidates([])
    assert isinstance(result, DiscoveredTopology)
    assert len(result.subnets) == 0
    assert len(result.virtual_networks) == 0
    assert len(result.resource_groups) == 0
    assert len(result.parse_errors) == 0


def test_empty_hcl_string(adapter: ReadOnlyHclAdapter):
    """Verify empty or whitespace HCL string returns empty DiscoveredTopology."""
    result = adapter.parse_hcl_string("")
    assert len(result.subnets) == 0
    assert len(result.parse_errors) == 0

    result2 = adapter.parse_hcl_string("   \n\t  ")
    assert len(result2.subnets) == 0
    assert len(result2.parse_errors) == 0


def test_standalone_subnet_extraction(adapter: ReadOnlyHclAdapter):
    """Verify standalone azurerm_subnet extraction with address_prefixes list and quote stripping."""
    hcl = """
    resource "azurerm_subnet" "snet" {
      address_prefixes     = ["10.0.1.0/24"]
      virtual_network_name = "vnet-prod"
      resource_group_name  = "rg-prod"
    }
    """
    result = adapter.parse_hcl_string(hcl, filename="subnets.tf", subscription="sub-prod")
    assert len(result.subnets) == 1
    subnet = result.subnets[0]
    assert subnet.name == "snet"
    assert subnet.address_prefixes == ["10.0.1.0/24"]
    assert subnet.virtual_network_name == "vnet-prod"
    assert subnet.resource_group_name == "rg-prod"
    assert subnet.is_inline is False
    assert subnet.is_data_source is False
    assert subnet.subscription == "sub-prod"
    assert subnet.file_path == "subnets.tf"


def test_standalone_subnet_with_explicit_name_and_multiple_prefixes(adapter: ReadOnlyHclAdapter):
    """Verify standalone subnet with explicit name attribute and multiple CIDRs."""
    hcl = """
    resource "azurerm_subnet" "web" {
      name                 = "snet-web-frontend"
      address_prefixes     = ["10.10.1.0/24", "10.10.2.0/24"]
      virtual_network_name = "vnet-spoke"
      resource_group_name  = "rg-spoke"
    }
    """
    result = adapter.parse_hcl_string(hcl)
    assert len(result.subnets) == 1
    subnet = result.subnets[0]
    assert subnet.name == "snet-web-frontend"
    assert subnet.address_prefixes == ["10.10.1.0/24", "10.10.2.0/24"]
    assert subnet.is_inline is False


def test_inline_subnet_in_vnet(adapter: ReadOnlyHclAdapter):
    """Verify inline subnet declared inside azurerm_virtual_network with singular address_prefix fallback."""
    hcl = """
    resource "azurerm_virtual_network" "hub" {
      name                = "vnet-hub"
      resource_group_name = "rg-hub"
      location            = "westeurope"
      address_space       = ["10.0.0.0/16"]

      subnet {
        name           = "pe"
        address_prefix = "10.0.2.0/24"
      }

      subnet {
        name             = "app"
        address_prefixes = ["10.0.3.0/24"]
      }
    }
    """
    result = adapter.parse_hcl_string(hcl)
    assert len(result.virtual_networks) == 1
    vnet = result.virtual_networks[0]
    assert vnet.name == "vnet-hub"
    assert vnet.resource_group_name == "rg-hub"
    assert vnet.location == "westeurope"
    assert vnet.address_space == ["10.0.0.0/16"]
    assert len(vnet.subnets) == 2

    # Inline subnet 1: singular address_prefix converted to address_prefixes list
    pe_sub = vnet.subnets[0]
    assert pe_sub.name == "pe"
    assert pe_sub.address_prefixes == ["10.0.2.0/24"]
    assert pe_sub.is_inline is True
    assert pe_sub.virtual_network_name == "vnet-hub"
    assert pe_sub.resource_group_name == "rg-hub"
    assert pe_sub.is_private_endpoint_candidate is True

    # Inline subnet 2
    app_sub = vnet.subnets[1]
    assert app_sub.name == "app"
    assert app_sub.address_prefixes == ["10.0.3.0/24"]
    assert app_sub.is_inline is True

    # Both subnets also present in top-level topology.subnets
    assert len(result.subnets) == 2
    assert result.subnets[0].name == "pe"
    assert result.subnets[1].name == "app"


def test_resource_group_extraction(adapter: ReadOnlyHclAdapter):
    """Verify azurerm_resource_group extraction with location and tags."""
    hcl = """
    resource "azurerm_resource_group" "rg" {
      name     = "rg-prod-core"
      location = "westeurope"
      tags = {
        "Environment" = "Production"
        Owner         = "PlatformTeam"
      }
    }
    """
    result = adapter.parse_hcl_string(hcl)
    assert len(result.resource_groups) == 1
    rg = result.resource_groups[0]
    assert rg.name == "rg-prod-core"
    assert rg.location == "westeurope"
    assert rg.tags == {"Environment": "Production", "Owner": "PlatformTeam"}
    assert rg.is_data_source is False


def test_resource_group_missing_name_falls_back_to_label(adapter: ReadOnlyHclAdapter):
    """Verify Resource Group missing explicit name attribute uses block label."""
    hcl = """
    resource "azurerm_resource_group" "rg_core" {
      location = "eastus"
    }
    """
    result = adapter.parse_hcl_string(hcl)
    assert len(result.resource_groups) == 1
    assert result.resource_groups[0].name == "rg_core"


def test_data_source_discovery(adapter: ReadOnlyHclAdapter):
    """Verify data sources for subnet, vnet, and resource group are extracted with is_data_source=True."""
    hcl = """
    data "azurerm_resource_group" "upstream_rg" {
      name = "rg-shared-hub"
    }

    data "azurerm_virtual_network" "upstream_vnet" {
      name                = "vnet-shared-hub"
      resource_group_name = "rg-shared-hub"
    }

    data "azurerm_subnet" "pe" {
      name                 = "snet-paas-01"
      virtual_network_name = "vnet-shared-hub"
      resource_group_name  = "rg-shared-hub"
    }
    """
    result = adapter.parse_hcl_string(hcl)
    assert len(result.resource_groups) == 1
    assert result.resource_groups[0].name == "rg-shared-hub"
    assert result.resource_groups[0].is_data_source is True

    assert len(result.virtual_networks) == 1
    assert result.virtual_networks[0].name == "vnet-shared-hub"
    assert result.virtual_networks[0].is_data_source is True

    assert len(result.subnets) == 1
    assert result.subnets[0].name == "snet-paas-01"
    assert result.subnets[0].virtual_network_name == "vnet-shared-hub"
    assert result.subnets[0].resource_group_name == "rg-shared-hub"
    assert result.subnets[0].is_data_source is True
    assert result.subnets[0].is_private_endpoint_candidate is True


def test_private_endpoint_heuristics(adapter: ReadOnlyHclAdapter):
    """Verify multi-factor Private Endpoint candidate heuristics."""
    # 1. Matching standards pattern glob
    hcl1 = """
    resource "azurerm_subnet" "s1" {
      name             = "snet-paas-01"
      address_prefixes = ["10.0.1.0/24"]
    }
    """
    r1 = adapter.parse_hcl_string(hcl1)
    assert r1.subnets[0].is_private_endpoint_candidate is True

    # 2. Attribute private_endpoint_network_policies_enabled = true
    hcl2 = """
    resource "azurerm_subnet" "s2" {
      name                                      = "snet-custom-01"
      address_prefixes                          = ["10.0.2.0/24"]
      private_endpoint_network_policies_enabled = true
    }
    """
    r2 = adapter.parse_hcl_string(hcl2)
    assert r2.subnets[0].is_private_endpoint_candidate is True
    assert r2.subnets[0].private_endpoint_network_policies_enabled is True

    # 3. Naming tokens: 'pe', 'private', 'privatelink'
    for name in ["snet-pe", "pe-subnet", "subnet-privatelink", "private-endpoint-subnet", "snet-pe-01"]:
        assert is_private_endpoint_subnet(name) is True

    # 4. Tags indication
    hcl4 = """
    resource "azurerm_subnet" "s4" {
      name             = "snet-workload-01"
      address_prefixes = ["10.0.4.0/24"]
      tags = {
        purpose = "private-endpoints"
      }
    }
    """
    r4 = adapter.parse_hcl_string(hcl4)
    assert r4.subnets[0].is_private_endpoint_candidate is True

    # 5. Non-PE regular subnet
    hcl5 = """
    resource "azurerm_subnet" "s5" {
      name             = "snet-compute-aks"
      address_prefixes = ["10.0.5.0/24"]
    }
    """
    r5 = adapter.parse_hcl_string(hcl5)
    assert r5.subnets[0].is_private_endpoint_candidate is False


def test_string_reference_resolution(adapter: ReadOnlyHclAdapter):
    """Verify resolution of HCL string references like azurerm_resource_group.rg.name."""
    hcl = """
    resource "azurerm_resource_group" "rg" {
      name     = "rg-prod-resolved"
      location = "westeurope"
    }

    resource "azurerm_virtual_network" "vnet" {
      name                = "vnet-prod-resolved"
      resource_group_name = azurerm_resource_group.rg.name
      location            = azurerm_resource_group.rg.location
      address_space       = ["10.0.0.0/16"]

      subnet {
        name           = "snet-app"
        address_prefix = "10.0.1.0/24"
      }
    }

    resource "azurerm_subnet" "db" {
      name                 = "snet-db"
      resource_group_name  = "${azurerm_resource_group.rg.name}"
      virtual_network_name = azurerm_virtual_network.vnet.name
      address_prefixes     = ["10.0.2.0/24"]
    }
    """
    result = adapter.parse_hcl_string(hcl)
    assert len(result.resource_groups) == 1
    assert len(result.virtual_networks) == 1
    assert len(result.subnets) == 2

    # VNet RG reference resolved
    vnet = result.virtual_networks[0]
    assert vnet.resource_group_name == "rg-prod-resolved"

    # Inline subnet RG inherited
    inline = vnet.subnets[0]
    assert inline.resource_group_name == "rg-prod-resolved"

    # Standalone subnet RG and VNet references resolved
    db_sub = [s for s in result.subnets if s.name == "snet-db"][0]
    assert db_sub.resource_group_name == "rg-prod-resolved"
    assert db_sub.virtual_network_name == "vnet-prod-resolved"


def test_malformed_hcl_isolated_and_recorded(tmp_path: Path, adapter: ReadOnlyHclAdapter):
    """Verify malformed HCL files record parse errors without aborting other candidate files."""
    valid_file = tmp_path / "valid.tf"
    valid_file.write_text(
        """
        resource "azurerm_subnet" "valid" {
          name             = "snet-valid"
          address_prefixes = ["10.0.0.0/24"]
        }
        """,
        encoding="utf-8",
    )

    bad_file = tmp_path / "broken.tf"
    bad_file.write_text(
        """
        resource "azurerm_subnet" "broken" {
          name = "broken
          unclosed_braces =
        """,
        encoding="utf-8",
    )

    valid_file2 = tmp_path / "valid2.tf"
    valid_file2.write_text(
        """
        resource "azurerm_resource_group" "valid_rg" {
          name     = "rg-valid"
          location = "northeurope"
        }
        """,
        encoding="utf-8",
    )

    candidates = [
        CandidateFile(path=str(valid_file), detected_types={"azurerm_subnet"}),
        CandidateFile(path=str(bad_file), detected_types={"azurerm_subnet"}),
        CandidateFile(path=str(valid_file2), detected_types={"azurerm_resource_group"}),
    ]

    result = adapter.parse_topology_candidates(candidates)

    # Valid files were successfully parsed
    assert len(result.subnets) == 1
    assert result.subnets[0].name == "snet-valid"
    assert len(result.resource_groups) == 1
    assert result.resource_groups[0].name == "rg-valid"

    # Bad file recorded in parse_errors
    assert len(result.parse_errors) == 1
    assert str(bad_file) in result.parse_errors[0]


def test_topology_filtering_methods(adapter: ReadOnlyHclAdapter):
    """Verify DiscoveredTopology query helper methods."""
    hcl = """
    resource "azurerm_subnet" "sub1" {
      name             = "snet-paas-01"
      address_prefixes = ["10.0.1.0/24"]
    }
    resource "azurerm_subnet" "sub2" {
      name             = "snet-app-02"
      address_prefixes = ["10.0.2.0/24"]
    }
    resource "azurerm_resource_group" "rg1" {
      name     = "rg-prod"
      location = "eastus"
    }
    """
    result = adapter.parse_hcl_string(hcl, subscription="sub-prod")
    assert len(result.get_subnets_for_subscription("sub-prod")) == 2
    assert len(result.get_subnets_for_subscription("sub-dev")) == 0

    pe_subnets = result.get_private_endpoint_subnets()
    assert len(pe_subnets) == 1
    assert pe_subnets[0].name == "snet-paas-01"

    rgs = result.get_resource_groups_for_subscription("sub-prod")
    assert len(rgs) == 1
    assert rgs[0].name == "rg-prod"


def test_read_only_guarantee_no_file_modification(tmp_path: Path, adapter: ReadOnlyHclAdapter):
    """Verify that parsing candidate files strictly preserves file content and mtime (AD-2)."""
    tf_file = tmp_path / "subnets.tf"
    content = (
        "# Important architecture comment that must not be deleted\n"
        'resource "azurerm_subnet" "snet" {\n'
        '  name                 = "snet-pe"\n'
        '  address_prefixes     = ["10.0.1.0/24"]\n'
        '  virtual_network_name = "vnet-hub"\n'
        '  resource_group_name  = "rg-hub"\n'
        "}\n"
    )
    tf_file.write_text(content, encoding="utf-8")
    original_mtime = os.path.getmtime(tf_file)

    result = adapter.parse_topology_candidates([CandidateFile(path=str(tf_file), detected_types={"azurerm_subnet"})])
    assert len(result.subnets) == 1

    # Verify file content is completely identical byte-for-byte
    current_content = tf_file.read_text(encoding="utf-8")
    assert current_content == content
    assert "# Important architecture comment" in current_content

    # Verify modification time was not touched
    current_mtime = os.path.getmtime(tf_file)
    assert current_mtime == original_mtime


def test_cross_file_reference_resolution_and_subscription_isolation(tmp_path: Path, adapter: ReadOnlyHclAdapter):
    """Verify references are resolved across separate candidate files with subscription scoping."""
    # sub-prod files
    prod_dir = tmp_path / "prod"
    prod_dir.mkdir(parents=True)
    rg_prod = prod_dir / "rg.tf"
    rg_prod.write_text('resource "azurerm_resource_group" "rg" { name = "rg-prod-core" }\n', encoding="utf-8")
    vnet_prod = prod_dir / "vnet.tf"
    vnet_prod.write_text(
        'resource "azurerm_virtual_network" "vnet" {\n'
        '  name = "vnet-prod-core"\n'
        '  resource_group_name = azurerm_resource_group.rg.name\n'
        '}\n',
        encoding="utf-8",
    )
    snet_prod = prod_dir / "snet.tf"
    snet_prod.write_text(
        'resource "azurerm_subnet" "snet" {\n'
        '  name = "snet-prod-app"\n'
        '  resource_group_name = azurerm_resource_group.rg.name\n'
        '  virtual_network_name = azurerm_virtual_network.vnet.name\n'
        '}\n',
        encoding="utf-8",
    )

    # sub-dev files reusing same labels 'rg' and 'vnet'
    dev_dir = tmp_path / "dev"
    dev_dir.mkdir(parents=True)
    rg_dev = dev_dir / "rg.tf"
    rg_dev.write_text('resource "azurerm_resource_group" "rg" { name = "rg-dev-core" }\n', encoding="utf-8")
    snet_dev = dev_dir / "snet.tf"
    snet_dev.write_text(
        'resource "azurerm_subnet" "snet" {\n'
        '  name = "snet-dev-app"\n'
        '  resource_group_name = azurerm_resource_group.rg.name\n'
        '}\n',
        encoding="utf-8",
    )

    candidates = [
        CandidateFile(path=str(rg_prod), subscription="sub-prod"),
        CandidateFile(path=str(vnet_prod), subscription="sub-prod"),
        CandidateFile(path=str(snet_prod), subscription="sub-prod"),
        CandidateFile(path=str(rg_dev), subscription="sub-dev"),
        CandidateFile(path=str(snet_dev), subscription="sub-dev"),
    ]

    result = adapter.parse_topology_candidates(candidates)

    prod_subnets = result.get_subnets_for_subscription("sub-prod")
    assert len(prod_subnets) == 1
    assert prod_subnets[0].resource_group_name == "rg-prod-core"
    assert prod_subnets[0].virtual_network_name == "vnet-prod-core"

    dev_subnets = result.get_subnets_for_subscription("sub-dev")
    assert len(dev_subnets) == 1
    assert dev_subnets[0].resource_group_name == "rg-dev-core"


def test_private_endpoint_token_heuristics_with_empty_standards_patterns():
    """Verify naming token and tag heuristics when standards_patterns is empty (non-matching globs)."""
    empty_patterns: list[str] = []

    # Token matches
    assert is_private_endpoint_subnet("snet-pe-01", standards_patterns=empty_patterns) is True
    assert is_private_endpoint_subnet("pe", standards_patterns=empty_patterns) is True
    assert is_private_endpoint_subnet("snet-private-link", standards_patterns=empty_patterns) is True
    assert is_private_endpoint_subnet("snet-paas-storage", standards_patterns=empty_patterns) is True

    # Words containing 'pe' as a substring must NOT match (e.g. developer, operations)
    assert is_private_endpoint_subnet("snet-developer-tools", standards_patterns=empty_patterns) is False
    assert is_private_endpoint_subnet("snet-operations", standards_patterns=empty_patterns) is False
    assert is_private_endpoint_subnet("snet-workload-compute", standards_patterns=empty_patterns) is False

    # Tag heuristics: Service Endpoint must NOT match, Private Endpoint must match
    assert is_private_endpoint_subnet("snet-misc", tags={"type": "service_endpoint"}, standards_patterns=empty_patterns) is False
    assert is_private_endpoint_subnet("snet-misc", tags={"type": "private_endpoint"}, standards_patterns=empty_patterns) is True
    assert is_private_endpoint_subnet("snet-misc", tags={"network": "privatelink"}, standards_patterns=empty_patterns) is True
    assert is_private_endpoint_subnet("snet-misc", tags={"purpose": "pe"}, standards_patterns=empty_patterns) is True

    # Boolean network_policies_enabled: False must not match, True must match
    assert is_private_endpoint_subnet("snet-misc", network_policies_enabled=False, standards_patterns=empty_patterns) is False
    assert is_private_endpoint_subnet("snet-misc", network_policies_enabled=True, standards_patterns=empty_patterns) is True

