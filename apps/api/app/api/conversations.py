"""The signed-in user's conversations and groups for the Chat app sidebar (DECISIONS §15).

Every endpoint acts as the token's user only: another user's conversation or
group, and a deleted one, is 404, and nothing is shared. Changes write new
rows (rename, pin, move, delete); a deleted conversation disappears from its
owner's list, search and reads while its rows stay for the admin view.
"""

from collections.abc import Callable
import logging
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.auth import current_principal
from app.api.runtime import get_conversation_store, unavailable
from app.auth.principal import Principal
from app.contracts.conversations import Conversation, ConversationGroup, ConversationPatch, ConversationThread, GroupInput
from app.conversation.store import ConversationNotFound, ConversationStore, GroupNotFound

logger = logging.getLogger(__name__)
router = APIRouter()
T = TypeVar("T")

User = Annotated[Principal, Depends(current_principal)]
Store = Annotated[ConversationStore, Depends(get_conversation_store)]


def _call(action: Callable[[], T]) -> T:
    """Run a store call, turning a missing conversation or group into 404 and a store failure into 503."""
    try:
        return action()
    except ConversationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="conversation not found") from None
    except GroupNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="group not found") from None
    except Exception:  # noqa: BLE001 - ClickHouse is unreachable or refused the conversation tables
        logger.exception("the conversation store failed")
        raise unavailable("the conversation store is unavailable") from None


@router.get("/conversations")
def list_conversations(
    user: User, store: Store, limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Conversation]:
    """The user's conversations, newest activity first."""
    return _call(lambda: store.conversations(user.user_id, limit=limit, offset=offset))


@router.get("/conversations/search")
def search_conversations(
    user: User, store: Store, q: Annotated[str, Query(min_length=1, max_length=200)],
) -> list[Conversation]:
    """The user's conversations whose title or own questions contain ``q``, ignoring case and diacritics."""
    return _call(lambda: store.search(user.user_id, q))


@router.get("/conversations/{conversation_id}")
def read_conversation(conversation_id: str, user: User, store: Store) -> ConversationThread:
    return _call(lambda: store.thread(user.user_id, conversation_id))


@router.patch("/conversations/{conversation_id}")
def update_conversation(conversation_id: str, patch: ConversationPatch, user: User, store: Store) -> Conversation:
    return _call(lambda: store.update(user.user_id, conversation_id, patch))


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, user: User, store: Store) -> Response:
    _call(lambda: store.delete(user.user_id, conversation_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/conversation-groups")
def list_groups(user: User, store: Store) -> list[ConversationGroup]:
    return _call(lambda: store.groups(user.user_id))


@router.post("/conversation-groups", status_code=status.HTTP_201_CREATED)
def create_group(body: GroupInput, user: User, store: Store) -> ConversationGroup:
    return _call(lambda: store.create_group(user.user_id, body.name))


@router.patch("/conversation-groups/{group_id}")
def rename_group(group_id: str, body: GroupInput, user: User, store: Store) -> ConversationGroup:
    return _call(lambda: store.rename_group(user.user_id, group_id, body.name))


@router.delete("/conversation-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: str, user: User, store: Store) -> Response:
    """Delete the group; its conversations move back to no group."""
    _call(lambda: store.delete_group(user.user_id, group_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
