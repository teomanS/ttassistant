"""Unit tests for DiskFileSystemAdapter atomic writes, fsync, and rollback."""

from pathlib import Path
from unittest.mock import patch
import pytest

from ttassistant.adapters.fs_adapter import DiskFileSystemAdapter
from ttassistant.domain.exceptions import FileSystemError
from ttassistant.domain.models import StagedFile, StagedWorkspace


@pytest.fixture
def staged_workspace() -> StagedWorkspace:
    """Create a sample StagedWorkspace targeting subfolder."""
    ws = StagedWorkspace(target_dir="azurerm_storage_account/sub-prod/")
    ws.add_file(
        StagedFile(
            path="main.tf",
            content='resource "azurerm_storage_account" "primary" {\n  name = "stappdataprod"\n}\n',
            is_new=True,
        )
    )
    ws.add_file(
        StagedFile(
            path="data.tf",
            content='data "azurerm_resource_group" "primary" {\n  name = "rg-sub-prod"\n}\n',
            is_new=True,
        )
    )
    ws.add_file(
        StagedFile(
            path="backend.tf",
            content='terraform {\n  backend "azurerm" {\n    key = "state.tfstate"\n  }\n}\n',
            is_new=True,
        )
    )
    return ws


def test_fs_adapter_happy_path_commit(tmp_path: Path, staged_workspace: StagedWorkspace):
    """Verify happy path commitment creates files with expected content and leaves no tmp files."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)
    committed = adapter.commit_workspace(staged_workspace)

    assert len(committed) == 3
    for p in committed:
        assert p.is_file()
        assert p.stat().st_size > 0

    target_dir = tmp_path / "azurerm_storage_account" / "sub-prod"
    assert (target_dir / "main.tf").read_text(encoding="utf-8") == staged_workspace["main.tf"].content
    assert (target_dir / "data.tf").read_text(encoding="utf-8") == staged_workspace["data.tf"].content
    assert (target_dir / "backend.tf").read_text(encoding="utf-8") == staged_workspace["backend.tf"].content

    # Ensure no sibling .tmp or .bak files remain
    tmp_files = list(target_dir.glob(".*.tmp"))
    bak_files = list(target_dir.glob(".*.bak"))
    assert len(tmp_files) == 0
    assert len(bak_files) == 0

    # Test adapter reader methods
    assert adapter.file_exists("azurerm_storage_account/sub-prod/main.tf") is True
    assert adapter.dir_exists("azurerm_storage_account/sub-prod") is True
    assert "stappdataprod" in adapter.read_file("azurerm_storage_account/sub-prod/main.tf")


def test_fs_adapter_calls_fsync(tmp_path: Path, staged_workspace: StagedWorkspace):
    """Verify os.fsync is called for every file written."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)
    with patch("os.fsync") as mock_fsync:
        adapter.commit_workspace(staged_workspace)
        # 3 file fsyncs + potentially directory fsyncs
        assert mock_fsync.call_count >= 3


def test_fs_adapter_read_workspace_existing_files(tmp_path: Path, staged_workspace: StagedWorkspace):
    """Verify read_workspace_existing_files discovers and reads already existing files on disk."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)
    target_dir = tmp_path / "azurerm_storage_account" / "sub-prod"
    target_dir.mkdir(parents=True)
    (target_dir / "main.tf").write_text("existing main content\n", encoding="utf-8")

    existing = adapter.read_workspace_existing_files(staged_workspace)
    assert "main.tf" in existing
    assert existing["main.tf"] == "existing main content\n"
    assert "data.tf" not in existing


def test_fs_adapter_rollback_on_write_failure_leaves_clean_dir(tmp_path: Path, staged_workspace: StagedWorkspace):
    """Verify write failure on 2nd file cleans up all temporary files, created directories, and raises FileSystemError."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)

    real_open = open
    open_call_count = 0

    def fail_on_second_open(*args, **kwargs):
        nonlocal open_call_count
        # Check if opening a temp file
        path_str = str(args[0])
        if ".tmp" in path_str:
            open_call_count += 1
            if open_call_count == 2:
                raise OSError("Injected disk write failure")
        return real_open(*args, **kwargs)

    with patch("builtins.open", side_effect=fail_on_second_open):
        with pytest.raises(FileSystemError, match="Disk write failure during atomic workspace commit"):
            adapter.commit_workspace(staged_workspace)

    # Verify no files or directories were left behind
    target_dir = tmp_path / "azurerm_storage_account" / "sub-prod"
    assert not target_dir.exists()
    assert not (tmp_path / "azurerm_storage_account").exists()


def test_fs_adapter_rollback_on_swap_failure_restores_state(tmp_path: Path, staged_workspace: StagedWorkspace):
    """Verify failure during os.replace on 2nd file rolls back previously swapped files."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)

    real_replace = __import__("os").replace
    replace_count = 0

    def fail_on_second_replace(src, dst):
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("Injected atomic swap failure")
        return real_replace(src, dst)

    with patch("os.replace", side_effect=fail_on_second_replace):
        with pytest.raises(FileSystemError, match="atomic swap failure"):
            adapter.commit_workspace(staged_workspace)

    # After rollback, 1st swapped file must be removed and directory cleaned up
    target_dir = tmp_path / "azurerm_storage_account" / "sub-prod"
    assert not (target_dir / "main.tf").exists()
    assert not (target_dir / "data.tf").exists()
    assert not (target_dir / "backend.tf").exists()
    # No tmp or bak files remain
    if target_dir.exists():
        assert list(target_dir.iterdir()) == []


def test_fs_adapter_rollback_restores_preexisting_file(tmp_path: Path, staged_workspace: StagedWorkspace):
    """Verify rollback restores previously existing file contents if swap fails."""
    adapter = DiskFileSystemAdapter(base_dir=tmp_path)
    target_dir = tmp_path / "azurerm_storage_account" / "sub-prod"
    target_dir.mkdir(parents=True)
    initial_backend_content = "# Pre-existing backend state\n"
    (target_dir / "backend.tf").write_text(initial_backend_content, encoding="utf-8")

    real_replace = __import__("os").replace
    replace_count = 0

    def fail_on_second_replace(src, dst):
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise OSError("Injected swap failure on 2nd file (data.tf)")
        return real_replace(src, dst)

    with patch("os.replace", side_effect=fail_on_second_replace):
        with pytest.raises(FileSystemError):
            adapter.commit_workspace(staged_workspace)

    # backend.tf (swap 1) was swapped, but rollback restored it from .bak!
    assert (target_dir / "backend.tf").exists()
    assert (target_dir / "backend.tf").read_text(encoding="utf-8") == initial_backend_content
