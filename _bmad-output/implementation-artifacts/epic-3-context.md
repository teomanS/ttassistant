# Epic 3 Context: Enterprise PaaS Security Triad & Universal Resource Catalog

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Enable infrastructure engineers to scaffold any Azure resource with enterprise-grade guardrails: for Tier 1 Enterprise PaaS resources, ttassistant enforces the Enterprise Security Triad by default (mandatory public network access denial, private endpoint binding to selected subnet, and private DNS zone group linked to Hub DNS); for Tier 2 long-tail resources, ttassistant synthesizes syntactically valid HCL blocks from a bundled offline AzureRM schema catalog with compliant naming, tags, and backend state without requiring external cloud connectivity, credentials, or terraform/az CLI binaries.

## Stories

- Story 3.1: Bundled Offline AzureRM Provider Schema Catalog
- Story 3.2: Tier 1 PaaS Scaffolding with Mandatory Public Network Access Denial
- Story 3.3: Automated Private Endpoint & Hub Private DNS Zone Group Bundling
- Story 3.4: Tier 2 Universal Azure Long-Tail Resource Scaffolding

## Requirements & Constraints

- **Tiered Azure Resource Delivery Model**: Support code generation for all Azure resources supported by the `azurerm` Terraform provider using a two-tier delivery model:
  - *Tier 1 (Guided Enterprise PaaS & Foundation)*: Full guided conversational prompts, automated private endpoint and DNS zone group bundling, candidate subnet discovery, and specialized attribute validation for core enterprise services (Storage Accounts, Key Vaults, Azure SQL, Cosmos DB, Event Hubs, PostgreSQL, MySQL, Redis, App Services, VNets, Subnets, Resource Groups).
  - *Tier 2 (Universal Azure Long-Tail)*: Universal syntax scaffolding for all other `azurerm_*` provider resources, emitting syntactically valid HCL blocks with corporate naming schemas, mandatory tags, isolated subscription backend state, and decoupled data sources.
- **Offline Schema Catalog & Air-Gapped Operation**: Package an offline AzureRM schema catalog (`ttassistant/data/azurerm_schema.json`) containing extracted resource argument metadata and required attributes. Schema inspection and validation must operate purely in memory with zero network calls, zero ARM REST API calls, and zero external CLI binaries (`terraform providers schema` or `az`).
- **Mandatory Public Network Access Denial (Tier 1 PaaS)**: Explicitly set public network access denial (`public_network_access_enabled = false` or resource-specific equivalent attribute) in primary PaaS resource blocks by default.
- **Public Access Security Warning Gate**: If the user explicitly attempts to enable public access on a PaaS resource, the CLI must display a high-visibility security warning and require explicit human confirmation.
- **Automated Private Endpoint & DNS Zone Group Bundling**:
  - Automatically synthesize an `azurerm_private_endpoint` resource in `main.tf` referencing the selected subnet data source (`data.azurerm_subnet.<name>.id`) and the primary resource ID.
  - Automatically synthesize a `private_dns_zone_group` block linked to the corporate Hub Private DNS Zone resolved from `common_standards/networking_policy.md`.
  - Automatically emit the required Hub Private DNS Zone data source block (`data "azurerm_private_dns_zone"`) in `data.tf`. Workload spoke configurations must never create new Hub Private DNS Zones.
- **Decoupled Data Architecture & State Isolation**: Reference upstream resources by name and resource group using `data "azurerm_*"` blocks. The generated HCL must contain strictly zero `terraform_remote_state` data blocks. Emit a dedicated `backend.tf` with the isolated subscription remote state key.
- **Lean File Layout**: Tier 2 universal resources omit `variables.tf` and `outputs.tf` by default, scaffolding only `main.tf`, `data.tf`, and `backend.tf`.

## Technical Decisions

- **Hexagonal Architecture Boundaries (AD-1)**:
  - `ttassistant.data`: Bundled static schema metadata (`azurerm_schema.json`).
  - `ttassistant.domain.scaffold`: Synthesis of Tier 1 & Tier 2 resource configurations, Security Triad bundling (`public_network_access_enabled = false`, `azurerm_private_endpoint`, `private_dns_zone_group`), and decoupled data sources.
  - `ttassistant.domain.standards`: Resolution of naming conventions, mandatory tags, backend mappings, and Hub DNS zone configurations from `common_standards/`.
  - `ttassistant.application.provisioning_flow`: Flow orchestration handling resource selection, catalog tier branching, interactive parameter collection, subnet selection integration, and security warning gates.
- **Tiered Catalog Architecture (AD-3, AD-7)**:
  - Partition the AzureRM catalog into Tier 1 (guided prompts and security bundling) and Tier 2 (universal long-tail schema generation).
  - Keeps CLI memory footprint under 150 MB RSS (NFR-3) and startup under 1.5s (NFR-1) while avoiding bloated static AST representations for 1,000+ resources.
- **Enterprise Security Triad Enforcement (AD-7)**:
  - For Tier 1 PaaS, generates the primary resource block, companion `azurerm_private_endpoint`, and child `private_dns_zone_group` in `main.tf`.
  - Upstream networking dependencies (`data.azurerm_subnet.<name>.id`, `data.azurerm_resource_group.<name>.name`) and Hub Private DNS Zone data sources are wired into `data.tf`.
- **Decoupled State & Lean Module Layout (AD-3)**:
  - Emitted files in `<resource-type>/<subscription>/` strictly follow the lean decoupled structure (`main.tf`, `data.tf`, `backend.tf`).
  - Dedicated Azure Blob backend state keys prevent state collisions across subscriptions.
- **Multi-Directory Atomic Staging (AD-5, NFR-7)**:
  - Staged file buffers are held in memory within `StagedWorkspace`. If missing dependencies (e.g., missing subnet definitions) are staged alongside the primary workload, all affected directories are committed atomically via sibling `.tmp` files with `os.replace` and rollback protection.

## UX & Interaction Patterns

- **Catalog Discovery & Tier Branching**: Interactive resource selection allowing fuzzy search across `azurerm_*` types. Selecting Tier 1 initiates guided conversational prompts with subnet selection and security triad bundling; selecting Tier 2 initiates prompt collection for naming, subscription, and required schema attributes.
- **Security Triad Visibility**: Terminal diff preview clearly visualizes the triad components: public network denial, private endpoint binding, and Hub Private DNS zone linking.
- **High-Visibility Security Confirmation Gate**: Explicit warning modal/banner when public access is requested, prompting the engineer to confirm or revert to private-only networking.
- **Terminal Degradation & Automation**: Graceful fallback to line-oriented standard input in non-TTY or `TERM=dumb` environments; supports headless execution via `--yes` and CLI arguments.

## Cross-Story Dependencies

- **Story 3.1** provides the bundled schema catalog (`azurerm_schema.json`) and catalog loading mechanism, defining the boundary and metadata for Tier 1 and Tier 2 resources.
- **Story 3.2** extends the scaffolding engine (`scaffold.py`) to enforce `public_network_access_enabled = false` and confirmation warning gates for Tier 1 PaaS resources.
- **Story 3.3** consumes the candidate subnet selected in Epic 2 (`data.azurerm_subnet.<name>.id`) and Hub DNS zone standards to bundle `azurerm_private_endpoint`, `private_dns_zone_group`, and `data.tf` DNS zone blocks.
- **Story 3.4** combines the schema catalog from Story 3.1 with the standards engine (Epic 1) to synthesize valid HCL blocks for any long-tail Tier 2 resource with compliant naming, tags, and backend state.
