# Architecture Reconciliation Review — ttassistant

- **Artifact Under Review:** [`ARCHITECTURE-SPINE.md`](file:///home/teosevinc/workspaces/ttassistant/_bmad-output/planning-artifacts/architecture/architecture-ttassistant-2026-09-21/ARCHITECTURE-SPINE.md)
- **Source Specification:** [`prd.md`](file:///home/teosevinc/workspaces/ttassistant/_bmad-output/planning-artifacts/prds/prd-ttassistant-2026-09-21/prd.md)
- **Review Date:** 2026-09-21
- **Reviewer Role:** Spec Reconciler & Architecture Quality Auditor
- **Verdict:** **NEEDS_ATTENTION**

---

## 1. Executive Summary

A comprehensive architectural reconciliation was conducted comparing the **`ttassistant` PRD** (`prd-ttassistant-2026-09-21`) against the **Architecture Spine** (`ARCHITECTURE-SPINE.md`). 

The Architecture Spine establishes a robust, highly modular foundation based on Hexagonal Architecture (Ports & Adapters) with Orchestrated Application Flows. It successfully captures and binds every explicit requirement identifier (`FR-1` through `FR-16` and `NFR-1` through `NFR-7`) in its metadata and Capability Map. Core constraints—including zero local binary dependencies, zero remote state blocks, zero live `terraform apply` operations, air-gapped local execution, and atomic disk transactions—are firmly codified in Architectural Decisions (`AD-1` through `AD-7`).

However, several subtle, quiet, and secondary requirements from the PRD were dropped, underspecified, or left without necessary technical dependencies in the stack:
1. **FR-6 Missing Dependency Scaffolding & Cross-Subscription Network Lookups:** The spine models single-directory atomic writes in `<resource-type>/<subscription>/`, but omits the architectural mechanism for cross-folder scaffolding (e.g. creating subnets in `subnets/<subscription>/`) and cross-subscription provider alias wiring.
2. **FR-8 Stack Gap for YAML Frontmatter:** The PRD requires parsing Markdown tables, key-value lists, and *optional YAML frontmatter* in `common_standards/*.md`. The spine lists `markdown-it-py` and `pydantic` in its stack, omitting a YAML parser (`PyYAML` or `ruamel.yaml`) or frontmatter plugin.
3. **FR-1 Non-TTY / Dumb Terminal Fallback:** PRD §9.2 mandates fallback to plain monochrome text in non-TTY or dumb terminals. The spine includes interactive libraries (`questionary`, `rich`), but leaves non-TTY graceful degradation undefined.
4. **FR-11 Long-Tail Tier 2 Synthesis Mechanism:** While `AD-3` defines file layout for Tier 2 (omitting variables/outputs), the actual generation and attribute discovery mechanism for arbitrary AzureRM provider resources without external binaries remains underspecified.
5. **FR-14 Remediation Mode Comment & Formatting Preservation:** In remediation mode, parsing and rewriting existing `.tf` files via `python-hcl2` risks stripping comments and AST formatting unless an AST-preserving or block-appending strategy is specified.
6. **FR-2 Interactive Step-Back Navigation:** PRD FR-2 explicitly requires that users can "step back" during the guided dialogue. The spine does not specify the navigation history/state stack in `provisioning_flow.py`.

---

## 2. Comprehensive Traceability Matrix

### 2.1 Functional Requirements (FR-1 to FR-16)

| ID | Requirement Name | PRD Target | Spine Mapping & Component | Architectural Decision | Status | Reconciliation Notes / Gaps |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **FR-1** | Cross-Platform Terminal Runtime | Windows & Linux terminal execution, ANSI/VT100 rendering, zero escape corruption, identical keyboard nav. | `ttassistant.adapters.terminal_adapter` | `AD-1` | **PARTIAL** | Core terminal adapter and libraries (`rich`, `questionary`) are present. However, PRD §9.2 requirement for non-TTY / dumb terminal monochrome fallback is not addressed in `AD-1` or adapter specs. |
| **FR-2** | Guided Interactive Dialogue Flow | Step-by-step prompts for subscription, resource type, workload name; inline validation; cancel, step back, conversational tweaks. | `ttassistant.application.provisioning_flow` | `AD-1`, `AD-5` | **PARTIAL** | Guided dialogue and cancellation are well represented. "Step back" (backtracking to previous prompt) in interactive wizards requires explicit state-stack handling, which is omitted in `provisioning_flow`. |
| **FR-3** | Zero Local Binaries Architecture | Pure-Python repo scanning, Markdown parsing, HCL emission; no `terraform` or `az` CLI on PATH. | `ttassistant.adapters.hcl_adapter`, `domain.hcl` | `AD-2`, `AD-3` | **PASS** | Firmly enforced in `AD-2` (pure-Python `python-hcl2`, zero C/tree-sitter extensions) and operational envelope. |
| **FR-4** | Monorepo Topology Traversal | Map all `<resource-type>/<subscription>/` directories; tolerate non-uniform folder naming. | `ttassistant.domain.topology` | `AD-2` | **PASS** | Enforced via Phase 1 streaming lexical pre-filter and topology indexer. |
| **FR-5** | Subnet & Resource Group Discovery | Scan existing `.tf` files across networking folders to find candidate subnets and parent Resource Group. | `ttassistant.domain.topology`, `adapters.hcl_adapter` | `AD-2` | **PASS** | Covered by Phase 1 lexical pre-filter and Phase 2 targeted AST extraction on candidate files. |
| **FR-6** | Collaborative Subnet Selection & Dependency Scaffolding | Rank candidate subnets `(Recommended)`; sort by proximity; if missing, prompt to scaffold missing subnet in network folder OR wire cross-subscription shared lookup. | `ttassistant.application.provisioning_flow` | `AD-1`, `AD-2` | **NEEDS_ATTENTION** | Subnet recommendation logic is mapped. **Gap:** Cross-folder scaffolding of missing networking definitions and cross-subscription provider alias wiring for shared VNets are completely absent from `AD-3` and `AD-5`. |
| **FR-7** | Decoupled Data Source Scaffolding | Emit `data "azurerm_*"` for upstream dependencies; zero `terraform_remote_state`. | `ttassistant.domain.scaffold` | `AD-3` | **PASS** | Explicitly mandated in `AD-3` (`data.tf` lean layout; zero remote state allowed). |
| **FR-8** | Dynamic Markdown Standards Ingestion & Fail-Fast | Parse `common_standards/*.md` on startup; support tables, lists, and YAML frontmatter; exit code 1 if missing. | `ttassistant.domain.standards` | `AD-6` | **NEEDS_ATTENTION** | Fail-fast exit code 1 and `markdown-it-py` dynamic ingestion are well specified. **Gap:** Stack lacks a YAML parser (`PyYAML`/`ruamel.yaml`) or frontmatter plugin to parse optional YAML frontmatter. |
| **FR-9** | Automated Naming & Tagging Rule Enforcement | Enforce prefixes, suffixes, character constraints, and mandatory tags from `common_standards/*.md`. | `ttassistant.domain.standards` | `AD-6` | **PASS** | Explicitly codified in `AD-6` via typed Pydantic models. |
| **FR-10** | Automated Azure Blob Backend Mapping | Resolve storage account, container, RG, state key per subscription from standards/patterns; scaffold `backend.tf`. | `ttassistant.domain.standards`, `domain.scaffold` | `AD-3`, `AD-6` | **PASS** | Codified in `AD-3` (`backend.tf` dedicated remote state backend) and `AD-6`. |
| **FR-11** | Tiered Azure Resource Catalog Architecture | Tier 1 (guided PaaS + security triad) + Tier 2 (universal syntax for all `azurerm_*` resources). | `ttassistant.domain.scaffold` | `AD-3`, `AD-7` | **PARTIAL** | Resolves PRD §10 Open Question 2 by omitting `variables.tf`/`outputs.tf` for Tier 2 in `AD-3`. **Gap:** Mechanism for universal syntax discovery/generation for arbitrary AzureRM resources without cloud APIs or CLI binaries is underspecified. |
| **FR-12** | Mandatory Public Network Denial | Set `public_network_access_enabled = false` for PaaS resources; alert if user override contradicts standards. | `ttassistant.domain.scaffold` | `AD-7` | **PASS** | Explicitly mandated in `AD-7` with mandatory interactive security confirmation warning on override. |
| **FR-13** | Automated Private Endpoint & DNS Zone Bundling | Scaffold `azurerm_private_endpoint` and `private_dns_zone_group` linked to central Hub Private DNS Zone. | `ttassistant.domain.scaffold` | `AD-7` | **PASS** | Explicitly codified in `AD-7` referencing discovered subnet and Hub Private DNS Zone data sources. |
| **FR-14** | Target Directory Scaffolding & Existing Folder Remediation | Calculate target path; scaffold greenfield; remediate existing folders with staged corrective diff. | `ttassistant.application.remediation_flow` | `AD-3`, `AD-5` | **PARTIAL** | Mapped to `remediation_flow.py` and `AD-5`. **Gap:** The AST modification strategy for existing files (preventing comment stripping or formatting destruction) is not defined. |
| **FR-15** | Unified In-Terminal Diff Display | Render colored unified terminal diff (`+`/`-`); reflect exact bytes before disk write. | `ttassistant.domain.diff`, `adapters.terminal_adapter` | `AD-5` | **PASS** | Mandated in `AD-5` via `StagedWorkspace` and `difflib.unified_diff`. |
| **FR-16** | In-Session Conversational Refinement & Confirmation Gate | Interactive `[Y]/[N]` confirmation; conversational tweak instructions update memory HCL and refresh diff; zero auto-apply. | `ttassistant.application.tweak_handler` | `AD-4`, `AD-5` | **PASS** | Mandated in `AD-4` (deterministic AST tweak engine) and `AD-5` (explicit human confirmation gate; zero terraform apply). |

---

### 2.2 Non-Functional Requirements (NFR-1 to NFR-7)

| ID | Requirement Name | PRD Target | Spine Mapping & Component | Architectural Decision | Status | Reconciliation Notes / Gaps |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **NFR-1** | Cold Startup Latency | $\le$ 1.5 seconds inside VSCode terminal until initial prompt. | `ttassistant.cli` | Minimal seed dependencies | **PASS (Watch)** | The dependency list is lean. However, because `rich`, `questionary`, `markdown-it-py`, and `pydantic` are loaded at start, lazy import patterns should be recommended in `cli.py` to guarantee meeting the 1.5s budget on Windows. |
| **NFR-2** | Repository Traversal Latency | $\le$ 3.0 seconds for monorepos with up to 10,000 files. | `ttassistant.domain.topology`, `adapters.hcl_adapter` | `AD-2` | **PASS** | Directly solved by `AD-2` Two-Phase indexing (streaming regex pre-filter + targeted AST extraction). |
| **NFR-3** | Memory Footprint | $\le$ 150 MB RSS during active execution. | All modules | Pure-Python streaming | **PASS** | Stateless in-memory domain models, pure Python streaming, zero memory-intensive daemon processes. |
| **NFR-4** | Zero Credential Storage | Zero processing, logging, or storage of Azure credentials, SPNs, or PATs. | Entire codebase | Operational envelope | **PASS** | Enforced by pure local Git static analysis; zero cloud authentication. |
| **NFR-5** | Air-Gapped Operation | Operates 100% locally against repository files; zero telemetry or external API calls. | Entire codebase | `AD-4` | **PASS** | `AD-4` explicitly mandates air-gapped deterministic local tweak evaluation by default. |
| **NFR-6** | Idempotent Scaffolding | Identical inputs produce byte-for-byte identical HCL output. | `ttassistant.domain.scaffold`, `domain.hcl` | Consistent HCL formatting | **PASS** | Pure domain serialization with deterministic template models and canonical sorting. |
| **NFR-7** | Atomic Disk Writes | Failure leaves existing files uncorrupted; rollback partial writes. | `ttassistant.adapters.fs_adapter` | `AD-5` | **PASS** | Codified in `AD-5`: hidden `.tmp` sibling writes, `os.fsync`, and atomic `os.replace` swap with rollback. |

---

## 3. Key Domain Constraints & Boundary Invariants

### 3.1 Zero Remote State Dependency
- **PRD Rule:** Generation of `terraform_remote_state` data blocks is strictly forbidden. Cross-resource dependencies must resolve via `data "azurerm_*"` blocks.
- **Spine Representation:** Fully addressed in `AD-3` (`data.tf` specification: *"All discovered upstream dependencies as decoupled `data "azurerm_*"` blocks. Zero `terraform_remote_state` allowed"*).
- **Status:** **PASS**

### 3.2 Governed Agency & Zero Terraform Apply
- **PRD Rule:** Silent file modifications are prohibited; interactive terminal diffs are mandatory; CLI will never execute `terraform apply`, `terraform destroy`, or make mutations against live cloud infrastructure.
- **Spine Representation:** Explicitly codified in `AD-5` (*"Terminal output requires explicit human confirmation `[Y]` before committing... The CLI must never invoke or wrap `terraform apply` or `terraform destroy`"*).
- **Status:** **PASS**

### 3.3 Dynamic Markdown Gold Standards Ingestion
- **PRD Rule:** Discover and parse all `.md` files in `common_standards/` at runtime without requiring CLI recompilation. If `common_standards/` is missing or empty, terminate immediately with exit code 1.
- **Spine Representation:** Explicitly codified in `AD-6` (*"At startup, `StandardsEngine` must parse all specification files in `common_standards/*.md` using `markdown-it-py` into typed Pydantic models. If `common_standards/` is missing or empty, the CLI must terminate immediately with exit code 1"*).
- **Status:** **PASS** (with dependency gap noted below).

### 3.4 Zero Local Binaries Architecture
- **PRD Rule:** All scanning, parsing, HCL generation, and validation performed internally without invoking `terraform`, `terragrunt`, or `az` CLI.
- **Spine Representation:** Codified in `AD-2`, `AD-3`, and Operational Envelope (*"Strictly zero local binary dependencies... Pure-Python AST parsing (`python-hcl2`)"*).
- **Status:** **PASS**

---

## 4. Detailed Findings & Subtle Omissions

### Finding 1: FR-6 Cross-Folder Dependency Scaffolding & Shared Network Lookups
- **Severity:** Medium-High
- **PRD Origin:** PRD §4.2, FR-6: *"If no candidate subnet exists within the subscription, the CLI prompts the user with the option to scaffold the missing subnet/VNet definition in its designated networking folder or wire a cross-subscription shared network lookup."*
- **Spine Deficiency:**
  1. `AD-3` and `AD-5` define file scaffolding and atomic disk mutations assuming a single destination directory (`<resource-type>/<subscription>/`). If the user chooses to scaffold a missing subnet in a separate folder (e.g. `virtual-networks/<subscription>/main.tf`), the architecture lacks a specification for multi-directory staging or atomic multi-file transactions across disjoint directories in `StagedWorkspace`.
  2. Wiring a "cross-subscription shared network lookup" requires configuring provider aliases (e.g. `provider = azurerm.hub_network` or `subscription_id = "..."` within `data "azurerm_subnet"` blocks). `AD-3` specifies `data.tf`, but does not define how cross-subscription provider aliases are represented or parameterized.
- **Recommendation:**
  - Update `AD-5` to state that `StagedWorkspace` can stage changes across multiple directories (e.g., target resource directory + dependency network directory), executing atomic `.replace` transactions per directory with all-or-nothing rollback.
  - In `AD-3`, specify the convention for cross-subscription data sources (e.g. including provider configuration alias or subscription ID attributes).

---

### Finding 2: FR-8 Missing YAML Frontmatter Parser Dependency in Stack
- **Severity:** Medium
- **PRD Origin:** PRD §4.3, FR-8: *"The CLI must discover and parse all `.md` files within `common_standards/` at the start of every session, supporting Markdown tables, key-value lists, and optional YAML frontmatter."*
- **Spine Deficiency:**
  The Stack table in the Architecture Spine lists `markdown-it-py >= 3.0.0` and `pydantic >= 2.8.0`. Core `markdown-it-py` parses CommonMark markdown; it does not parse YAML frontmatter blocks (`--- ... ---`). Python standard libraries do not parse YAML.
- **Recommendation:**
  Add a YAML parser or frontmatter library to the Stack:
  - Option A: Add `pyyaml >= 6.0.1` and `mdit-py-plugins >= 0.4.0`.
  - Option B: Add `python-frontmatter >= 1.1.0` or standard regex frontmatter extraction combined with `pyyaml`.

---

### Finding 3: FR-1 Non-TTY and Dumb Terminal Fallback Specification
- **Severity:** Low-Medium
- **PRD Origin:** PRD §9.2: *"Supports 256-color ANSI terminals with fallback to plain monochrome text when running in non-TTY or dumb terminals."*
- **Spine Deficiency:**
  The spine delegates terminal UI to `RichTerminalAdapter` using `rich` and `questionary`. `questionary` relies on `prompt_toolkit`, which by default expects a functional POSIX/Windows TTY. In headless environments, piped execution, or dumb terminals (`TERM=dumb`), interactive prompts will crash unless explicitly intercepted.
- **Recommendation:**
  Add a rule in `AD-1` or `Consistency Conventions` stating:
  *"When stdin/stdout is not an interactive TTY (e.g., CI execution or `TERM=dumb`), `RichTerminalAdapter` must disable ANSI styling (`rich.console.Console(no_color=True, force_terminal=False)`) and fail gracefully or fall back to standard `input()` line prompts."*

---

### Finding 4: FR-11 Tier 2 Universal AzureRM Resource Synthesis Architecture
- **Severity:** Medium
- **PRD Origin:** PRD §4.4, FR-11: *"Universal syntax scaffolding for all other `azurerm_*` resources supported by the provider, generating syntactically valid HCL blocks with mandatory `common_standards/` tags, naming prefixes, decoupled data sources, and subscription backend wiring."*
- **Spine Deficiency:**
  `AD-3` settles the file layout for Tier 2 (omitting `variables.tf` and `outputs.tf`), but does not describe the synthesis strategy. Without calling the `az` CLI or `terraform providers schema`, how does `domain.scaffold` know the structure of arbitrary long-tail resources?
- **Recommendation:**
  Clarify in `AD-3` or `domain.scaffold` whether Tier 2:
  1. Emits a generic skeleton block: `resource "<target_resource_type>" "this" { name = ... resource_group_name = data.azurerm_resource_group.this.name location = data.azurerm_resource_group.this.location tags = ... }`, OR
  2. Embeds an offline static metadata registry of known `azurerm_*` resource schemas generated at package build time.

---

### Finding 5: FR-14 Remediation Mode AST Preservation & Comment Safety
- **Severity:** Medium
- **PRD Origin:** PRD §4.5, FR-14: *"When executed targeting an existing folder, the CLI inspects the existing files for missing mandatory tags, public network access exposures, or missing Private Endpoints, and stages corrective additions as a proposed diff."*
- **Spine Deficiency:**
  `AD-5` describes computing diffs between existing files and staged HCL. However, if existing `.tf` files are parsed into an AST via `python-hcl2` and serialized back out, `python-hcl2` (which produces standard Python dictionaries/lists) will drop all existing developer comments and alter formatting.
- **Recommendation:**
  Clarify in `AD-5` or `ttassistant.application.remediation_flow` the strategy for remediation:
  - For adding missing blocks (e.g. missing `azurerm_private_endpoint` or `backend.tf`): Append new distinct blocks to files rather than round-tripping existing code through a lossy AST parser.
  - For attribute fixes (e.g. injecting `public_network_access_enabled = false` or missing tags): Use targeted line insertion or AST-guided text surgery to preserve surrounding developer comments and custom formatting.

---

### Finding 6: FR-2 Interactive Guided Dialogue Step-Back Navigation
- **Severity:** Low-Medium
- **PRD Origin:** PRD §4.1, FR-2: *"Users can cancel, step back, or input conversational tweaks at any point before final staging."*
- **Spine Deficiency:**
  `AD-1` and `AD-4` cover conversational tweaks during diff review, and `AD-5` covers session cancellation. However, step-back navigation during the prompt sequence (e.g., returning from Workload Name back to Resource Type or Subscription) requires a state-machine stack in `provisioning_flow.py`.
- **Recommendation:**
  In `ttassistant.application.provisioning_flow`, define the flow as a stack-based state machine where each prompt step can yield a `Back` action that pops the top state from the history stack and re-prompts the previous question.

---

## 5. Architectural Recommendations & Next Steps

1. **Update `ARCHITECTURE-SPINE.md` Stack Table:**
   Add `pyyaml >= 6.0.1` and `mdit-py-plugins >= 0.4.0` (or `python-frontmatter`) to ensure `common_standards/*.md` YAML frontmatter is supported natively.
2. **Amend `AD-3` (Scaffolding File Layout & Tier 2 Synthesis):**
   - Document the synthesis model for Tier 2 resources (generic skeleton with naming/tags/resource group).
   - Document cross-subscription provider alias conventions for shared network data sources.
3. **Amend `AD-5` (Governed Agency & Multi-Directory Mutations):**
   - Explicitly support multi-directory staged transactions in `StagedWorkspace` to fulfill FR-6 dependency scaffolding.
   - Clarify non-destructive remediation rules (preserving existing comments via block appending/targeted attribute insertion).
4. **Amend `AD-1` / Consistency Conventions (Terminal Degradation & Backtracking):**
   - Specify non-TTY / dumb terminal fallback behavior for `RichTerminalAdapter`.
   - Specify stack-based history navigation in `ProvisioningFlow` to satisfy the FR-2 step-back requirement.

---
*Reconciliation complete. With the above adjustments addressed, ttassistant's architecture will be fully aligned with all functional, non-functional, and domain requirements specified in the PRD.*
