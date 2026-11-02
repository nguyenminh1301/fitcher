"use client";

import { useEffect, useRef, useState } from "react";

import { Finch } from "@/components/brand/Logo";
import { Skeleton } from "@/components/ui/feedback";
import type { Turn } from "@/lib/api/provisional";
import { useChat } from "@/lib/chat/ChatContext";
import { useI18n } from "@/lib/i18n/react";

import { AssistantTurn } from "./AssistantTurn";
import { Composer, PackChip } from "./Composer";
import { MessageBubble } from "./MessageBubble";

/** One conversation: its turns, newest at the bottom, and the composer docked below. */
export function ConversationView({ id }: { id: string }) {
  const { t } = useI18n();
  const { api, threads, loadThread, ask, stop, busy, pack } = useChat();
  const [missing, setMissing] = useState(false);
  const scroll = useRef<HTMLDivElement>(null);
  const thread = threads[id];

  useEffect(() => {
    setMissing(false);
    void loadThread(id).then((found) => setMissing(found === null));
  }, [id, loadThread]);

  const running = busy === id;
  const lastEvents = thread?.turns.at(-1)?.events.length ?? 0;
  useEffect(() => {
    const element = scroll.current;
    if (element && running) element.scrollTop = element.scrollHeight;
  }, [running, lastEvents]);

  if (missing) return <div className="fc-scroll"><div className="fc-thread"><p className="fc-muted">{t("ui.noResults")}</p></div></div>;
  return (
    <>
      <div className="fc-scroll" ref={scroll}>
        {!thread ? (
          <div className="fc-thread"><Skeleton variant="thread" /></div>
        ) : (
          <div className="fc-thread" role="log" aria-live="polite" aria-label={t("ui.history")}>
            {thread.turns.map((turn: Turn, index) => {
              const streaming = running && index === thread.turns.length - 1;
              return (
                <div key={`${turn.turn}-${turn.revision}`} className="fc-stack">
                  <MessageBubble lang={turn.question_lang} disabled={running} onEdit={(text) => void ask(text, { conversationId: id, editOf: turn.turn })}>
                    {turn.question}
                  </MessageBubble>
                  <div className="fc-turn">
                    <Finch live={streaming} />
                    <AssistantTurn
                      turn={turn}
                      streaming={streaming}
                      onStop={stop}
                      onRetry={running ? undefined : () => void ask(turn.question, { conversationId: id, retryOf: turn.turn })}
                      onFollowUp={(text) => void ask(text, { conversationId: id })}
                      onFeedback={(input) => void api.feedback.send(input)}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <div className="fc-dock">
        <Composer running={running} onStop={stop} onSend={(text) => void ask(text, { conversationId: id })} meta={pack ? <PackChip name={pack.name} /> : null} />
      </div>
    </>
  );
}
