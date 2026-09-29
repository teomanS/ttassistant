---
title: 'Story 2.2: Targeted Read-Only HCL AST Extraction for Networking & Resource Groups (Phase 2)'
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

**Problem:** Fast lexical indexing from Phase 1 identifies candidate files, but cannot reliably extract structured attributes (e.g. subnet CIDRs, virtual network bindings, Private Endpoint flags, or parent Resource Groups) without understanding HCL block semantics and nested structures.

**Approach:** Implement Phase 2 of the Two-Phase Discovery Pipeline (AD-2): a pure-Python read-only AST parser adapter (`ttassistant.adapters.hcl_adapter`) leveraging `python-hcl2` to extract typed domain models (`SubnetCandidate`, `VirtualNetworkCandidate`, `ResourceGroupCandidate`, `DiscoveredTopology`) from candidate `.tf` files, classify Private Endpoint subnets via naming/attribute/standards heuristics, and enforce strictly zero comment stripping or round-trip HCL dumping.

## Boundaries & Constraints

**Always:**
- Strictly read-only AST parsing using `python-hcl2` (imported as `hcl2`); never call `hcl2.dump()` or write back to scanned files (AD-2).
- Keep domain entities (`SubnetCandidate`, `VirtualNetworkCandidate`, `ResourceGroupCandidate`, `DiscoveredTopology`) inside `ttassistant.domain.topology`, completely free from `hcl2`, terminal UI, or file I/O imports (AD-1).
- Define abstract parser interface `HCLParserPort` in `ttassistant.ports.hcl_parser` as a `@runtime_checkable` Protocol (AD-1).
- Normalize `python-hcl2` AST artifacts (strip enclosing string quotes `"\"..."\"`, parse address prefixes list and singular strings, resolve string references) into clean Python values.
- Support both standalone `azurerm_subnet` resources and inline `subnet { ... }` blocks declared inside `azurerm_virtual_network`.
- Support `data "azurerm_subnet"`, `data "azurerm_virtual_network"`, and `data "azurerm_resource_group"` blocks when encountered.
- Identify Private Endpoint subnets using multi-factor heuristics: attributes (`private_endpoint_network_policies_enabled`), name/tag tokens (`pe`, `private`, `privatelink`, `paas`), and `common_standards/networking_policy.md` subnet pattern globs.
- Handle malformed or unparseable HCL files gracefully by logging a warning/recording parse error without aborting the entire scan across other files.

**Never:**
- Never call external `terraform` or `az` CLI binaries (FR-3, NFR-5).
- Never serialize or dump AST back to disk; AST parsing is strictly read-only (AD-2).
- Never allow `ttassistant.domain` or `ttassistant.ports` to import `python-hcl2` / `hcl2` (AD-1).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Standalone Subnet Resource | Candidate file with `resource "azurerm_subnet" "snet"` containing `address_prefixes = ["10.0.1.0/24"]` | Emits `SubnetCandidate(name="snet", address_prefixes=["10.0.1.0/24"], is_inline=False)` | Strips AST quotes, handles missing fields |
| Inline Subnet in VNet | Candidate file with `resource "azurerm_virtual_network"` containing `subnet { name = "pe" address_prefix = "10.0.2.0/24" }` | Emits `VirtualNetworkCandidate` and nested `SubnetCandidate(is_inline=True)` | Fallback from singular `address_prefix` to `address_prefixes` list |
| Resource Group Extraction | Candidate file with `resource "azurerm_resource_group" "rg"` | Emits `ResourceGroupCandidate(name=..., location=..., tags=...)` | Strips quotes from keys and string literals |
| Data Source Discovery | Candidate file with `data "azurerm_subnet" "pe"` | Discovered as candidate subnet with `is_data_source=True` | Extracts upstream dependency reference cleanly |
| Private Endpoint Heuristics | Subnet with name `snet-paas-01` matching standards glob `*snet-paas*` | Flagged with `is_private_endpoint_candidate=True` | Evaluates regex, tags, and standards patterns |
| Malformed / Invalid HCL | File containing invalid syntax e.g. unclosed braces | Logs warning, records file error in `DiscoveredTopology.parse_errors`, continues scanning remaining candidates | Catches Lark/hcl2 parser exceptions gracefully |
| Empty Candidate List | Empty list of candidate files passed | Returns empty `DiscoveredTopology` immediately | N/A |

</frozen-after-approval>

## Code Map

- `ttassistant/domain/topology.py` -- Add `SubnetCandidate`, `VirtualNetworkCandidate`, `ResourceGroupCandidate`, `DiscoveredTopology`, and pure `is_private_endpoint_subnet` classifier.
- `ttassistant/ports/hcl_parser.py` -- Define abstract `HCLParserPort` protocol.
- `ttassistant/adapters/hcl_adapter.py` -- Concrete `ReadOnlyHclAdapter` wrapping `python-hcl2` with AST traversal, string unquoting, and error isolation.
- `ttassistant/cli.py` -- Extend `scan` command to support `--ast` flag to print discovered subnets and resource groups.
- `tests/test_hcl_adapter.py` -- Unit tests for HCL AST extraction: standalone/inline subnets, VNets, Resource Groups, data sources, PE heuristics, and malformed files.
- `tests/test_architecture.py` -- Validate boundary rules: ensure `hcl2` is never imported in `domain/` or `ports/`.

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/domain/topology.py` -- Define domain entities (`SubnetCandidate`, `VirtualNetworkCandidate`, `ResourceGroupCandidate`, `DiscoveredTopology`) and pure `is_private_endpoint_subnet` heuristic function.
- [x] `ttassistant/ports/hcl_parser.py` -- Create `HCLParserPort` Protocol with `parse_topology_candidates` and `parse_hcl_string` signatures.
- [x] `ttassistant/adapters/hcl_adapter.py` -- Implement `ReadOnlyHclAdapter` using `python-hcl2` to parse candidates into domain entities with AST string sanitization and fault tolerance.
- [x] `ttassistant/cli.py` -- Add `--ast` option to `ttassistant scan` command displaying extracted subnets and resource groups.
- [x] `tests/test_hcl_adapter.py` -- Comprehensive test suite covering all AST extraction scenarios and edge cases.
- [x] `tests/test_architecture.py` -- Verify architectural isolation for HCL parser port and adapter.

**Acceptance Criteria:**
- Given candidate `.tf` files from Phase 1 indexing.
- When `ReadOnlyHclAdapter.parse_topology_candidates` processes candidate files.
- Then it parses HCL AST in-memory to identify declared `azurerm_subnet` blocks (name, address_prefixes, tags, VNet/RG links) and `azurerm_resource_group` blocks.
- It identifies candidate subnets designated for Private Endpoints based on naming, subnet attributes, and `common_standards/` heuristics.
- `python-hcl2` is strictly used in read-only mode, with zero round-trip `hcl2.dump()` calls.

## Implementation Notes

- Implemented pure domain entities `SubnetCandidate`, `VirtualNetworkCandidate`, `ResourceGroupCandidate`, and `DiscoveredTopology` in `ttassistant.domain.topology` (AD-1).
- Implemented pure multi-factor `is_private_endpoint_subnet` classifier combining attribute checks (`private_endpoint_network_policies_enabled`), standards pattern globs from `networking_policy.md`, token-bounded naming rules, and tag tokens without external I/O or `hcl2` dependencies.
- Created `@runtime_checkable` `HCLParserPort` Protocol in `ttassistant.ports.hcl_parser` defining `parse_topology_candidates`, `parse_hcl_file`, and `parse_hcl_string`.
- Implemented `ReadOnlyHclAdapter` in `ttassistant.adapters.hcl_adapter` wrapping `python-hcl2` strictly in read-only mode (`hcl2.dump()` is prohibited per AD-2). Handled AST quote normalization, singular `address_prefix` fallback, inline and standalone subnet discovery, data sources, and intra/cross-file reference resolution scoped by subscription.
- Extended `ttassistant scan` CLI command with `--ast` flag to render formatted Rich tables of discovered networking and resource group entities.
- Addressed all triaged review findings (token-bounded PE patterns, boolean flag validation, inline attribute extraction, subscription-scoped label resolution, and cross-platform maxrss calculations).
- Verified complete test suite passing 241 tests in 19.18s.

## Spec Change Log

## Review Triage Log

- `ttassistant/domain/topology.py`: `DEFAULT_PE_PATTERNS` bare `*pe*` matches common words like `developer` and `operations` — Verdict: `medium` — Fix: use token-bounded patterns (`*pe-*`, `*-pe`, `*-pe-*`, `*snet-pe*`).
- `ttassistant/domain/topology.py`: `if network_policies_enabled is not None: return True` classifies `False` as PE candidate — Verdict: `high` — Fix: check `if network_policies_enabled is True: return True`.
- `ttassistant/adapters/hcl_adapter.py`: Inline subnets inside VNet omit `private_endpoint_network_policies_enabled` and `tags` extraction — Verdict: `medium` — Fix: extract attributes and tags on inline blocks.
- `ttassistant/adapters/hcl_adapter.py`: Global `rg_by_label` / `vnet_by_label` cross-file resolution clobbers labels across subscriptions — Verdict: `medium` — Fix: scope label lookup by subscription / directory.
- `ttassistant/domain/topology.py`: `DiscoveredTopology.__len__` returns `len(self.subnets)` resulting in false falsiness when subnets are empty — Verdict: `medium` — Fix: sum subnets, VNets, and resource groups.
- `ttassistant/cli.py`: `--subscription unassigned` drops unassigned candidates — Verdict: `low` — Fix: query `index.get_candidates_for_subscription(subscription)`.
- `ttassistant/domain/topology.py`: `infer_subscription` slices off directory name with dot — Verdict: `low` — Fix: check `.endswith((".tf", ".tf.json"))`.
- `ttassistant/domain/topology.py`: `CandidateFile.normalize_path` converts `None` to `"None"` string — Verdict: `low` — Fix: reject `None` with `ValueError`.
- `ttassistant/ports/__init__.py` & `ttassistant/adapters/__init__.py`: Incomplete package exports — Verdict: `low` — Fix: export all ports and adapters in `__all__`.
- `ttassistant/ports/hcl_parser.py`: Missing `parse_hcl_file` on `HCLParserPort` Protocol — Verdict: `low` — Fix: declare `parse_hcl_file` on port.
- `ttassistant/cli.py`: Hardcodes `"default"` networking policy and ignores `-r / --resource-type` — Verdict: `low` — Fix: pass `resource_type or "default"`.
- `ttassistant/domain/topology.py`: Overly broad tag check `"endpoint"` matches service endpoints — Verdict: `low` — Fix: match `"private_endpoint"`, `"privatelink"`, or `"pe"`.
- `tests/test_hcl_adapter.py`: Missing test for cross-file reference resolution across separate candidate files — Verdict: `low` — Fix: add multi-file cross-reference test.
- `tests/test_hcl_adapter.py`: Missing test for naming token heuristics with non-matching globs — Verdict: `low` — Fix: test `is_private_endpoint_subnet` with `standards_patterns=[]`.
- `tests/test_topology_scanner.py`: macOS benchmark failure on `ru_maxrss` bytes vs KB — Verdict: `low` — Fix: account for `sys.platform == "darwin"`.
- `ttassistant/adapters/hcl_adapter.py`: Target reference unresolvable inside `${...}` keeps `${}` — Verdict: `false` — Normal behavior when target resource is external/missing.

## Verification

**Commands:**
- `./.venv/bin/pytest tests/test_hcl_adapter.py` -- expected: All HCL AST extraction tests pass.
- `./.venv/bin/pytest tests/test_architecture.py` -- expected: All architectural boundaries pass (no hcl2 in domain/ports).
- `./.venv/bin/pytest` -- expected: Complete test suite passes.
- `./.venv/bin/python -m ttassistant scan --ast` -- expected: Displays extracted AST entities cleanly.

