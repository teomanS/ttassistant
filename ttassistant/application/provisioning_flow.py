"""Guided provisioning dialogue orchestrator application flow."""

import fnmatch
import ipaddress
from pathlib import Path
import re
from typing import Optional

from ttassistant.application.tweak_handler import TweakHandler
from ttassistant.domain.catalog import is_tier_1_paas, is_tier_1_resource
from ttassistant.domain.diff import compute_workspace_diff
from ttassistant.domain.exceptions import SecurityPolicyViolationError
from ttassistant.domain.models import ProvisioningParameters, StagedFile, StagedWorkspace
from ttassistant.domain.scaffold import ScaffoldEngine
from ttassistant.domain.standards import StandardsEngine
from ttassistant.domain.topology import DiscoveredTopology, SubnetCandidate
from ttassistant.ports.catalog import ResourceCatalogPort
from ttassistant.ports.filesystem import FileSystemPort
from ttassistant.ports.hcl_parser import HCLParserPort
from ttassistant.ports.terminal import TerminalUIPort

OTHER_SUBSCRIPTION_CHOICE = "Other (Enter custom...)"


class ProvisioningFlow:
    """Application flow orchestrating step-by-step guided provisioning parameter collection and scaffolding."""

    def __init__(
        self,
        terminal: TerminalUIPort,
        standards: StandardsEngine,
        scaffold_engine: Optional[ScaffoldEngine] = None,
        fs: Optional[FileSystemPort] = None,
        hcl_parser: Optional[HCLParserPort] = None,
        discovered_topology: Optional[DiscoveredTopology] = None,
        require_subnet: Optional[bool] = None,
        catalog: Optional[ResourceCatalogPort] = None,
        tweak_handler: Optional[TweakHandler] = None,
    ) -> None:
        """Initialize the provisioning flow with terminal UI, standards engine, scaffold engine, filesystem, and parser.

        Args:
            terminal: Terminal UI port implementation.
            standards: Standards engine domain service.
            scaffold_engine: Optional scaffolding engine domain service.
            fs: Optional filesystem port implementation for reading existing files and atomic commits.
            hcl_parser: Optional HCL parser port implementation for topology candidate extraction.
            discovered_topology: Optional pre-discovered or mocked DiscoveredTopology domain entity.
            require_subnet: Optional flag to force subnet dialogue even when 0 candidates discovered.
            catalog: Optional ResourceCatalogPort for querying the provider schema catalog.
            tweak_handler: Optional TweakHandler application service for in-session refinements.
        """
        self.terminal = terminal
        self.standards = standards
        self.catalog = catalog or (scaffold_engine.catalog if scaffold_engine else None)
        self.scaffold_engine = scaffold_engine or ScaffoldEngine(standards, catalog=self.catalog)
        if self.scaffold_engine.catalog is None and self.catalog is not None:
            self.scaffold_engine.catalog = self.catalog
        self.fs = fs
        self.hcl_parser = hcl_parser
        self.discovered_topology = discovered_topology
        self.require_subnet = require_subnet
        self.tweak_handler = tweak_handler

    def _get_subscription_choices(self) -> list[str]:
        """Get the list of available subscription choices including custom fallback."""
        backend_rules = self.standards.bundle.backend_rules
        unique_subs: list[str] = []
        seen: set[str] = set()

        for rule in backend_rules:
            sub = rule.subscription.strip()
            if not sub or sub == "default" or any(c in sub for c in ("*", "?", "[")):
                continue
            if sub not in seen:
                seen.add(sub)
                unique_subs.append(sub)

        return unique_subs + [OTHER_SUBSCRIPTION_CHOICE]

    def _validate_subscription(self, sub: str) -> bool | str:
        """Validate a subscription name."""
        val = sub.strip()
        if not val:
            return "Subscription name cannot be empty"
        if not re.fullmatch(r"^[a-zA-Z0-9_-]+$", val):
            return "Subscription name must contain only alphanumeric characters, hyphens, or underscores"
        try:
            self.standards.resolve_backend(val)
        except Exception as exc:
            return f"Backend resolution failed: {exc}"
        return True

    def _collect_subscription(self, pre_seeded: Optional[str] = None) -> str:
        """Collect and validate the target subscription."""
        if pre_seeded is not None:
            val = pre_seeded.strip()
            res = self._validate_subscription(val)
            if res is not True:
                raise ValueError(str(res))
            return val

        choices = self._get_subscription_choices()
        selection = self.terminal.prompt_select("Select Target Subscription:", choices=choices)

        if selection == OTHER_SUBSCRIPTION_CHOICE:
            custom_sub = self.terminal.prompt_text(
                "Enter custom subscription name:",
                validate=self._validate_subscription,
            )
            return custom_sub.strip()

        return selection

    def _determine_environment(self, subscription: str, pre_seeded: Optional[str] = None) -> str:
        """Determine environment from pre-seeded flag or inferred from subscription."""
        tag_rule = self.standards.bundle.get_tag_rule("Environment")
        allowed = [v.lower() for v in tag_rule.allowed_values] if (tag_rule and tag_rule.allowed_values) else []

        if pre_seeded is not None:
            env = pre_seeded.strip().lower()
            if not env:
                raise ValueError("Environment cannot be empty")
            if allowed and env not in allowed:
                allowed_str = ", ".join(tag_rule.allowed_values)
                raise ValueError(f"Invalid environment '{env}'. Allowed values: [{allowed_str}]")
            return env

        return self.standards.infer_environment(subscription)

    def _collect_resource_type(self, pre_seeded: Optional[str] = None) -> str:
        """Collect and validate target resource type."""
        available_types = list(self.standards.bundle.naming_rules.keys())
        if self.catalog is not None:
            for r in self.catalog.list_resources():
                if r not in available_types:
                    available_types.append(r)

        if pre_seeded is not None:
            rt = pre_seeded.strip().lower()
            if not rt:
                raise ValueError("Resource type cannot be empty")
            matching = next((t for t in available_types if t.lower() == rt), None)
            if not matching:
                types_str = ", ".join(available_types)
                raise ValueError(f"Unknown resource type '{rt}'. Available types: [{types_str}]")
            return matching

        if not available_types:
            raise ValueError("No resource types defined in corporate standards or catalog")

        return self.terminal.prompt_select("Select Target Resource Type:", choices=available_types)

    def _make_workload_validator(self, resource_type: str, environment: str):
        """Create inline validation function for workload name."""
        rule = self.standards.bundle.get_naming_rule(resource_type)

        def validate_workload(val: str) -> bool | str:
            val_clean = val.strip()
            if not val_clean:
                return "Workload name cannot be empty"

            if rule is not None:
                has_hyphen = False
                if rule.allowed_characters:
                    has_hyphen = "hyphen" in rule.allowed_characters.lower() or "dash" in rule.allowed_characters.lower()
                else:
                    has_hyphen = bool(re.search(r"\[[^\]]*-[^a-zA-Z0-9\]]|\[[^\]]*[a-zA-Z0-9]-\]|\\-", rule.pattern))

                workload_pattern = r"^[a-z0-9-]+$" if has_hyphen else r"^[a-z0-9]+$"

                if not re.fullmatch(workload_pattern, val_clean):
                    return f"Invalid name: must match {workload_pattern}"

                candidate_name = self.standards.compute_resource_name(resource_type, val_clean, environment)
                if len(val_clean) > rule.max_length or len(candidate_name) > rule.max_length:
                    return f"Name exceeds maximum length of {rule.max_length} characters"

                is_valid, err = rule.validate_name(candidate_name)
                if not is_valid:
                    return err or "Invalid resource name"
            else:
                if not re.fullmatch(r"^[a-z0-9-]+$", val_clean):
                    return "Invalid name: must match ^[a-z0-9-]+$"

            return True

        return validate_workload

    def _collect_workload_name(
        self, resource_type: str, environment: str, pre_seeded: Optional[str] = None
    ) -> str:
        """Collect and validate workload name."""
        validator = self._make_workload_validator(resource_type, environment)

        if pre_seeded is not None:
            wl = pre_seeded.strip()
            res = validator(wl)
            if res is not True:
                raise ValueError(str(res))
            return wl

        val = self.terminal.prompt_text("Enter Workload Name:", validate=validator)
        return val.strip()

    def _discover_topology(self) -> DiscoveredTopology:
        """Discover monorepo topology if parser and filesystem are available."""
        if self.discovered_topology is not None:
            return self.discovered_topology
        if self.hcl_parser is not None and self.fs is not None:
            base_dir = getattr(self.fs, "base_dir", None) or "."
            index = self.fs.build_topology_index(base_dir)
            if index.candidates:
                return self.hcl_parser.parse_topology_candidates(index.candidates)
        return DiscoveredTopology()

    def _format_subnet_candidate(self, s: SubnetCandidate, is_recommended: bool) -> str:
        """Format candidate subnet for display in interactive selection menu."""
        cidr_str = f"[{', '.join(s.address_prefixes)}]" if s.address_prefixes else "[no CIDR]"
        if s.virtual_network_name and s.resource_group_name:
            parent_str = f"({s.virtual_network_name} / {s.resource_group_name})"
        elif s.virtual_network_name:
            parent_str = f"({s.virtual_network_name})"
        elif s.resource_group_name:
            parent_str = f"({s.resource_group_name})"
        else:
            parent_str = ""
        purpose = "Private Endpoint" if s.is_private_endpoint_candidate else "Workload"
        rec = " (Recommended)" if is_recommended else ""
        parts = [s.name, cidr_str]
        if parent_str:
            parts.append(parent_str)
        parts.append(f"- {purpose}{rec}")
        return " ".join(parts)

    def _is_subnet_recommended(self, s: SubnetCandidate, resource_type: str) -> bool:
        """Check if candidate subnet matches recommendations in networking policy or PE heuristics."""
        if s.is_private_endpoint_candidate:
            return True
        net_rule = self.standards.resolve_networking_policy(resource_type)
        if net_rule and net_rule.subnet_patterns:
            for pattern in net_rule.subnet_patterns:
                if pattern and fnmatch.fnmatch(s.name.lower(), pattern.lower()):
                    return True
        return False

    def _handle_subnet_selection(
        self,
        subscription: str,
        resource_type: str,
        environment: str,
        workload_name: str,
        pre_seeded_subnet: Optional[str] = None,
        workspace: Optional[StagedWorkspace] = None,
        auto_approve: bool = False,
    ) -> tuple[
        Optional[str],
        Optional[str],
        Optional[str],
        Optional[str],
        Optional[str],
        list[StagedFile],
    ]:
        """Guide collaborative subnet selection, recommendation ranking, or missing dependency scaffolding."""
        if resource_type == "azurerm_resource_group":
            return (None, None, None, None, None, [])

        # Determine if resource is Tier 2 (or non-Tier-1 long-tail resource)
        is_tier_2 = not is_tier_1_resource(resource_type)
        if not is_tier_2 and self.catalog is not None:
            is_tier_2 = self.catalog.is_tier_2(resource_type)

        # Skip conversational subnet discovery prompts for Tier 2 resources unless --subnet is pre-seeded
        if is_tier_2 and pre_seeded_subnet is None:
            return (None, None, None, None, None, [])

        topology = self._discover_topology()
        subnets = topology.get_subnets_for_subscription(subscription)

        naming_rule = self.standards.bundle.get_naming_rule("azurerm_subnet")

        def validate_subnet_name(val: str) -> bool | str:
            c = val.strip()
            if not c:
                return "Subnet name cannot be empty"
            if naming_rule:
                is_valid, err = naming_rule.validate_name(c)
                if not is_valid:
                    return err or "Invalid subnet name"
            return True

        # 1. Pre-seeded subnet flag (--subnet)
        if pre_seeded_subnet is not None:
            clean_pre = pre_seeded_subnet.strip()
            res = validate_subnet_name(clean_pre)
            if res is not True:
                raise ValueError(str(res))
            matching = [s for s in subnets if s.name == clean_pre]
            if subnets and not matching:
                self.terminal.print_warning(
                    f"Pre-seeded subnet '{clean_pre}' not found in discovered topology for subscription '{subscription}'."
                )
            sel_vnet = matching[0].virtual_network_name if matching else None
            sel_rg = matching[0].resource_group_name if matching else None
            return (clean_pre, "existing", None, sel_vnet, sel_rg, [])

        # 2. Automated / non-interactive run (--yes / auto_approve) without interactive TTY
        if auto_approve and not self.terminal.is_interactive():
            if subnets:
                recommended = [s for s in subnets if self._is_subnet_recommended(s, resource_type)]
                chosen = recommended[0] if recommended else subnets[0]
                return (
                    chosen.name,
                    "existing",
                    None,
                    chosen.virtual_network_name,
                    chosen.resource_group_name,
                    [],
                )
            return (None, "none", None, None, None, [])

        # Check if subnet dialogue should run:
        # Trigger when resource requires network binding and discovery is active or subnets exist
        discovery_active = (
            self.discovered_topology is not None
            or (self.hcl_parser is not None and self.fs is not None)
        )
        should_prompt = (
            discovery_active
            or self.require_subnet is True
            or len(subnets) > 0
            or len(topology.subnets) > 0
        )

        if not should_prompt:
            return (None, None, None, None, None, [])

        # 2. Case: Candidate subnets exist in this subscription
        if subnets:
            recommended_subnets: list[tuple[SubnetCandidate, str]] = []
            other_subnets: list[tuple[SubnetCandidate, str]] = []

            for s in subnets:
                is_rec = self._is_subnet_recommended(s, resource_type)
                text = self._format_subnet_candidate(s, is_rec)
                if is_rec:
                    recommended_subnets.append((s, text))
                else:
                    other_subnets.append((s, text))

            ordered = recommended_subnets + other_subnets
            formatted_choices = [text for _, text in ordered]
            choice_to_candidate = {text: s for s, text in ordered}
            choice_to_name = {text: s.name for s, text in ordered}

            default_choice = formatted_choices[0] if formatted_choices else None
            formatted_choices.append("Other (Enter custom subnet name...)")

            prompt_func = getattr(self.terminal, "prompt_select_subnet", self.terminal.prompt_select)
            selection = prompt_func("Select Target Subnet:", choices=formatted_choices, default=default_choice)

            if selection == "Other (Enter custom subnet name...)":
                custom_name = self.terminal.prompt_text(
                    "Enter custom subnet name:", validate=validate_subnet_name
                ).strip()
                matching_vnets = topology.get_virtual_networks_for_subscription(subscription)
                sel_vnet = matching_vnets[0].name if matching_vnets else None
                sel_rg = matching_vnets[0].resource_group_name if matching_vnets else None
                return (custom_name, "existing", None, sel_vnet, sel_rg, [])
            else:
                cand = choice_to_candidate.get(selection)
                s_name = cand.name if cand else choice_to_name.get(selection, selection.split()[0])
                sel_vnet = cand.virtual_network_name if cand else None
                sel_rg = cand.resource_group_name if cand else None
                return (s_name, "existing", None, sel_vnet, sel_rg, [])

        # 3. Case: No candidate subnets in target subscription (Scaffold vs Cross-Sub)
        self.terminal.print_warning(f"No candidate subnets discovered in subscription '{subscription}'.")
        action_choices = [
            "Scaffold missing subnet in this subscription",
            "Configure cross-subscription shared network lookup",
            "Skip network configuration",
        ]
        action = self.terminal.prompt_select(
            "Select networking action:",
            choices=action_choices,
            default=action_choices[0],
        )

        if action == "Skip network configuration":
            return (None, "none", None, None, None, [])

        if action == "Scaffold missing subnet in this subscription":
            default_name = f"snet-pe-{environment}"
            snet_name = self.terminal.prompt_text(
                "Enter Subnet Name:",
                default=default_name,
                validate=validate_subnet_name,
            ).strip()

            def validate_cidr(val: str) -> bool | str:
                c = val.strip()
                if not c:
                    return "CIDR prefix cannot be empty"
                try:
                    ipaddress.ip_network(c, strict=True)
                    return True
                except ValueError as exc:
                    return f"Invalid CIDR prefix '{c}': {exc}"

            cidr = self.terminal.prompt_text(
                "Enter Subnet CIDR Prefix:",
                default="10.0.1.0/24",
                validate=validate_cidr,
            ).strip()

            discovered_vnets = [
                v.name for v in topology.get_virtual_networks_for_subscription(subscription)
            ]
            default_vnet = discovered_vnets[0] if discovered_vnets else f"vnet-{subscription}"
            vnet_name = self.terminal.prompt_text(
                "Enter Target Virtual Network Name:",
                default=default_vnet,
            ).strip()
            if not vnet_name:
                vnet_name = default_vnet

            scaffolded_files = self.scaffold_engine.scaffold_subnet(
                subscription=subscription,
                subnet_name=snet_name,
                address_prefixes=[cidr],
                vnet_name=vnet_name,
                environment=environment,
                workspace=workspace,
            )

            return (snet_name, "scaffold", None, vnet_name, None, scaffolded_files)
        else:
            def validate_cross_sub(val: str) -> bool | str:
                s = val.strip()
                if s == subscription:
                    return "Source subscription cannot be the same as target subscription"
                return self._validate_subscription(s)

            source_sub = self.terminal.prompt_text(
                "Enter Source Subscription for Shared Network:",
                validate=validate_cross_sub,
            ).strip()

            shared_snet = self.terminal.prompt_text(
                "Enter Shared Subnet Name:",
                validate=validate_subnet_name,
            ).strip()

            return (
                shared_snet,
                "cross_subscription",
                source_sub,
                f"vnet-{source_sub}",
                f"rg-{source_sub}",
                [],
            )

    def _handle_public_network_access_gate(
        self,
        resource_type: str,
        requested: Optional[bool] = None,
        auto_approve: bool = False,
        confirm_override: bool = False,
        prompt_if_interactive: bool = False,
    ) -> bool:
        """Handle security confirmation gate for public network access on Tier 1 PaaS resources."""
        if not is_tier_1_paas(resource_type):
            return bool(requested)

        is_requested = False
        if requested is True:
            is_requested = True
        elif requested is None and prompt_if_interactive and self.terminal.is_interactive():
            is_requested = self.terminal.confirm(
                "Enable public network access for this PaaS resource?",
                default=False,
            )

        if not is_requested:
            return False

        # Public access explicitly requested on a Tier 1 PaaS resource:
        # Check headless / non-interactive safeguard
        is_interactive = self.terminal.is_interactive()
        if not is_interactive or auto_approve:
            if confirm_override:
                return True
            raise SecurityPolicyViolationError(
                f"Security policy violation: Public network access on Tier 1 PaaS resource '{resource_type}' is prohibited by corporate security policy (AD-7, FR-12).",
                details=(
                    "Automated/non-interactive execution cannot enable public network access without explicit confirmation override. "
                    "Specify --confirm-public-network-access to confirm public access."
                ),
            )

        # In interactive mode:
        if confirm_override:
            return True

        # Render high-visibility security warning banner
        warning_msg = f"Public Network Access requested for Tier 1 PaaS resource '{resource_type}'."
        warning_details = [
            "Violates Corporate Security Policy AD-7 & FR-12: PaaS services must deny public network access by default.",
            f"Exposing '{resource_type}' to the public internet risks unauthorized access and infrastructure exposure.",
            "PaaS resources must enforce private network access via Private Endpoints and Hub DNS.",
        ]
        self.terminal.display_security_warning(
            message=warning_msg,
            details=warning_details,
            title="CRITICAL SECURITY POLICY WARNING",
        )

        # Require explicit human confirmation ([y/N], default False)
        confirmed = self.terminal.confirm(
            "Enable public network access despite corporate security policy violation?",
            default=False,
        )

        if confirmed:
            self.terminal.print_warning(
                "Explicit override acknowledged: public network access will be enabled in main.tf."
            )
            return True
        else:
            self.terminal.print_info(
                "Security confirmation rejected: reverting to secure private-only configuration (public_network_access_enabled = false)."
            )
            return False

    def run(
        self,
        subscription: Optional[str] = None,
        resource_type: Optional[str] = None,
        workload_name: Optional[str] = None,
        environment: Optional[str] = None,
        subnet: Optional[str] = None,
        auto_approve: bool = False,
        public_network_access: Optional[bool] = None,
        confirm_public_network_access: bool = False,
        prompt_public_access: bool = False,
    ) -> tuple[ProvisioningParameters, StagedWorkspace]:
        """Execute the guided provisioning parameter collection and workspace scaffolding flow.

        Args:
            subscription: Optional pre-seeded subscription identifier.
            resource_type: Optional pre-seeded resource type.
            workload_name: Optional pre-seeded workload name.
            environment: Optional pre-seeded environment name.
            subnet: Optional pre-seeded target subnet name.
            auto_approve: If True, bypasses interactive confirmation gate ([Y] Commit).
            public_network_access: Optional flag indicating whether public network access is requested.
            confirm_public_network_access: If True, provides explicit confirmation override for automated runs.
            prompt_public_access: If True, prompts interactively for public access when not pre-seeded.

        Returns:
            Tuple of (ProvisioningParameters, StagedWorkspace).

        Raises:
            ValueError: If pre-seeded parameter values fail standards validation.
            SecurityPolicyViolationError: If unconfirmed public network access is attempted in headless mode.
            typer.Abort: If user aborts interactive prompts.
        """
        sub = self._collect_subscription(pre_seeded=subscription)
        env = self._determine_environment(sub, pre_seeded=environment)
        rt = self._collect_resource_type(pre_seeded=resource_type)
        wl = self._collect_workload_name(rt, env, pre_seeded=workload_name)

        resource_name = self.standards.compute_resource_name(rt, wl, env)
        tags = self.standards.apply_default_tags({"Environment": env})

        # Evaluate public network access security confirmation gate
        pna_enabled = self._handle_public_network_access_gate(
            resource_type=rt,
            requested=public_network_access,
            auto_approve=auto_approve,
            confirm_override=confirm_public_network_access,
            prompt_if_interactive=prompt_public_access,
        )

        params = ProvisioningParameters(
            subscription=sub,
            resource_type=rt,
            workload_name=wl,
            environment=env,
            resource_name=resource_name,
            tags=tags,
            public_network_access=pna_enabled,
        )

        scaffolded_files: list[StagedFile] = []
        if rt != "azurerm_resource_group":
            sel_subnet, net_action, cross_source, sel_vnet, sel_rg, scaffolded_files = (
                self._handle_subnet_selection(
                    subscription=sub,
                    resource_type=rt,
                    environment=env,
                    workload_name=wl,
                    pre_seeded_subnet=subnet,
                    auto_approve=auto_approve,
                )
            )
            if sel_subnet is not None:
                params.selected_subnet = sel_subnet
            if net_action is not None:
                params.network_action = net_action
            if cross_source is not None:
                params.cross_sub_source = cross_source
            if sel_vnet is not None:
                params.selected_vnet = sel_vnet
            if sel_rg is not None:
                params.selected_subnet_rg = sel_rg

        workspace = self.scaffold_engine.scaffold(params)
        for sf in scaffolded_files:
            workspace.add_file(sf)

        # Print collected parameters summary
        self.terminal.print()
        self.terminal.print_success("Provisioning parameters collected successfully.")
        self.terminal.print(f"  Subscription:  {params.subscription}")
        self.terminal.print(f"  Resource Type: {params.resource_type}")
        self.terminal.print(f"  Workload Name: {params.workload_name}")
        self.terminal.print(f"  Environment:   {params.environment}")
        self.terminal.print(f"  Resource Name: {params.resource_name}")
        if is_tier_1_paas(params.resource_type):
            pna_status = "Enabled (Public)" if params.public_network_access else "Disabled (Private-only, AD-7/FR-12)"
            self.terminal.print(f"  Public Access: {pna_status}")
            if params.selected_subnet and params.network_action != "none":
                self.terminal.print(f"  Private Endpoint: Enabled (pe-{params.resource_name})")
                dns_info = self.standards.resolve_hub_dns_zone(params.resource_type)
                if dns_info.get("name"):
                    self.terminal.print(f"  Hub DNS Zone:  {dns_info['name']}")
            else:
                self.terminal.print_warning("  Private Endpoint: Omitted (no subnet selected)")
        if params.selected_subnet:
            self.terminal.print(f"  Subnet:        {params.selected_subnet}")
        if params.network_action:
            self.terminal.print(f"  Network Action: {params.network_action}")
        if params.cross_sub_source:
            self.terminal.print(f"  Shared Source: {params.cross_sub_source}")
        if params.tags:
            tags_str = ", ".join(f"{k}={v}" for k, v in sorted(params.tags.items()))
            self.terminal.print(f"  Tags:          {tags_str}")

        # Collect all affected target directories
        target_dir = workspace.target_dir.rstrip("/").replace("\\", "/")
        affected_dirs: set[str] = set()
        if target_dir:
            affected_dirs.add(target_dir)
        for sf in workspace.files.values():
            norm_path = sf.path.replace("\\", "/")
            if norm_path.startswith(target_dir):
                affected_dirs.add(target_dir)
            elif "/" in norm_path:
                affected_dirs.add(str(Path(norm_path).parent).replace("\\", "/"))
            elif target_dir:
                affected_dirs.add(target_dir)
        target_folders_list = sorted(affected_dirs)
        target_folders_str = ", ".join(target_folders_list)

        # Print staged workspace summary
        self.terminal.print()
        if len(target_folders_list) > 1:
            self.terminal.print_success(f"Staged workspace generated in memory: {target_folders_str}")
            self.terminal.print(f"  Target Folders: {target_folders_str}")
        else:
            self.terminal.print_success(f"Staged workspace generated in memory: {workspace.target_dir}")
            self.terminal.print(f"  Target Folder: {workspace.target_dir}")
        self.terminal.print(f"  Files Generated ({workspace.file_count}):")
        for key, staged_file in sorted(workspace.files.items()):
            display_path = (
                staged_file.path
                if ("/" in staged_file.path or "\\" in staged_file.path)
                else staged_file.filename
            )
            self.terminal.print(f"    - {display_path} ({staged_file.line_count} lines)")
        self.terminal.print(f"  Total Lines:   {workspace.total_lines}")

        # Dynamic unified diff preview and interactive tweak confirmation loop (AD-4, AD-5)
        existing_files = (
            self.fs.read_workspace_existing_files(workspace) if self.fs is not None else {}
        )

        if auto_approve:
            workspace_diff = compute_workspace_diff(workspace, existing_files)
            if workspace_diff.diff_text:
                self.terminal.print()
                self.terminal.display_diff(workspace_diff.diff_text)
            else:
                self.terminal.print()
                self.terminal.print_info("Files on disk are already identical. No changes to apply.")
            confirmed = True
        else:
            confirmed = False
            loop_iteration = 0
            while True:
                # Clear terminal screen on subsequent iterations if supported
                if loop_iteration > 0 and hasattr(self.terminal, "clear_screen"):
                    self.terminal.clear_screen()
                loop_iteration += 1

                # Re-compute & display unified diff preview
                workspace_diff = compute_workspace_diff(workspace, existing_files)
                if workspace_diff.diff_text:
                    self.terminal.print()
                    self.terminal.display_diff(workspace_diff.diff_text)
                else:
                    self.terminal.print()
                    self.terminal.print_info("Files on disk are already identical. No changes to apply.")

                # Interactive confirmation gate
                choice: Any = None
                if hasattr(self.terminal, "prompt_confirmation_gate"):
                    try:
                        choice = self.terminal.prompt_confirmation_gate("Commit changes to disk?")
                    except (AttributeError, NotImplementedError):
                        choice = None

                # Fallback to confirm() if prompt_confirmation_gate returned mock/unrecognized or isn't a string choice
                if not isinstance(choice, str) or choice.lower() not in ("commit", "cancel", "tweak"):
                    conf_val = self.terminal.confirm("Commit changes to disk?", default=False)
                    choice = "commit" if conf_val else "cancel"

                choice_normalized = choice.strip().lower()

                if choice_normalized == "commit":
                    confirmed = True
                    break
                elif choice_normalized == "cancel":
                    confirmed = False
                    break
                elif choice_normalized == "tweak":
                    if self.tweak_handler is None:
                        self.terminal.print_error("Tweak engine is not configured in this session.")
                        continue

                    tweak_instruction = self.terminal.prompt_text(
                        "Enter refinement instruction (e.g. 'Change replication to GRS'):"
                    )
                    if not tweak_instruction or not tweak_instruction.strip():
                        self.terminal.print_info("No refinement instruction entered.")
                        continue

                    res = self.tweak_handler.apply_tweak(workspace, tweak_instruction.strip())
                    if res.success:
                        self.terminal.print()
                        self.terminal.print_success(
                            f"Applied refinement: {res.diff_summary} ({res.elapsed_ms:.2f}ms)"
                        )
                        # Security policy AD-7 check if tweak enabled public network access on a Tier 1 PaaS
                        rt = workspace.parameters.resource_type if workspace.parameters else None
                        if (
                            rt
                            and is_tier_1_paas(rt)
                            and workspace.parameters
                            and workspace.parameters.public_network_access
                            and res.parsed_tweak
                            and res.parsed_tweak.attribute_name == "public_network_access_enabled"
                            and res.parsed_tweak.value is True
                        ):
                            allowed = self._handle_public_network_access_gate(
                                resource_type=rt,
                                requested=True,
                                auto_approve=False,
                                confirm_override=False,
                                prompt_if_interactive=True,
                            )
                            if not allowed:
                                self.tweak_handler.apply_tweak(workspace, "Disable public network access")
                    else:
                        self.terminal.print()
                        self.terminal.print_error(f"Refinement failed: {res.error_message}")

        folder_desc = target_folders_str if len(target_folders_list) > 1 else workspace.target_dir
        if confirmed:
            self.terminal.print()
            if self.fs is not None:
                committed_paths = self.fs.commit_workspace(workspace)
                self.terminal.print_success(
                    f"Committed {len(committed_paths)} files atomically to disk: {folder_desc}"
                )
            else:
                self.terminal.print_info(
                    f"Staged {workspace.file_count} files in memory (dry run): {folder_desc}"
                )
            workspace.metadata["committed"] = True
        else:
            self.terminal.print()
            self.terminal.print("Scaffolding cancelled. No files written to disk.")
            workspace.metadata["committed"] = False

        return params, workspace

