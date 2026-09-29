"""Unit tests for pure-Python domain diff engine (ttassistant.domain.diff)."""

import pytest

from ttassistant.domain.diff import (
    FileDiff,
    WorkspaceDiff,
    compute_file_diff,
    compute_workspace_diff,
    generate_workspace_diff,
)
from ttassistant.domain.models import StagedFile, StagedWorkspace


def test_compute_file_diff_greenfield():
    """Verify greenfield file diff has /dev/null fromfile header and addition lines."""
    content = 'resource "azurerm_storage_account" "primary" {\n  name = "stappdataprod"\n}\n'
    file_diff = compute_file_diff(
        file_path="azurerm_storage_account/sub-prod/main.tf",
        new_content=content,
        existing_content=None,
    )

    assert isinstance(file_diff, FileDiff)
    assert file_diff.is_new is True
    assert file_diff.has_changes is True
    assert file_diff.path == "azurerm_storage_account/sub-prod/main.tf"
    assert "--- /dev/null" in file_diff.diff_text
    assert "+++ azurerm_storage_account/sub-prod/main.tf" in file_diff.diff_text
    assert '+resource "azurerm_storage_account" "primary" {' in file_diff.diff_text
    assert '+  name = "stappdataprod"' in file_diff.diff_text


def test_compute_file_diff_existing_modified():
    """Verify existing file modification shows diff header and additions/removals."""
    existing = 'resource "azurerm_storage_account" "primary" {\n  account_tier = "Standard"\n}\n'
    new = 'resource "azurerm_storage_account" "primary" {\n  account_tier = "Premium"\n}\n'
    file_diff = compute_file_diff(
        file_path="azurerm_storage_account/sub-prod/main.tf",
        new_content=new,
        existing_content=existing,
    )

    assert file_diff.is_new is False
    assert file_diff.has_changes is True
    assert "--- azurerm_storage_account/sub-prod/main.tf" in file_diff.diff_text
    assert "+++ azurerm_storage_account/sub-prod/main.tf" in file_diff.diff_text
    assert '-  account_tier = "Standard"' in file_diff.diff_text
    assert '+  account_tier = "Premium"' in file_diff.diff_text


def test_compute_file_diff_unchanged():
    """Verify identical existing and new content yields no diff."""
    content = 'resource "azurerm_storage_account" "primary" {}\n'
    file_diff = compute_file_diff(
        file_path="main.tf",
        new_content=content,
        existing_content=content,
    )

    assert file_diff.has_changes is False
    assert file_diff.diff_text == ""


def test_compute_workspace_diff_greenfield():
    """Verify complete greenfield StagedWorkspace diff computes diffs for all 3 files."""
    workspace = StagedWorkspace(target_dir="azurerm_storage_account/sub-prod/")
    workspace.add_file(
        StagedFile(
            path="main.tf",
            content='resource "azurerm_storage_account" "primary" {}\n',
            is_new=True,
        )
    )
    workspace.add_file(
        StagedFile(
            path="data.tf",
            content='data "azurerm_resource_group" "primary" {}\n',
            is_new=True,
        )
    )
    workspace.add_file(
        StagedFile(
            path="backend.tf",
            content='terraform {\n  backend "azurerm" {}\n}\n',
            is_new=True,
        )
    )

    ws_diff = compute_workspace_diff(workspace)
    assert isinstance(ws_diff, WorkspaceDiff)
    assert ws_diff.has_changes is True
    assert ws_diff.changed_file_count == 3
    assert len(ws_diff.files) == 3

    assert "--- /dev/null" in ws_diff.diff_text
    assert "+++ azurerm_storage_account/sub-prod/backend.tf" in ws_diff.diff_text
    assert "+++ azurerm_storage_account/sub-prod/data.tf" in ws_diff.diff_text
    assert "+++ azurerm_storage_account/sub-prod/main.tf" in ws_diff.diff_text

    # Helper also works
    gen_text = generate_workspace_diff(workspace)
    assert gen_text == ws_diff.diff_text


def test_compute_workspace_diff_empty():
    """Verify empty workspace diff produces empty diff text and no changes."""
    workspace = StagedWorkspace(target_dir="empty/sub/")
    ws_diff = compute_workspace_diff(workspace)

    assert ws_diff.has_changes is False
    assert ws_diff.changed_file_count == 0
    assert ws_diff.diff_text == ""
    assert ws_diff.files == []


def test_compute_workspace_diff_partial_modifications():
    """Verify workspace diff with one unchanged file and two changed files."""
    workspace = StagedWorkspace(target_dir="azurerm_storage_account/sub-prod/")
    workspace.add_file(
        StagedFile(
            path="main.tf",
            content='resource "azurerm_storage_account" "primary" {\n  account_tier = "Premium"\n}\n',
            is_new=False,
        )
    )
    workspace.add_file(
        StagedFile(
            path="data.tf",
            content='data "azurerm_resource_group" "primary" {}\n',
            is_new=False,
        )
    )
    workspace.add_file(
        StagedFile(
            path="backend.tf",
            content='terraform {\n  backend "azurerm" {}\n}\n',
            is_new=True,
        )
    )

    existing = {
        "main.tf": 'resource "azurerm_storage_account" "primary" {\n  account_tier = "Standard"\n}\n',
        "data.tf": 'data "azurerm_resource_group" "primary" {}\n',  # Unchanged
    }

    ws_diff = compute_workspace_diff(workspace, existing_files=existing)

    assert ws_diff.has_changes is True
    assert ws_diff.changed_file_count == 2
    # backend.tf is new from /dev/null
    assert "+++ azurerm_storage_account/sub-prod/backend.tf" in ws_diff.diff_text
    # main.tf is modified
    assert "--- azurerm_storage_account/sub-prod/main.tf" in ws_diff.diff_text
    # data.tf is unchanged, so its diff shouldn't appear in combined diff
    assert "azurerm_storage_account/sub-prod/data.tf" not in ws_diff.diff_text
