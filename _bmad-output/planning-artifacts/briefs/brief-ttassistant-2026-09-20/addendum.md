# Product Brief Addendum: ttassistant

## 1. Repository Topology & Folder Architecture Details
- **Existing Structure:** The Bitbucket repository organizes infrastructure primarily by `<resourcetypename>/<subscription-name>` (e.g., `storage-account/dev-subs`, `storage-account/test-subs`, `aks/prod-subs`).
- **Inconsistency Reality:** There is currently no strict naming uniformity across directory names or file names. Child folder naming may vary across resource types.
- **Cross-Folder Dependencies:** Core dependencies (such as Resource Groups, Virtual Networks, Route Tables) frequently reside in distinct directories (e.g., `resource-group/<subs>/`).
- **Referencing Patterns:**
  - Standard approach: Referencing external resource groups via `data "azurerm_resource_group" "..."` blocks.
  - Legacy approach: Hardcoded string names for resource groups.
  - The CLI should identify standard shared resource groups within the target subscription and automatically generate appropriate `data` blocks rather than hardcoding names.

## 2. Azure Blob Backend Configuration Variance
- Every subscription has specific backend storage requirements for the Terraform state file.
- Azure Blob backend variables (`resource_group_name`, `storage_account_name`, `container_name`, `key`) must be mapped dynamically based on the active subscription.
- The assistant must infer or look up the subscription-specific backend values from `.md` gold standards or repository conventions.

## 3. Enterprise Networking & Private Link Deep Dive
- When provisioning Azure PaaS services (e.g., Storage Accounts, Key Vaults, Azure SQL, CosmosDB, Event Hubs), the CLI must generate:
  1. The target Azure resource configured to deny public network access.
  2. The `azurerm_private_endpoint` resource linked to the designated application/data subnet.
  3. The `azurerm_private_dns_zone_virtual_network_link` and DNS zone group records to ensure private name resolution within the VNet.

## 4. Deferred Capabilities (Parked for Post-MVP)
- **Destruction & Replacement Interception:** AST plan analysis to alert on `forces replacement` or `prevent_destroy` violations (deliberately scoped out of v1 MVP to prioritize authoring speed and folder resolution).
- **Automated Drift & Modernization PRs:** Batch analysis of legacy folders against `.md` standards to generate refactoring pull requests.
- **Multi-Cloud Extensions:** AWS and GCP provider support.

