"use client";

// State the chat app shares between the sidebar and the page: who is signed in, the pack, the
// conversation history and groups, the open conversation and how to navigate between them.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { AccessRefused } from "@/lib/api/http/auth";
import { AskRefused } from "@/lib/api/http/chat";
import type { FitcherApi } from "@/lib/api/client";
import type { Conversation, ConversationGroup, ConversationThread, Turn } from "@/lib/api/conversations";
import type { Identity } from "@/lib/api/provisional";
import type { AskRequest } from "@/lib/contracts";
import { isSample, sources as currentSources, type Sources } from "@/lib/api/sources";
import { langOf } from "@/lib/text";

// A conversation's title is its first question cut to 80 characters (DECISIONS §15).
const TITLE_LENGTH = 80;
const FOLLOW_MS = 2000;

/** ``clarifyOption`` is the id of the clarifying option the question picks, which the api applies as it is. */
export type AskOptions = { conversationId?: string; editOf?: number; retryOf?: number; clarifyOption?: string };

export type ChatState = {
  api: FitcherApi;
  sources: Partial<Sources>;
  identity: Identity | null;
  /** The api's reason when it refused this browser outright (see AccessRefused), else null. */
  refused: string | null;
  pack: { name: string; display_name: string; roles: string[] } | null;
  conversations: Conversation[];
  groups: ConversationGroup[];
  loaded: boolean;
  activeId: string | null;
  now: () => Date;
  navigate: (conversationId: string | null) => void;
  refresh: () => Promise<void>;
  /** Open conversations by id, with their turns as streamed so far. */
  threads: Record<string, ConversationThread>;
  /** The conversation whose answer is streaming, if any. */
  busy: string | null;
  loadThread: (id: string) => Promise<ConversationThread | null>;
  /** Ask in a conversation (a new one without ``conversationId``); edit or retry replace that turn and the ones after it. */
  ask: (question: string, options?: AskOptions) => Promise<string>;
  /** Stop the answer of a conversation, the one streaming here by default. */
  stop: (conversationId?: string) => void;
  /** The pack (one per data source) a new conversation is answered from: the api's current pack. */
  chosenPack: string | null;
  /** Make a source's pack the current one on the api, for the console and a new conversation alike. */
  choosePack: (name: string) => Promise<void>;
};

const ChatContext = createContext<ChatState | null>(null);

type ProviderProps = {
  api: FitcherApi;
  navigate: (conversationId: string | null) => void;
  activeId: string | null;
  sources?: Partial<Sources>;
  now?: () => Date;
  /** Called when real sign-in finds no session, to send the user to the sign-in page. */
  onSignedOut?: () => void;
  children: ReactNode;
};

export function ChatProvider({ api, navigate, activeId, sources = currentSources, now = () => new Date(), onSignedOut, children }: ProviderProps) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [pack, setPack] = useState<ChatState["pack"]>(null);
  // The api keeps the current pack, so the chat, the console and other tabs agree on the source.
  const chosenPack = pack?.name ?? null;
  const choosePack = useCallback(async (name: string) => {
    await api.auth.choosePack(name).then(setPack).catch(() => undefined);
  }, [api]);
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
      let answers;
      try {
        answers = await Promise.all([api.auth.current(), api.auth.pack()]);
      } catch (error) {
        if (!cancelled && error instanceof AccessRefused) setRefused(error.reason);
        if (error instanceof AccessRefused) return;
        throw error;
      }
      const [current, packInfo] = answers;
      if (cancelled) return;
      if (current === null && !isSample("auth", sources)) {
        onSignedOut?.();
        return;
      }
      setIdentity(current);
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

  // A conversation the api is still answering, after this page was left and opened again, is read again until the
  // answer is stored.
  const followed = useRef(new Set<string>());
  const follow = useCallback((id: string) => {
    if (followed.current.has(id)) return;
    followed.current.add(id);
    const tick = async () => {
      try {
        const fresh = await api.conversations.get(id);
        if (fresh && busyRef.current !== id) putThread(fresh);
        if (fresh?.running) {
          setTimeout(() => void tick(), FOLLOW_MS);
          return;
        }
      } catch {
        setTimeout(() => void tick(), FOLLOW_MS);
        return;
      }
      followed.current.delete(id);
      await refresh();
    };
    setTimeout(() => void tick(), FOLLOW_MS);
  }, [api, putThread, refresh]);

  const loadThread = useCallback(
    async (id: string) => {
      if (threadsRef.current[id]) return threadsRef.current[id];
      const thread = await api.conversations.get(id);
      if (thread) putThread(thread);
      if (thread?.running && busyRef.current !== id) follow(id);
      return thread;
    },
    [api, putThread, follow],
  );

  const ask = useCallback(
    async (question: string, options: AskOptions = {}) => {
      if (busyRef.current) return options.conversationId ?? busyRef.current;
      const existing = options.conversationId ? await loadThread(options.conversationId) : null;
      // A new conversation shows under a browser id until the api names it.
      let id = existing?.conversation.id ?? crypto.randomUUID();
      const stamp = now().toISOString();
      const conversation: Conversation = existing
        ? { ...existing.conversation, updated_at: stamp }
        : { id, title: question.slice(0, TITLE_LENGTH), pinned: false, group_id: null, updated_at: stamp, pack: chosenPack };
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
      // Edit and retry replace the turn here and on the api, which stores the new revision.
      const request: AskRequest = {
        question: turn.question,
        conversation_id: existing ? id : null,
        // A conversation keeps the pack it started with; a new one starts from the chosen source.
        pack: existing ? null : chosenPack,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        edit_of_turn: options.editOf ?? null,
        retry_of_turn: options.retryOf ?? null,
        clarify_option: options.clarifyOption ?? null,
      };
      const named = (apiId: string) => {
        if (apiId === id) return;
        const { [id]: _replaced, ...others } = threadsRef.current;
        threadsRef.current = others;
        id = apiId;
        thread = { ...thread, conversation: { ...thread.conversation, id } };
        putThread(thread);
        busyRef.current = id;
        setBusy(id);
        navigate(id);
      };
      void (async () => {
        try {
          for await (const event of api.chat.ask(request, abort.signal, named)) {
            const last = thread.turns.at(-1) as Turn;
            thread = { ...thread, turns: [...thread.turns.slice(0, -1), { ...last, events: [...last.events, event] }] };
            putThread(thread);
          }
        } catch (error) {
          const last = thread.turns.at(-1) as Turn;
          // A refusal before the stream started has the api's reason; anything else lost the stream.
          const refused = error instanceof AskRefused;
          const failure = {
            event: "error" as const, kind: refused ? "refused" as const : "network" as const,
            message: refused ? error.reason : String(error), sql: null, error: null, trace_id: last.events.at(-1)?.trace_id ?? "",
          };
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
    [api, loadThread, navigate, now, putThread, refresh, chosenPack, pack],
  );

  const stop = useCallback((conversationId?: string) => {
    const target = conversationId ?? busyRef.current;
    if (target) void api.chat.stop(target).catch(() => undefined);
    if (!conversationId || conversationId === busyRef.current) controller.current?.abort();
  }, [api]);

  const value = useMemo<ChatState>(
    () => ({
      api, sources, identity, refused, pack, conversations, groups, loaded, activeId, now, navigate, refresh,
      threads, busy, loadThread, ask, stop, chosenPack, choosePack,
    }),
    [api, sources, identity, refused, pack, conversations, groups, loaded, activeId, now, navigate, refresh, threads, busy, loadThread, ask, stop, chosenPack, choosePack],
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
