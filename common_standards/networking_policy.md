---
title: Corporate Networking & DNS Policy
version: "1.0.0"
---

# Enterprise Security Triad & Networking Policy

Private endpoint DNS zone mappings and subnet selection policies for Tier 1 PaaS services.

| Resource Type | Private DNS Zone ID | Private DNS Zone Name | Subnet Patterns | Allow Public Access |
| :--- | :--- | :--- | :--- | :--- |
| azurerm_storage_account | /subscriptions/hub-sub-id/resourceGroups/rg-hub-dns/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net | privatelink.blob.core.windows.net | *snet-paas*, *private*, *data* | False |
| azurerm_key_vault | /subscriptions/hub-sub-id/resourceGroups/rg-hub-dns/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net | privatelink.vaultcore.azure.net | *snet-paas*, *private*, *security* | False |
| default | | | *snet-paas*, *private* | False |
