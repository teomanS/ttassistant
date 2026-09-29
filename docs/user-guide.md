# `ttassistant` User Guide

Welcome to `ttassistant`! This guide walks you through common developer workflows, from greenfield resource scaffolding to legacy code compliance auditing in CI/CD pipelines.

---

## Table of Contents
1. [Installation & Setup](#1-installation--setup)
2. [Workflow 1: Greenfield Tier 1 PaaS Provisioning](#2-workflow-1-greenfield-tier-1-paas-provisioning)
3. [Workflow 2: Interactive Tweak Loop](#3-workflow-2-interactive-tweak-loop)
4. [Workflow 3: Monorepo Topology Discovery](#4-workflow-3-monorepo-topology-discovery)
5. [Workflow 4: Offline Catalog Inspection](#5-workflow-4-offline-catalog-inspection)
6. [Workflow 5: CI/CD Compliance Gating & Surgical Remediation](#6-workflow-5-cicd-compliance-gating--surgical-remediation)

---

## 1. Installation & Setup

### Option A: Install Directly from Git (Recommended)
End users do not need to download or build `.whl` files manually. `pip` can install `ttassistant` directly from your Git repository:

```bash
pip install git+https://github.com/teomans/ttassistant.git
```

### Option B: Build the Wheel Locally
If users clone the repository or need an air-gapped `.whl` package:

```bash
# Build the wheel into dist/
python -c "import hatchling.build; hatchling.build.build_wheel('dist')"

# Install the built wheel
pip install dist/ttassistant-0.1.0-py3-none-any.whl
```

### Option C: Download from GitHub Releases
Maintainers can upload the built `ttassistant-0.1.0-py3-none-any.whl` to GitHub Releases (e.g., Release `v0.1.0`). Users can install it directly via:

```bash
pip install https://github.com/teomans/ttassistant/releases/download/v0.1.0/ttassistant-0.1.0-py3-none-any.whl
```

### Verify Installation
```bash
ttassistant --version
# Output: ttassistant 0.1.0
```

### Corporate Standards Discovery
`ttassistant` automatically searches for a `common_standards/` directory in the current working directory and its ancestor directories. You can also point to a custom directory using the `--standards-dir` flag or the `TT_STANDARDS_DIR` environment variable:

```bash
export TT_STANDARDS_DIR="/path/to/corporate/common_standards"
```

---

## 2. Workflow 1: Greenfield Tier 1 PaaS Provisioning

When provisioning sensitive Azure resources (like Storage Accounts, Key Vaults, or Cosmos DB), enterprise security policy mandates private endpoints, hub DNS integration, and state backend isolation.

### Example: Provisioning a Secure Storage Account

Run `ttassistant new` with pre-populated arguments:

```bash
ttassistant new \
  --subscription workload-prod \
  --resource-type azurerm_storage_account \
  --workload orderdata \
  --env prod \
  --subnet snet-paas \
  --yes
```

`ttassistant` generates three decoupled Terraform files under `azurerm_storage_account/workload-prod/`:

1. **`backend.tf`**:
   Configured with remote state isolation for `workload-prod`:
   ```terraform
   terraform {
     backend "azurerm" {
       resource_group_name  = "rg-tfstate-prod"
       storage_account_name = "sttfstateprod"
       container_name       = "tfstate"
       key                  = "prod/azurerm_storage_account.tfstate"
     }
   }
   ```

2. **`data.tf`**:
   Decoupled data lookups eliminating brittle remote state dependencies:
   ```terraform
   data "azurerm_resource_group" "primary" {
     name = "rg-tfstate-prod"
   }

   data "azurerm_virtual_network" "primary" {
     name                = "vnet-prod-hub"
     resource_group_name = "rg-network-prod"
   }

   data "azurerm_subnet" "primary" {
     name                 = "snet-paas"
     resource_group_name  = data.azurerm_virtual_network.primary.resource_group_name
     virtual_network_name = data.azurerm_virtual_network.primary.name
   }

   data "azurerm_private_dns_zone" "hub" {
     name                = "privatelink.blob.core.windows.net"
     resource_group_name = "rg-hub-dns"
   }
   ```

3. **`main.tf`**:
   The primary resource accompanied by corporate tags, public access denial, and companion Private Endpoint:
   ```terraform
   resource "azurerm_storage_account" "primary" {
     name                          = "storderdataprod"
     resource_group_name           = data.azurerm_resource_group.primary.name
     location                      = data.azurerm_resource_group.primary.location
     account_tier                  = "Standard"
     account_replication_type      = "LRS"
     public_network_access_enabled = false

     tags = {
       CostCenter  = "CC-1001"
       Environment = "prod"
       ManagedBy   = "terraform"
       Owner       = "cloud-platform@corporate.com"
       Project     = "CorePlatform"
     }
   }

   resource "azurerm_private_endpoint" "primary" {
     name                = "pe-storderdataprod"
     location            = data.azurerm_resource_group.primary.location
     resource_group_name = data.azurerm_resource_group.primary.name
     subnet_id           = data.azurerm_subnet.primary.id

     tags = {
       CostCenter  = "CC-1001"
       Environment = "prod"
       ManagedBy   = "terraform"
       Owner       = "cloud-platform@corporate.com"
       Project     = "CorePlatform"
     }

     private_service_connection {
       name                           = "psc-storderdataprod"
       private_connection_resource_id = azurerm_storage_account.primary.id
       is_manual_connection           = false
       subresource_names              = ["blob"]
     }

     private_dns_zone_group {
       name                 = "default"
       private_dns_zone_ids = [
         data.azurerm_private_dns_zone.hub.id,
       ]
     }
   }
   ```

---

## 3. Workflow 2: Interactive Tweak Loop

If you run `ttassistant new` without `--yes`, you enter the interactive review screen:

```bash
ttassistant new --subscription workload-dev --resource-type azurerm_storage_account --workload cache
```

You are presented with a colorized unified diff and a prompt:
```text
Tweak expression (or Enter to accept, 'c' to cancel):
```

### Supported Tweak Syntax

- **Direct attribute assignment**:
  `account_replication_type = GRS`
- **Natural shorthand & aliasing**:
  `replication_type = ZRS`
  `sku = Standard_GRS`
  `tier = Premium`
- **Tag modifications**:
  `tags.CostCenter = CC-5555`
  `tags.Service = CacheLayer`
- **Complex blocks**:
  `network_rules.default_action = Deny`

Whenever you apply a tweak, `ttassistant` validates the changes in-memory against corporate policies, updates the staged files, and displays a fresh unified diff.

---

## 4. Workflow 3: Monorepo Topology Discovery

Before provisioning, understand what networking resources exist across the monorepo:

```bash
# Fast regex scan of the repository
ttassistant scan .

# Deep AST scan with CIDR and PE candidate verification
ttassistant scan . --ast
```

Output:
```text
[*] Topology Discovery: scanned 42 .tf files in 0.048s.
Discovered Subnets (6 total, 4 Private Endpoint candidates)
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ Subnet Name  ┃ CIDR         ┃ VNet Name     ┃ Resource Group     ┃ Type      ┃ PE Candidate ┃ Subscription  ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ snet-paas-01 │ 10.10.1.0/24 │ vnet-prod-hub │ rg-network-prod    │ Standalone│ Yes          │ workload-prod │
│ snet-db-01   │ 10.10.2.0/24 │ vnet-prod-hub │ rg-network-prod    │ Standalone│ Yes          │ workload-prod │
└──────────────┴──────────────┴───────────────┴────────────────────┴───────────┴──────────────┴───────────────┘
[x] Phase 2 AST Extraction Complete: 6 subnets, 2 VNets, 4 resource groups.
```

---

## 5. Workflow 4: Offline Catalog Inspection

Check resource schemas without internet access or waiting on Terraform provider downloads:

```bash
# List all Tier 1 PaaS resources
ttassistant catalog list --tier 1

# Search resources by prefix
ttassistant catalog list --prefix azurerm_mssql

# Inspect schema arguments and types for a resource
ttassistant catalog info azurerm_key_vault
```

---

## 6. Workflow 5: CI/CD Compliance Gating & Surgical Remediation

### Step A: Audit in CI/CD Pipeline (`--check`)

Add `ttassistant remediate <path> --check` to your pull request pipeline:

```bash
ttassistant remediate ./workload-dev/storage/ --check
```

If non-compliant code is present, it prints a diagnostic table and **exits with code 1**:
```text
[?] Compliance Audit: Found 2 violation(s) (1 critical, 1 high, 0 medium, 0 low).

=== Non-Compliance Diagnostics ===
Severity | Violation Category            | Target Resource               | File    | Remediation Hint
---------+-------------------------------+-------------------------------+---------+-------------------------------------------------------------
CRITICAL | public_network_access_enabled | azurerm_storage_account.sa01  | main.tf | Set 'public_network_access_enabled = false'.
HIGH     | missing_tag                   | azurerm_storage_account.sa01  | main.tf | Add 'CostCenter = "CC-1001"' to tags = { ... }.
```

### Step B: Surgically Remediate (`--yes`)

Run with `--yes` to apply surgical fixes directly to the `.tf` files:

```bash
ttassistant remediate ./workload-dev/storage/ --yes
```

All developer comments, formatting, and surrounding resources remain 100% intact while corporate standards are enforced.

