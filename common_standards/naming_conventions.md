---
title: Corporate Azure Naming Conventions
version: "1.0.0"
---

# Azure Resource Naming Conventions

Corporate naming standards for Azure infrastructure resources deployed via Terraform.

| Resource Type | Naming Pattern | Allowed Characters | Max Length |
| :--- | :--- | :--- | :--- |
| azurerm_resource_group | ^rg-[a-z0-9-]+$ | Lowercase alphanumeric, hyphen | 90 |
| azurerm_storage_account | ^st[a-z0-9]{3,22}$ | Lowercase alphanumeric | 24 |
| azurerm_key_vault | ^kv-[a-z0-9-]{1,21}$ | Lowercase alphanumeric, hyphen | 24 |
| azurerm_virtual_network | ^vnet-[a-z0-9-]+$ | Lowercase alphanumeric, hyphen | 64 |
| azurerm_subnet | ^snet-[a-z0-9-]+$ | Lowercase alphanumeric, hyphen | 80 |
| azurerm_private_endpoint | ^pe-[a-z0-9-]+$ | Lowercase alphanumeric, hyphen | 80 |
| azurerm_linux_virtual_machine | ^vm-[a-z0-9-]+$ | Lowercase alphanumeric, hyphen | 15 |
| azurerm_windows_virtual_machine | ^vm-[a-z0-9-]+$ | Lowercase alphanumeric, hyphen | 15 |
