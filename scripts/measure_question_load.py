"""Measure how the api answers 1, 5 and 20 questions at once with a fake graph of fixed latency.

Run with ``uv run --project apps/api python scripts/measure_question_load.py``. Each question
streams through the api's ``event_stream`` and its ``QuestionGate`` exactly as ``POST /ask`` does;
the graph is replaced by nodes that sleep a fixed time (``LLM_SECONDS`` on the nodes that call a
model, ``STEP_SECONDS`` on the others), so the result measures the api's queueing, threads and
streaming, not a model or ClickHouse. ``docs/operations.md`` records a run.
"""

import asyncio
import json
import os
import resource
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.api.ask import AnswerEvents, event_stream  # noqa: E402 - needs apps/api on the path
from app.api.limits import QuestionGate  # noqa: E402

# The nodes up to the query: the fake has no result, so the stream would end at execute.
NODES = ("screen", "extract", "resolve_time", "retrieve", "build_spec", "gate", "generate_sql", "guard", "explain")
LLM_NODES = {"extract", "generate_sql"}
LLM_SECONDS, STEP_SECONDS = 1.0, 0.02
LEVELS = (1, 5, 20)


class FixedLatencyRun:
    def run(self, question, progress):
        state = {"trace_id": "0" * 32, "attempts": []}
        for node in NODES:
            progress(node, "start", state, None)
            time.sleep(LLM_SECONDS if node in LLM_NODES else STEP_SECONDS)
            progress(node, "end", state, {})
        raise RuntimeError("the fake graph stops after its last node")

    def cancel(self):
        pass


async def one(gate: QuestionGate) -> dict:
    started, seen, node_times, waited = time.monotonic(), {}, {}, 0.0
    async for chunk in event_stream(FixedLatencyRun(), "q", AnswerEvents("viewer"), gate=gate):
        if not chunk.startswith("event: status"):
            continue
        event = json.loads(chunk.split("data: ", 1)[1])
        now = time.monotonic()
        if event["phase"] == "start":
            seen[event["node"]] = now
        elif event["node"] == "queue":
            waited = now - seen["queue"]
        else:
            node_times[event["node"]] = now - seen[event["node"]]
    return {"total": time.monotonic() - started, "queue": waited, "nodes": node_times}


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


async def level(count: int, limit: int) -> dict:
    gate = QuestionGate(lambda: limit, poll_seconds=0.05)
    results = await asyncio.gather(*(one(gate) for _ in range(count)))
    totals = [r["total"] for r in results]
    llm = [t for r in results for name, t in r["nodes"].items() if name in LLM_NODES]
    steps = [t for r in results for name, t in r["nodes"].items() if name not in LLM_NODES]
    return {"questions": count, "median_s": round(statistics.median(totals), 2), "p95_s": round(percentile(totals, 0.95), 2),
            "median_queue_s": round(statistics.median(r["queue"] for r in results), 2),
            "median_llm_node_s": round(statistics.median(llm), 2), "median_step_node_s": round(statistics.median(steps), 3),
            "threads_peak": threading.active_count()}


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    print(f"CPUs {os.cpu_count()}; the event loop's default executor would hold {min(32, (os.cpu_count() or 1) + 4)} threads")
    print(f"limits.concurrent_questions = {limit}; LLM node {LLM_SECONDS}s, other node {STEP_SECONDS}s")
    for count in LEVELS:
        print(json.dumps(asyncio.run(level(count, limit))))
    print(f"peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
