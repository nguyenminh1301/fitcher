"""POST /feedback: the signed-in user's like or dislike of one of their answers (DECISIONS §10 and §15).

The answer is found by its trace id among the user's own stored answers, so a
trace of another user's answer, or one that does not exist, is 404 and nothing
is written.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.auth import current_principal
from app.api.runtime import get_conversation_store, unavailable
from app.auth.principal import Principal
from app.contracts.feedback import FeedbackInput
from app.conversation.store import AnswerNotFound, ConversationStore

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
def send_feedback(
    body: FeedbackInput,
    user: Annotated[Principal, Depends(current_principal)],
    store: Annotated[ConversationStore, Depends(get_conversation_store)],
) -> Response:
    try:
        store.record_feedback(user.user_id, body)
    except AnswerNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="answer not found") from None
    except Exception:  # noqa: BLE001 - ClickHouse is unreachable or refused the feedback table
        logger.exception("the feedback write failed")
        raise unavailable("the feedback store is unavailable") from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
