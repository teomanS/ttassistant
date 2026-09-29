"""Integration tests for Monorepo Topology Traversal and Candidate Indexing (Story 2.1).

Verifies streaming traversal, ignored directory exclusion, symlink cycle handling,
non-uniform directory conventions, and <= 3.0s / <150MB RSS performance benchmarks.
"""

import os
from pathlib import Path
import resource
import sys
import time
import pytest
from typer.testing import CliRunner

from ttassistant.adapters.fs_adapter import DiskFileSystemAdapter
from ttassistant.cli import app
from ttassistant.domain.topology import CandidateFile, TopologyIndex
from ttassistant.ports.filesystem import FileSystemPort

runner = CliRunner()


def test_filesystem_port_protocol_conformance():
    """Verify DiskFileSystemAdapter satisfies the FileSystemPort runtime_checkable protocol."""
    adapter = DiskFileSystemAdapter()
    assert isinstance(adapter, FileSystemPort)


def test_standard_monorepo_traversal(tmp_path):
    """Verify discovery of .tf files, matching azurerm_subnet, and mapping candidate to subscription."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)

    # Monorepo root containing <type>/<sub-prod>/main.tf with azurerm_subnet
    subnet_dir = tmp_path / "networking" / "sub-prod"
    subnet_dir.mkdir(parents=True)
    tf_file = subnet_dir / "main.tf"
    tf_file.write_text(
        'resource "azurerm_subnet" "core_snet" {\n  name = "snet-core"\n}\n',
        encoding="utf-8",
    )

    index = adapter.build_topology_index(tmp_path)
    assert index.total_files_scanned == 1
    assert index.candidate_count == 1
    candidate = index.candidates[0]
    assert candidate.subscription == "sub-prod"
    assert "azurerm_subnet" in candidate.detected_types


def test_ignored_directories_exclusion(tmp_path):
    """Verify ignored directories (.git, .terraform, .venv, etc.) are skipped during traversal."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)

    # Valid candidate
    valid_dir = tmp_path / "azurerm_subnet" / "sub-prod"
    valid_dir.mkdir(parents=True)
    (valid_dir / "main.tf").write_text('resource "azurerm_subnet" "s1" {}')

    # Ignored directories with candidate .tf files
    ignored_names = [
        ".git",
        ".terraform",
        ".venv",
        "venv",
        ".env",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".bin",
    ]
    for ign in ignored_names:
        ign_dir = tmp_path / ign / "sub-prod"
        ign_dir.mkdir(parents=True)
        (ign_dir / "ignored.tf").write_text(
            'resource "azurerm_subnet" "should_be_ignored" {}\n'
            'resource "azurerm_virtual_network" "ignored_vnet" {}\n'
        )

    index = adapter.build_topology_index(tmp_path)
    # Only the 1 valid file should be scanned and indexed
    assert index.total_files_scanned == 1
    assert index.candidate_count == 1
    assert index.candidates[0].filename == "main.tf"
    assert "sub-prod" == index.candidates[0].subscription


def test_non_uniform_folder_naming(tmp_path):
    """Verify non-uniform naming (rg/sub_prod/ vs resource-groups/sub-prod/) infers correct subscriptions."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)

    # rg/sub_prod/
    rg_dir = tmp_path / "rg" / "sub_prod"
    rg_dir.mkdir(parents=True)
    (rg_dir / "rg.tf").write_text('resource "azurerm_resource_group" "rg1" {}')

    # resource-groups/sub-prod/
    rg2_dir = tmp_path / "resource-groups" / "sub-prod"
    rg2_dir.mkdir(parents=True)
    (rg2_dir / "main.tf").write_text('resource "azurerm_resource_group" "rg2" {}')

    index = adapter.build_topology_index(tmp_path)
    assert index.candidate_count == 2
    subs = {c.subscription for c in index.candidates}
    assert subs == {"sub_prod", "sub-prod"}

    for c in index.candidates:
        assert "azurerm_resource_group" in c.detected_types


def test_multiple_resource_types_in_one_file(tmp_path):
    """Verify a single .tf file with multiple resource types records all in detected_types."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)

    net_dir = tmp_path / "networking" / "sub-prod"
    net_dir.mkdir(parents=True)
    (net_dir / "vnet_and_subnets.tf").write_text(
        'resource "azurerm_virtual_network" "vnet" {\n  name = "vnet-01"\n}\n'
        'resource "azurerm_subnet" "snet" {\n  name = "snet-01"\n}\n'
    )

    index = adapter.build_topology_index(tmp_path)
    assert index.candidate_count == 1
    cand = index.candidates[0]
    assert cand.detected_types == {"azurerm_virtual_network", "azurerm_subnet"}
    assert cand.subscription == "sub-prod"


def test_empty_repository_or_no_tf_files(tmp_path):
    """Verify an empty directory or folder with no .tf files returns an empty index without error."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)

    # Folder with non-tf files only
    other_dir = tmp_path / "docs"
    other_dir.mkdir(parents=True)
    (other_dir / "README.md").write_text("# Readme")
    (other_dir / "notes.txt").write_text("notes")

    index = adapter.build_topology_index(tmp_path)
    assert index.total_files_scanned == 0
    assert index.candidate_count == 0
    assert len(index) == 0


def test_deeply_nested_monorepo(tmp_path):
    """Verify traversal traverses monorepo hierarchies nested >10 levels deep without stack overflow."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)

    # Create 14 levels deep folder
    deep_path = tmp_path
    for i in range(14):
        deep_path = deep_path / f"level_{i}"
    deep_sub_path = deep_path / "sub-prod"
    deep_sub_path.mkdir(parents=True)

    (deep_sub_path / "deep.tf").write_text(
        'resource "azurerm_subnet" "deep_snet" {}\n'
    )

    index = adapter.build_topology_index(tmp_path)
    assert index.total_files_scanned == 1
    assert index.candidate_count == 1
    assert index.candidates[0].subscription == "sub-prod"
    assert "azurerm_subnet" in index.candidates[0].detected_types


def test_symlink_cycle_prevention(tmp_path):
    """Verify recursive directory symlinks do not cause infinite loops during traversal."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)

    dir_a = tmp_path / "dir_a"
    dir_b = dir_a / "dir_b"
    dir_b.mkdir(parents=True)

    # Normal candidate
    (dir_b / "sub-prod").mkdir(parents=True)
    (dir_b / "sub-prod" / "main.tf").write_text('resource "azurerm_subnet" "s1" {}')

    # Create recursive symlink: dir_b/cyclic_link -> dir_a
    cycle_link = dir_b / "cyclic_link"
    try:
        cycle_link.symlink_to(dir_a, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported in this environment")

    # Should complete without infinite recursion
    index = adapter.build_topology_index(tmp_path)
    assert index.candidate_count == 1
    assert index.candidates[0].subscription == "sub-prod"


def test_performance_benchmark_and_rss_footprint(tmp_path):
    """Verify indexing of up to 10,000 files completes in <= 3.0s with memory under 150MB RSS (NFR-2, NFR-3)."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)

    # Synthesize 10,000 files across 100 directories
    num_dirs = 100
    files_per_dir = 100
    total_expected = num_dirs * files_per_dir

    for d_idx in range(num_dirs):
        sub_name = f"sub-env-{d_idx % 5}"
        d_path = tmp_path / f"service_{d_idx}" / sub_name
        d_path.mkdir(parents=True)
        for f_idx in range(files_per_dir):
            file_path = d_path / f"file_{f_idx}.tf"
            if f_idx % 25 == 0:
                # 4 candidates per directory (total 400 candidates)
                content = (
                    'resource "azurerm_subnet" "snet" {\n'
                    '  name = "snet-benchmark"\n'
                    '}\n'
                )
            else:
                # Non-candidate .tf file
                content = (
                    'resource "azurerm_storage_account" "sa" {\n'
                    '  name = "sabenchmark"\n'
                    '}\n'
                )
            file_path.write_text(content, encoding="utf-8")

    start_time = time.perf_counter()
    index = adapter.build_topology_index(tmp_path)
    elapsed = time.perf_counter() - start_time

    # Performance assertions (NFR-2)
    assert index.total_files_scanned == total_expected
    assert index.candidate_count == 400
    assert elapsed <= 3.0, f"Indexing took {elapsed:.3f}s, exceeding 3.0s SLA (NFR-2)"

    # Process RSS footprint assertion (NFR-3: < 150MB RSS) with Windows guard
    try:
        import resource
        has_resource = hasattr(resource, "getrusage")
    except ImportError:
        has_resource = False

    if has_resource:
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        if sys.platform == "darwin":
            rss_mb = rusage.ru_maxrss / (1024.0 * 1024.0)
        else:
            rss_mb = rusage.ru_maxrss / 1024.0
        assert rss_mb < 150.0, f"Process RSS is {rss_mb:.1f} MB, exceeding 150 MB ceiling (NFR-3)"


def test_scan_tf_files_streaming_generator(tmp_path):
    """Verify scan_tf_files yields discovered .tf files and respects custom ignored_dirs."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)
    (tmp_path / "a.tf").write_text("# a")
    (tmp_path / "b.txt").write_text("# b")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.tf").write_text("# c")
    custom_ign = tmp_path / "custom_ignored"
    custom_ign.mkdir()
    (custom_ign / "d.tf").write_text("# d")

    files = list(adapter.scan_tf_files(tmp_path, ignored_dirs=["custom_ignored"]))
    filenames = {f.name for f in files}
    assert filenames == {"a.tf", "c.tf"}
    assert "d.tf" not in filenames
    assert "b.txt" not in filenames


def test_scan_candidates_streaming_generator(tmp_path):
    """Verify scan_candidates lazily yields CandidateFile instances matching target types."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)
    net_dir = tmp_path / "networking" / "sub-prod"
    net_dir.mkdir(parents=True)
    (net_dir / "main.tf").write_text('resource "azurerm_subnet" "s1" {}\n')
    rg_dir = tmp_path / "rg" / "sub-dev"
    rg_dir.mkdir(parents=True)
    (rg_dir / "main.tf").write_text('resource "azurerm_resource_group" "rg1" {}\n')

    # Stream all candidates
    candidates = list(adapter.scan_candidates(tmp_path))
    assert len(candidates) == 2

    # Stream with target_types filter
    subnet_only = list(adapter.scan_candidates(tmp_path, target_types={"azurerm_subnet"}))
    assert len(subnet_only) == 1
    assert "azurerm_subnet" in subnet_only[0].detected_types
    assert subnet_only[0].subscription == "sub-prod"


def test_cli_scan_command_output(tmp_path):
    """Verify ttassistant scan outputs candidate files, resource types, subscriptions, and elapsed time."""
    repo_root = Path(__file__).resolve().parent.parent
    standards_dir = repo_root / "common_standards"

    # Create dummy candidate monorepo in tmp_path
    service_dir = tmp_path / "networking" / "sub-prod"
    service_dir.mkdir(parents=True)
    (service_dir / "main.tf").write_text(
        'resource "azurerm_subnet" "snet" {\n  name = "snet-01"\n}\n'
        'resource "azurerm_virtual_network" "vnet" {\n  name = "vnet-01"\n}\n'
    )

    result = runner.invoke(
        app,
        ["--standards-dir", str(standards_dir), "scan", str(tmp_path)],
    )
    assert result.exit_code == 0
    # Expected output details
    assert "Topology Discovery: scanned 1 .tf files" in result.output
    assert "Discovered Dependency Candidates" in result.output
    assert "sub-prod" in result.output
    assert "azurerm_subnet" in result.output
    assert "azurerm_virtual_network" in result.output
    assert "Indexed 1 candidate files" in result.output


def test_cli_scan_filters_and_validation(tmp_path):
    """Verify CLI scan --subscription, --resource-type, and directory validation checks."""
    # Monorepo with two subscriptions
    prod_dir = tmp_path / "networking" / "sub-prod"
    prod_dir.mkdir(parents=True)
    (prod_dir / "main.tf").write_text('resource "azurerm_subnet" "s1" {}\n')

    dev_dir = tmp_path / "networking" / "sub-dev"
    dev_dir.mkdir(parents=True)
    (dev_dir / "main.tf").write_text('resource "azurerm_virtual_network" "v1" {}\n')

    # Test running without common_standards directory in workspace (must not raise MissingStandardsError)
    res_no_standards = runner.invoke(app, ["scan", str(tmp_path)])
    assert res_no_standards.exit_code == 0
    assert "Indexed 2 candidate files" in res_no_standards.output

    # Test --subscription filter
    res_sub = runner.invoke(app, ["scan", str(tmp_path), "--subscription", "sub-prod"])
    assert res_sub.exit_code == 0
    assert "Indexed 1 candidate files" in res_sub.output
    assert "sub-prod" in res_sub.output
    assert "sub-dev" not in res_sub.output

    # Test --resource-type filter
    res_type = runner.invoke(app, ["scan", str(tmp_path), "-r", "azurerm_virtual_network"])
    assert res_type.exit_code == 0
    assert "Indexed 1 candidate files" in res_type.output
    assert "azurerm_virtual_network" in res_type.output
    assert "azurerm_subnet" not in res_type.output

    # Test non-existent path validation
    res_missing = runner.invoke(app, ["scan", str(tmp_path / "does_not_exist")])
    assert res_missing.exit_code == 1
    assert "Directory does not exist" in res_missing.output

    # Test path is not a directory validation
    file_path = tmp_path / "single_file.txt"
    file_path.write_text("not a dir")
    res_not_dir = runner.invoke(app, ["scan", str(file_path)])
    assert res_not_dir.exit_code == 1
    assert "Specified path is not a directory" in res_not_dir.output


def test_cli_scan_ast_option(tmp_path):
    """Verify CLI scan --ast extracts and renders structured subnets, VNets, and resource groups."""
    repo_root = Path(__file__).resolve().parent.parent
    standards_dir = repo_root / "common_standards"

    net_dir = tmp_path / "networking" / "sub-prod"
    net_dir.mkdir(parents=True)
    (net_dir / "network.tf").write_text(
        """
        resource "azurerm_resource_group" "rg" {
          name     = "rg-prod-core"
          location = "westeurope"
          tags = {
            Environment = "Production"
          }
        }

        resource "azurerm_virtual_network" "vnet" {
          name                = "vnet-prod-core"
          resource_group_name = azurerm_resource_group.rg.name
          address_space       = ["10.0.0.0/16"]

          subnet {
            name           = "snet-paas-01"
            address_prefix = "10.0.1.0/24"
          }
        }

        resource "azurerm_subnet" "app" {
          name                 = "snet-app-02"
          virtual_network_name = azurerm_virtual_network.vnet.name
          resource_group_name  = azurerm_resource_group.rg.name
          address_prefixes     = ["10.0.2.0/24"]
        }
        """,
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["--standards-dir", str(standards_dir), "scan", str(tmp_path), "--ast"],
        env={"COLUMNS": "160"},
    )
    assert result.exit_code == 0
    assert "Discovered Subnets" in result.output
    assert "snet-paas-01" in result.output
    assert "snet-app-02" in result.output
    assert "Yes" in result.output  # snet-paas-01 is PE candidate
    assert "Discovered Virtual Networks" in result.output
    assert "vnet-prod-core" in result.output
    assert "Discovered Resource Groups" in result.output
    assert "rg-prod-core" in result.output
    assert "Phase 2 AST Extraction Complete" in result.output


def test_cli_scan_ast_with_malformed_file(tmp_path):
    """Verify CLI scan --ast displays warning on malformed HCL without aborting."""
    net_dir = tmp_path / "networking" / "sub-prod"
    net_dir.mkdir(parents=True)
    (net_dir / "valid.tf").write_text(
        'resource "azurerm_subnet" "s1" { address_prefixes = ["10.0.1.0/24"] }\n',
        encoding="utf-8",
    )
    (net_dir / "broken.tf").write_text(
        'resource "azurerm_subnet" "s2" { broken syntax here\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["scan", str(tmp_path), "--ast"])
    assert result.exit_code == 0
    assert "AST Parse Warning" in result.output
    assert "broken.tf" in result.output
    assert "s1" in result.output
    assert "Phase 2 AST Extraction Complete" in result.output

