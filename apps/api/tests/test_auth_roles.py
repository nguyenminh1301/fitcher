"""Token roles mapped to the active pack role (Phase 7 open question 1)."""

import pytest

from app.auth.roles import RoleError, active_role, known_roles

PACK_ROLES = ["analyst", "marketing", "partner"]


def test_the_only_pack_role_is_active():
    assert active_role(["marketing", "offline_access"], PACK_ROLES, None) == "marketing"


def test_without_a_requested_role_the_first_in_policy_order_is_active():
    assert active_role(["partner", "admin", "analyst"], PACK_ROLES, None) == "analyst"


def test_a_requested_role_the_token_holds_is_active():
    assert active_role(["partner", "analyst"], PACK_ROLES, "partner") == "partner"


@pytest.mark.parametrize("requested", ["marketing", "admin", "unknown"])
def test_a_requested_role_the_token_does_not_hold_as_a_pack_role_is_refused(requested):
    with pytest.raises(RoleError, match=requested):
        active_role(["analyst", "admin"], PACK_ROLES, requested)


def test_a_token_without_a_pack_role_is_refused():
    with pytest.raises(RoleError, match="no role of this pack"):
        active_role(["admin", "offline_access"], PACK_ROLES, None)


def test_known_roles_keep_pack_and_console_roles_only():
    assert known_roles(["offline_access", "admin", "partner", "default-roles-lab", "analyst"], PACK_ROLES) == [
        "analyst", "partner", "admin",
    ]
