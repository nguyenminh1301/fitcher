"""The owner password over HTTP (DECISIONS §9): its status, signing in and out, and setting or removing it.

``GET /owner/status``, ``POST /owner/session`` and ``DELETE /owner/session`` are public; the guard of
``app/auth/origin.py`` lets every other request through only with a signed-in session once a password is set.
The session cookie is ``HttpOnly``, ``SameSite=Strict``, sent on every path, and ``Secure`` when the request
arrived over HTTPS. Setting the password is possible only from this computer, ends every other session and
signs the caller in; removing it needs the current password and is refused while the instance is reachable
through a name in ``FITCHER_ALLOWED_HOSTS``.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status

from app.api.runtime import get_state_db
from app.auth import origin, owner
from app.contracts.owner import OwnerPasswordChange, OwnerPasswordRemoval, OwnerSignIn, OwnerStatus
from app.state.db import StateDb

router = APIRouter(prefix="/owner")
State = Annotated[StateDb, Depends(get_state_db)]
Session = Annotated[str | None, Cookie(alias=owner.SESSION_COOKIE)]


def _browser_host(request: Request) -> str:
    return request.headers.get("x-forwarded-host") or request.headers.get("host", "")


def _peer(request: Request) -> str:
    return request.headers.get(origin.PEER_HEADER) or (request.client.host if request.client else "unknown")


def _cookie_options(request: Request) -> dict:
    return {"path": "/", "httponly": True, "samesite": "strict",
            "secure": request.url.scheme == "https" or origin.https_forwarded(request.headers)}


def _sign_in(request: Request, response: Response, db: StateDb) -> None:
    response.set_cookie(owner.SESSION_COOKIE, owner.start_session(db), max_age=owner.LIFETIME_SECONDS,
                        **_cookie_options(request))


@router.get("/status")
def get_status(request: Request, db: State, session: Session = None) -> OwnerStatus:
    return OwnerStatus(password_set=owner.password_set(db), signed_in=owner.session_valid(db, session),
                       exposed=origin.remote(_browser_host(request)) or origin.exposed())


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT)
def sign_in(body: OwnerSignIn, request: Request, response: Response, db: State) -> None:
    if not owner.password_set(db):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="no owner password is set; there is nothing to sign in to")
    throttle = owner.SignInThrottle(db)
    wait, attempt = throttle.reserve(_peer(request))
    if wait:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="too many wrong passwords; try again later",
                            headers={"Retry-After": str(wait)})
    if not owner.verify(db, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="the password is not right")
    throttle.succeeded(attempt)
    _sign_in(request, response, db)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(request: Request, response: Response, db: State, session: Session = None) -> None:
    if session:
        owner.end_session(db, session)
    response.delete_cookie(owner.SESSION_COOKIE, **_cookie_options(request))


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
def set_password(body: OwnerPasswordChange, request: Request, response: Response, db: State) -> None:
    if origin.remote(_browser_host(request)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="the owner password is set from this computer only")
    try:
        owner.set_password(db, body.new_password, current=body.current_password)
    except owner.WrongPassword as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(error)) from None
    except owner.WeakPassword as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from None
    _sign_in(request, response, db)


@router.delete("/password", status_code=status.HTTP_204_NO_CONTENT)
def remove_password(body: OwnerPasswordRemoval, request: Request, response: Response, db: State) -> None:
    if origin.exposed():
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="this instance is reachable from other machines (FITCHER_ALLOWED_HOSTS), so it keeps "
                                   "its password")
    try:
        owner.remove_password(db, body.current_password)
    except owner.WrongPassword as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(error)) from None
    response.delete_cookie(owner.SESSION_COOKIE, **_cookie_options(request))
