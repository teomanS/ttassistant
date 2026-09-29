# `ttassistant` CLI Reference Guide

`ttassistant` is an air-gapped terminal CLI copilot designed for enterprise Azure Terraform engineering. It enforces corporate standards at creation time, discovers monorepo network topologies, validates resource schemas offline, and performs surgical, comment-preserving compliance remediation.

---

## Architectural Principles

1. **Pure Air-Gapped Local Operation (AD-2, NFR-5)**:
   - Does **not** require or execute `terraform`, `az` CLI, or any external network connections.
   - Operates strictly against local monorepo `.tf` files and bundled AzureRM provider schemas.
2. **Hexagonal Architecture (AD-1)**:
   - Domain logic (standards, HCL syntax, topology, tweak engine, compliance rules, surgical patcher) remains strictly isolated from framework and I/O adapters.
3. **Fail-Fast Corporate Standards (FR-1, FR-3)**:
   - Dynamic ingestion and strict schema validation of corporate standards markdown tables (`naming_conventions.md`, `tagging_baseline.md`, `networking_policy.md`, `backend_mapping.md`).
4. **Surgical Non-Destructive In-Memory Staging (AD-4, FR-8, FR-20)**:
   - All code generation, tweaks, and remediations are staged inside an in-memory `StagedWorkspace` before human confirmation or CI commit.
   - Atomic disk writes utilize sibling `.tmp` files, `os.fsync`, and atomic `os.replace` with automatic rollback on error.

---

## Global Options

```bash
ttassistant [OPTIONS] COMMAND [ARGS]...
```

| Option | Flag | Description |
|---|---|---|
| `--standards-dir` | `-s` | Path to corporate standards directory containing markdown files. Defaults to discovering `./common_standards` in the current or ancestor directories. Environment variable: `TT_STANDARDS_DIR`. |
| `--version` | `-v` | Show package version and exit. |
| `--debug` | `-d` | Enable debug mode with full exception tracebacks. |
| `--help` | | Show help message and exit. |

---

## Commands

### 1. `ttassistant new`

Scaffold a new enterprise-governed Terraform workspace for Tier 1 PaaS or Tier 2 Universal Azure resources.

```bash
ttassistant new [OPTIONS]
```

#### Options

| Option | Flag | Description |
|---|---|---|
| `--subscription` | `-sub` | Target Azure subscription identifier (e.g. `workload-prod`, `workload-dev`). |
| `--resource-type` | `-r` | Target Azure resource type (e.g. `azurerm_storage_account`, `azurerm_resource_group`). |
| `--workload` | `-w` | Workload identifier (e.g. `appdata`, `analytics`). Formatted automatically via corporate naming patterns. |
| `--env` | `-e` | Deployment environment (`dev`, `stage`, `prod`, `qa`, etc.). |
| `--subnet` | `-snet` | Target candidate subnet name or resource ID. |
| `--public-network-access` | | Enable public network access on Tier 1 PaaS resource (requires explicit confirmation). |
| `--confirm-public-network-access` | | Explicit override confirming public access waiver for headless CI/CD scripts. |
| `--yes` | `-y` | Skip interactive tweak prompt and diff confirmation gate; commit workspace to disk immediately. |

#### Scaffolding Features

- **Tier 1 Guided PaaS**:
  - Scaffolds `backend.tf`, `data.tf`, and `main.tf`.
  - Enforces the **Enterprise Security Triad**:
    - Mandatory public network denial: `public_network_access_enabled = false`.
    - Companion Private Endpoint: `resource "azurerm_private_endpoint" "primary"` wired to target subnet.
    - Hub Private DNS Zone Group: `private_dns_zone_group` referencing corporate Hub DNS zone.
  - Generates decoupled data source references (`data "azurerm_subnet"`, `data "azurerm_resource_group"`) instead of fragile remote state references.
- **Tier 2 Universal Resources**:
  - Validates argument schemas against the offline AzureRM catalog.
  - Automatically injects corporate mandatory compliance tags (`Environment`, `Owner`, `Project`, `CostCenter`).
- **Interactive Tweak Loop (Story 4.1 & 4.2)**:
  - If `--yes` is omitted, `ttassistant` enters an interactive tweak loop displaying a colorized unified diff.
  - Accepts natural attribute expressions: `sku=Standard_GRS`, `replication_type=GRS`, `tier=Premium`, `tags.CostCenter=CC-9999`.
  - Re-validates against corporate policies and re-renders live diffs in real-time.

---

### 2. `ttassistant scan`

Recursively scan the monorepo filesystem to discover Azure networking topology, candidate subnets, VNets, and resource groups.

```bash
ttassistant scan [OPTIONS] [SCAN_PATH]
```

#### Arguments & Options

| Argument / Option | Flag | Description |
|---|---|---|
| `SCAN_PATH` | | Directory path to scan (defaults to current working directory `.`). |
| `--ast` | `-a` | Enable Phase 2 full AST parsing via `python-hcl2` for high-precision extraction. |
| `--subscription` | `-sub` | Filter discovered networking resources by subscription. |
| `--resource-type` | `-r` | Filter output by resource type (`azurerm_subnet`, `azurerm_virtual_network`, `azurerm_resource_group`). |

#### Two-Phase Scanning Pipeline

- **Phase 1 (Lexical Fast-Scan)**:
  - Scans thousands of files in under 500ms using compiled lexical regular expressions.
  - Filters out `.terraform/`, `vendor/`, and hidden folders.
- **Phase 2 (AST Extraction)**:
  - Triggered automatically when candidate subnets are needed or when `--ast` is specified.
  - Resolves subnet CIDRs, inline subnets, standalone subnets, and Private Endpoint eligibility (checks for gateway/bastion subnets and delegated PaaS subnets).

---

### 3. `ttassistant catalog`

Inspect the bundled, offline AzureRM provider schema catalog.

```bash
ttassistant catalog [COMMAND]
```

#### Subcommands

##### `ttassistant catalog list`
List resources available in the offline catalog.

```bash
ttassistant catalog list [OPTIONS]
```

| Option | Flag | Description |
|---|---|---|
| `--tier` | `-t` | Filter by tier (`1` for Guided PaaS, `2` for Universal long-tail). |
| `--prefix` | `-p` | Filter by resource type prefix (e.g. `azurerm_mssql`, `azurerm_storage`). |

##### `ttassistant catalog info`
Inspect the schema arguments and metadata for a specific resource type.

```bash
ttassistant catalog info <RESOURCE_TYPE>
```

Displays:
- Resource classification tier and description.
- Required attributes vs optional attributes.
- Type definitions, descriptions, and security triad classifications.

---

### 4. `ttassistant remediate`

Inspect an existing Terraform directory, diagnose non-compliance issues against corporate standards, and surgically apply fixes while preserving 100% of comments.

```bash
ttassistant remediate [OPTIONS] <TARGET_DIR>
```

#### Options

| Option | Flag | Description |
|---|---|---|
| `TARGET_DIR` | | Target directory containing `.tf` files to inspect or remediate. |
| `--check` | `-c` | Audit-only mode. Outputs diagnostic table and diff preview, exiting with code `1` if non-compliance is detected (ideal for CI/CD gates). |
| `--yes` | `-y` | Skip interactive prompt and apply surgical remediation directly to disk. |

#### Surgical Remediation Capabilities

- **Diagnostic Classification**:
  - `CRITICAL`: `public_network_access_enabled` violation on Tier 1 PaaS.
  - `HIGH`: Missing corporate tags or missing companion Private Endpoint.
  - `MEDIUM`: Invalid resource naming patterns.
  - `LOW`: Formatting or non-critical attribute discrepancies.
- **Surgical In-Place Patching**:
  - Updates `public_network_access_enabled = false` in-place without altering other attributes.
  - Injects missing tags into existing `tags = { ... }` blocks with matching interior indentation.
  - Synthesizes companion `azurerm_private_endpoint` blocks with matching subresources (`blob`, `vault`, etc.) and Hub DNS zone group.
- **100% Comment & Style Preservation**:
  - Retains all `#`, `//`, and `/* ... */` comments.
  - Preserves inline comments trailing modified attributes.
  - Respects existing indentation and quoting styles.

