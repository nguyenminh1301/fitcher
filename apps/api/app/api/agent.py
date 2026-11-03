"""The agent behind ``/ask``: clients shared by every request, and one run per question.

``Agent`` holds the LLM, search, embedding and log clients of the active pack
and one ClickHouse client per pack role, created on that role's first
question. ``Agent.start`` prepares a run as one user and role over the
conversation's thread so far; the run records
the id of each query it sends, so ``cancel`` can stop the one still running
when the client goes away, through the ``agent_query_stopper`` user.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from functools import partial
import logging
import threading
from typing import Protocol
from uuid import uuid4

from app.agent.graph import run_question
from app.agent.state import AgentDeps, AgentState, Progress
from app.config import Settings
from app.conversation.store import Turn
from app.data.clickhouse import ClickHouseRunner, QueryLimits, QueryStopper, agent_client, stopper_client
from app.llm.client import LiteLLMClient
from app.llm.embeddings import LiteLLMEmbeddings
from app.observability.log_writer import start_log_writer
from app.packs.compiler import CompiledPack
from app.packs.policy_compiler import Names
from app.search.opensearch import OpenSearch

logger = logging.getLogger(__name__)


class AgentRun(Protocol):
    def run(self, question: str, progress: Progress) -> AgentState: ...

    def cancel(self) -> None: ...


class QueryIds:
    """Generates the run's ClickHouse query ids and remembers the latest one."""

    def __init__(self):
        self.latest: str | None = None

    def __call__(self) -> str:
        self.latest = str(uuid4())
        return self.latest


@dataclass
class GraphRun:
    deps: AgentDeps
    query_ids: QueryIds | None = None
    # Returns the stopper and the ClickHouse user whose query it stops.
    stopper: Callable[[], tuple[QueryStopper, str]] | None = None

    def run(self, question: str, progress: Progress) -> AgentState:
        return run_question(question, replace(self.deps, progress=progress))

    def cancel(self) -> None:
        query_id = self.query_ids.latest if self.query_ids else None
        if self.stopper is None or query_id is None:
            return
        try:
            stopper, user = self.stopper()
            stopper.stop(query_id, user)
        except Exception:  # noqa: BLE001 - a failed stop leaves the query to its time limit
            logger.warning("could not stop query %s", query_id, exc_info=True)


class Agent:
    def __init__(self, settings: Settings, compiled: CompiledPack):
        self.compiled = compiled
        self._llm = LiteLLMClient(settings.litellm_base_url, settings.litellm_master_key)
        self._search = OpenSearch(settings.opensearch_url)
        # Query vectors must match the indexed ones, so the compiled size wins over the environment.
        self._embeddings = LiteLLMEmbeddings(
            settings.litellm_base_url, settings.litellm_master_key, compiled.embedding_dimensions,
        )
        self._limits = QueryLimits.from_env()
        self._logs = start_log_writer(settings)
        self._clients: dict[str, object] = {}
        self._stopper: QueryStopper | None = None
        self._lock = threading.Lock()

    def _client(self, role: str):
        with self._lock:
            if role not in self._clients:
                self._clients[role] = agent_client(self.compiled.pack.name, role)
            return self._clients[role]

    def _stopper_for(self, role: str) -> tuple[QueryStopper, str]:
        with self._lock:
            if self._stopper is None:
                self._stopper = QueryStopper(stopper_client())
        return self._stopper, Names(self.compiled.pack.name).user(role)

    def start(self, *, role: str, user_id: str, today: date, history: Sequence[Turn] = ()) -> GraphRun:
        query_ids = QueryIds()
        runner = ClickHouseRunner(self._client(role), self._limits, new_query_id=query_ids)
        deps = AgentDeps(
            llm=self._llm, search=self._search, embeddings=self._embeddings, runner=runner,
            compiled=self.compiled, today=today, logs=self._logs, user_id=user_id, role=role, history=tuple(history),
        )
        return GraphRun(deps, query_ids, partial(self._stopper_for, role))

    def close(self) -> None:
        self._logs.close()
