# Epic 4 Context: In-Session Conversational Refinements & Surgical Folder Remediation

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Enable infrastructure engineers to conversationally refine staged Terraform configurations using colloquial terminal instructions powered by a sub-10ms air-gapped deterministic attribute aliasing engine, and execute surgical remediation on existing directories to audit, detect compliance violations (such as missing mandatory tags, enabled public access, or missing Private Endpoints), and stage non-destructive corrective patches without clobbering existing code or comments.

## Stories

- Story 4.1: Air-Gapped Deterministic Tweak Engine & Attribute Aliasing
- Story 4.2: Interactive Tweak Loop & Dynamic Diff Re-rendering
- Story 4.3: Existing Folder Inspection & Non-Compliance Diagnostics
- Story 4.4: Surgical Remediation Staging & Comment Preservation

## Requirements & Constraints

- **Deterministic Air-Gapped Conversational Tweaks**:
  - Accept colloquial refinement instructions (e.g., "Set minimum TLS version to 1.2", "Change replication to GRS", "Add tag team=core") directly during the terminal diff preview.
  - Resolve colloquial terms to target Terraform attributes using an AzureRM Attribute Alias Dictionary.
  - Mutate in-memory configuration in <= 10ms with strictly zero external network calls, zero LLM/AI API calls, and zero cloud credentials.
- **Dynamic Diff Re-rendering & Interactive Tweak Loop**:
  - Immediately re-render the unified terminal diff upon applying a tweak, showing additions (`+`) and modifications/deletions (`-`) in color.
  - Re-present the confirmation gate (`[Y] Commit / [N] Cancel / [Tweak] Enter refinement`), supporting multiple consecutive tweaks within the same active session.
  - Aborting via `N`, `Escape`, or `Ctrl+C` must exit immediately leaving disk contents completely untouched.
- **Existing Directory Inspection & Diagnostics (Remediation Mode)**:
  - Audit existing `<resource-type>/<subscription>/` directories against `common_standards/*.md` and Enterprise Security Triad policies.
  - Identify non-compliance items: missing mandatory tags from `tagging_baseline.md`, public access enabled or missing denial (`public_network_access_enabled = false`), and absent `azurerm_private_endpoint` blocks.
- **Surgical Remediation & Non-Destructive Patching**:
  - Stage corrective patches (appending missing tag keys, toggling public network denial, appending companion `azurerm_private_endpoint` blocks).
  - 100% preserve existing file comments, custom variable references, unmanaged resource blocks, and original formatting.
  - Never silently overwrite files or clobber existing code.
- **Governed Agency & Atomic Multi-Directory Writes**:
  - Require explicit human confirmation (`[Y]`) on the rendered diff before committing any disk writes.
  - Commit writes via atomic swap (`.tmp` sibling files, `os.fsync`, and `os.replace`) with automatic rollback across all target directories on failure.
  - Under no circumstances does the CLI invoke `terraform apply` or execute automated live cloud deployments.

## Technical Decisions

- **Hexagonal Architecture Boundaries (AD-1, AD-4, AD-5)**:
  - `ttassistant.ports.tweak_parser`: Abstract `TweakParserPort` interface wrapping tweak interpretation, allowing deterministic rule-based implementation by default while leaving an extension point for an internal proxy adapter.
  - `ttassistant.application.tweak_handler`: Coordinates colloquial alias resolution and in-memory AST mutations.
  - `ttassistant.application.remediation_flow`: Coordinates existing directory scanning, standards auditing, and surgical diff staging.
  - `ttassistant.domain.hcl`: Pure-Python HCL AST model, attribute alias dictionary, and non-destructive syntax mutation.
  - `ttassistant.domain.diff`: In-memory unified diff generator comparing disk baselines against modified `StagedWorkspace` buffers.
  - `ttassistant.adapters.hcl_adapter`: Read-only AST extraction for inspecting existing files (`python-hcl2`); strictly no `hcl2.dump()` round-tripping to avoid comment loss and formatting corruption.
- **Deterministic Attribute Aliasing Engine (AD-4)**:
  - Maps common operational synonyms to AzureRM schema attributes (e.g., `tls` -> `minimum_tls_version`, `replication` -> `account_replication_type`).
  - Executes locally in memory in <10ms (NFR-4, NFR-5) without remote dependencies.
- **Comment-Preserving Surgical Patching (AD-2, AD-5)**:
  - To prevent comment loss caused by naive AST re-serialization, remediation patches are generated surgically (inserting missing attributes/blocks into existing file text or AST span offsets), preserving all surrounding comments, indentation, and structure.
- **In-Memory Cache Invalidation (AD-5)**:
  - Proposed file buffers are held in memory within `StagedWorkspace`. Conversational tweak mutations invalidate cached buffers and immediately trigger diff re-calculation without writing to disk.
- **Atomic Multi-Directory Staging & Rollback (AD-5, NFR-7)**:
  - When committing remediation or multi-directory updates, files are staged to hidden sibling `.tmp` files, synced with `os.fsync`, and atomically renamed with `os.replace`. Write failures trigger clean rollback across all affected directories.
- **Performance & Resource Footprint (NFR-1, NFR-3)**:
  - All inspection and tweak loops run purely in-process, maintaining total CLI memory usage below 150MB RSS and fast interactive responses.

## UX & Interaction Patterns

- **Interactive Review & Conversational Tweak Loop**:
  - During the diff preview, the prompt offers `[Y] Commit`, `[N] Cancel`, and `[Tweak] Enter refinement`.
  - Selecting `[Tweak]` prompts for colloquial instructions (e.g., "Change replication to GRS").
  - The diff clears and re-renders dynamically showing the updated modifications in green/red, allowing continuous refinement until satisfied.
- **Remediation Inspection Display**:
  - When targeting an existing folder, the CLI outputs an audit breakdown of detected compliance gaps before displaying the proposed surgical diff.
- **Non-Destructive Safe Abort**:
  - Exiting via `N`, `Escape`, or `Ctrl+C` immediately aborts the session, leaving disk contents intact.
- **Terminal Degradation & Automation**:
  - Gracefully falls back to plain line-oriented text prompts in non-TTY or `TERM=dumb` environments; `--yes` bypasses interactive gates for CI/headless verification.

## Cross-Story Dependencies

- **Story 4.1** provides the deterministic tweak engine (`TweakHandler`, `TweakParserPort`) and the AzureRM Attribute Alias Dictionary.
- **Story 4.2** integrates the tweak engine into the interactive diff review loop in `ProvisioningFlow` and terminal adapter, enabling dynamic diff re-rendering and multi-turn refinements.
- **Story 4.3** implements the existing directory diagnostic engine in `RemediationFlow`, parsing existing `.tf` files via `hcl_adapter` and auditing against `common_standards/*.md`.
- **Story 4.4** delivers comment-preserving surgical patching and remediation staging in `RemediationFlow` and `domain.diff`, executing atomic writes upon human confirmation.
- Builds directly upon **Epic 1** (StandardsEngine, StagedWorkspace, diff preview, atomic writes), **Epic 2** (HCL AST parsing), and **Epic 3** (Enterprise Security Triad and PaaS/schema attributes).
