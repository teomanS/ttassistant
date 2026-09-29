import pytest
from pydantic import ValidationError

from ttassistant.domain.exceptions import StandardsError
from ttassistant.domain.models import (
    BackendMappingRule,
    NamingRule,
    NetworkingPolicyRule,
    ProvisioningParameters,
    StandardsBundle,
    TagRule,
)


class TestNamingRule:
    """Test suite for NamingRule model and validation."""

    def test_valid_naming_rule(self):
        rule = NamingRule(
            resource_type="azurerm_storage_account",
            pattern="^st[a-z0-9]{3,22}$",
            allowed_characters="Lowercase alphanumeric",
            max_length=24,
            min_length=3,
        )
        assert rule.resource_type == "azurerm_storage_account"
        assert rule.pattern == "^st[a-z0-9]{3,22}$"
        assert rule.max_length == 24
        assert rule.min_length == 3

    def test_invalid_regex_pattern_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc_info:
            NamingRule(
                resource_type="azurerm_resource_group",
                pattern="^rg-[a-z0-9-(broken$",
                allowed_characters="Alphanumeric",
                max_length=90,
            )
        assert "Invalid regular expression" in str(exc_info.value)

    def test_empty_regex_pattern_raises_validation_error(self):
        with pytest.raises(ValidationError):
            NamingRule(
                resource_type="azurerm_resource_group",
                pattern="   ",
                max_length=90,
            )

    def test_negative_or_zero_max_length_raises_validation_error(self):
        with pytest.raises(ValidationError):
            NamingRule(
                resource_type="azurerm_resource_group",
                pattern="^rg-[a-z]+$",
                max_length=0,
            )
        with pytest.raises(ValidationError):
            NamingRule(
                resource_type="azurerm_resource_group",
                pattern="^rg-[a-z]+$",
                max_length=-5,
            )

    def test_min_length_greater_than_max_length_raises(self):
        with pytest.raises(ValidationError):
            NamingRule(
                resource_type="azurerm_resource_group",
                pattern="^rg-[a-z]+$",
                max_length=10,
                min_length=15,
            )

    def test_validate_name_success(self):
        rule = NamingRule(
            resource_type="azurerm_resource_group",
            pattern="^rg-[a-z0-9-]+$",
            allowed_characters="Lowercase alphanumeric, hyphen",
            max_length=90,
            min_length=4,
        )
        is_valid, err = rule.validate_name("rg-workload-dev")
        assert is_valid is True
        assert err is None

    def test_validate_name_exceeds_max_length(self):
        rule = NamingRule(
            resource_type="azurerm_storage_account",
            pattern="^st[a-z0-9]+$",
            max_length=10,
        )
        is_valid, err = rule.validate_name("stworkloadextremelylongaccountname")
        assert is_valid is False
        assert "exceeds maximum length of 10" in err

    def test_validate_name_below_min_length(self):
        rule = NamingRule(
            resource_type="azurerm_storage_account",
            pattern="^st[a-z0-9]+$",
            max_length=24,
            min_length=5,
        )
        is_valid, err = rule.validate_name("st1")
        assert is_valid is False
        assert "is shorter than minimum length of 5" in err

    def test_validate_name_pattern_mismatch(self):
        rule = NamingRule(
            resource_type="azurerm_storage_account",
            pattern="^st[a-z0-9]{3,22}$",
            allowed_characters="Lowercase alphanumeric",
            max_length=24,
        )
        is_valid, err = rule.validate_name("st_UPPERCASE_invalid!")
        assert is_valid is False
        assert "does not match naming pattern" in err
        assert "Allowed: Lowercase alphanumeric" in err

    def test_validate_name_rejects_partial_substring_match(self):
        rule = NamingRule(
            resource_type="azurerm_storage_account",
            pattern="st[a-z0-9]+",
            max_length=24,
        )
        is_valid, err = rule.validate_name("prefix-st123-suffix")
        assert is_valid is False
        assert "does not match naming pattern" in err


class TestTagRule:
    """Test suite for TagRule model and validation."""

    def test_valid_tag_rule(self):
        rule = TagRule(
            key="Environment",
            required=True,
            allowed_values=["dev", "test", "stage", "prod"],
            default_value="dev",
            description="Deployment target",
        )
        assert rule.key == "Environment"
        assert rule.required is True
        assert rule.allowed_values == ["dev", "test", "stage", "prod"]
        assert rule.default_value == "dev"

    def test_validate_tag_missing_mandatory(self):
        rule = TagRule(key="Environment", required=True)
        is_valid, err = rule.validate_tag(None)
        assert is_valid is False
        assert "Missing mandatory tag: 'Environment'" in err

        is_valid, err = rule.validate_tag("   ")
        assert is_valid is False
        assert "Missing mandatory tag: 'Environment'" in err

    def test_validate_tag_optional_empty_allowed(self):
        rule = TagRule(key="ManagedBy", required=False)
        is_valid, err = rule.validate_tag(None)
        assert is_valid is True
        assert err is None

    def test_validate_tag_allowed_values_violation(self):
        rule = TagRule(
            key="Environment",
            required=True,
            allowed_values=["dev", "test", "prod"],
        )
        is_valid, err = rule.validate_tag("sandbox")
        assert is_valid is False
        assert "is not allowed" in err
        assert "dev, test, prod" in err

    def test_validate_tag_allowed_values_success(self):
        rule = TagRule(
            key="Environment",
            required=True,
            allowed_values=["dev", "test", "prod"],
        )
        is_valid, err = rule.validate_tag("dev")
        assert is_valid is True
        assert err is None


class TestBackendMappingRule:
    """Test suite for BackendMappingRule model and key resolution."""

    def test_resolve_key_default_pattern(self):
        rule = BackendMappingRule(
            subscription="workload-dev",
            storage_account_name="sttfstatedev",
            container_name="tfstate",
            key_pattern="{subscription}/{resource_type}.tfstate",
            resource_group_name="rg-tfstate-dev",
        )
        key = rule.resolve_key(resource_type="storage_account")
        assert key == "workload-dev/storage_account.tfstate"

    def test_resolve_key_override_subscription(self):
        rule = BackendMappingRule(
            subscription="*",
            storage_account_name="sttfstatedefault",
            container_name="tfstate",
            key_pattern="{subscription}/terraform.tfstate",
        )
        key = rule.resolve_key(resource_type="vnet", subscription="core-shared")
        assert key == "core-shared/terraform.tfstate"

    def test_resolve_key_invalid_braces_raises_standards_error(self):
        rule = BackendMappingRule(
            subscription="sub",
            storage_account_name="st",
            key_pattern="{invalid_brace",
        )
        with pytest.raises(StandardsError) as exc_info:
            rule.resolve_key(resource_type="rg")
        assert "Invalid key_pattern template" in exc_info.value.message


class TestNetworkingPolicyRule:
    """Test suite for NetworkingPolicyRule."""

    def test_default_allow_public_access_is_false(self):
        rule = NetworkingPolicyRule(
            resource_type="azurerm_storage_account",
            private_dns_zone_name="privatelink.blob.core.windows.net",
            subnet_patterns=["*snet-paas*", "*private*"],
        )
        assert rule.allow_public_access is False
        assert rule.subnet_patterns == ["*snet-paas*", "*private*"]

    def test_hub_resource_group_and_subscription_extraction(self):
        # Standard format
        rule1 = NetworkingPolicyRule(
            resource_type="azurerm_storage_account",
            private_dns_zone_id="/subscriptions/sub-123-abc/resourceGroups/rg-hub-dns/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net",
        )
        assert rule1.hub_resource_group == "rg-hub-dns"
        assert rule1.hub_subscription_id == "sub-123-abc"

        # Case variations and trailing slash variations
        rule2 = NetworkingPolicyRule(
            resource_type="azurerm_key_vault",
            private_dns_zone_id="/SUBSCRIPTIONS/my-sub-id/RESOURCEGROUPS/my-custom-hub-rg",
        )
        assert rule2.hub_resource_group == "my-custom-hub-rg"
        assert rule2.hub_subscription_id == "my-sub-id"

        rule3 = NetworkingPolicyRule(
            resource_type="azurerm_key_vault",
            private_dns_zone_id="/subscriptions/sub-456/resourcegroups/rg-custom-hub/",
        )
        assert rule3.hub_resource_group == "rg-custom-hub"
        assert rule3.hub_subscription_id == "sub-456"

        # None if not present
        rule4 = NetworkingPolicyRule(resource_type="default")
        assert rule4.hub_resource_group is None
        assert rule4.hub_subscription_id is None


class TestStandardsBundle:
    """Test suite for StandardsBundle indexing and lookups."""

    def test_bundle_lookups(self):
        naming = {
            "azurerm_resource_group": NamingRule(
                resource_type="azurerm_resource_group",
                pattern="^rg-[a-z]+$",
                max_length=90,
            )
        }
        tags = {
            "Environment": TagRule(key="Environment", required=True),
        }
        backends = [
            BackendMappingRule(
                subscription="workload-dev",
                storage_account_name="stdev",
            ),
            BackendMappingRule(
                subscription="workload-*",
                storage_account_name="stworkloadglob",
            ),
            BackendMappingRule(
                subscription="*",
                storage_account_name="stfallback",
            ),
        ]
        networking = {
            "azurerm_storage_account": NetworkingPolicyRule(
                resource_type="azurerm_storage_account",
                private_dns_zone_name="privatelink.blob.core.windows.net",
            ),
            "default": NetworkingPolicyRule(
                resource_type="default",
                subnet_patterns=["*snet*"],
            ),
        }

        bundle = StandardsBundle(
            naming_rules=naming,
            tag_rules=tags,
            backend_rules=backends,
            networking_rules=networking,
        )

        # Naming rule lookup
        assert bundle.get_naming_rule("azurerm_resource_group") is not None
        assert bundle.get_naming_rule("unknown") is None

        # Tag rule lookup (case insensitive)
        assert bundle.get_tag_rule("Environment") is not None
        assert bundle.get_tag_rule("environment") is not None
        assert bundle.get_tag_rule("Unknown") is None

        # Backend rule lookup with exact, glob, and wildcard fallback
        assert bundle.get_backend_rule("workload-dev").storage_account_name == "stdev"
        assert bundle.get_backend_rule("workload-staging").storage_account_name == "stworkloadglob"
        assert bundle.get_backend_rule("random-sub").storage_account_name == "stfallback"

        # Networking rule lookup with default fallback
        assert (
            bundle.get_networking_rule("azurerm_storage_account").private_dns_zone_name
            == "privatelink.blob.core.windows.net"
        )
        assert bundle.get_networking_rule("unknown_res").subnet_patterns == ["*snet*"]

    def test_backend_rule_default_does_not_intercept_globs(self):
        """Verify 'default' backend rule placed before globs does not intercept glob matching."""
        backends = [
            BackendMappingRule(
                subscription="default",
                storage_account_name="stdefault",
            ),
            BackendMappingRule(
                subscription="workload-*",
                storage_account_name="stworkloadglob",
            ),
        ]
        bundle = StandardsBundle(backend_rules=backends)
        assert bundle.get_backend_rule("workload-test").storage_account_name == "stworkloadglob"
        assert bundle.get_backend_rule("other-sub").storage_account_name == "stdefault"



class TestProvisioningParameters:
    """Test suite for ProvisioningParameters model and field validation."""

    def test_valid_provisioning_parameters(self):
        params = ProvisioningParameters(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="appdata",
            environment="prod",
            resource_name="stappdataprod",
            tags={"Environment": "prod"},
        )
        assert params.subscription == "sub-prod"
        assert params.resource_type == "azurerm_storage_account"
        assert params.workload_name == "appdata"
        assert params.environment == "prod"
        assert params.resource_name == "stappdataprod"
        assert params.tags == {"Environment": "prod"}

    @pytest.mark.parametrize(
        "field_name",
        ["subscription", "resource_type", "workload_name", "environment", "resource_name"],
    )
    def test_empty_string_field_raises_validation_error(self, field_name):
        valid_kwargs = {
            "subscription": "sub-prod",
            "resource_type": "azurerm_storage_account",
            "workload_name": "appdata",
            "environment": "prod",
            "resource_name": "stappdataprod",
            "tags": {},
        }
        # Test empty string
        kwargs = dict(valid_kwargs, **{field_name: ""})
        with pytest.raises(ValidationError) as exc_info:
            ProvisioningParameters(**kwargs)
        assert f"{field_name} cannot be empty" in str(exc_info.value)

        # Test whitespace-only string
        kwargs_ws = dict(valid_kwargs, **{field_name: "   "})
        with pytest.raises(ValidationError) as exc_info:
            ProvisioningParameters(**kwargs_ws)
        assert f"{field_name} cannot be empty" in str(exc_info.value)

    def test_selected_subnet_whitespace_stripping(self):
        params = ProvisioningParameters(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="appdata",
            environment="prod",
            resource_name="stappdataprod",
            selected_subnet="   snet-data-prod   ",
        )
        assert params.selected_subnet == "snet-data-prod"

        params_empty = ProvisioningParameters(
            subscription="sub-prod",
            resource_type="azurerm_storage_account",
            workload_name="appdata",
            environment="prod",
            resource_name="stappdataprod",
            selected_subnet="   ",
        )
        assert params_empty.selected_subnet is None

