"""Signing in and out with a local account (DECISIONS §9).

``POST /session`` checks the e-mail and password and answers with the session
cookie: ``HttpOnly``, ``SameSite=Strict``, sent on every path, and ``Secure``
when the request arrived over HTTPS. A failure answers the same 401 whether
the account exists or not; repeated failures for one e-mail or one client
address answer 429 with ``Retry-After`` until the throttling window passes.
``DELETE /session`` ends the session and clears the cookie.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status

from app.api.runtime import get_state_db
from app.auth import accounts, account_sessions
from app.auth.principal import SESSION_COOKIE
from app.contracts.session import SignIn
from app.state.db import StateDb

router = APIRouter(prefix="/session")
State = Annotated[StateDb, Depends(get_state_db)]


def _cookie_options(request: Request) -> dict:
    return {"path": "/", "httponly": True, "samesite": "strict", "secure": request.url.scheme == "https"}


def sign_in_response(request: Request, response: Response, db: StateDb, account_id: str) -> None:
    """Start a session for the account and set its cookie on ``response``."""
    token = account_sessions.start(db, account_id)
    response.set_cookie(SESSION_COOKIE, token, max_age=account_sessions.LIFETIME_SECONDS, **_cookie_options(request))


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
def sign_in(body: SignIn, request: Request, response: Response, db: State) -> None:
    throttle = account_sessions.SignInThrottle(db)
    address = request.client.host if request.client else "unknown"
    keys = [account_sessions.email_key(body.email), account_sessions.address_key(address)]
    wait, attempt = throttle.reserve(keys)
    if wait:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="too many failed sign-ins; try again later",
                            headers={"Retry-After": str(wait)})
    account = accounts.authenticate(db, body.email, body.password)
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")
    throttle.succeeded(attempt, keys[0])
    sign_in_response(request, response, db, account.id)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(
    request: Request, response: Response, db: State,
    session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    if session:
        account_sessions.end(db, session)
    response.delete_cookie(SESSION_COOKIE, **_cookie_options(request))
