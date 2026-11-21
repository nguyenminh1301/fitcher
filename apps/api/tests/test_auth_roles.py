"""The pack role a request runs as: the owner's first role in policy order (DECISIONS §9)."""

import pytest

from app.auth.roles import RoleError, active_role, held_pack_roles

PACK_ROLES = ["analyst", "marketing", "partner"]


def test_the_only_pack_role_is_active():
    assert active_role(["marketing"], PACK_ROLES) == "marketing"


def test_the_first_held_role_in_policy_order_is_active():
    assert active_role(["partner", "analyst"], PACK_ROLES) == "analyst"


def test_a_principal_without_a_pack_role_is_refused():
    with pytest.raises(RoleError, match="no role of this pack"):
        active_role(["offline_access"], PACK_ROLES)


def test_held_roles_keep_the_pack_roles_in_policy_order():
    assert held_pack_roles(["offline_access", "partner", "analyst"], PACK_ROLES) == ["analyst", "partner"]
