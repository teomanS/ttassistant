"""Unit tests for StagedFile and StagedWorkspace domain models."""

from pathlib import Path
import pytest

from ttassistant.domain.models import ProvisioningParameters, StagedFile, StagedWorkspace


def test_staged_file_properties():
    """Verify StagedFile correctly computes line_count, filename, and default is_new."""
    content = "terraform {\n  required_version = \">= 1.0\"\n}\n"
    sf = StagedFile(path="backend.tf", content=content)

    assert sf.filename == "backend.tf"
    assert sf.line_count == 3
    assert sf.is_new is True
    assert sf.metadata == {}

    # Empty content
    empty_sf = StagedFile(path="subfolder/nested/main.tf", content="")
    assert empty_sf.filename == "main.tf"
    assert empty_sf.line_count == 0


def test_staged_workspace_operations():
    """Verify StagedWorkspace supports adding, retrieving, indexing, and calculating totals."""
    file1 = StagedFile(path="main.tf", content="resource \"azurerm_resource_group\" \"primary\" {\n  name = \"rg-prod\"\n}\n")
    file2 = StagedFile(path="backend.tf", content="terraform {\n  backend \"azurerm\" {}\n}\n")

    ws = StagedWorkspace(target_dir="azurerm_resource_group/sub-prod/")
    ws.add_file(file1)
    ws.add_file(file2)

    assert ws.file_count == 2
    assert len(ws) == 2
    assert "main.tf" in ws
    assert "backend.tf" in ws
    assert "nonexistent.tf" not in ws

    assert ws.get_file("main.tf") == file1
    assert ws["main.tf"] == file1
    assert ws.get_file("backend.tf") == file2
    assert ws["backend.tf"] == file2
    assert ws.get_file("missing.tf") is None

    with pytest.raises(KeyError):
        _ = ws["missing.tf"]

    # Verify iteration yields all staged files
    files_list = list(ws)
    assert len(files_list) == 2
    assert file1 in files_list
    assert file2 in files_list

    # Total lines
    expected_lines = file1.line_count + file2.line_count
    assert ws.total_lines == expected_lines


def test_staged_workspace_with_parameters():
    """Verify StagedWorkspace stores associated ProvisioningParameters and metadata."""
    params = ProvisioningParameters(
        subscription="sub-prod",
        resource_type="azurerm_storage_account",
        workload_name="appdata",
        environment="prod",
        resource_name="stappdataprod",
        tags={"Environment": "prod"},
    )
    ws = StagedWorkspace(
        target_dir="azurerm_storage_account/sub-prod/",
        parameters=params,
        metadata={"created_by": "test"},
    )

    assert ws.parameters is not None
    assert ws.parameters.subscription == "sub-prod"
    assert ws.metadata["created_by"] == "test"
