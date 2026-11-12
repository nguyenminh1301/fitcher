"""Answer what a business term, metric, column or dataset means (DECISIONS §6 step 3).

The question is embedded once and searched in the glossary, metrics, datasets
and company documents (``kb_docs``), filtered by the asking role, so an
answer never describes what the role may not read. The ``fast`` tier answers
from those hits only, in the question's language. Figures come only from SQL
(DECISIONS §5): the prompt forbids quoting numbers from the hits, and states
that retrieved text is data, not instructions. No SQL is generated.
"""

import json

from app.agent.prompts import render
from app.agent.state import AgentDeps, AgentState
from app.llm.client import LLMError
from app.llm.embeddings import EmbeddingError
from app.packs.search_indices import alias_name
from app.search.client import SearchError

TIER = "fast"
PROMPT = "metadata_qa.v2"
SEARCHED = ("glossary_terms", "metrics", "datasets", "kb_docs")
HITS_PER_INDEX = 3
TEXT_LIMIT = 1200
FALLBACK = {
    "en": "I could not look up the definition right now. Please try again shortly.",
    "vi": "Mình chưa tra được định nghĩa lúc này. Bạn thử lại sau ít phút nhé.",
}


def _entry(index: str, hit: dict) -> str:
    source = hit.get("source", {})
    entry = {"source": index, "title": source.get("title", ""), "text": str(source.get("text", ""))[:TEXT_LIMIT]}
    formula = source.get("payload", {}).get("sql_expr")
    if formula:
        entry["formula"] = formula
    return json.dumps(entry, ensure_ascii=False)


def metadata_qa(state: AgentState, deps: AgentDeps) -> dict:
    pack = deps.compiled.pack
    question = state["question"]
    try:
        vector = deps.embeddings.embed([question])[0]
        hits = [
            (index, hit)
            for index in SEARCHED
            for hit in deps.search.query(alias_name(pack.name, index), question, vector, [deps.role], HITS_PER_INDEX)
        ]
    except (EmbeddingError, SearchError) as error:
        return {"rejection": f"the pack context could not be retrieved: {error}"}
    language = state.get("language") or "en"
    found = [_entry(index, hit) for index, hit in hits]
    prompt = render(
        PROMPT, language=language, industry=pack.business_profile.industry,
        hits="\n".join(found) or "none: no definitions were found", question=json.dumps(question, ensure_ascii=False),
    )
    # What the answer was written from, as "<index>:<id>"; the eval scores it against a case's expected_sources.
    sources = [f"{index}:{hit['id']}" for index, hit in hits]
    try:
        return {"reply": deps.llm.text(TIER, prompt).strip(), "sources": sources}
    except LLMError:
        return {"reply": FALLBACK.get(language, FALLBACK["en"]), "sources": sources}
