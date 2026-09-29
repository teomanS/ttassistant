---
title: 'Story 3.1: Bundled Offline AzureRM Provider Schema Catalog'
type: 'feature'
created: '2026-09-24'
status: 'done'
baseline_commit: 'NO_VCS'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '_bmad-output/planning-artifacts/architecture/architecture-ttassistant-2026-09-21/ARCHITECTURE-SPINE.md'
  - '_bmad-output/implementation-artifacts/epic-3-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Scaffolding Azure Terraform resources in enterprise air-gapped environments without external internet connectivity or local `terraform`/`az` binaries currently lacks a deterministic, offline schema source for argument validation, leading to guessing argument names, invalid HCL generation, and inability to distinguish between guided Tier 1 PaaS services and Tier 2 universal services.

**Approach:** Package an offline, bundled AzureRM provider schema catalog (`azurerm_schema.json`) under `ttassistant/data/`, backed by a pure-Python in-memory catalog domain service and abstract port/adapter that categorizes resources into Tier 1 (guided PaaS and foundation) and Tier 2 (universal long-tail) services, providing instant offline schema inspection, argument requirements, and validation.

## Boundaries & Constraints

**Always:**
- Keep pure catalog domain logic and models in `ttassistant.domain.catalog`, strictly decoupled from file loading and terminal UI (AD-1).
- Package `azurerm_schema.json` directly under `ttassistant/data/` as a bundled package resource loadable via `importlib.resources` or filesystem path (AD-3, NFR-5).
- Distinguish between Tier 1 (guided Enterprise PaaS and core foundation) and Tier 2 (universal long-tail) resources (AD-3, AD-7):
  - Tier 1 includes: `azurerm_storage_account`, `azurerm_key_vault`, `azurerm_mssql_server`, `azurerm_cosmosdb_account`, `azurerm_eventhub_namespace`, `azurerm_postgresql_flexible_server`, `azurerm_mysql_flexible_server`, `azurerm_redis_cache`, `azurerm_linux_web_app`, `azurerm_virtual_network`, `azurerm_subnet`, `azurerm_resource_group`.
  - Tier 2 includes all other `azurerm_*` resources defined in the schema catalog.
- Support querying required arguments, optional arguments, types, descriptions, and default values for any cataloged resource.
- Keep catalog loading in memory fast (< 50ms) and lightweight (< 15 MB RAM), preserving NFR-1 (< 1.5s cold startup) and NFR-3 (< 150 MB RSS).
- Expose an abstract `ResourceCatalogPort` in `ttassistant.ports.catalog` and a concrete `JsonResourceCatalogAdapter` in `ttassistant.adapters.catalog_adapter`.
- Expose CLI inspection commands/options (`ttassistant catalog` or `ttassistant catalog info <resource>`) to allow offline exploration of resource schemas.
- Operate 100% offline: strictly zero external network requests, zero ARM REST API calls, and zero external CLI binaries (`terraform providers schema` or `az`).

**Never:**
- Never invoke external `terraform` or `az` binaries to extract provider schemas (AD-2, NFR-5).
- Never make outbound network requests or authenticate against Azure APIs (NFR-4, NFR-5).
- Never crash on unknown resource queries; return clear domain errors or `None`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
| :--- | :--- | :--- | :--- |
| Query Tier 1 Resource Schema | `get_resource_schema("azurerm_storage_account")` | Returns `ResourceSchema` with `tier=ResourceTier.TIER_1`, required arguments (`name`, `resource_group_name`, `location`, `account_tier`, `account_replication_type`), and descriptions | N/A |
| Query Tier 2 Resource Schema | `get_resource_schema("azurerm_cognitive_account")` | Returns `ResourceSchema` with `tier=ResourceTier.TIER_2`, argument schemas, and required fields | N/A |
| Check Tier 1 Classification | `is_tier_1("azurerm_key_vault")` / `is_tier_1("azurerm_log_analytics_workspace")` | Returns `True` for Key Vault; returns `False` for Log Analytics Workspace | N/A |
| Query Unknown Resource | `get_resource_schema("azurerm_nonexistent_service")` | Returns `None`; `is_known_resource` returns `False` | Clean `None` / `False`, no exception |
| Search / List Resources | `list_resources(filter_prefix="azurerm_mssql")` | Returns list of matching resource type strings | Returns empty list if no matches |
| Missing or Corrupt Catalog File | Catalog file missing or invalid JSON format | Raises `CatalogError` with descriptive actionable message | Raises `CatalogError` (inherits `TTAssistantError`) |
| CLI Catalog Info Command | `ttassistant catalog info azurerm_storage_account` | Prints formatted Rich table with tier, description, and required/optional arguments | Exit code 0; clean exit |
| CLI Catalog List Command | `ttassistant catalog list --tier 1` | Lists all Tier 1 guided PaaS and foundation services | Exit code 0 |

</frozen-after-approval>

## Code Map

- `ttassistant/data/azurerm_schema.json` -- Bundled offline provider schema catalog containing resource argument definitions, types, descriptions, and required attributes.
- `ttassistant/domain/catalog.py` -- Domain models (`ResourceTier`, `ResourceArgumentSchema`, `ResourceSchema`, `CatalogSummary`) and domain validation logic.
- `ttassistant/ports/catalog.py` -- Protocol interface `ResourceCatalogPort` defining catalog operations.
- `ttassistant/adapters/catalog_adapter.py` -- Concrete adapter `JsonResourceCatalogAdapter` loading and indexing `azurerm_schema.json`.
- `ttassistant/domain/exceptions.py` -- Define `CatalogError` hierarchy.
- `ttassistant/ports/__init__.py` -- Export `ResourceCatalogPort`.
- `ttassistant/cli.py` -- Add `catalog` subcommand group (`catalog list`, `catalog info`) for offline developer exploration.
- `tests/test_catalog.py` -- Comprehensive unit and integration tests covering catalog loading, tier classification, argument extraction, search, error handling, and CLI commands.
- `tests/test_architecture.py` -- Architectural boundary verification (AD-1).

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/data/azurerm_schema.json` -- Package bundled offline schema catalog with Tier 1 PaaS/foundation and Tier 2 universal resources.
- [x] `ttassistant/domain/catalog.py` -- Define `ResourceTier`, `ResourceArgumentSchema`, `ResourceSchema`, and catalog models.
- [x] `ttassistant/domain/exceptions.py` -- Add `CatalogError` exception class.
- [x] `ttassistant/ports/catalog.py` & `ttassistant/ports/__init__.py` -- Define and export `ResourceCatalogPort` protocol.
- [x] `ttassistant/adapters/catalog_adapter.py` -- Implement `JsonResourceCatalogAdapter` with caching, search, and air-gapped schema inspection.
- [x] `ttassistant/cli.py` -- Implement `catalog` subcommands (`list` and `info`) for interactive and scriptable schema queries.
- [x] `tests/test_catalog.py` -- Author comprehensive tests covering schema resolution, tier categorization, CLI commands, and error handling.
- [x] `tests/test_architecture.py` -- Verify strict architectural boundaries and zero local binaries.

**Acceptance Criteria:**
- Given an air-gapped terminal environment with zero internet access.
- When the developer queries or selects any valid `azurerm_*` resource type.
- Then the catalog provider loads resource schema definitions from bundled offline `ttassistant/data/azurerm_schema.json`.
- And it distinguishes between Tier 1 PaaS services (requiring full guided prompts and security bundling) and Tier 2 universal services.
- And the catalog operates strictly in memory without executing external binaries or ARM REST API calls.

## Implementation Notes

- **Bundled Offline Catalog**: Packaged `ttassistant/data/azurerm_schema.json` (~59 KB) covering all 12 Tier 1 PaaS and foundation services plus 21+ Tier 2 long-tail services with typed arguments, required flags, descriptions, and defaults. Added `ttassistant/data/__init__.py` for `importlib.resources` discoverability.
- **Domain Models & Enums**: Defined `ResourceTier` (str Enum supporting integer and string coercion), `ResourceArgumentSchema`, `ArgumentLookupList` (supporting simultaneous iteration and dictionary access), `ResourceSchema`, and `CatalogSummary` in `ttassistant.domain.catalog`. Defined canonical `TIER_1_RESOURCES` set.
- **Exceptions**: Extended domain error hierarchy with `CatalogError`, `MissingCatalogError`, `InvalidCatalogError`, and `ResourceNotFoundError` in `ttassistant.domain.exceptions`.
- **Port & Adapter**: Defined `@runtime_checkable` `ResourceCatalogPort` in `ttassistant.ports.catalog` and exported in `ttassistant.ports.__init__`. Implemented `JsonResourceCatalogAdapter` in `ttassistant.adapters.catalog_adapter` with dual `importlib.resources` and path loading, in-memory caching (< 5ms load latency), prefix filtering, and substring search. Operates 100% offline with zero external network or binary calls.
- **CLI Subcommand Group**: Registered `ttassistant catalog` subcommand group with `list` and `info` commands. Configured root CLI callback to bypass `common_standards/` requirement for `catalog` commands.
- **Testing**: 18 unit/integration tests in `tests/test_catalog.py` and 3 new architectural boundary tests in `tests/test_architecture.py`. 304/304 tests passing across full monorepo.

## Spec Change Log

## Review Triage Log

- `ttassistant/adapters/catalog_adapter.py`: `is_tier_2` returns `True` for unknown or nonexistent resources — Verdict: `medium` — Fix: require `self.is_known_resource(resource_type) and not is_tier_1_resource(resource_type)`.
- `ttassistant/adapters/catalog_adapter.py`: Unrecognized tier parameter in `list_resources` silently resets to all resources — Verdict: `medium` (pre-verified gap) — Fix: return `[]` when an invalid tier is queried.
- `ttassistant/cli.py`: Root CLI main callback crashes with `MissingStandardsError` when no subcommand is specified — Verdict: `medium` — Fix: allow `ctx.invoked_subcommand is None` to proceed to help / default without crashing on missing `common_standards/`.
- `ttassistant/cli.py`: Missing verification for `catalog` commands in workspace without `common_standards/` — Verdict: `medium` (pre-verified gap) — Fix: add test `test_cli_catalog_without_common_standards` asserting exit code 0.
- `ttassistant/cli.py`: Missing verification for `catalog list` with non-matching filter criteria — Verdict: `medium` (pre-verified gap) — Fix: add test `test_cli_catalog_list_no_matches`.
- `ttassistant/domain/catalog.py`: `ResourceTier.__eq__` coerces `bool` (subclass of `int`) to `True` for `TIER_1` — Verdict: `low` — Fix: guard `not isinstance(other, bool)`.
- `ttassistant/domain/catalog.py`: `validate_arguments` raises `TypeError` when `args is None` — Verdict: `low` — Fix: handle `args is None` returning `(False, required)`.
- `ttassistant/adapters/catalog_adapter.py`: Malformed catalog JSON non-dict or non-dict arguments field crashes with `AttributeError` — Verdict: `low` — Fix: validate structure and raise `InvalidCatalogError`.
- `ttassistant/ports/catalog.py`: Port interface parity gap for `search`, `is_tier_2`, `get_required_arguments`, `get_optional_arguments` — Verdict: `low` — Fix: declare methods in `ResourceCatalogPort`.
- `ttassistant/data/azurerm_schema.json`: Omitted PaaS companion blocks (e.g. `private_dns_zone_group`) — Verdict: `false` — Security Triad bundling and PaaS companion scaffolding are explicitly scheduled for Stories 3.2 and 3.3.

## Verification

**Commands:**
- `./.venv/bin/pytest tests/test_catalog.py` -- expected: All catalog unit, integration, and CLI tests pass.
- `./.venv/bin/pytest tests/test_architecture.py` -- expected: Architectural boundaries remain intact.
- `./.venv/bin/pytest` -- expected: Full test suite passes (295+ tests).
- `./.venv/bin/python -m ttassistant catalog list --tier 1` -- expected: Lists Tier 1 enterprise PaaS services.
- `./.venv/bin/python -m ttassistant catalog info azurerm_storage_account` -- expected: Renders argument schema table.

