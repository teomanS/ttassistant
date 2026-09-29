---
title: 'Story 2.1: Monorepo Topology Traversal & Lexical Candidate Indexer (Phase 1)'
type: 'feature'
created: '2026-09-23'
status: 'done'
baseline_commit: 'NO_VCS'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '_bmad-output/planning-artifacts/architecture/architecture-ttassistant-2026-09-21/ARCHITECTURE-SPINE.md'
  - '_bmad-output/implementation-artifacts/epic-2-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Large Terraform monorepos contain thousands of directories with non-uniform naming (e.g. `resource-groups/sub-prod/` vs `rg/sub_prod/`), making full AST parsing across every file prohibitively slow (>30s) and memory-intensive, which blocks rapid interactive guided provisioning.

**Approach:** Implement Phase 1 of the Two-Phase Discovery Pipeline (AD-2): a high-speed streaming repository walker in `ttassistant.adapters.fs_adapter` and a pure-Python lexical candidate indexer in `ttassistant.domain.topology` that scans monorepo `.tf` files in <= 3.0s (<150 MB RSS), filters for networking and Resource Group blocks via streaming keyword pre-filtering, and maps candidate files to subscriptions in-memory.

## Boundaries & Constraints

**Always:**
- Keep pure domain logic (`ttassistant.domain.topology`) strictly decoupled from filesystem I/O and UI libraries (AD-1).
- Use fast streaming file traversal (`os.scandir`) to ignore irrelevant directories (`.git`, `.terraform`, `.venv`, `__pycache__`, `node_modules`, `dist`, `build`, `.bin`) without loading complete directory trees into memory (AD-2, NFR-2, NFR-3).
- Only inspect `.tf` files, streaming lines to detect candidate resource/data blocks (`azurerm_subnet`, `azurerm_virtual_network`, `azurerm_resource_group`) without executing AST parsing or loading file contents entirely when not needed (AD-2).
- Infer target subscription from path segments and folder conventions (e.g. `<resource-type>/<subscription>/`, `subscription = "..."` attributes, or known subscription patterns).
- Complete monorepo indexing of up to 10,000 files in <= 3.0 seconds with process memory under 150 MB RSS (NFR-2, NFR-3).
- Execute purely air-gapped with zero network calls and zero external binaries (AD-2, NFR-5).

**Never:**
- Never execute AST parsing (`python-hcl2`) in Phase 1 (reserved strictly for Phase 2 in Story 2.2).
- Never invoke external `find`, `grep`, `terraform`, or `az` CLI binaries.
- Never write or modify files during repository traversal (strictly read-only discovery).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Standard Monorepo Traversal | Monorepo root containing `<type>/<sub-prod>/main.tf` with `azurerm_subnet` | Discovers `.tf`, matches `azurerm_subnet`, maps candidate to `sub-prod` | N/A |
| Ignored Directories | Directory tree containing `.terraform/`, `.git/`, `.venv/` with `.tf` files | Ignores all files within ignored directories, zero candidates indexed from them | N/A |
| Non-Uniform Folder Naming | Folders named `rg/sub_prod/` vs `resource-groups/sub-prod/` | Infers subscription `sub-prod` / `sub_prod` and associates resource group candidate | N/A |
| Multiple Resource Types in One File | Single `.tf` file containing `azurerm_virtual_network` and `azurerm_subnet` | Candidate records both resource types in `detected_types` set | N/A |
| Empty Repository or No .tf Files | Empty folder or folder with zero `.tf` files | Returns empty `TopologyIndex` with 0 candidate files | Clean empty result, no error |
| Deeply Nested Monorepo | Monorepo hierarchy nested >10 levels deep | Traverses all levels without recursion overflow or path truncation | Handled iteratively via `os.scandir` |
| Symlink Cycles | Monorepo containing recursive directory symlinks | Follows non-cyclic paths or ignores symlinked directories to prevent infinite loops | Ignores cyclic symlinks |

</frozen-after-approval>

## Code Map

- `ttassistant/domain/topology.py` -- Domain models (`CandidateFile`, `TopologyIndex`) and pure candidate filtering / subscription inference rules (AD-1).
- `ttassistant/ports/filesystem.py` -- Extend `FileSystemPort` to specify streaming `.tf` file traversal (`scan_tf_files`) and streaming candidate pre-filtering.
- `ttassistant/adapters/fs_adapter.py` -- Implement fast `os.scandir` generator in `DiskFileSystemAdapter` skipping ignored directories and streaming candidate detection.
- `ttassistant/cli.py` -- Add optional diagnostic `scan` subcommand to inspect discovered candidates and performance metrics.
- `tests/test_topology.py` -- Unit tests for `CandidateFile`, `TopologyIndex`, and lexical matching.
- `tests/test_topology_scanner.py` -- Integration tests with synthetic directory structures (including ignored folders, nested subfolders, non-uniform naming, and performance benchmark).
- `tests/test_architecture.py` -- Verify AD-1 domain layer purity for `ttassistant.domain.topology`.

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/domain/topology.py` -- Define `CandidateFile`, `TopologyIndex`, and lexical discovery models with pure subscription inference heuristics.
- [x] `ttassistant/ports/filesystem.py` -- Add `scan_tf_files` and `scan_candidates` method signatures to `FileSystemPort`.
- [x] `ttassistant/adapters/fs_adapter.py` -- Implement fast streaming `os.scandir` traversal ignoring `.git`, `.terraform`, `.venv`, etc., with streaming regex/keyword pre-filtering.
- [x] `ttassistant/cli.py` -- Add `scan` command to CLI for diagnostic topology traversal and summary display.
- [x] `tests/test_topology.py` -- Unit tests for domain models, candidate indexing, and subscription resolution.
- [x] `tests/test_topology_scanner.py` -- Test scanner across simulated monorepos, verifying ignored folder exclusion, subscription mapping, and <= 3.0s benchmark.
- [x] `tests/test_architecture.py` -- Assert AD-1 domain isolation for `ttassistant.domain.topology`.

**Acceptance Criteria:**
- Given a repository with up to 10,000 files and non-uniform folder naming (e.g., `resource-groups/sub-prod/` vs `rg/sub_prod/`).
- When the topology scanner executes, then it ignores `.git`, `.terraform`, `.venv`, and binary directories, completing the scan in <= 3.0 seconds with process memory under 150 MB RSS.
- It streams regex/keyword pre-filtering across `.tf` files to identify files containing `azurerm_subnet`, `azurerm_virtual_network`, or `azurerm_resource_group` blocks.
- It maps candidate file paths to their respective subscriptions in memory in a `TopologyIndex`.

## Implementation Notes

- Implemented pure domain models `CandidateFile` and `TopologyIndex` in `ttassistant.domain.topology`.
- Implemented pure lexical matching `extract_candidate_types` with comment filtering and keyword pre-filtering for `azurerm_subnet`, `azurerm_virtual_network`, and `azurerm_resource_group`.
- Implemented `infer_subscription` with multi-tier heuristic detection (attribute hints, folder conventions, naming rules) and `root_dir` relativization.
- Extended `FileSystemPort` in `ttassistant.ports.filesystem` with `scan_tf_files`, `scan_candidates`, and `build_topology_index`.
- Implemented fast streaming `os.scandir` traversal in `DiskFileSystemAdapter` skipping ignored directories and cyclic symlinks, with 64KB chunked reading.
- Added diagnostic `scan` command to `ttassistant/cli.py` with `--subscription` and `--resource-type` filters.
- Added test suites `tests/test_topology.py` and `tests/test_topology_scanner.py` including 10,000-file benchmark, achieving 218 passing tests.

## Spec Change Log

## Review Triage Log

- `ttassistant/domain/topology.py`: Pattern 4 in `infer_subscription` walked up into host directory names — Verdict: `medium` — Patched: relativized against `root_dir` and added `SYSTEM_DIR_TOKENS` filter.
- `ttassistant/domain/topology.py`: Commented-out subscription declarations in `content_hints` were matched — Verdict: `low` — Patched: filtered out `#` and `//` lines prior to regex search.
- `ttassistant/domain/topology.py`: `CandidateFile.normalize_path` did not normalize Windows backslashes — Verdict: `low` — Patched: normalized with `Path(s).as_posix()`.
- `ttassistant/domain/topology.py`: `TopologyIndex.get_candidates_for_subscription("unassigned")` returned empty — Verdict: `low` — Patched: supported querying unassigned candidates.
- `ttassistant/domain/topology.py`: `RESOURCE_DIR_TOKENS` omitted `virtual-networks` and `resource-groups` variants — Verdict: `low` — Patched: added plural and hyphenated variants.
- `ttassistant/adapters/fs_adapter.py`: Code duplication between `scan_candidates` and `build_topology_index` — Verdict: `low` — Patched: unified inspection via `_inspect_tf_file` helper.
- `ttassistant/adapters/fs_adapter.py`: `DEFAULT_IGNORED_DIRS` included `"env"` which could skip valid TF folders — Verdict: `low` — Patched: removed `"env"` (kept `venv`, `.venv`, `.env`).
- `ttassistant/adapters/fs_adapter.py`: `assert dest_path.is_relative_to` disabled under python -O — Verdict: `low` — Patched: replaced with explicit `if not ... raise FileSystemError`.
- `ttassistant/cli.py`: `scan` command failed when `common_standards/` was missing — Verdict: `medium` — Patched: allowed `scan` command execution without requiring standards directory.
- `ttassistant/cli.py`: Non-existent path silently scanned 0 files — Verdict: `low` — Patched: added path validation exiting with code 1 on non-existent directory.
- `ttassistant/ports/filesystem.py`: Port signatures omitted `ignored_dirs` and flexible `target_types` — Verdict: `low` — Patched: aligned signatures with adapter.
- `tests/test_topology_scanner.py`: Missing tests for `scan_candidates` and `scan_tf_files` — Verdict: `low` — Patched: added unit and integration tests for streaming generators.

## Design Notes

- Phase 1 relies on streaming regular expressions (e.g. `re.compile(r'(?:resource|data)\s+"(azurerm_subnet|azurerm_virtual_network|azurerm_resource_group)"')`) executed line-by-line or over 64KB chunks to avoid reading large files into memory.
- Subscription inference utilizes directory path tokens (e.g. matching `sub-prod`, `workload-prod`, or standard corporate subscription patterns) as well as inline provider/block attributes if present.

## Verification

**Commands:**
- `./.venv/bin/pytest` -- expected: All existing 192 tests plus new topology unit and integration tests pass (100% pass rate).
- `./.venv/bin/python -m ttassistant scan .` -- expected: Displays discovered candidate files, detected resource types, inferred subscriptions, and execution time under 3.0s.

