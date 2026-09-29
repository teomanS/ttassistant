"""Architectural boundary tests for Hexagonal Architecture enforcement."""

import ast
from pathlib import Path
import pytest

from ttassistant.ports.terminal import TerminalUIPort
from ttassistant.adapters.terminal_adapter import RichTerminalAdapter

# Prohibited UI and external I/O packages inside domain layer (AD-1)
PROHIBITED_DOMAIN_IMPORTS = {
    "rich",
    "questionary",
    "prompt_toolkit",
    "typer",
    "click",
    "ttassistant.adapters",
    "ttassistant.application",
    "ttassistant.cli",
}


def resolve_relative_import(
    file_path: Path,
    project_root: Path,
    level: int,
    module: str | None,
) -> str:
    """Resolve a relative import against the package hierarchy."""
    rel_path = file_path.relative_to(project_root)
    pkg_parts = rel_path.parent.parts

    if level > len(pkg_parts):
        base = ""
    else:
        base = ".".join(pkg_parts[: len(pkg_parts) - level + 1])

    if base and module:
        return f"{base}.{module}"
    if base:
        return base
    return module or ""


def get_imports_from_file(file_path: Path, project_root: Path | None = None) -> set[str]:
    """Parse a python source file into an AST and collect all imported module names (including relative imports)."""
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                # Relative import
                if node.module:
                    resolved = resolve_relative_import(file_path, project_root, node.level, node.module)
                    imports.add(resolved)
                    for alias in node.names:
                        imports.add(f"{resolved}.{alias.name}")
                else:
                    resolved_base = resolve_relative_import(file_path, project_root, node.level, None)
                    for alias in node.names:
                        imports.add(f"{resolved_base}.{alias.name}" if resolved_base else alias.name)
            else:
                if node.module:
                    imports.add(node.module)
                    for alias in node.names:
                        imports.add(f"{node.module}.{alias.name}")
    return imports


def test_hexagonal_packages_exist():
    """Verify standard hexagonal directory structure exists."""
    project_root = Path(__file__).resolve().parent.parent
    base_pkg = project_root / "ttassistant"

    required_dirs = ["domain", "ports", "adapters", "application"]
    for dir_name in required_dirs:
        layer_dir = base_pkg / dir_name
        assert layer_dir.is_dir(), f"Layer directory {layer_dir} missing"
        assert (layer_dir / "__init__.py").is_file(), f"__init__.py missing in {layer_dir}"


def test_domain_layer_isolation_ad1():
    """Verify ttassistant.domain contains zero prohibited UI or adapter imports (AD-1)."""
    project_root = Path(__file__).resolve().parent.parent
    domain_dir = project_root / "ttassistant" / "domain"
    domain_files = list(domain_dir.glob("*.py"))
    assert len(domain_files) > 0, "No domain files found to inspect"

    for py_file in domain_files:
        imports = get_imports_from_file(py_file, project_root)
        for imp in imports:
            for prohibited in PROHIBITED_DOMAIN_IMPORTS:
                assert (
                    imp != prohibited and not imp.startswith(f"{prohibited}.")
                ), f"Boundary Violation (AD-1): Domain file {py_file.name} imports '{imp}'"


def test_scaffold_and_hcl_domain_isolation_ad1():
    """Verify ttassistant.domain.scaffold and ttassistant.domain.hcl contain zero forbidden UI or I/O imports (AD-1)."""
    project_root = Path(__file__).resolve().parent.parent
    domain_dir = project_root / "ttassistant" / "domain"

    scaffold_file = domain_dir / "scaffold.py"
    hcl_file = domain_dir / "hcl.py"

    assert scaffold_file.is_file(), "ttassistant.domain.scaffold missing"
    assert hcl_file.is_file(), "ttassistant.domain.hcl missing"

    for target_file in [scaffold_file, hcl_file]:
        imports = get_imports_from_file(target_file, project_root)
        for imp in imports:
            for prohibited in PROHIBITED_DOMAIN_IMPORTS:
                assert (
                    imp != prohibited and not imp.startswith(f"{prohibited}.")
                ), f"Boundary Violation (AD-1): {target_file.name} imports '{imp}'"


def test_topology_domain_isolation_ad1():
    """Verify ttassistant.domain.topology contains zero forbidden UI, I/O, or hcl2 imports (AD-1, AD-2)."""
    project_root = Path(__file__).resolve().parent.parent
    domain_dir = project_root / "ttassistant" / "domain"
    topology_file = domain_dir / "topology.py"

    assert topology_file.is_file(), "ttassistant.domain.topology missing"

    imports = get_imports_from_file(topology_file, project_root)
    # Strictly prohibited imports in topology domain (including hcl2 which is reserved for Phase 2)
    prohibited_topology = PROHIBITED_DOMAIN_IMPORTS | {"hcl2", "python-hcl2", "ttassistant.ports"}
    for imp in imports:
        for prohibited in prohibited_topology:
            assert (
                imp != prohibited and not imp.startswith(f"{prohibited}.")
            ), f"Boundary Violation (AD-1/AD-2): topology.py imports '{imp}'"


def test_ports_layer_isolation():
    """Verify ttassistant.ports does not import from adapters or application layers."""
    project_root = Path(__file__).resolve().parent.parent
    ports_dir = project_root / "ttassistant" / "ports"
    ports_files = list(ports_dir.glob("*.py"))
    assert len(ports_files) > 0, "No ports files found to inspect"

    prohibited_in_ports = {
        "ttassistant.adapters",
        "ttassistant.application",
        "ttassistant.cli",
    }
    for py_file in ports_files:
        imports = get_imports_from_file(py_file, project_root)
        for imp in imports:
            for prohibited in prohibited_in_ports:
                assert (
                    imp != prohibited and not imp.startswith(f"{prohibited}.")
                ), f"Boundary Violation: Ports file {py_file.name} imports '{imp}'"


def test_application_layer_isolation_ad1():
    """Verify ttassistant.application contains zero prohibited UI or CLI framework imports (AD-1)."""
    project_root = Path(__file__).resolve().parent.parent
    app_dir = project_root / "ttassistant" / "application"
    app_files = list(app_dir.glob("*.py"))
    assert len(app_files) > 0, "No application files found to inspect"

    prohibited = {
        "rich",
        "questionary",
        "prompt_toolkit",
        "typer",
        "click",
        "ttassistant.adapters",
        "ttassistant.cli",
    }
    for py_file in app_files:
        imports = get_imports_from_file(py_file, project_root)
        for imp in imports:
            for p in prohibited:
                assert (
                    imp != p and not imp.startswith(f"{p}.")
                ), f"Boundary Violation (AD-1): Application file {py_file.name} imports '{imp}'"


def test_terminal_ui_port_runtime_checkable():
    """Verify TerminalUIPort is a runtime_checkable Protocol satisfied by RichTerminalAdapter."""
    adapter = RichTerminalAdapter()
    assert isinstance(adapter, TerminalUIPort)


def test_standards_source_port_runtime_checkable():
    """Verify StandardsSourcePort is a runtime_checkable Protocol satisfied by MarkdownStandardsAdapter."""
    from ttassistant.adapters.standards_adapter import MarkdownStandardsAdapter
    from ttassistant.ports.standards_source import StandardsSourcePort


    adapter = MarkdownStandardsAdapter()
    assert isinstance(adapter, StandardsSourcePort)


def test_diff_domain_isolation_ad1():
    """Verify ttassistant.domain.diff contains zero forbidden UI or I/O imports (AD-1)."""
    project_root = Path(__file__).resolve().parent.parent
    diff_file = project_root / "ttassistant" / "domain" / "diff.py"
    assert diff_file.is_file(), "ttassistant.domain.diff missing"

    imports = get_imports_from_file(diff_file, project_root)
    for imp in imports:
        for prohibited in PROHIBITED_DOMAIN_IMPORTS:
            assert (
                imp != prohibited and not imp.startswith(f"{prohibited}.")
            ), f"Boundary Violation (AD-1): diff.py imports '{imp}'"


def test_filesystem_port_runtime_checkable():
    """Verify FileSystemPort is a runtime_checkable Protocol satisfied by DiskFileSystemAdapter."""
    from ttassistant.adapters.fs_adapter import DiskFileSystemAdapter
    from ttassistant.ports.filesystem import FileSystemPort

    adapter = DiskFileSystemAdapter()
    assert isinstance(adapter, FileSystemPort)


def test_hcl_parser_port_runtime_checkable():
    """Verify HCLParserPort is a runtime_checkable Protocol satisfied by ReadOnlyHclAdapter."""
    from ttassistant.adapters.hcl_adapter import ReadOnlyHclAdapter
    from ttassistant.ports.hcl_parser import HCLParserPort

    adapter = ReadOnlyHclAdapter()
    assert isinstance(adapter, HCLParserPort)


def test_hcl_parser_port_isolation_ad1():
    """Verify ttassistant.ports.hcl_parser contains zero imports of hcl2 or adapters (AD-1, AD-2)."""
    project_root = Path(__file__).resolve().parent.parent
    port_file = project_root / "ttassistant" / "ports" / "hcl_parser.py"
    assert port_file.is_file(), "hcl_parser.py missing"

    imports = get_imports_from_file(port_file, project_root)
    forbidden = {"hcl2", "python-hcl2", "ttassistant.adapters", "ttassistant.application", "ttassistant.cli"}
    for imp in imports:
        for f in forbidden:
            assert (
                imp != f and not imp.startswith(f"{f}.")
            ), f"Boundary Violation: hcl_parser.py imports '{imp}'"


def test_all_domain_files_isolate_hcl2_ad1():
    """Verify all domain files strictly forbid importing hcl2 (AD-1, AD-2)."""
    project_root = Path(__file__).resolve().parent.parent
    domain_dir = project_root / "ttassistant" / "domain"
    for py_file in domain_dir.glob("*.py"):
        imports = get_imports_from_file(py_file, project_root)
        for imp in imports:
            assert (
                imp != "hcl2" and not imp.startswith("hcl2.") and "python-hcl2" not in imp
            ), f"Boundary Violation: Domain file {py_file.name} imports '{imp}'"


def test_resource_catalog_port_runtime_checkable():
    """Verify ResourceCatalogPort is a runtime_checkable Protocol satisfied by JsonResourceCatalogAdapter."""
    from ttassistant.adapters.catalog_adapter import JsonResourceCatalogAdapter
    from ttassistant.ports.catalog import ResourceCatalogPort

    adapter = JsonResourceCatalogAdapter()
    assert isinstance(adapter, ResourceCatalogPort)


def test_resource_catalog_port_isolation_ad1():
    """Verify ttassistant.ports.catalog contains zero imports of adapters, application, or cli (AD-1)."""
    project_root = Path(__file__).resolve().parent.parent
    port_file = project_root / "ttassistant" / "ports" / "catalog.py"
    assert port_file.is_file(), "catalog.py missing in ports"

    imports = get_imports_from_file(port_file, project_root)
    forbidden = {"ttassistant.adapters", "ttassistant.application", "ttassistant.cli"}
    for imp in imports:
        for f in forbidden:
            assert (
                imp != f and not imp.startswith(f"{f}.")
            ), f"Boundary Violation: ports/catalog.py imports '{imp}'"


def test_catalog_adapter_zero_external_network_binaries():
    """Verify JsonResourceCatalogAdapter strictly forbids external network/cloud client libraries (AD-3, NFR-5)."""
    project_root = Path(__file__).resolve().parent.parent
    adapter_file = project_root / "ttassistant" / "adapters" / "catalog_adapter.py"
    assert adapter_file.is_file(), "catalog_adapter.py missing in adapters"

    imports = get_imports_from_file(adapter_file, project_root)
    forbidden = {
        "requests",
        "urllib3",
        "httpx",
        "aiohttp",
        "azure",
        "azure.identity",
        "azure.mgmt",
        "msrest",
    }
    for imp in imports:
        for f in forbidden:
            assert (
                imp != f and not imp.startswith(f"{f}.")
            ), f"Boundary Violation: catalog_adapter.py imports '{imp}'"


def test_relative_import_inspection_catches_violations(tmp_path):
    """Verify get_imports_from_file correctly catches relative imports of prohibited layers."""
    project_root = tmp_path
    domain_dir = project_root / "ttassistant" / "domain"
    domain_dir.mkdir(parents=True)

    bad_file = domain_dir / "bad_module.py"
    bad_file.write_text(
        "from ..adapters.terminal_adapter import RichTerminalAdapter\n"
        "from .. import application\n"
    )

    imports = get_imports_from_file(bad_file, project_root)
    assert "ttassistant.adapters.terminal_adapter" in imports
    assert "ttassistant.application" in imports

    # Ensure prohibited check catches both
    violations = [
        imp for imp in imports
        if any(imp == p or imp.startswith(f"{p}.") for p in PROHIBITED_DOMAIN_IMPORTS)
    ]
    assert len(violations) >= 2
