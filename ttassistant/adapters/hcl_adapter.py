"""Read-only HCL AST parser adapter using python-hcl2 (AD-1, AD-2)."""

from collections.abc import Iterable
import logging
from pathlib import Path
import re
from typing import Any, Optional, Union

import hcl2

from ttassistant.domain.compliance import ParsedResource
from ttassistant.domain.topology import (
    CandidateFile,
    DiscoveredTopology,
    ResourceGroupCandidate,
    SubnetCandidate,
    VirtualNetworkCandidate,
    infer_subscription,
    is_private_endpoint_subnet,
)
from ttassistant.ports.hcl_parser import HCLParserPort

logger = logging.getLogger(__name__)


def _strip_quotes(val: Any) -> Any:
    """Normalize HCL string artifacts by stripping enclosing quotes and trailing whitespace."""
    if not isinstance(val, str):
        return val
    s = val.strip()
    # Strip double and single quotes (repeatedly if nested like '"\"..."\"')
    while len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        s = s[1:-1].strip()
    return s


def _clean_string(val: Any) -> str:
    """Return a sanitized, unquoted string."""
    if val is None:
        return ""
    cleaned = _strip_quotes(str(val))
    return cleaned


def _clean_tags(raw: Any) -> dict[str, str]:
    """Clean and normalize resource tags dictionary from HCL AST."""
    if not isinstance(raw, dict):
        if isinstance(raw, list):
            merged: dict[str, str] = {}
            for item in raw:
                if isinstance(item, dict):
                    merged.update(_clean_tags(item))
            return merged
        return {}

    cleaned: dict[str, str] = {}
    for k, v in raw.items():
        if k == "__is_block__":
            continue
        clean_k = _clean_string(k)
        if isinstance(v, (dict, list)):
            clean_v = str(v)
        else:
            clean_v = _clean_string(v)
        if clean_k:
            cleaned[clean_k] = clean_v
    return cleaned


def _extract_address_prefixes(body: dict[str, Any]) -> list[str]:
    """Extract and normalize address prefixes list, falling back from singular address_prefix."""
    raw_prefixes = body.get("address_prefixes")
    if raw_prefixes is not None:
        if isinstance(raw_prefixes, list):
            return [_clean_string(p) for p in raw_prefixes if p is not None]
        return [_clean_string(raw_prefixes)]

    raw_prefix = body.get("address_prefix")
    if raw_prefix is not None:
        if isinstance(raw_prefix, list):
            return [_clean_string(p) for p in raw_prefix if p is not None]
        return [_clean_string(raw_prefix)]

    return []


def _extract_address_space(body: dict[str, Any]) -> list[str]:
    """Extract and normalize address_space list for Virtual Networks."""
    raw_space = body.get("address_space")
    if raw_space is not None:
        if isinstance(raw_space, list):
            return [_clean_string(p) for p in raw_space if p is not None]
        return [_clean_string(raw_space)]
    return []


def _extract_bool(val: Any) -> Optional[bool]:
    """Normalize boolean attributes (e.g. private_endpoint_network_policies_enabled)."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    cleaned = _clean_string(val).lower()
    if cleaned in ("true", "1", "yes"):
        return True
    if cleaned in ("false", "0", "no"):
        return False
    return None


class ReadOnlyHclAdapter(HCLParserPort):
    """Read-only HCL AST parser adapter using python-hcl2 (AD-1, AD-2).

    Parses candidate .tf files in memory into typed domain models.
    Enforces strictly zero round-trip serialization (hcl2.dump() is never called).
    """

    def __init__(self, standards_patterns: Optional[list[str]] = None) -> None:
        """Initialize adapter with optional corporate standards subnet patterns.

        Args:
            standards_patterns: Optional list of glob patterns from networking policy.
        """
        self.standards_patterns = standards_patterns

    def parse_hcl_string(
        self,
        content: str,
        filename: str = "<string>",
        subscription: Optional[str] = None,
    ) -> DiscoveredTopology:
        """Parse raw HCL string content in-memory into DiscoveredTopology entities."""
        topology = DiscoveredTopology()
        if not content or not content.strip():
            return topology

        try:
            parsed = hcl2.loads(content)
        except Exception as exc:
            msg = f"{filename}: {exc}"
            logger.warning("Failed to parse HCL string: %s", msg)
            topology.parse_errors.append(msg)
            return topology

        if not isinstance(parsed, dict):
            return topology

        # Lookups for intra-file reference resolution
        rg_by_label: dict[str, ResourceGroupCandidate] = {}
        vnet_by_label: dict[str, VirtualNetworkCandidate] = {}

        # 1. Parse Resource Groups
        self._extract_resource_groups(
            parsed=parsed,
            filename=filename,
            subscription=subscription,
            topology=topology,
            rg_lookup=rg_by_label,
        )

        # 2. Parse Virtual Networks (and nested inline subnets)
        self._extract_virtual_networks(
            parsed=parsed,
            filename=filename,
            subscription=subscription,
            topology=topology,
            vnet_lookup=vnet_by_label,
        )

        # 3. Parse Standalone Subnets
        self._extract_subnets(
            parsed=parsed,
            filename=filename,
            subscription=subscription,
            topology=topology,
        )

        # 4. Resolve references between resources in this file
        self._resolve_references(topology, rg_by_label, vnet_by_label)

        return topology

    def parse_hcl_file(
        self,
        file_path: Union[Path, str],
        subscription: Optional[str] = None,
    ) -> DiscoveredTopology:
        """Read and parse a single HCL file into DiscoveredTopology."""
        path = Path(file_path)
        sub = subscription or infer_subscription(path)
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            msg = f"{path}: {exc}"
            logger.warning("Failed to read HCL file: %s", msg)
            return DiscoveredTopology(parse_errors=[msg])

        return self.parse_hcl_string(content, filename=str(path), subscription=sub)

    def parse_topology_candidates(
        self,
        candidates: Union[Iterable[CandidateFile], Iterable[Union[Path, str]]],
    ) -> DiscoveredTopology:
        """Parse identified candidate files into structured domain topology entities."""
        cand_list = list(candidates)
        if not cand_list:
            return DiscoveredTopology()

        total_topology = DiscoveredTopology()
        rg_by_label: dict[str, ResourceGroupCandidate] = {}
        vnet_by_label: dict[str, VirtualNetworkCandidate] = {}

        for item in cand_list:
            if isinstance(item, CandidateFile):
                file_path = item.path
                subscription = item.subscription
            else:
                file_path = str(item)
                subscription = infer_subscription(file_path)

            path = Path(file_path)
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                msg = f"{file_path}: {exc}"
                logger.warning("Failed to read candidate file %s: %s", file_path, exc)
                total_topology.parse_errors.append(msg)
                continue

            file_topo = self.parse_hcl_string(
                content=content,
                filename=file_path,
                subscription=subscription,
            )

            total_topology.subnets.extend(file_topo.subnets)
            total_topology.virtual_networks.extend(file_topo.virtual_networks)
            total_topology.resource_groups.extend(file_topo.resource_groups)
            total_topology.parse_errors.extend(file_topo.parse_errors)

            sub_key = subscription or ""
            for rg in file_topo.resource_groups:
                label = rg.metadata.get("label")
                if label:
                    rg_by_label[(sub_key, label)] = rg
                    rg_by_label[label] = rg
                rg_by_label[(sub_key, rg.name)] = rg
                rg_by_label[rg.name] = rg

            for vnet in file_topo.virtual_networks:
                label = vnet.metadata.get("label")
                if label:
                    vnet_by_label[(sub_key, label)] = vnet
                    vnet_by_label[label] = vnet
                vnet_by_label[(sub_key, vnet.name)] = vnet
                vnet_by_label[vnet.name] = vnet

        # Cross-file reference resolution pass
        self._resolve_references(total_topology, rg_by_label, vnet_by_label)

        return total_topology

    def _extract_resource_groups(
        self,
        parsed: dict[str, Any],
        filename: str,
        subscription: Optional[str],
        topology: DiscoveredTopology,
        rg_lookup: dict[str, ResourceGroupCandidate],
    ) -> None:
        """Extract azurerm_resource_group resource and data blocks."""
        sections = [("resource", False), ("data", True)]
        for sec_name, is_data in sections:
            blocks = parsed.get(sec_name, [])
            if not isinstance(blocks, list):
                continue
            for item in blocks:
                if not isinstance(item, dict):
                    continue
                for raw_type, labels_dict in item.items():
                    type_name = _clean_string(raw_type)
                    if type_name != "azurerm_resource_group" or not isinstance(labels_dict, dict):
                        continue
                    for raw_label, body in labels_dict.items():
                        label = _clean_string(raw_label)
                        if not isinstance(body, dict):
                            continue
                        name_attr = _clean_string(body.get("name"))
                        rg_name = name_attr if name_attr else label
                        location = _clean_string(body.get("location")) or None
                        tags = _clean_tags(body.get("tags"))

                        rg_cand = ResourceGroupCandidate(
                            name=rg_name,
                            location=location,
                            tags=tags,
                            is_data_source=is_data,
                            file_path=filename,
                            subscription=subscription,
                            metadata={"label": label, "raw_name": name_attr},
                        )
                        topology.resource_groups.append(rg_cand)
                        sub_key = subscription or ""
                        if label:
                            rg_lookup[(sub_key, label)] = rg_cand
                            rg_lookup[label] = rg_cand
                        rg_lookup[(sub_key, rg_name)] = rg_cand
                        rg_lookup[rg_name] = rg_cand

    def _extract_virtual_networks(
        self,
        parsed: dict[str, Any],
        filename: str,
        subscription: Optional[str],
        topology: DiscoveredTopology,
        vnet_lookup: dict[str, VirtualNetworkCandidate],
    ) -> None:
        """Extract azurerm_virtual_network resource and data blocks, including inline subnets."""
        sections = [("resource", False), ("data", True)]
        for sec_name, is_data in sections:
            blocks = parsed.get(sec_name, [])
            if not isinstance(blocks, list):
                continue
            for item in blocks:
                if not isinstance(item, dict):
                    continue
                for raw_type, labels_dict in item.items():
                    type_name = _clean_string(raw_type)
                    if type_name != "azurerm_virtual_network" or not isinstance(labels_dict, dict):
                        continue
                    for raw_label, body in labels_dict.items():
                        label = _clean_string(raw_label)
                        if not isinstance(body, dict):
                            continue
                        name_attr = _clean_string(body.get("name"))
                        vnet_name = name_attr if name_attr else label
                        rg_name = _clean_string(body.get("resource_group_name")) or None
                        location = _clean_string(body.get("location")) or None
                        address_space = _extract_address_space(body)
                        tags = _clean_tags(body.get("tags"))

                        inline_subnets: list[SubnetCandidate] = []
                        raw_subnets = body.get("subnet")
                        sub_blocks = []
                        if isinstance(raw_subnets, list):
                            sub_blocks.extend([s for s in raw_subnets if isinstance(s, dict)])
                        elif isinstance(raw_subnets, dict):
                            sub_blocks.append(raw_subnets)

                        for s_dict in sub_blocks:
                            s_name = _clean_string(s_dict.get("name"))
                            s_prefixes = _extract_address_prefixes(s_dict)
                            s_pe_policies = _extract_bool(s_dict.get("private_endpoint_network_policies_enabled"))
                            s_tags = _clean_tags(s_dict.get("tags"))
                            is_pe = is_private_endpoint_subnet(
                                s_name,
                                network_policies_enabled=s_pe_policies,
                                tags=s_tags,
                                standards_patterns=self.standards_patterns,
                            )
                            s_cand = SubnetCandidate(
                                name=s_name,
                                address_prefixes=s_prefixes,
                                virtual_network_name=vnet_name,
                                resource_group_name=rg_name,
                                is_inline=True,
                                is_data_source=is_data,
                                is_private_endpoint_candidate=is_pe,
                                private_endpoint_network_policies_enabled=s_pe_policies,
                                tags=s_tags,
                                file_path=filename,
                                subscription=subscription,
                                metadata={"parent_vnet": vnet_name},
                            )
                            inline_subnets.append(s_cand)
                            topology.subnets.append(s_cand)

                        vnet_cand = VirtualNetworkCandidate(
                            name=vnet_name,
                            resource_group_name=rg_name,
                            location=location,
                            address_space=address_space,
                            subnets=inline_subnets,
                            tags=tags,
                            is_data_source=is_data,
                            file_path=filename,
                            subscription=subscription,
                            metadata={"label": label, "raw_name": name_attr},
                        )
                        topology.virtual_networks.append(vnet_cand)
                        sub_key = subscription or ""
                        if label:
                            vnet_lookup[(sub_key, label)] = vnet_cand
                            vnet_lookup[label] = vnet_cand
                        vnet_lookup[(sub_key, vnet_name)] = vnet_cand
                        vnet_lookup[vnet_name] = vnet_cand

    def _extract_subnets(
        self,
        parsed: dict[str, Any],
        filename: str,
        subscription: Optional[str],
        topology: DiscoveredTopology,
    ) -> None:
        """Extract standalone azurerm_subnet resource and data blocks."""
        sections = [("resource", False), ("data", True)]
        for sec_name, is_data in sections:
            blocks = parsed.get(sec_name, [])
            if not isinstance(blocks, list):
                continue
            for item in blocks:
                if not isinstance(item, dict):
                    continue
                for raw_type, labels_dict in item.items():
                    type_name = _clean_string(raw_type)
                    if type_name != "azurerm_subnet" or not isinstance(labels_dict, dict):
                        continue
                    for raw_label, body in labels_dict.items():
                        label = _clean_string(raw_label)
                        if not isinstance(body, dict):
                            continue
                        name_attr = _clean_string(body.get("name"))
                        subnet_name = name_attr if name_attr else label
                        address_prefixes = _extract_address_prefixes(body)
                        vnet_name = _clean_string(body.get("virtual_network_name")) or None
                        rg_name = _clean_string(body.get("resource_group_name")) or None
                        pe_policies = _extract_bool(body.get("private_endpoint_network_policies_enabled"))
                        tags = _clean_tags(body.get("tags"))

                        is_pe = is_private_endpoint_subnet(
                            subnet_name,
                            network_policies_enabled=pe_policies,
                            tags=tags,
                            standards_patterns=self.standards_patterns,
                        )

                        s_cand = SubnetCandidate(
                            name=subnet_name,
                            address_prefixes=address_prefixes,
                            virtual_network_name=vnet_name,
                            resource_group_name=rg_name,
                            is_inline=False,
                            is_data_source=is_data,
                            is_private_endpoint_candidate=is_pe,
                            private_endpoint_network_policies_enabled=pe_policies,
                            tags=tags,
                            file_path=filename,
                            subscription=subscription,
                            metadata={"label": label, "raw_name": name_attr},
                        )
                        topology.subnets.append(s_cand)

    def _resolve_references(
        self,
        topology: DiscoveredTopology,
        rg_lookup: dict[Any, ResourceGroupCandidate],
        vnet_lookup: dict[Any, VirtualNetworkCandidate],
    ) -> None:
        """Resolve HCL string references (e.g. azurerm_resource_group.rg.name) to extracted resource names."""
        for subnet in topology.subnets:
            sub_key = subnet.subscription or ""
            if subnet.resource_group_name:
                resolved_rg = self._resolve_ref(subnet.resource_group_name, "azurerm_resource_group", rg_lookup, sub_key=sub_key)
                subnet.resource_group_name = resolved_rg
            if subnet.virtual_network_name:
                resolved_vnet = self._resolve_ref(subnet.virtual_network_name, "azurerm_virtual_network", vnet_lookup, sub_key=sub_key)
                subnet.virtual_network_name = resolved_vnet

        for vnet in topology.virtual_networks:
            sub_key = vnet.subscription or ""
            if vnet.resource_group_name:
                resolved_rg = self._resolve_ref(vnet.resource_group_name, "azurerm_resource_group", rg_lookup, sub_key=sub_key)
                vnet.resource_group_name = resolved_rg
            for inline_sub in vnet.subnets:
                inline_sub.resource_group_name = vnet.resource_group_name

    @staticmethod
    def _resolve_ref(ref_str: str, target_type: str, lookup: dict[Any, Any], sub_key: Optional[str] = None) -> str:
        """Resolve a single reference string to target entity name if present."""
        clean = ref_str.strip()
        # Pattern: [data.]azurerm_resource_group.<label>.name or ${...}
        m = re.match(
            rf'^\$?\{{?(?:data\.)?{re.escape(target_type)}\.([a-zA-Z0-9_-]+)\.name\}}?$',
            clean,
        )
        if m:
            label = m.group(1)
            if sub_key is not None and (sub_key, label) in lookup:
                return lookup[(sub_key, label)].name
            if label in lookup:
                return lookup[label].name
            return clean

        # If wrapped in ${...} without matching target type, strip outer ${}
        if clean.startswith("${") and clean.endswith("}"):
            inner = clean[2:-1].strip()
            # If inner is a simple identifier or reference
            if "${" not in inner:
                return inner
        return clean

    def parse_resources(
        self,
        content: str,
        filename: str = "<string>",
    ) -> tuple[list[ParsedResource], list[str]]:
        """Extract declared resource blocks and their attributes from HCL content.

        Args:
            content: Raw HCL code string.
            filename: Virtual or source filename.

        Returns:
            Tuple of (list of ParsedResource, list of parse warning strings).
        """
        resources: list[ParsedResource] = []
        warnings: list[str] = []

        if not content or not content.strip():
            return resources, warnings

        try:
            parsed = hcl2.loads(content)
        except Exception as exc:
            msg = f"{filename}: {exc}"
            logger.warning("Failed to parse HCL resources: %s", msg)
            warnings.append(msg)
            # Regex fallback to at least extract declared resource types and names
            for m in re.finditer(r'resource\s+"([^"]+)"\s+"([^"]+)"', content):
                resources.append(
                    ParsedResource(
                        resource_type=m.group(1),
                        resource_name=m.group(2),
                        file_path=filename,
                    )
                )
            return resources, warnings

        if not isinstance(parsed, dict) or "resource" not in parsed:
            return resources, warnings

        for res_entry in parsed.get("resource", []):
            if not isinstance(res_entry, dict):
                continue
            for raw_type, res_dict in res_entry.items():
                res_type = _clean_string(raw_type)
                if not isinstance(res_dict, dict):
                    continue
                for raw_name, body in res_dict.items():
                    res_name = _clean_string(raw_name)
                    if not isinstance(body, dict):
                        continue

                    attrs: dict[str, Any] = {}
                    nested_blocks: dict[str, Any] = {}
                    tags: dict[str, str] = {}

                    for k, v in body.items():
                        if k == "__is_block__":
                            continue
                        clean_k = _clean_string(k)
                        if clean_k == "tags":
                            tags = _clean_tags(v)
                        elif isinstance(v, list) and v and isinstance(v[0], dict) and v[0].get("__is_block__"):
                            nested_blocks[clean_k] = v
                        elif isinstance(v, dict) and v.get("__is_block__"):
                            nested_blocks[clean_k] = v
                        else:
                            if isinstance(v, str):
                                attrs[clean_k] = _strip_quotes(v)
                            else:
                                attrs[clean_k] = v

                    resources.append(
                        ParsedResource(
                            resource_type=res_type,
                            resource_name=res_name,
                            file_path=filename,
                            attributes=attrs,
                            tags=tags,
                            nested_blocks=nested_blocks,
                        )
                    )

        return resources, warnings

    def parse_resources_from_file(
        self,
        file_path: Union[Path, str],
    ) -> tuple[list[ParsedResource], list[str]]:
        """Read and extract declared resource blocks from an HCL file."""
        path = Path(file_path)
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            msg = f"{path}: {exc}"
            logger.warning("Failed to read HCL file: %s", msg)
            return [], [msg]

        return self.parse_resources(content, filename=str(path))


