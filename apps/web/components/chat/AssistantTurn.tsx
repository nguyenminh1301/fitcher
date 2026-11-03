"use client";

// One assistant turn, built from its streamed /ask events (DECISIONS §6): live steps while streaming,
// then the answer card, a clarifying question or a notice. Never a guessed result.

import { useState } from "react";

import { WarningBanner } from "@/components/ui/feedback";
import type { AskEvent } from "@/lib/api/events";
import type { Turn } from "@/lib/api/conversations";
import type { FeedbackInput, OrientedChartSpec } from "@/lib/api/provisional";
import type { ChartType } from "@/lib/contracts";
import { stepFor, type StepId } from "@/lib/steps";

import { ChartCard } from "./ChartCard";
import { ClarifyOptions, FeedbackBar, NoticeCard, ProgressSteps, Summary, type Step } from "./answer-parts";
import { DataTable } from "./DataTable";
import { SqlView } from "./SqlView";

type Props = {
  turn: Turn;
  streaming: boolean;
  onStop: () => void;
  onRetry?: () => void;
  onFollowUp: (text: string) => void;
  onFeedback?: (input: FeedbackInput) => void;
};

function only<K extends AskEvent["event"]>(events: AskEvent[], kind: K): Extract<AskEvent, { event: K }> | undefined {
  return [...events].reverse().find((event) => event.event === kind) as Extract<AskEvent, { event: K }> | undefined;
}

/** The design's steps in the order the graph reached them; the last one is active while streaming. */
export function stepsOf(events: AskEvent[], streaming: boolean, failed: boolean, denied: boolean): Step[] {
  const steps: Step[] = [];
  for (const event of events) {
    if (event.event !== "status") continue;
    const attempt = event.attempt ?? undefined;
    const id = stepFor(event.node, attempt) as StepId | undefined;
    if (!id) continue;
    const previous = steps.at(-1);
    if (previous && previous.id === id && previous.attempt === attempt) continue;
    steps.push({ id, attempt, status: "done" });
  }
  const last = steps.at(-1);
  if (last && streaming) last.status = "active";
  else if (last && failed) last.status = "failed";
  else if (last && denied) last.status = "denied";
  return steps;
}

export function AssistantTurn({ turn, streaming, onStop, onRetry, onFollowUp, onFeedback }: Props) {
  const events = turn.events;
  const result = only(events, "result")?.result;
  // Sample scenarios carry a bar orientation the contract gains in Phase 9.
  const spec = only(events, "chart_spec")?.spec as OrientedChartSpec | undefined;
  const summary = only(events, "summary");
  const sql = only(events, "sql")?.sql;
  const deny = only(events, "deny");
  const clarify = only(events, "clarify");
  const error = only(events, "error");
  const traceId = events[0]?.trace_id ?? "";
  const [type, setType] = useState<ChartType>(spec?.type ?? "table");
  const [orientation, setOrientation] = useState<"vertical" | "horizontal">(spec?.orientation ?? "horizontal");
  const steps = stepsOf(events, streaming, error?.kind === "failed", !!deny);
  const feedback = (rating: "like" | "dislike", note?: string) => onFeedback?.({ trace_id: traceId, rating, ...(note ? { note } : {}) });

  if (streaming) return <article className="fc-answer"><ProgressSteps steps={steps} live onStop={onStop} /></article>;
  const lang = summary?.lang ?? deny?.lang ?? clarify?.lang ?? turn.question_lang;

  return (
    <article className="fc-answer">
      {steps.length ? <ProgressSteps steps={steps} live={false} /> : null}
      {deny ? <NoticeCard kind="denied" lang={deny.lang} text={deny.message} blocked={deny.blocked} /> : null}
      {clarify ? <ClarifyOptions question={clarify.question} options={clarify.options} lang={clarify.lang} onPick={onFollowUp} /> : null}
      {error ? (
        <NoticeCard
          kind={error.kind === "failed" ? "failed" : error.kind === "stopped" ? "stopped" : "network"}
          lang={lang}
          sql={error.sql ?? undefined}
          error={error.error ?? undefined}
          onRetry={error.kind === "failed" ? undefined : onRetry}
        />
      ) : null}
      {summary ? <Summary text={summary.text} lang={summary.lang} /> : null}
      {summary?.warnings.map((warning) => (
        <WarningBanner key={warning} tone="warning"><span lang={summary.lang}>{warning}</span></WarningBanner>
      ))}
      {result && result.row_count === 0 ? <NoticeCard kind="empty" lang={lang} sql={sql} /> : null}
      {result && result.row_count > 0 && spec ? (
        <ChartCard spec={spec} result={result} type={type} onType={setType} orientation={orientation} onOrientation={setOrientation} />
      ) : null}
      {result && result.row_count > 0 && type !== "table" ? <DataTable result={result} /> : null}
      {sql && result && result.row_count > 0 ? <SqlView sql={sql} /> : null}
      {summary || result ? <FeedbackBar onSubmit={feedback} onCopy={() => summary?.text.replace(/\*\*/g, "") ?? ""} onRetry={onRetry} /> : null}
    </article>
  );
}
