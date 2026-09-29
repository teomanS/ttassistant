"""Unit tests for StandardsEngine pure domain service."""

import pytest

from ttassistant.domain.exceptions import StandardsError
from ttassistant.domain.models import (
    BackendMappingRule,
    NamingRule,
    NetworkingPolicyRule,
    StandardsBundle,
    TagRule,
)
from ttassistant.domain.standards import StandardsEngine


@pytest.fixture
def sample_bundle():
    naming = {
        "azurerm_resource_group": NamingRule(
            resource_type="azurerm_resource_group",
            pattern="^rg-[a-z0-9-]+$",
            allowed_characters="Lowercase alphanumeric, hyphen",
            max_length=90,
            min_length=4,
        ),
        "azurerm_storage_account": NamingRule(
            resource_type="azurerm_storage_account",
            pattern="^st[a-z0-9]{3,22}$",
            allowed_characters="Lowercase alphanumeric",
            max_length=24,
            min_length=3,
        ),
    }

    tags = {
        "Environment": TagRule(
            key="Environment",
            required=True,
            allowed_values=["dev", "test", "stage", "prod"],
            default_value="dev",
        ),
        "Owner": TagRule(
            key="Owner",
            required=True,
            default_value="platform-team@corp.internal",
        ),
        "CostCenter": TagRule(
            key="CostCenter",
            required=False,
            default_value="CC-DEFAULT",
        ),
    }

    backends = [
        BackendMappingRule(
            subscription="workload-dev",
            storage_account_name="sttfstatedev",
            container_name="tfstate",
            key_pattern="dev/{resource_type}.tfstate",
            resource_group_name="rg-tfstate-dev",
        ),
        BackendMappingRule(
            subscription="*",
            storage_account_name="sttfstatedefault",
            container_name="tfstate",
            key_pattern="{subscription}/{resource_type}.tfstate",
            resource_group_name="rg-tfstate-default",
        ),
    ]

    networking = {
        "azurerm_storage_account": NetworkingPolicyRule(
            resource_type="azurerm_storage_account",
            private_dns_zone_name="privatelink.blob.core.windows.net",
            subnet_patterns=["*snet-paas*", "*private*"],
            allow_public_access=False,
        ),
        "default": NetworkingPolicyRule(
            resource_type="default",
            subnet_patterns=["*snet-default*"],
            allow_public_access=False,
        ),
    }

    return StandardsBundle(
        naming_rules=naming,
        tag_rules=tags,
        backend_rules=backends,
        networking_rules=networking,
    )


@pytest.fixture
def engine(sample_bundle):
    return StandardsEngine(sample_bundle)


class TestStandardsEngineNaming:
    """Test naming validation logic in StandardsEngine."""

    def test_valid_resource_name(self, engine):
        is_valid, err = engine.validate_resource_name("azurerm_resource_group", "rg-workload-dev")
        assert is_valid is True
        assert err is None

    def test_invalid_resource_name_pattern(self, engine):
        is_valid, err = engine.validate_resource_name("azurerm_resource_group", "RG_INVALID_NAME")
        assert is_valid is False
        assert "does not match naming pattern" in err

    def test_resource_name_length_exceeded(self, engine):
        long_name = "st" + "a" * 25
        is_valid, err = engine.validate_resource_name("azurerm_storage_account", long_name)
        assert is_valid is False
        assert "exceeds maximum length of 24" in err

    def test_unregistered_resource_type_accepted(self, engine):
        # When no naming rule exists, defaults to accepted
        is_valid, err = engine.validate_resource_name("azurerm_untracked_resource", "any-name")
        assert is_valid is True
        assert err is None


class TestStandardsEngineTags:
    """Test tagging validation and defaults in StandardsEngine."""

    def test_validate_tags_all_mandatory_present_and_valid(self, engine):
        tags = {
            "Environment": "dev",
            "Owner": "devops@corp.internal",
        }
        is_valid, errors = engine.validate_tags(tags)
        assert is_valid is True
        assert errors == []

    def test_validate_tags_missing_mandatory(self, engine):
        tags = {
            "Environment": "dev",
            # Missing Owner
        }
        is_valid, errors = engine.validate_tags(tags)
        assert is_valid is False
        assert any("Missing mandatory tag: 'Owner'" in e for e in errors)

    def test_validate_tags_allowed_values_violation(self, engine):
        tags = {
            "Environment": "qa-sandbox",
            "Owner": "team@corp.internal",
        }
        is_valid, errors = engine.validate_tags(tags)
        assert is_valid is False
        assert any("value 'qa-sandbox' is not allowed" in e for e in errors)

    def test_apply_default_tags(self, engine):
        defaults = engine.apply_default_tags()
        assert defaults["Environment"] == "dev"
        assert defaults["Owner"] == "platform-team@corp.internal"
        assert defaults["CostCenter"] == "CC-DEFAULT"

    def test_apply_default_tags_with_existing_overrides(self, engine):
        existing = {
            "Environment": "prod",
            "CostCenter": "CC-PROJECT-A",
            "CustomTag": "CustomVal",
        }
        merged = engine.apply_default_tags(existing)
        assert merged["Environment"] == "prod"
        assert merged["Owner"] == "platform-team@corp.internal"
        assert merged["CostCenter"] == "CC-PROJECT-A"
        assert merged["CustomTag"] == "CustomVal"

    def test_validate_tags_optional_tag_empty_allowed_with_allowed_values(self):
        bundle = StandardsBundle(
            tag_rules={
                "ManagedBy": TagRule(
                    key="ManagedBy",
                    required=False,
                    allowed_values=["terraform", "manual"],
                ),
            }
        )
        eng = StandardsEngine(bundle)
        # Empty string should be permitted for optional tag
        is_valid, errors = eng.validate_tags({"ManagedBy": ""})
        assert is_valid is True
        assert errors == []

    def test_apply_default_tags_case_insensitive_override_no_duplicates(self, engine):
        # User provides lowercase "environment" overriding default "Environment"
        existing = {"environment": "staging"}
        merged = engine.apply_default_tags(existing)
        assert "environment" in merged
        assert "Environment" not in merged
        assert merged["environment"] == "staging"


class TestStandardsEngineBackend:
    """Test remote state backend resolution in StandardsEngine."""

    def test_resolve_backend_exact_subscription(self, engine):
        backend = engine.resolve_backend(
            subscription="workload-dev",
            resource_type="azurerm_storage_account",
        )
        assert backend["storage_account_name"] == "sttfstatedev"
        assert backend["container_name"] == "tfstate"
        assert backend["key"] == "dev/azurerm_storage_account.tfstate"
        assert backend["resource_group_name"] == "rg-tfstate-dev"

    def test_resolve_backend_wildcard_fallback(self, engine):
        backend = engine.resolve_backend(
            subscription="custom-subscription",
            resource_type="azurerm_key_vault",
        )
        assert backend["storage_account_name"] == "sttfstatedefault"
        assert backend["key"] == "custom-subscription/azurerm_key_vault.tfstate"

    def test_resolve_backend_missing_rule_raises_standards_error(self):
        bundle = StandardsBundle()  # No backend rules
        empty_engine = StandardsEngine(bundle)
        with pytest.raises(StandardsError) as exc_info:
            empty_engine.resolve_backend("any-sub", "azurerm_storage_account")
        assert "No remote state backend mapping found" in exc_info.value.message


class TestStandardsEngineNetworking:
    """Test networking policy resolution in StandardsEngine."""

    def test_resolve_networking_policy_exact(self, engine):
        policy = engine.resolve_networking_policy("azurerm_storage_account")
        assert policy is not None
        assert policy.private_dns_zone_name == "privatelink.blob.core.windows.net"
        assert policy.allow_public_access is False

    def test_resolve_networking_policy_default_fallback(self, engine):
        policy = engine.resolve_networking_policy("azurerm_other_service")
        assert policy is not None
        assert policy.subnet_patterns == ["*snet-default*"]

    def test_resolve_networking_policy_custom_zone_id_without_explicit_name(self):
        bundle = StandardsBundle(
            networking_rules={
                "azurerm_storage_account": NetworkingPolicyRule(
                    resource_type="azurerm_storage_account",
                    private_dns_zone_id="/subscriptions/sub-1/resourcegroups/rg-custom-hub/providers/Microsoft.Network/privateDnsZones/privatelink.custom-blob.net/",
                ),
            }
        )
        custom_engine = StandardsEngine(bundle)
        policy = custom_engine.resolve_networking_policy("azurerm_storage_account")
        assert policy is not None
        # Must extract custom zone from zone ID instead of falling back to default
        assert policy.private_dns_zone_name == "privatelink.custom-blob.net"
        assert policy.hub_resource_group == "rg-custom-hub"

    def test_resolve_hub_dns_zone_casing_and_trailing_slash(self):
        bundle = StandardsBundle(
            networking_rules={
                "azurerm_key_vault": NetworkingPolicyRule(
                    resource_type="azurerm_key_vault",
                    private_dns_zone_id="/SUBSCRIPTIONS/sub-core/RESOURCEGROUPS/my-custom-sec-rg",
                    private_dns_zone_name="privatelink.custom-vault.azure.net",
                ),
            }
        )
        custom_engine = StandardsEngine(bundle)
        dns_info = custom_engine.resolve_hub_dns_zone("azurerm_key_vault")
        assert dns_info["name"] == "privatelink.custom-vault.azure.net"
        assert dns_info["resource_group_name"] == "my-custom-sec-rg"

    def test_resolve_hub_dns_zone_default_rule_rg_fallback(self):
        bundle = StandardsBundle(
            networking_rules={
                "default": NetworkingPolicyRule(
                    resource_type="default",
                    private_dns_zone_id="/subscriptions/sub-hub/resourceGroups/rg-hub-from-default/providers/Microsoft.Network/privateDnsZones/privatelink.default.net",
                ),
            }
        )
        custom_engine = StandardsEngine(bundle)
        # azurerm_mssql_server will fall back to default rule and use its hub resource group
        dns_info = custom_engine.resolve_hub_dns_zone("azurerm_mssql_server")
        assert dns_info["resource_group_name"] == "rg-hub-from-default"
        assert dns_info["name"] == "privatelink.database.windows.net"


class TestStandardsEngineResourceNameAndEnvironment:
    """Test compute_resource_name and infer_environment domain methods."""

    def test_compute_resource_name_storage_account(self, engine):
        name = engine.compute_resource_name("azurerm_storage_account", "appdata", "prod")
        assert name == "stappdataprod"

    def test_compute_resource_name_resource_group(self, engine):
        name = engine.compute_resource_name("azurerm_resource_group", "appdata", "prod")
        assert name == "rg-appdata-prod"

    def test_compute_resource_name_workload_ends_with_env_name(self, engine):
        # Workload 'contest' in 'test' environment must append 'test' -> 'stcontesttest'
        name_sa = engine.compute_resource_name("azurerm_storage_account", "contest", "test")
        assert name_sa == "stcontesttest"

        name_rg = engine.compute_resource_name("azurerm_resource_group", "contest", "test")
        assert name_rg == "rg-contest-test"

    def test_compute_resource_name_explicit_env_separator(self, engine):
        name_sa = engine.compute_resource_name("azurerm_storage_account", "appdata-prod", "prod")
        assert name_sa == "stappdataprod"

        name_rg = engine.compute_resource_name("azurerm_resource_group", "appdata-prod", "prod")
        assert name_rg == "rg-appdata-prod"

    def test_compute_resource_name_without_environment(self, engine):
        name_sa = engine.compute_resource_name("azurerm_storage_account", "appdata", "")
        assert name_sa == "stappdata"

        name_rg = engine.compute_resource_name("azurerm_resource_group", "appdata", "")
        assert name_rg == "rg-appdata"

    def test_compute_resource_name_unknown_resource_type(self, engine):
        name = engine.compute_resource_name("unknown_resource", "myworkload", "prod")
        assert name == "myworkload-prod"

    def test_infer_environment_matching_tokens(self, engine):
        assert engine.infer_environment("sub-prod") == "prod"
        assert engine.infer_environment("workload-dev") == "dev"
        assert engine.infer_environment("my.stage.sub") == "stage"

    def test_infer_environment_fallback(self, engine):
        # Subscriptions without known environment token fall back to default ("dev")
        assert engine.infer_environment("core-networking") == "dev"
        assert engine.infer_environment("custom-subscription") == "dev"

    def test_infer_environment_empty_bundle_fallback(self):
        empty_engine = StandardsEngine(StandardsBundle())
        assert empty_engine.infer_environment("custom-sub") == "dev"

