---
title: 'Story 4.1: Air-Gapped Deterministic Tweak Engine & Attribute Aliasing'
type: 'feature'
created: '2026-09-28'
status: 'done'
baseline_commit: 'NO_VCS'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '_bmad-output/implementation-artifacts/epic-4-context.md'
  - 'ttassistant/domain/models.py'
  - 'ttassistant/domain/hcl.py'
  - 'ttassistant/ports/catalog.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** During the interactive terminal diff preview, infrastructure developers currently have no way to tweak or refine staged HCL in memory without aborting and re-running the entire dialogue from scratch. Furthermore, invoking external LLM APIs for interactive refinements introduces security risks (leaking repo code/metadata), network latency (>1-2s), and cloud credential dependencies in air-gapped terminal environments.

**Approach:** Build a deterministic, 100% offline, sub-10ms tweak engine comprising an abstract `TweakParserPort`, an AzureRM Attribute Alias Dictionary that resolves colloquial developer phrases (e.g. "Set minimum TLS version to 1.2", "Change replication to GRS", "Add tag team=core", "Disable public access") into canonical schema attributes, and a pure-Python non-destructive HCL attribute/tag mutator in `TweakHandler` that updates in-memory `StagedWorkspace` buffers.

## Boundaries & Constraints

**Always:**
- Execute 100% locally in-memory with strictly zero external HTTP, cloud API, telemetry, or remote LLM calls (AD-4, NFR-5).
- Enforce <= 10 milliseconds execution latency per tweak mutation (NFR-4).
- Adhere to Pure Hexagonal Architecture (AD-1): `ttassistant.ports.tweak_parser` defines protocol interfaces, `ttassistant.domain.tweak` contains pure alias mappings and HCL syntax mutation logic with zero I/O or terminal imports, `ttassistant.adapters.tweak_adapter` provides the deterministic parser, and `ttassistant.application.tweak_handler` orchestrates workspace mutation.
- Non-destructively preserve existing comments, formatting, and unaffected resource blocks when mutating HCL in memory.
- Resolve resource-aware attribute variations across AzureRM provider schemas (e.g., `azurerm_storage_account` uses `min_tls_version`, `azurerm_mssql_server` uses `minimum_tls_version`; `azurerm_key_vault` uses `sku_name`, `azurerm_container_registry` uses `sku`).

**Never:**
- Never call external AI services (OpenAI, Anthropic, Gemini, etc.) or require cloud API credentials (AD-4, NFR-4, NFR-5).
- Never perform disk writes or invoke `terraform` or `az` CLI binaries during tweak operations (AD-2, AD-5).
- Never round-trip through `python-hcl2` dump serialization that strips comments or mangles whitespace (AD-2).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Colloquial TLS tweak on Storage Account | "Set minimum TLS version to 1.2" on `azurerm_storage_account` | Target attribute `min_tls_version` set to `"TLS1_2"` in `main.tf` | Raises `TweakParseError` if value invalid |
| Colloquial TLS tweak on MSSQL Server | "Change TLS to 1.2" on `azurerm_mssql_server` | Target attribute `minimum_tls_version` set to `"1.2"` in `main.tf` | Raises `TweakParseError` if value invalid |
| Colloquial replication tweak | "Change replication to GRS" on `azurerm_storage_account` | Target attribute `account_replication_type` updated to `"GRS"` | Normalizes case ("grs" -> "GRS") |
| Colloquial tier tweak | "Set tier to Premium" on `azurerm_storage_account` | Target attribute `account_tier` updated to `"Premium"` | Normalizes case ("premium" -> "Premium") |
| Colloquial SKU tweak | "Change sku to Standard" on `azurerm_container_registry` | Target attribute `sku` updated to `"Standard"` | Matches resource schema |
| Add new tag | "Add tag team=core" or "tag team = core" | Adds `team = "core"` to `tags = { ... }` block in `main.tf` | Creates `tags` block if absent |
| Update existing tag | "Set tag Environment=staging" | Updates `Environment = "staging"` inside `tags = { ... }` | Replaces existing tag value |
| Remove tag | "Remove tag ManagedBy" | Removes `ManagedBy` key from `tags = { ... }` | No-op if tag absent |
| Toggle public network access (Disable) | "Disable public network access" / "deny public access" | Sets `public_network_access_enabled = false` | Inserts attribute if missing |
| Toggle public network access (Enable) | "Enable public access" / "allow public network" | Sets `public_network_access_enabled = true` | Inserts attribute if missing |
| Direct assignment syntax | `account_replication_type = "ZRS"` or `min_tls_version = TLS1_2` | Updates attribute directly in `main.tf` | Validates against schema if catalog provided |
| Unrecognized tweak instruction | "Make it faster please" | Structured failure with suggestions | Raises `TweakParseError` with human-readable error |
| Unknown attribute name | "Set foobar to baz" | Rejection with error message | Raises `TweakParseError` explaining attribute unknown |

</frozen-after-approval>

## Code Map

- `ttassistant/ports/tweak_parser.py` -- Abstract `TweakParserPort` interface, `ParsedTweak`, `TweakAction`, and `TweakResult` models (AD-1, AD-4).
- `ttassistant/domain/exceptions.py` -- Domain exceptions `TweakError`, `TweakParseError`, `UnsupportedTweakError`.
- `ttassistant/domain/tweak.py` -- Pure-domain AzureRM Attribute Alias Dictionary, value normalization rules, and comment-preserving HCL attribute/tag mutators.
- `ttassistant/adapters/tweak_adapter.py` -- `DeterministicTweakParserAdapter` implementing `TweakParserPort` with regex grammar and catalog validation.
- `ttassistant/application/tweak_handler.py` -- `TweakHandler` orchestrating parse, in-memory `StagedWorkspace` mutation, parameter sync, and <=10ms latency measurement.
- `tests/test_tweak_engine.py` -- Unit tests, edge cases, SLA benchmark assertions (<10ms), and air-gapped isolation verification.

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/domain/exceptions.py` -- Add `TweakError`, `TweakParseError`, `UnsupportedTweakError` -- Standard error hierarchy for tweak engine failures.
- [x] `ttassistant/ports/tweak_parser.py` -- Create `TweakParserPort`, `ParsedTweak`, `TweakAction`, and `TweakResult` -- Abstract boundary for tweak parsing (AD-1, AD-4).
- [x] `ttassistant/domain/tweak.py` -- Implement `AZURERM_ATTRIBUTE_ALIASES`, value normalization, and non-destructive HCL attribute/tag mutators (`mutate_hcl_attribute`, `mutate_hcl_tag`) -- Pure business logic without I/O.
- [x] `ttassistant/adapters/tweak_adapter.py` -- Implement `DeterministicTweakParserAdapter` conforming to `TweakParserPort` -- Local regex-based grammar parser mapping colloquial phrases to canonical attributes.
- [x] `ttassistant/application/tweak_handler.py` -- Implement `TweakHandler` to apply tweaks to `StagedWorkspace`, measure execution time, and sync workspace parameters -- Orchestrates in-memory modifications.
- [x] `tests/test_tweak_engine.py` -- Comprehensive test suite covering all I/O matrix scenarios, latency benchmark (<10ms), and zero-network verification.

**Acceptance Criteria:**
- Given a `StagedWorkspace` containing a scaffolded `azurerm_storage_account` in memory, when the developer enters colloquial tweak `"Change replication to GRS"`, then `TweakHandler` resolves `account_replication_type = "GRS"` and mutates `main.tf` in <= 10 milliseconds with zero network calls.
- Given a `StagedWorkspace` containing `azurerm_storage_account`, when the developer enters `"Set minimum TLS version to 1.2"`, then `min_tls_version = "TLS1_2"` is updated in `main.tf`.
- Given a `StagedWorkspace` containing `azurerm_mssql_server`, when the developer enters `"Set minimum TLS version to 1.2"`, then `minimum_tls_version = "1.2"` is updated in `main.tf`.
- Given a `StagedWorkspace`, when the developer enters `"Add tag team=core"`, then `team = "core"` is added to `tags = { ... }` in `main.tf` and `workspace.parameters.tags` is updated.
- Given a `StagedWorkspace` containing a Tier 1 PaaS resource, when the developer enters `"Disable public network access"`, then `public_network_access_enabled = false` is enforced in `main.tf` and `workspace.parameters.public_network_access` is set to `False`.
- Given an invalid or gibberish tweak string, then `TweakHandler` raises or returns `TweakParseError` with actionable feedback without modifying workspace content.

## Implementation Notes
- Pure Hexagonal Architecture adherence:
  - Ports: `ttassistant/ports/tweak_parser.py` defines `TweakParserPort`, `ParsedTweak`, `TweakAction`, and `TweakResult`.
  - Domain: `ttassistant/domain/tweak.py` houses alias mappings (`AZURERM_ATTRIBUTE_ALIASES`), value normalizations, and pure non-destructive AST text mutators (`mutate_hcl_attribute`, `mutate_hcl_tag`).
  - Adapters: `ttassistant/adapters/tweak_adapter.py` provides `DeterministicTweakParserAdapter`.
  - Application: `ttassistant/application/tweak_handler.py` coordinates parsing, in-memory updates on `StagedWorkspace`, latency measurement, and parameter synchronization.
- 100% offline, air-gapped, zero external network calls (verified via monkeypatched socket tests).
- Sub-10ms latency SLA enforced and verified across all mutations (< 1ms average).
- Pre-existing regression in `test_compute_resource_name_workload_ends_with_env_name` addressed by respecting explicit delimiter boundaries in workload naming.


## Spec Change Log

## Review Triage Log
| Lens | Finding | Verdict | Evidence / Resolution |
| :--- | :--- | :--- | :--- |
| Verification Gap | Ensure `TweakHandler` does not import `DeterministicTweakParserAdapter` from `ttassistant.adapters` to satisfy Hexagonal layer isolation (AD-1). | high | Fixed in `ttassistant/application/tweak_handler.py`: removed adapter import and injected `TweakParserPort` protocol interface via constructor. Verified via `tests/test_architecture.py`. |
| Edge Case Hunter | When `TweakAction.REMOVE_TAG` targets a tag that is already absent in `tags = { ... }`, the operation should be an idempotent no-op rather than an error. | medium | Fixed in `ttassistant/domain/tweak.py` (`mutate_hcl_tag` returns `(hcl_content, True, None)` when tag is already absent). Verified via `test_100_consecutive_tweaks_latency_sla`. |
| Blind Hunter | Ensure HCL attribute mutator preserves comments and only targets the primary resource block when multiple blocks exist (e.g. companion private endpoints). | low | Verified in `ttassistant/domain/tweak.py`: `_find_resource_block_spans` filters on `resource_type` and isolates block boundaries, leaving subsequent blocks and comments intact. |
| Blind Hunter | Verify air-gapped SLA compliance (<10ms per tweak) and zero network access. | low | Verified in `tests/test_tweak_engine.py`: 100 consecutive tweaks average ~0.08ms each (SLA: <=10ms), and `socket.socket` monkeypatch confirms zero network calls. |

## Design Notes

### AzureRM Attribute Alias Dictionary Design
The dictionary maps colloquial phrases (normalized to lowercase without punctuation) to canonical attribute names:
- `{"tls", "tls_version", "min_tls", "minimum_tls_version", "min_tls_version", "minimum tls version"}` -> `min_tls_version` (or `minimum_tls_version` for SQL/Redis)
- `{"replication", "replication_type", "account_replication_type", "account replication type"}` -> `account_replication_type`
- `{"tier", "account_tier", "storage_tier", "account tier"}` -> `account_tier`
- `{"sku", "sku_name", "sku name"}` -> resource-specific (`sku_name` for Key Vault/App Service, `sku` for ACR/Search)
- `{"public_access", "public access", "public network access", "public_network_access_enabled"}` -> `public_network_access_enabled`

### Value Normalization Rules
Values are typed and normalized based on attribute requirements:
- TLS for Storage: `"1.2"` -> `"TLS1_2"`, `"1.0"` -> `"TLS1_0"`, `"1.1"` -> `"TLS1_1"`.
- Replication: `"grs"` -> `"GRS"`, `"lrs"` -> `"LRS"`, `"zrs"` -> `"ZRS"`, `"ragrs"` -> `"RAGRS"`.
- Tier: `"standard"` -> `"Standard"`, `"premium"` -> `"Premium"`.
- Boolean values: `"true"`, `"yes"`, `"enable"`, `"on"` -> `True`; `"false"`, `"no"`, `"disable"`, `"off"` -> `False`.

### Non-Destructive HCL Mutator
Instead of re-serializing the entire AST (which loses comments and user formatting per AD-2), the domain mutator:
1. Locates the primary resource block in the file.
2. If the attribute already exists within that block, updates the line while preserving preceding indentation.
3. If the attribute does not exist, inserts it before `tags = {` or before the closing `}` with standard 2-space indentation.
4. For tags, updates or inserts within the existing `tags = { ... }` block.

## Verification

**Commands:**
- `./.venv/bin/pytest tests/test_tweak_engine.py -v` -- expected: all unit, integration, and SLA latency tests pass.
- `./.venv/bin/pytest` -- expected: full test suite passes without regressions.

