"""Unit tests for Topology domain models, lexical candidate extraction, and subscription inference (AD-1)."""

from pathlib import Path
import pytest

from ttassistant.domain.topology import (
    DEFAULT_TARGET_RESOURCE_TYPES,
    CandidateFile,
    TopologyIndex,
    extract_candidate_types,
    infer_subscription,
)


def test_candidate_file_model():
    """Verify CandidateFile initialization, path normalization, and properties."""
    cf1 = CandidateFile(
        path="networking/sub-prod/main.tf",
        subscription="sub-prod",
        detected_types={"azurerm_subnet"},
    )
    assert cf1.path == "networking/sub-prod/main.tf"
    assert cf1.subscription == "sub-prod"
    assert "azurerm_subnet" in cf1.detected_types
    assert cf1.filename == "main.tf"

    # Accepts Path object and normalizes to string
    cf2 = CandidateFile(
        path=Path("rg/sub_dev/resource_group.tf"),
        subscription="sub_dev",
        detected_types={"azurerm_resource_group"},
    )
    assert isinstance(cf2.path, str)
    assert cf2.filename == "resource_group.tf"

    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CandidateFile(path=None, detected_types=set())


def test_discovered_topology_len_includes_all_entities():
    """Verify DiscoveredTopology.__len__ returns sum of subnets, VNets, and RGs."""
    from ttassistant.domain.topology import (
        DiscoveredTopology,
        ResourceGroupCandidate,
        VirtualNetworkCandidate,
    )
    topo = DiscoveredTopology(
        virtual_networks=[VirtualNetworkCandidate(name="vnet1")],
        resource_groups=[ResourceGroupCandidate(name="rg1")],
    )
    assert len(topo) == 2


def test_infer_subscription_directory_with_dot():
    """Verify infer_subscription correctly identifies subscription directory containing dots."""
    sub = infer_subscription("networking/corp.prod.01/main.tf")
    assert sub == "corp.prod.01"


def test_default_pe_patterns_bounded():
    """Verify DEFAULT_PE_PATTERNS does not match common words like developer or operations."""
    import fnmatch
    from ttassistant.domain.topology import DEFAULT_PE_PATTERNS

    for word in ["snet-developer", "snet-operations", "compute-developer-tools"]:
        assert not any(fnmatch.fnmatch(word, p) for p in DEFAULT_PE_PATTERNS)



def test_topology_index_empty():
    """Verify empty TopologyIndex behavior and default metrics."""
    index = TopologyIndex()
    assert index.candidate_count == 0
    assert len(index) == 0
    assert index.total_files_scanned == 0
    assert index.duration_seconds == 0.0
    assert index.subscriptions == set()
    assert index.by_subscription == {}
    assert index.get_candidates_for_subscription("sub-prod") == []
    assert index.get_candidates_by_type("azurerm_subnet") == []


def test_topology_index_add_and_query():
    """Verify adding candidates and querying by subscription and resource type."""
    index = TopologyIndex(total_files_scanned=42, duration_seconds=0.12)
    c1 = CandidateFile(
        path="rg/sub-prod/main.tf",
        subscription="sub-prod",
        detected_types={"azurerm_resource_group"},
    )
    c2 = CandidateFile(
        path="networking/sub-prod/main.tf",
        subscription="sub-prod",
        detected_types={"azurerm_virtual_network", "azurerm_subnet"},
    )
    c3 = CandidateFile(
        path="networking/sub-dev/main.tf",
        subscription="sub-dev",
        detected_types={"azurerm_subnet"},
    )
    c4 = CandidateFile(
        path="shared/main.tf",
        subscription=None,
        detected_types={"azurerm_resource_group"},
    )

    for c in [c1, c2, c3, c4]:
        index.add_candidate(c)

    assert index.candidate_count == 4
    assert len(index) == 4
    assert index.subscriptions == {"sub-prod", "sub-dev"}

    # Query by subscription
    prod_cands = index.get_candidates_for_subscription("sub-prod")
    assert len(prod_cands) == 2
    assert c1 in prod_cands and c2 in prod_cands

    # Query by type
    subnet_cands = index.get_candidates_by_type("azurerm_subnet")
    assert len(subnet_cands) == 2
    assert c2 in subnet_cands and c3 in subnet_cands

    rg_cands = index.get_candidates_by_type("azurerm_resource_group")
    assert len(rg_cands) == 2
    assert c1 in rg_cands and c4 in rg_cands

    # by_subscription grouping
    grouped = index.by_subscription
    assert "sub-prod" in grouped
    assert "sub-dev" in grouped
    assert "unassigned" in grouped
    assert len(grouped["unassigned"]) == 1
    assert grouped["unassigned"][0].path == "shared/main.tf"

    # Index iteration and access
    items = list(index)
    assert len(items) == 4
    assert index[0] == c1


def test_extract_candidate_types_resources_and_data():
    """Verify lexical extraction detects resource and data blocks for target types."""
    content = """
    # Comments should be ignored
    # resource "azurerm_subnet" "ignored_comment" {}
    // data "azurerm_virtual_network" "ignored_slash" {}

    resource "azurerm_resource_group" "rg" {
      name     = "rg-prod-core"
      location = "westeurope"
    }

    data "azurerm_virtual_network" "vnet" {
      name                = "vnet-prod-core"
      resource_group_name = azurerm_resource_group.rg.name
    }

    resource "azurerm_subnet" "snet" {
      name                 = "snet-paas-01"
      resource_group_name  = azurerm_resource_group.rg.name
      virtual_network_name = data.azurerm_virtual_network.vnet.name
    }

    resource "azurerm_storage_account" "sa" {
      name = "stprod01"
    }
    """
    types = extract_candidate_types(content)
    assert types == {
        "azurerm_resource_group",
        "azurerm_virtual_network",
        "azurerm_subnet",
    }


def test_extract_candidate_types_no_match():
    """Verify content without target candidate types yields an empty set."""
    content = """
    resource "azurerm_key_vault" "kv" {
      name = "kv-prod"
    }
    resource "azurerm_storage_account" "st" {
      name = "stprod"
    }
    """
    assert extract_candidate_types(content) == set()


def test_extract_candidate_types_custom_target():
    """Verify custom target_types filter is respected."""
    content = """
    resource "azurerm_subnet" "s1" {}
    resource "azurerm_virtual_network" "v1" {}
    """
    types = extract_candidate_types(content, target_types=frozenset({"azurerm_subnet"}))
    assert types == {"azurerm_subnet"}


def test_infer_subscription_path_patterns():
    """Verify subscription inference across various monorepo directory naming conventions."""
    # Standard <resource-type>/<subscription>/ layout
    assert infer_subscription("azurerm_subnet/sub-prod/main.tf") == "sub-prod"
    assert infer_subscription("azurerm_virtual_network/sub-dev/network.tf") == "sub-dev"

    # Non-uniform naming: resource-groups/sub-prod vs rg/sub_prod
    assert infer_subscription("resource-groups/sub-prod/main.tf") == "sub-prod"
    assert infer_subscription("rg/sub_prod/main.tf") == "sub_prod"
    assert infer_subscription("networking/sub-prod/subnets.tf") == "sub-prod"
    assert infer_subscription("virtual-networks/sub-stage/vnet.tf") == "sub-stage"

    # Directory with subscriptions/ or subscription/
    assert infer_subscription("subscriptions/sub-core-infra/networking/main.tf") == "sub-core-infra"
    assert infer_subscription("subscription/workload-prod/rg.tf") == "workload-prod"

    # Workload or sub- prefix
    assert infer_subscription("infra/workload-prod/main.tf") == "workload-prod"
    assert infer_subscription("cloud/corp-prod-sub/main.tf") == "corp-prod-sub"

    # Path without recognizable subscription cues
    assert infer_subscription("main.tf") is None


def test_infer_subscription_content_hints():
    """Verify subscription inference respects inline content hints."""
    hint1 = 'provider "azurerm" {\n  subscription_id = "00000000-0000-0000-0000-000000000000"\n  subscription = "sub-inline-hint"\n}'
    assert infer_subscription("modules/networking/main.tf", content_hints=hint1) == "sub-inline-hint"

    hint2 = 'subscription_id = "sub-from-id"'
    assert infer_subscription("unknown/main.tf", content_hints=hint2) == "sub-from-id"


def test_topology_index_get_unassigned_candidates():
    """Verify get_candidates_for_subscription('unassigned') returns candidates with None subscription."""
    index = TopologyIndex()
    c1 = CandidateFile(path="a.tf", subscription="sub-prod", detected_types={"azurerm_subnet"})
    c2 = CandidateFile(path="b.tf", subscription=None, detected_types={"azurerm_subnet"})
    c3 = CandidateFile(path="c.tf", subscription="unassigned", detected_types={"azurerm_subnet"})
    index.add_candidate(c1)
    index.add_candidate(c2)
    index.add_candidate(c3)

    unassigned = index.get_candidates_for_subscription("unassigned")
    assert len(unassigned) == 2
    assert c2 in unassigned
    assert c3 in unassigned


def test_candidate_file_normalize_posix_path():
    """Verify CandidateFile path is normalized to POSIX forward-slash format."""
    cf = CandidateFile(
        path=r"networking\sub-prod\main.tf",
        subscription="sub-prod",
        detected_types={"azurerm_subnet"},
    )
    assert cf.path == "networking/sub-prod/main.tf"
    assert "\\" not in cf.path


def test_infer_subscription_root_dir_isolation():
    """Verify infer_subscription with root_dir prevents leaking host directories for root files."""
    root = Path("/home/user/workspace/repo")
    # File in repository root must infer None, not 'repo' or 'workspace' or 'home'
    assert infer_subscription(root / "main.tf", root_dir=root) is None
    # File in virtual-networks/sub-prod/main.tf within root
    assert infer_subscription(root / "virtual-networks" / "sub-prod" / "main.tf", root_dir=root) == "sub-prod"
    assert infer_subscription(root / "virtual_networks" / "sub-dev" / "main.tf", root_dir=root) == "sub-dev"
    assert infer_subscription(root / "resource_groups" / "sub-prod" / "main.tf", root_dir=root) == "sub-prod"


def test_infer_subscription_ignores_comment_hints():
    """Verify comment lines with subscription attributes are ignored."""
    hint_comment = (
        '# subscription = "commented-sub-hash"\n'
        '// subscription = "commented-sub-slash"\n'
        'provider "azurerm" {\n'
        '  subscription = "real-sub"\n'
        '}\n'
    )
    assert infer_subscription("modules/net/main.tf", content_hints=hint_comment) == "real-sub"

    only_comment = (
        '# subscription = "fake-sub"\n'
        '// subscription_id = "00000000-0000-0000-0000-000000000000"\n'
    )
    assert infer_subscription("main.tf", content_hints=only_comment) is None
