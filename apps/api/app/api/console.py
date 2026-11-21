"""Who reaches the workspace console's endpoints (DECISIONS §9, §15).

fitcher is a personal app: the owner holds the whole console, and the address
checks and the optional owner password of ``app/auth/origin.py`` decide who is
the owner. ``Owner`` names that principal in the console's endpoints.
"""

from typing import Annotated

from fastapi import Depends

from app.api.auth import current_principal
from app.auth.principal import Principal

Owner = Annotated[Principal, Depends(current_principal)]
