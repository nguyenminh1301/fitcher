"use client";

import type { AskEvent, Turn } from "@/lib/api/provisional";
import { stepFor } from "@/lib/steps";
import { useI18n } from "@/lib/i18n/react";

import { Button } from "@/components/ui/controls";

type Props = { turn: Turn; streaming: boolean; onStop: () => void; onRetry?: () => void; onFollowUp: (text: string) => void };

function find<K extends AskEvent["event"]>(events: AskEvent[], kind: K): Extract<AskEvent, { event: K }> | undefined {
  return events.find((event) => event.event === kind) as Extract<AskEvent, { event: K }> | undefined;
}

/** The assistant's answer to one turn, built from its streamed events. */
export function AssistantTurn({ turn, streaming, onStop, onFollowUp }: Props) {
  const { t } = useI18n();
  const events = turn.events;
  const last = [...events].reverse().find((event) => event.event === "status") as Extract<AskEvent, { event: "status" }> | undefined;
  const summary = find(events, "summary");
  const deny = find(events, "deny");
  const clarify = find(events, "clarify");
  const error = find(events, "error");

  return (
    <div className="fc-stack" style={{ minWidth: 0, flex: 1 }}>
      {streaming ? (
        <div className="fc-row">
          <span className="fc-muted">{last ? t(`ui.step_${stepFor(last.node, last.attempt) ?? "understand"}`, { n: last.attempt ?? 2 }) : t("ui.working")}</span>
          <Button size="sm" icon="stop" onClick={onStop}>{t("ui.stop")}</Button>
        </div>
      ) : null}
      {summary ? <p lang={summary.lang} style={{ margin: 0 }}>{summary.text}</p> : null}
      {deny ? <p lang={deny.lang} style={{ margin: 0 }}>{deny.message}</p> : null}
      {clarify ? (
        <div className="fc-stack" lang={clarify.lang}>
          <p style={{ margin: 0 }}>{clarify.question}</p>
          <div className="fc-row">{clarify.options.map((option) => <Button key={option.id} onClick={() => onFollowUp(option.label)}>{option.label}</Button>)}</div>
        </div>
      ) : null}
      {error ? <p className="fc-muted" style={{ margin: 0 }}>{error.kind === "stopped" ? t("ui.stoppedText") : error.message}</p> : null}
    </div>
  );
}
