"use client";

// State the chat app shares between the sidebar and the page: who is signed in, the pack, the
// conversation history and groups, the open conversation and how to navigate between them.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type { FitcherApi } from "@/lib/api/client";
import type { Conversation, ConversationGroup, ConversationThread, Identity, Turn } from "@/lib/api/provisional";
import type { AskRequest } from "@/lib/contracts";
import { sources as currentSources, type Sources } from "@/lib/api/sources";
import { langOf } from "@/lib/text";

// A conversation's title is its first question cut to 80 characters (DECISIONS §15).
const TITLE_LENGTH = 80;

export type AskOptions = { conversationId?: string; editOf?: number; retryOf?: number };

export type ChatState = {
  api: FitcherApi;
  sources: Partial<Sources>;
  identity: Identity | null;
  identities: Identity[];
  pack: { name: string; display_name: string; roles: string[] } | null;
  conversations: Conversation[];
  groups: ConversationGroup[];
  loaded: boolean;
  activeId: string | null;
  now: () => Date;
  navigate: (conversationId: string | null) => void;
  refresh: () => Promise<void>;
  switchIdentity: (userId: string) => Promise<void>;
  /** Open conversations by id, with their turns as streamed so far. */
  threads: Record<string, ConversationThread>;
  /** The conversation whose answer is streaming, if any. */
  busy: string | null;
  loadThread: (id: string) => Promise<ConversationThread | null>;
  /** Ask in a conversation (a new one without ``conversationId``); edit or retry replace that turn and the ones after it. */
  ask: (question: string, options?: AskOptions) => Promise<string>;
  stop: () => void;
};

const ChatContext = createContext<ChatState | null>(null);

type ProviderProps = {
  api: FitcherApi;
  navigate: (conversationId: string | null) => void;
  activeId: string | null;
  sources?: Partial<Sources>;
  now?: () => Date;
  children: ReactNode;
};

export function ChatProvider({ api, navigate, activeId, sources = currentSources, now = () => new Date(), children }: ProviderProps) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [pack, setPack] = useState<ChatState["pack"]>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [groups, setGroups] = useState<ConversationGroup[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [threads, setThreads] = useState<Record<string, ConversationThread>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const threadsRef = useRef(threads);
  const busyRef = useRef<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    const [list, groupList] = await Promise.all([api.conversations.list(), api.conversations.groups()]);
    setConversations(list);
    setGroups(groupList);
    setLoaded(true);
  }, [api]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [current, all, packInfo] = await Promise.all([api.auth.current(), api.auth.identities(), api.auth.pack()]);
      if (cancelled) return;
      setIdentity(current);
      setIdentities(all);
      setPack(packInfo);
      await refresh();
    })();
    return () => {
      cancelled = true;
    };
  }, [api, refresh]);

  const putThread = useCallback((thread: ConversationThread) => {
    threadsRef.current = { ...threadsRef.current, [thread.conversation.id]: thread };
    setThreads(threadsRef.current);
  }, []);

  const loadThread = useCallback(
    async (id: string) => {
      if (threadsRef.current[id]) return threadsRef.current[id];
      const thread = await api.conversations.get(id);
      if (thread) putThread(thread);
      return thread;
    },
    [api, putThread],
  );

  const ask = useCallback(
    async (question: string, options: AskOptions = {}) => {
      if (busyRef.current) return options.conversationId ?? busyRef.current;
      const existing = options.conversationId ? await loadThread(options.conversationId) : null;
      const id = existing?.conversation.id ?? crypto.randomUUID();
      const stamp = now().toISOString();
      const conversation: Conversation = existing
        ? { ...existing.conversation, updated_at: stamp }
        : { id, title: question.slice(0, TITLE_LENGTH), pinned: false, group_id: null, updated_at: stamp };
      let turns = existing?.turns ?? [];
      const replaced = options.editOf ?? options.retryOf;
      let turn: Turn;
      if (replaced !== undefined) {
        const previous = turns.find((item) => item.turn === replaced);
        const text = options.retryOf !== undefined && previous ? previous.question : question;
        turns = turns.filter((item) => item.turn < replaced);
        turn = { turn: replaced, revision: (previous?.revision ?? 0) + 1, question: text, question_lang: langOf(text), events: [] };
      } else {
        turn = { turn: (turns.at(-1)?.turn ?? 0) + 1, revision: 1, question, question_lang: langOf(question), events: [] };
      }
      let thread: ConversationThread = { conversation, turns: [...turns, turn] };
      putThread(thread);
      await api.conversations.save(thread);
      await refresh();
      if (!existing) navigate(id);

      busyRef.current = id;
      setBusy(id);
      const abort = new AbortController();
      controller.current = abort;
      // Edit and retry replace the turn here; /ask learns of them with the conversation endpoints (Phase 8).
      const request: AskRequest = {
        question: turn.question,
        conversation_id: id,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      };
      void (async () => {
        try {
          for await (const event of api.chat.ask(request, abort.signal)) {
            const last = thread.turns.at(-1) as Turn;
            thread = { ...thread, turns: [...thread.turns.slice(0, -1), { ...last, events: [...last.events, event] }] };
            putThread(thread);
          }
        } catch (error) {
          const last = thread.turns.at(-1) as Turn;
          const failure = { event: "error" as const, kind: "network" as const, message: String(error), sql: null, error: null, trace_id: last.events.at(-1)?.trace_id ?? "" };
          thread = { ...thread, turns: [...thread.turns.slice(0, -1), { ...last, events: [...last.events, failure] }] };
          putThread(thread);
        } finally {
          await api.conversations.save(thread);
          busyRef.current = null;
          controller.current = null;
          setBusy(null);
          await refresh();
        }
      })();
      return id;
    },
    [api, loadThread, navigate, now, putThread, refresh],
  );

  const stop = useCallback(() => controller.current?.abort(), []);

  const switchIdentity = useCallback(
    async (userId: string) => {
      setIdentity(await api.auth.switchTo(userId));
      threadsRef.current = {};
      setThreads({});
      navigate(null);
      await refresh();
    },
    [api, navigate, refresh],
  );

  const value = useMemo<ChatState>(
    () => ({
      api, sources, identity, identities, pack, conversations, groups, loaded, activeId, now, navigate, refresh, switchIdentity,
      threads, busy, loadThread, ask, stop,
    }),
    [api, sources, identity, identities, pack, conversations, groups, loaded, activeId, now, navigate, refresh, switchIdentity, threads, busy, loadThread, ask, stop],
  );
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatState {
  const context = useContext(ChatContext);
  if (context === null) throw new Error("useChat needs a ChatProvider");
  return context;
}

/** Today, past week or past month, as the sidebar's Recent section groups them. */
export function recency(updatedAt: string, now: Date): "today" | "week" | "month" {
  const updated = new Date(updatedAt);
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (updated >= startOfToday) return "today";
  return now.getTime() - updated.getTime() <= 7 * 24 * 3600 * 1000 ? "week" : "month";
}

/** Whether these roles may open the workspace console (DECISIONS §15). */
export function hasConsole(roles: string[] = []): boolean {
  return roles.includes("pack_reviewer") || roles.includes("admin");
}
