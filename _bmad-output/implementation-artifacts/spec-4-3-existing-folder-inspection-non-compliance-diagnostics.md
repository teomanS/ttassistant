---
title: 'Story 4.3: Existing Folder Inspection & Non-Compliance Diagnostics'
type: 'feature'
created: '2026-09-28'
status: 'done'
baseline_commit: 'NO_VCS'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '_bmad-output/implementation-artifacts/epic-4-context.md'
  - 'ttassistant/domain/compliance.py'
  - 'ttassistant/application/remediation_flow.py'
  - 'ttassistant/cli.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Existing Terraform codebases across enterprise monorepos frequently drift from corporate standards (`common_standards/*.md`) and Enterprise Security Triad policies, leaving storage accounts, databases, and key vaults exposed to the public internet or lacking mandatory compliance tags and Private Endpoints. Developers currently lack an automated, offline diagnostic command to inspect an existing `<resource-type>/<subscription>/` directory and surface an actionable breakdown of non-compliance findings.

**Approach:** Implement a non-destructive folder inspection and diagnostic audit engine in `ttassistant.application.remediation_flow` and `ttassistant.domain.compliance`. Provide a `ttassistant remediate <path>` CLI command that reads existing `.tf` files in the target directory, parses HCL AST structures, audits against `common_standards/` (mandatory tags, naming rules) and Enterprise Security Triad policies (public access denial and companion private endpoints for Tier 1 PaaS), and displays a structured diagnostic report table with remediation hints.

## Boundaries & Constraints

**Always:**
- Keep folder inspection strictly read-only; never modify, overwrite, or delete any files on disk during audit/inspection (AD-1, AD-5).
- Audit all mandatory tags defined in `tagging_baseline.md` (e.g. `CostCenter`, `Environment`, `ManagedBy`, `Owner`, `Project`) against primary resource blocks.
- For Tier 1 PaaS services (`azurerm_storage_account`, `azurerm_mssql_server`, `azurerm_key_vault`, `azurerm_cosmosdb_account`, etc.), verify that `public_network_access_enabled = false` is explicitly set (flagging missing denial or `true` as a critical violation) (AD-7, FR-12).
- For Tier 1 PaaS services, verify the presence of a companion `azurerm_private_endpoint` targeting the primary resource in the same directory files.
- Return exit code 0 when a directory is compliant; when `--check` is specified and violations exist, exit with code 1 for CI/CD pipeline gating.
- Support non-TTY / `TERM=dumb` environments with plain text tables and zero formatting errors.

**Never:**
- Never execute external binaries (no `terraform`, `az`, or network calls) during directory inspection (AD-2, NFR-5).
- Never fail or crash on malformed `.tf` files, empty directories, or files with unmanaged resources; report parsing warnings gracefully.
- Never write or stage diff files to disk during Story 4.3 (surgical diff staging and interactive application belong to Story 4.4).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fully compliant PaaS folder | `azurerm_storage_account/sub-prod/` with tags, `public_network_access_enabled = false`, and private endpoint | Green summary banner: `100% compliant with corporate standards`, 0 violations | Returns exit code 0 |
| Missing mandatory tags | Storage account missing `CostCenter` and `Owner` tags | Audit table showing 2 `HIGH` severity violations with missing tag names and suggested values | Lists all missing tags |
| Public access enabled on PaaS | `azurerm_mssql_server` with `public_network_access_enabled = true` | Audit table showing `CRITICAL` severity violation flagging AD-7 security policy breach | Highlights critical risk |
| Public access attribute omitted | `azurerm_key_vault` lacking `public_network_access_enabled` attribute | Audit table showing `CRITICAL` severity violation for omitted explicit denial | Highlights omission |
| Missing Private Endpoint | PaaS resource with no `azurerm_private_endpoint` block in directory | Audit table showing `HIGH` severity violation for absent private endpoint | Suggests companion PE |
| Multiple violations in legacy folder | Legacy folder with missing tags, public access enabled, and missing PE | Unified report detailing all violations ordered by severity (`CRITICAL` -> `HIGH` -> `MEDIUM`) | Comprehensive breakdown |
| Non-existent target directory | User runs `ttassistant remediate /invalid/path` | Red error banner: `Directory does not exist` | Exits code 1 |
| Empty directory (0 `.tf` files) | User runs `ttassistant remediate empty_folder/` | Informational warning: `No .tf files discovered in directory` | Exits cleanly code 0 |
| CI Gating mode (`--check`) | Directory has violations and user runs with `--check` | Outputs audit table and exits with code 1 | CI exit code 1 |

</frozen-after-approval>

## Code Map

- `ttassistant/domain/compliance.py` -- Define domain models: `ComplianceSeverity`, `ComplianceViolationType`, `ComplianceViolation`, and `ComplianceReport`.
- `ttassistant/domain/scaffold.py` / `ttassistant/domain/catalog.py` -- Reuse `is_tier_1_paas` and catalog schema validations for PaaS classification.
- `ttassistant/adapters/hcl_adapter.py` -- Use read-only HCL AST parsing (`ReadOnlyHclAdapter`) to extract resources, attributes, and tags without re-serializing.
- `ttassistant/application/remediation_flow.py` -- Implement `RemediationFlow` coordinating file scanning, standards auditing, violation aggregation, and terminal table rendering.
- `ttassistant/cli.py` -- Register `remediate` command calling `RemediationFlow.run_diagnostics()` with `--check` flag.
- `tests/test_compliance_diagnostics.py` -- Comprehensive unit and integration test suite covering all compliance rules, severity rankings, edge cases, and CLI invocations.

## Tasks & Acceptance

**Execution:**
- [x] `ttassistant/domain/compliance.py` -- Define `ComplianceSeverity`, `ComplianceViolationType`, `ComplianceViolation`, and `ComplianceReport` domain models -- Core compliance domain models.
- [x] `ttassistant/application/remediation_flow.py` -- Implement `RemediationFlow.inspect_directory()` and diagnostic reporting -- Application audit service.
- [x] `ttassistant/cli.py` -- Register `remediate` command with path argument and `--check` option -- CLI command entrypoint.
- [x] `tests/test_compliance_diagnostics.py` -- Implement comprehensive tests covering compliant folders, tag violations, public access violations, missing PE violations, `--check` exit codes, and non-TTY outputs -- Verification.

**Acceptance Criteria:**
- Given an existing directory containing legacy `.tf` files, when `ttassistant remediate <path>` executes, then it parses HCL files and compares them against `common_standards/` and Enterprise Security Triad policies.
- Given a Tier 1 PaaS resource with `public_network_access_enabled = true` or missing denial, then the report flags a `CRITICAL` violation for security policy non-compliance.
- Given a resource missing mandatory tags from `tagging_baseline.md`, then the report flags `HIGH` violations identifying each missing tag key.
- Given a Tier 1 PaaS resource lacking a companion `azurerm_private_endpoint`, then the report flags a `HIGH` violation identifying the missing private endpoint.
- Given `--check`, when any compliance violation is detected, then the CLI exits with non-zero exit code 1.
- Given a fully compliant folder, when inspected, then the CLI outputs a 100% compliant banner and exits with code 0.

## Implementation Notes

- Implemented pure Hexagonal domain logic in `ttassistant/domain/compliance.py` isolating all external I/O and UI dependencies (AD-1).
- Extended `HCLParserPort` and `ReadOnlyHclAdapter` to parse arbitrary `.tf` files and return `list[ParsedResource]` with attributes, tags, and nested blocks without external binaries (AD-2, NFR-5).
- Added non-TTY and color-capable tabular display via `TerminalUIPort.display_table()` and `RichTerminalAdapter.display_table()`.
- Implemented `RemediationFlow` in `ttassistant/application/remediation_flow.py` coordinating subscription inference, AST extraction, tag audit, PaaS security triad audit, naming convention validation, and table rendering with file attribution.
- Registered `ttassistant remediate` CLI command supporting directory path argument and `--check` audit flag.

## Review Triage Log

- **Missing `Table` import in `RichTerminalAdapter.display_table()`**: Imported `from rich.table import Table` in `terminal_adapter.py` and guarded plain-text formatting column indices.
- **Companion PE Targeting Check**: Added `_pe_targets_resource` helper checking `private_connection_resource_id` / `target_resource_id` in PE attributes and nested `private_service_connection` blocks to ensure each PaaS resource is individually paired.
- **Individual `private_dns_zone_group` Audit**: Each companion PE is now individually verified for `private_dns_zone_group` block presence, preventing cross-endpoint masking.
- **Strict Public Network Access Denial**: Enforced strict explicit denial (`False` or lowercase strings `"false"`, `"0"`, `"no"`, `"disabled"`); any truthy or non-denial string triggers `CRITICAL` violation.
- **Tag Empty String Validation**: Flagged tags containing only whitespace as `INVALID_TAG_VALUE` (`HIGH`).
- **Resource Naming Rule Validation**: Integrated `StandardsEngine.validate_resource_name()` against declared Azure `name` attributes, flagging violations as `INVALID_RESOURCE_NAME` (`MEDIUM`).
- **File Attribution in Diagnostics**: Added `File` column to diagnostic table for immediate file-level pinpointing.
- **Computed Fields for Serialization**: Added `@computed_field` decorators on `is_compliant`, `critical_count`, `high_count`, `medium_count`, and `low_count` in `ComplianceReport`.

## Design Notes

### Diagnostic Audit Output Table
```text
┌──────────┬───────────────────────────────┬──────────────────────────────┬──────────┬────────────────────────────────────────────────────────┐
│ Severity │ Violation Category            │ Target Resource              │ File     │ Remediation Hint                                       │
├──────────┼───────────────────────────────┼──────────────────────────────┼──────────┼────────────────────────────────────────────────────────┤
│ CRITICAL │ Public Network Access Enabled │ azurerm_storage_account.main │ main.tf  │ Set 'public_network_access_enabled = false' in main.tf │
│ HIGH     │ Missing Mandatory Tag 'Owner' │ azurerm_storage_account.main │ main.tf  │ Add 'Owner = "..."' to tags = { ... } in main.tf       │
│ HIGH     │ Missing Private Endpoint      │ azurerm_storage_account.main │ main.tf  │ Scaffold companion 'azurerm_private_endpoint' block    │
└──────────┴───────────────────────────────┴──────────────────────────────┴──────────┴────────────────────────────────────────────────────────┘
```

## Verification

**Commands:**
- `./.venv/bin/pytest tests/test_compliance_diagnostics.py -v` -- Result: 28/28 tests passed.
- `./.venv/bin/pytest tests/test_architecture.py -v` -- Result: 17/17 tests passed (zero forbidden imports in domain/application).
- `./.venv/bin/pytest` -- Result: 470/470 tests passed.

