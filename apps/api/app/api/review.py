"""The console's Review page: list, edit, approve, delete and test-run pack items (DECISIONS §11 step 5).

Only a ``pack_reviewer`` reaches these endpoints. Changes are written to the
active pack's working tree (``PACKS_DIR``), never committed by the app; a
reviewer commits approved YAML through the normal pull request workflow and
compiles the pack, which uses approved items only. Changes answer 409 while
the pack compiles and 422 when the file would no longer match its schema or a
formula fails its test-run on approval.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.console import require_reviewer
from app.api.runtime import get_review_service
from app.auth.principal import Principal
from app.contracts.review import ReviewItem, ReviewItemPatch
from app.onboarding.pack_yaml import ItemNotFound
from app.onboarding.review import ReviewRefused, ReviewService
from app.packs.loader import PackValidationError

router = APIRouter(prefix="/review/items")
Reviewer = Annotated[Principal, Depends(require_reviewer)]
Service = Annotated[ReviewService, Depends(get_review_service)]


def _refusal(error: Exception) -> HTTPException:
    if isinstance(error, ItemNotFound):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail="review item not found")
    if isinstance(error, ReviewRefused):
        return HTTPException(error.status, detail=str(error))
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


REFUSED = (ItemNotFound, ReviewRefused, PackValidationError)


@router.get("")
def list_items(
    _: Reviewer,
    service: Service,
    file: str | None = None,
    status_filter: Annotated[Literal["draft", "approved"] | None, Query(alias="status")] = None,
) -> list[ReviewItem]:
    try:
        return service.items(file=file, status=status_filter)
    except REFUSED as error:
        raise _refusal(error) from None


@router.patch("/{item_id}")
def edit_item(item_id: str, body: ReviewItemPatch, _: Reviewer, service: Service) -> ReviewItem:
    try:
        return service.update(item_id, body=body.body, formula=body.formula, spec=body.spec, spec_reviewed=body.spec_reviewed)
    except REFUSED as error:
        raise _refusal(error) from None


@router.post("/{item_id}/approve")
def approve_item(item_id: str, _: Reviewer, service: Service) -> ReviewItem:
    try:
        return service.approve(item_id)
    except REFUSED as error:
        raise _refusal(error) from None


@router.post("/{item_id}/test-run")
def test_run_item(item_id: str, _: Reviewer, service: Service) -> ReviewItem:
    try:
        return service.test_run(item_id)
    except REFUSED as error:
        raise _refusal(error) from None


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: str, _: Reviewer, service: Service) -> Response:
    try:
        service.delete(item_id)
    except REFUSED as error:
        raise _refusal(error) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
