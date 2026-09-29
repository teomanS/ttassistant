---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-ttassistant-2026-09-21/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-ttassistant-2026-09-21/ARCHITECTURE-SPINE.md
---

# ttassistant - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for ttassistant, decomposing the requirements from the PRD and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: Cross-Platform Terminal Runtime — The CLI must execute interactively inside the VSCode integrated terminal across Linux (x86_64, arm64) and Windows (PowerShell, Command Prompt, WSL) environments without platform-specific rendering artifacts. ANSI/VT100 prompt components render cleanly, keyboard navigation (arrows, enter, tab-completion, escape) functions identically across platforms.
FR2: Guided Interactive Dialogue Flow — The CLI must prompt the user step-by-step for core provisioning parameters: target subscription, target Azure resource type, workload name, and service-specific configurations. Entering invalid input triggers inline validation without crashing; users can cancel, step back, or input conversational tweaks.
FR3: Zero Local Binaries Architecture — The CLI must perform all repository scanning, Markdown parsing, HCL generation, and validation internally without invoking terraform, az, or external shell binaries. Emitted .tf files conform to standard Terraform HCL2 syntax and formatting directly from memory. Local terraform init/plan/apply are strictly out of scope.
FR4: Monorepo Topology Traversal — The CLI must recursively scan the repository starting from the working directory root to map all existing <resource-type>/<subscription>/ directories and resource locations, tolerating non-uniform directory naming conventions.
FR5: Subnet & Resource Group Discovery — The CLI must analyze existing .tf files across networking and foundation folders to discover available Subnets, Virtual Networks, and Resource Groups within the target subscription, identifying private endpoint subnets and parent Resource Groups.
FR6: Collaborative Subnet Selection & Missing Dependency Scaffolding — When multiple candidate subnets exist for a resource private endpoint, the CLI must present an interactive selection prompt displaying candidate subnet names, CIDRs, and purpose recommendations (marking common_standards recommendations as default). If no candidate exists, it offers proactive scaffolding of the missing subnet/VNet definition or cross-subscription lookup.
FR7: Decoupled Data Source Scaffolding — The CLI must emit Terraform data "azurerm_*" blocks for all discovered upstream dependencies (Resource Groups, Subnets, VNets) rather than hardcoded resource IDs or terraform_remote_state blocks.
FR8: Dynamic Markdown Specification Ingestion & Fail-Fast Policy — The CLI must discover and parse all .md files within common_standards/ at the start of every session, supporting Markdown tables, key-value lists, and optional YAML frontmatter. Modifying standards immediately alters CLI behavior without recompilation. If common_standards/ is missing or empty, CLI terminates immediately (exit code 1) with an actionable error message.
FR9: Automated Naming & Tagging Rule Enforcement — The CLI must enforce naming conventions and mandatory tag baseline defined in common_standards/*.md for every generated resource (prefixes, suffixes, Azure length/character constraints, and mandatory tags such as environment, owner, cost-center, data-classification).
FR10: Automated Azure Blob Backend Mapping — The CLI must dynamically resolve the Azure Storage Account, Resource Group, Container, and state key for the target subscription from common_standards/*.md (or existing subscription patterns) and scaffold the terraform { backend "azurerm" { ... } } configuration with isolated state keys.
FR11: Tiered Azure Resource Catalog Architecture — The CLI must support code generation for all Azure resources supported by the azurerm Terraform provider using a two-tier delivery model: Tier 1 (Guided Enterprise PaaS & Foundation with full prompts, automated private endpoint & DNS zone group bundling, subnet discovery, attribute validation) and Tier 2 (Universal Azure Long-Tail with syntactically valid HCL, mandatory tags, naming prefixes, decoupled data sources, and backend state).
FR12: Mandatory Public Network Denial — For all Azure PaaS resources supporting public network restrictions, the CLI must explicitly set public access denial arguments in the primary resource block (public_network_access_enabled = false or equivalent) by default, alerting the user if an explicit override is requested.
FR13: Automated Private Endpoint & DNS Zone Group Bundling — For any PaaS resource provisioned, the CLI must automatically scaffold the accompanying azurerm_private_endpoint resource referencing the selected subnet ID and target resource ID, and wire its private_dns_zone_group to the corporate Hub Private DNS Zone.
FR14: Target Directory Scaffolding & Existing Folder Remediation — The CLI must calculate destination paths (<resource-type>/<subscription>/) and support both greenfield creation (main.tf, data.tf, backend.tf, variables.tf, outputs.tf) and existing folder inspection/remediation (staging corrective additions for missing tags, public network access exposures, or missing Private Endpoints as proposed diffs).
FR15: Unified In-Terminal Diff Display — Before writing new files or modifying existing configurations, the CLI must render a unified terminal diff showing added lines (+), removed lines (-), and unchanged context with standard color coding matching exact bytes to be written.
FR16: In-Session Conversational Refinement & Human Confirmation Gate — Before committing writes to disk, the CLI must provide an interactive confirmation gate allowing the engineer to accept [Y], cancel [N] (leaving workspace untouched), or supply conversational tweak instructions to re-generate the diff. Under no circumstances does the CLI invoke terraform apply.

### NonFunctional Requirements

NFR1: CLI Cold Startup — Cold startup time inside the VSCode terminal must not exceed 1.5 seconds until the initial interactive prompt is rendered.
NFR2: Repository Traversal Latency — Recursive repository scanning and subnet discovery must complete in under 3.0 seconds for monorepos containing up to 10,000 files.
NFR3: Process Memory Footprint — CLI process memory footprint must remain under 150 MB RSS during active execution.
NFR4: Zero Credential Storage — The CLI must not request, process, log, or persist Azure credentials, service principal secrets, or Bitbucket personal access tokens.
NFR5: Air-Gapped Local Operation — The CLI must operate entirely locally against repository files without transmitting repository code, metadata, or file paths to unauthorized third-party external services.
NFR6: Idempotent Scaffolding — Running ttassistant repeatedly with identical inputs against a target directory must produce deterministic, byte-for-byte identical HCL output.
NFR7: Atomic Disk Writes — File writing must be atomic across directories; any failure during write operations must leave existing repository files uncorrupted and rollback partial writes.

### Additional Requirements

- Packaging & Project Seed: Standard enterprise Python package configured via Hatchling (pyproject.toml, PEP 621) targeting Python 3.10+, distributed as wheel via internal Python repository. Bundled offline AzureRM provider schema catalog (ttassistant/data/azurerm_schema.json).
- Hexagonal Architecture Decoupling (AD-1): Strict layer separation: ttassistant.domain (pure business logic, zero I/O, zero terminal UI imports, 100% testable in memory), ttassistant.ports (abstract Protocol interfaces for TerminalUIPort, FileSystemPort, StandardsSourcePort, TweakParserPort), ttassistant.adapters (concrete Rich/Questionary, FileSystem, python-hcl2 parser, CommonMark standards reader), ttassistant.application (flow orchestrators).
- Two-Phase Repository Discovery Pipeline (AD-2): Phase 1 streaming regex pre-filter on .tf files (identifying azurerm_subnet, azurerm_virtual_network, azurerm_resource_group; skipping .git and .terraform) followed by Phase 2 targeted AST parsing with python-hcl2. Read-only parsing adapter; no round-trip hcl2.dump() to avoid comment loss.
- Scaffolding Layout & Tier 2 Lean Strategy (AD-3): Standard emission in <resource-type>/<subscription>/: main.tf, data.tf (decoupled data sources, zero terraform_remote_state), backend.tf (isolated state key). Tier 2 universal resources omit variables.tf and outputs.tf by default. Offline schema validation without external cloud/binary calls.
- Air-Gapped Deterministic Tweak Engine (AD-4): Local in-memory attribute AST modifier executing in <10ms with zero network/cloud calls using AzureRM Attribute Alias Dictionary (e.g., replication -> account_replication_type, tls -> minimum_tls_version), wrapped by TweakParserPort interface.
- Atomic Multi-Directory Writes & Surgical Remediation (AD-5): Memory-staged workspace (StagedWorkspace). Remediation mode patches or appends resource blocks without destroying existing code or comments. Multi-directory atomic write writes to sibling .tmp files, calls os.fsync, and performs atomic os.replace swap with full rollback on failure. Governed agency: never invoke terraform apply.
- Dynamic Standards Parsing via CommonMark & PyYAML (AD-6): Startup parsing of common_standards/*.md (naming_conventions.md, tagging_baseline.md, backend_mapping.md, networking_policy.md) using markdown-it-py and PyYAML into typed Pydantic models. Fail-fast with exit code 1 if missing or invalid.
- Terminal Encoding & Fallback (Consistency Conventions): UTF-8 stream handling with ASCII glyph fallbacks on Windows non-UTF-8 code pages. Graceful degradation to plain-text line inputs or fail-fast when non-TTY or TERM=dumb.
- Cross-Platform Path Normalization: Standardized pathlib.Path handling with POSIX forward slashes in emitted HCL across Windows and Linux.

### UX Design Requirements

UX-DR1: Cross-Platform Terminal Interface & ASCII Fallback — Terminal UI rendered via Rich and Questionary with clean ANSI styling, color-coded unified diffs (green additions, red deletions), and automatic fallback to ASCII glyphs on Windows legacy code pages and plain-line prompts for non-TTY / TERM=dumb.
UX-DR2: Progressive Disclosure Guided Dialogue — Interactive step-by-step terminal prompts for subscription, resource type, workload name, and service parameters with inline validation errors and non-crashing recovery.
UX-DR3: Interactive Candidate Subnet Selection Menu — Ranked interactive prompt displaying candidate subnets with CIDR, purpose, and clear (Recommended) indicators, plus proactive prompt to scaffold missing dependencies when none exist.
UX-DR4: In-Session Diff Review & Confirmation Gate — Visual terminal diff preview before any disk modification with prompt to confirm [Y], cancel [N], or enter conversational tweak instructions that re-render the diff interactively.

### FR Coverage Map

- FR1: Epic 1 — Cross-Platform Terminal Runtime
- FR2: Epic 1 — Guided Interactive Dialogue Flow
- FR3: Epic 1 — Zero Local Binaries Architecture
- FR4: Epic 2 — Monorepo Topology Traversal
- FR5: Epic 2 — Subnet & Resource Group Discovery
- FR6: Epic 2 — Collaborative Subnet Selection & Missing Dependency Scaffolding
- FR7: Epic 2 — Decoupled Data Source Scaffolding
- FR8: Epic 1 — Dynamic Markdown Specification Ingestion & Fail-Fast Policy
- FR9: Epic 1 — Automated Naming & Tagging Rule Enforcement
- FR10: Epic 1 — Automated Azure Blob Backend Mapping
- FR11: Epic 3 — Tiered Azure Resource Catalog Architecture (Tier 1 Guided & Tier 2 Universal)
- FR12: Epic 3 — Mandatory Public Network Denial
- FR13: Epic 3 — Automated Private Endpoint & DNS Zone Group Bundling
- FR14: Epic 4 — Target Directory Scaffolding & Existing Folder Remediation
- FR15: Epic 1 — Unified In-Terminal Diff Display
- FR16: Epic 1 (Human Confirmation Gate) & Epic 4 (In-Session Conversational Refinements)

## Epic List

### Epic 1: CLI Foundation, Dynamic Standards & Governed Scaffolding Flow
Infrastructure engineers can launch ttassistant in their VSCode terminal across Linux and Windows without external terraform or az binaries, dynamically load corporate Markdown standards (naming, tags, remote state backend mapping), step through a guided provisioning dialogue, preview color-coded unified diffs, and atomically commit compliant scaffolding to disk upon explicit confirmation with zero live apply.
**FRs covered:** FR1, FR2, FR3, FR8, FR9, FR10, FR15, FR16 (gate)

### Epic 2: Monorepo Topology Discovery & Decoupled Networking Archaeology
Infrastructure engineers can provision resources in complex monorepos where ttassistant automatically traverses directory hierarchies, rapidly scans existing Terraform files via a two-phase lexical and read-only AST pipeline to discover parent Resource Groups and candidate subnets, guides interactive subnet selection (or scaffolds missing subnet definitions), and emits decoupled data "azurerm_*" blocks with zero hardcoded IDs and zero terraform_remote_state blocks.
**FRs covered:** FR4, FR5, FR6, FR7

### Epic 3: Enterprise PaaS Security Triad & Universal Resource Catalog
Infrastructure engineers can scaffold any Azure resource with enterprise-grade guardrails: for Tier 1 Enterprise PaaS resources, ttassistant enforces the Enterprise Security Triad by default (mandatory public access denial, private endpoint binding to selected subnet, and private DNS zone group linked to Hub DNS); for Tier 2 long-tail resources, ttassistant synthesizes syntactically valid HCL blocks from a bundled offline AzureRM schema catalog with compliant naming, tags, and backend state.
**FRs covered:** FR11, FR12, FR13

### Epic 4: In-Session Conversational Refinements & Surgical Folder Remediation
Infrastructure engineers can conversationally refine staged Terraform configurations using colloquial terminal instructions (powered by a sub-10ms air-gapped deterministic attribute aliasing engine), and run ttassistant in remediation mode against existing non-compliant directories to inspect, detect missing tags or public network exposures, and stage non-destructive surgical repair diffs without clobbering existing code or comments.
**FRs covered:** FR14, FR16 (tweak refinement)

## Epic 1: CLI Foundation, Dynamic Standards & Governed Scaffolding Flow

Infrastructure engineers can launch ttassistant in their VSCode terminal across Linux and Windows without external terraform or az binaries, dynamically load corporate Markdown standards (naming, tags, remote state backend mapping), step through a guided provisioning dialogue, preview color-coded unified diffs, and atomically commit compliant scaffolding to disk upon explicit confirmation with zero live apply.

### Story 1.1: Project Skeleton, Hexagonal Architecture & Typer CLI Entrypoint

As an infrastructure engineer,
I want to execute ttassistant in my terminal on Linux or Windows without requiring local terraform or az binaries,
So that I have a fast, cross-platform terminal CLI co-pilot entrypoint that boots in under 1.5 seconds.

**Acceptance Criteria:**

**Given** an environment with Python 3.10+ where terraform and az are not installed on PATH
**When** the user runs ttassistant --help or ttassistant --version
**Then** the CLI responds in <= 1.5 seconds with clear command-line usage and version information
**And** terminal output renders cleanly with standard ANSI colors without escape code corruption on both Linux Bash and Windows PowerShell/CMD
**And** non-TTY or TERM=dumb terminals degrade gracefully to plain text output without crashing
**And** the project structure adheres to Hexagonal Architecture (domain/, ports/, adapters/, application/) defined in pyproject.toml (Hatchling).

### Story 1.2: Dynamic Markdown Standards Engine & Fail-Fast Policy

As a platform engineer,
I want ttassistant to dynamically discover, parse, and validate common_standards/*.md at runtime,
So that corporate naming conventions, tagging baselines, and Azure Blob backend mappings are enforced immediately without CLI recompilations or binary releases.

**Acceptance Criteria:**

**Given** a repository root containing common_standards/ with Markdown specification files (naming_conventions.md, tagging_baseline.md, backend_mapping.md)
**When** StandardsEngine initializes
**Then** it parses Markdown tables, bullet lists, and YAML frontmatter into strongly typed Pydantic models in memory
**And** if common_standards/ directory is missing or empty, the CLI terminates immediately with exit code 1 and a helpful error message guiding the engineer to pull corporate standards
**And** modifying a naming pattern or adding a mandatory tag in common_standards/*.md is reflected on the next CLI run without code changes.

### Story 1.3: Guided Provisioning Dialogue & Parameter Collection

As an infrastructure developer,
I want ttassistant to prompt me step-by-step for the target Azure subscription, resource type, and workload name with inline validation,
So that I can easily configure new cloud infrastructure without memorizing complex naming schemes or CLI flags.

**Acceptance Criteria:**

**Given** a valid common_standards/ specification
**When** the developer starts the provisioning flow in the terminal
**Then** the CLI presents progressive prompts for: Target Subscription, Target Resource Type, and Workload Name
**And** user input is validated inline against naming rules (character set, min/max length) from common_standards/ with immediate non-crashing error feedback on invalid characters
**And** users can navigate prompts using arrow keys, Enter, and Tab completion, or exit cleanly using Ctrl+C or Escape without unhandled exceptions.

### Story 1.4: Standards-Governed Greenfield Scaffolding & State Backend Synthesis

As an infrastructure developer,
I want ttassistant to generate in-memory Terraform configuration files (main.tf, data.tf, backend.tf) applying corporate naming prefixes, mandatory compliance tags, and isolated Azure Blob remote state,
So that my scaffolded module complies with company infrastructure standards right out of the box.

**Acceptance Criteria:**

**Given** validated provisioning parameters for subscription and workload
**When** the scaffolding engine runs in memory
**Then** it produces HCL content structured in <resource-type>/<subscription>/ containing main.tf, data.tf, and backend.tf
**And** main.tf resource names follow the exact prefix/suffix schema from common_standards/naming_conventions.md
**And** tags = { ... } contains all mandatory tags (environment, owner, cost-center, data-classification) populated from standards
**And** backend.tf configures terraform { backend "azurerm" { ... } } with the target subscription's designated storage account, container, and unique state key path
**And** all generated HCL uses valid 2-space indentation and POSIX path separators without executing terraform or cloud APIs.

### Story 1.5: Unified Terminal Diff Preview, Human Confirmation Gate & Atomic Disk Writes

As an infrastructure developer,
I want to inspect a color-coded unified terminal diff of the staged Terraform files and explicitly confirm [Y] before any changes are written to disk,
So that I maintain full governed control over my workspace with zero silent file modifications and atomic, corruption-proof disk writes.

**Acceptance Criteria:**

**Given** staged Terraform files held in StagedWorkspace memory
**When** the scaffolding flow reaches the review stage
**Then** the CLI renders a unified terminal diff showing additions (+) in green and context lines matching the exact bytes to be written
**And** the CLI prompts the user with an explicit confirmation gate: [Y] Commit / [N] Cancel
**And** selecting [N] or pressing Ctrl+C exits cleanly leaving the working directory completely untouched
**And** selecting [Y] atomically writes all files by writing to hidden .tmp sibling files, flushing via os.fsync, and swapping via os.replace
**And** any disk write failure triggers an immediate rollback leaving no orphaned temporary or corrupt files
**And** under no circumstances does the CLI invoke terraform apply or live cloud deployments.

## Epic 2: Monorepo Topology Discovery & Decoupled Networking Archaeology

Infrastructure engineers can provision resources in complex monorepos where ttassistant automatically traverses directory hierarchies, rapidly scans existing Terraform files via a two-phase lexical and read-only AST pipeline to discover parent Resource Groups and candidate subnets, guides interactive subnet selection (or scaffolds missing subnet definitions), and emits decoupled data "azurerm_*" blocks with zero hardcoded IDs and zero terraform_remote_state blocks.

### Story 2.1: Monorepo Topology Traversal & Lexical Candidate Indexer (Phase 1)

As an infrastructure developer,
I want ttassistant to recursively traverse my monorepo's <resource-type>/<subscription>/ hierarchy and pre-filter .tf files using streaming keyword matching in under 3.0 seconds,
So that relevant networking and foundation files are quickly indexed without scanning irrelevant directories or exceeding latency and memory budgets.

**Acceptance Criteria:**

**Given** a repository with up to 10,000 files and non-uniform folder naming (e.g., resource-groups/sub-prod/ vs rg/sub_prod/)
**When** the topology scanner executes
**Then** it ignores .git, .terraform, .venv, and binary directories, completing the scan in <= 3.0 seconds with process memory under 150 MB RSS
**And** it streams regex/keyword pre-filtering across .tf files to identify files containing azurerm_subnet, azurerm_virtual_network, or azurerm_resource_group blocks
**And** it maps candidate file paths to their respective subscriptions in memory.

### Story 2.2: Targeted Read-Only HCL AST Extraction for Networking & Resource Groups (Phase 2)

As an infrastructure developer,
I want ttassistant to extract existing Subnets, Virtual Networks, and parent Resource Groups from candidate .tf files using pure-Python AST parsing,
So that subnet names, CIDR blocks, private endpoint configurations, and Resource Group definitions are accurately discovered from code without local terraform or cloud APIs.

**Acceptance Criteria:**

**Given** the list of candidate .tf files from Phase 1
**When** the AST extraction adapter (python-hcl2) processes candidate files
**Then** it parses HCL AST in memory to identify declared azurerm_subnet blocks (including name, address_prefixes, and tags) and azurerm_resource_group blocks
**And** it identifies candidate subnets designated for Private Endpoints based on naming, subnet attributes, or common_standards/ heuristics
**And** python-hcl2 is strictly used in read-only mode, with zero round-trip hcl2.dump() AST serialization to preserve original file comments and formatting.

### Story 2.3: Collaborative Subnet Selection & Missing Dependency Scaffolding

As an infrastructure developer,
I want ttassistant to present candidate subnets in an interactive menu with recommendations, or offer to scaffold a missing subnet if none exist,
So that I can easily connect my workload to the correct network without guessing or manually authoring missing network configurations from scratch.

**Acceptance Criteria:**

**Given** discovered candidate subnets for the target subscription
**When** multiple candidate subnets are available
**Then** the CLI presents an interactive numbered prompt showing subnet names, CIDRs, and purpose, highlighting any subnet matching common_standards/ recommendations with (Recommended) as default
**And** if no candidate subnet exists within the subscription, the CLI prompts the developer with options to either scaffold a missing subnet/VNet definition in its designated networking directory or wire a cross-subscription shared network lookup
**And** if the developer elects to scaffold a missing subnet, the missing network configuration is added to StagedWorkspace for multi-directory atomic staging.

### Story 2.4: Decoupled Data Source Generator

As an infrastructure developer,
I want ttassistant to scaffold decoupled data "azurerm_*" blocks in data.tf for all discovered upstream dependencies (Resource Group, Subnet, Virtual Network),
So that my module cleanly references existing infrastructure without hardcoding resource IDs or relying on fragile terraform_remote_state blocks.

**Acceptance Criteria:**

**Given** the selected subnet, parent Resource Group, and target subscription
**When** the scaffolding engine generates data.tf
**Then** it emits data "azurerm_resource_group" referencing the parent resource group by name
**And** it emits data "azurerm_subnet" and data "azurerm_virtual_network" referencing the selected subnet and VNet by name and resource group
**And** the generated HCL contains strictly zero terraform_remote_state data blocks
**And** primary resource blocks reference data.azurerm_resource_group.<name>.name and data.azurerm_subnet.<name>.id.

## Epic 3: Enterprise PaaS Security Triad & Universal Resource Catalog

Infrastructure engineers can scaffold any Azure resource with enterprise-grade guardrails: for Tier 1 Enterprise PaaS resources, ttassistant enforces the Enterprise Security Triad by default (mandatory public access denial, private endpoint binding to selected subnet, and private DNS zone group linked to Hub DNS); for Tier 2 long-tail resources, ttassistant synthesizes syntactically valid HCL blocks from a bundled offline AzureRM schema catalog with compliant naming, tags, and backend state.

### Story 3.1: Bundled Offline AzureRM Provider Schema Catalog

As an infrastructure developer,
I want ttassistant to package an offline AzureRM resource schema catalog (azurerm_schema.json),
So that any azurerm_* resource type can be validated and scaffolded offline with correct argument schemas without requiring cloud connectivity or terraform providers schema.

**Acceptance Criteria:**

**Given** an air-gapped terminal environment with zero internet access
**When** the developer queries or selects any valid azurerm_* resource type
**Then** the catalog provider loads resource schema definitions from bundled offline ttassistant/data/azurerm_schema.json
**And** it distinguishes between Tier 1 PaaS services (requiring full guided prompts and security bundling) and Tier 2 universal services
**And** the catalog operates strictly in memory without executing external binaries or ARM REST API calls.

### Story 3.2: Tier 1 PaaS Scaffolding with Mandatory Public Network Access Denial

As a security and platform engineer,
I want ttassistant to automatically configure public network access denial (public_network_access_enabled = false or equivalent) on all Tier 1 PaaS resources by default,
So that developers never accidentally expose database, storage, or secrets infrastructure to the public internet.

**Acceptance Criteria:**

**Given** a Tier 1 PaaS resource selection (e.g., azurerm_storage_account, azurerm_mssql_server, azurerm_key_vault, azurerm_cosmosdb_account)
**When** the scaffolding engine generates the primary resource block in main.tf
**Then** the resource configuration explicitly sets public_network_access_enabled = false (or resource-specific equivalent attribute)
**And** if the user explicitly attempts to enable public access, the CLI displays a high-visibility security warning and requires explicit confirmation.

### Story 3.3: Automated Private Endpoint & Hub Private DNS Zone Group Bundling

As an infrastructure developer,
I want ttassistant to automatically generate azurerm_private_endpoint and private_dns_zone_group resource blocks mapped to the selected subnet and corporate Hub Private DNS zone,
So that newly scaffolded PaaS workloads achieve full internal network isolation and private DNS resolution without manual networking boilerplate.

**Acceptance Criteria:**

**Given** a scaffolded Tier 1 PaaS resource and selected candidate subnet
**When** main.tf and data.tf are synthesized
**Then** main.tf includes an azurerm_private_endpoint resource referencing data.azurerm_subnet.<name>.id and the primary resource ID
**And** it includes a private_dns_zone_group block linked to the corporate Hub Private DNS zone data source resolved from common_standards/
**And** data.tf automatically includes the required Hub Private DNS Zone data source block referencing central shared infrastructure.

### Story 3.4: Tier 2 Universal Azure Long-Tail Resource Scaffolding

As an infrastructure developer,
I want ttassistant to scaffold syntactically valid HCL blocks for any long-tail AzureRM provider resource outside Tier 1,
So that I can use ttassistant to author any arbitrary Azure resource while still benefiting from corporate naming rules, compliance tags, and isolated remote state backends.

**Acceptance Criteria:**

**Given** any valid azurerm_* resource type outside Tier 1 (e.g. azurerm_log_analytics_workspace, azurerm_application_insights, etc.)
**When** the developer initiates scaffolding for that resource
**Then** the CLI generates a syntactically valid main.tf block containing required schema attributes and corporate naming schema
**And** tags = { ... } contains all mandatory enterprise tags from common_standards/
**And** backend.tf is generated with the isolated subscription remote state key
**And** variables.tf and outputs.tf are omitted by default per the lean layout rule (AD-3).

## Epic 4: In-Session Conversational Refinements & Surgical Folder Remediation

Infrastructure engineers can conversationally refine staged Terraform configurations using colloquial terminal instructions (powered by a sub-10ms air-gapped deterministic attribute aliasing engine), and run ttassistant in remediation mode against existing non-compliant directories to inspect, detect missing tags or public network exposures, and stage non-destructive surgical repair diffs without clobbering existing code or comments.

### Story 4.1: Air-Gapped Deterministic Tweak Engine & Attribute Aliasing

As an infrastructure developer,
I want to supply colloquial tweak instructions (e.g. "Set minimum TLS version to 1.2" or "Change replication to GRS") during diff preview,
So that the staged HCL in memory is updated in under 10 milliseconds via an air-gapped attribute alias dictionary without external AI network calls or cloud credentials.

**Acceptance Criteria:**

**Given** staged Terraform configuration blocks held in StagedWorkspace memory
**When** the developer enters a colloquial tweak string
**Then** TweakHandler resolves the target resource attribute using the AzureRM Attribute Alias Dictionary (e.g. tls -> minimum_tls_version, replication -> account_replication_type)
**And** it mutates the HCL AST model in memory in <= 10 milliseconds
**And** the operation completes 100% locally with zero external network or LLM API calls.

### Story 4.2: Interactive Tweak Loop & Dynamic Diff Re-rendering

As an infrastructure developer,
I want ttassistant to dynamically re-render the unified terminal diff immediately after applying a conversational tweak,
So that I can verify the exact syntax changes before deciding whether to commit or cancel.

**Acceptance Criteria:**

**Given** an updated in-memory StagedWorkspace following a conversational tweak
**When** the tweak mutation finishes
**Then** the terminal clears or refreshes the unified diff display showing updated additions and modifications in green/red
**And** the interactive confirmation gate is re-presented ([Y] Commit / [N] Cancel / [Tweak] Enter refinement)
**And** multiple consecutive tweaks can be applied incrementally within the same interactive session.

### Story 4.3: Existing Folder Inspection & Non-Compliance Diagnostics

As a platform engineer or developer,
I want ttassistant to inspect an existing <resource-type>/<subscription>/ directory and detect missing mandatory tags, enabled public access, or missing Private Endpoints,
So that legacy or non-compliant infrastructure folders can be audited against common_standards/*.md.

**Acceptance Criteria:**

**Given** an existing destination directory containing legacy .tf files
**When** ttassistant runs targeting that directory in remediation mode
**Then** it parses existing HCL files and compares them against common_standards/ and Enterprise Security Triad policies
**And** it identifies compliance violations: missing mandatory tags, public_network_access_enabled = true (or missing denial), and absent azurerm_private_endpoint blocks.

### Story 4.4: Surgical Remediation Staging & Comment Preservation

As an infrastructure developer,
I want ttassistant to stage corrective additions and attribute patches for non-compliant existing folders as a surgical unified diff without deleting comments or existing custom code,
So that I can bring legacy modules up to compliance standards safely without risk of accidental code clobbering.

**Acceptance Criteria:**

**Given** detected non-compliance items in an existing directory
**When** remediation staging executes
**Then** it generates surgical diff patches (appending missing tag entries to tags = { ... }, appending missing azurerm_private_endpoint blocks, or toggling public access denial)
**And** original file comments, custom variable references, and unmanaged resource blocks are 100% preserved
**And** the surgical diff is presented for explicit user confirmation [Y] before committing via atomic swap (os.replace), with strictly zero live terraform apply.

