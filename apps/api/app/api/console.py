"""Role checks of the workspace console's endpoints (DECISIONS §15).

The console's navigation (``apps/web/lib/console/sections.ts``) lists a
section only for these roles, and every endpoint behind a section enforces
the same rule here.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.api.auth import current_principal
from app.auth.jwt import Principal

PACK_REVIEWER = "pack_reviewer"
ADMIN = "admin"


def require_reviewer(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    """Review, Documents and Datasets belong to the ``pack_reviewer`` role."""
    if PACK_REVIEWER not in principal.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="this console section needs the pack_reviewer role")
    return principal


def require_admin(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    """Runs and trace, Audit, Costs, Users and Models belong to the ``admin`` role."""
    if ADMIN not in principal.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="this console section needs the admin role")
    return principal
