// The user's conversations and groups from the api (Phase 8), through the web server's /api/conversations
// and /api/conversation-groups routes. The api stores every turn when it answers, so saving a thread here
// does nothing; a thread read back gives each question its language for the message bubble.

import type { ConversationThreadContract } from "@/lib/contracts";
import { langOf } from "@/lib/text";

import type { FitcherApi } from "../client";
import type { AskEvent } from "../events";

/** How many conversations the sidebar reads; the api keeps them for 90 days. */
export const LIST_LIMIT = 200;

/** The error for a refused api call, with the api's reason when it gave one. */
export async function refused(response: Response): Promise<Error> {
  let reason = "";
  try {
    const body = (await response.json()) as { detail?: unknown; error?: unknown };
    reason = typeof body.detail === "string" ? body.detail : typeof body.error === "string" ? body.error : "";
  } catch {
    // The body was not JSON; the status says enough.
  }
  return new Error(`The api answered ${response.status}${reason ? `: ${reason}` : ""}`);
}

export function createHttpConversations(fetcher: typeof fetch = (...args) => fetch(...args)): FitcherApi["conversations"] {
  async function send<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = init.body ? { "content-type": "application/json" } : undefined;
    const response = await fetcher(path, { ...init, headers });
    if (!response.ok) throw await refused(response);
    return (response.status === 204 ? undefined : await response.json()) as T;
  }
  const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });
  const conversation = (id: string) => `/api/conversations/${encodeURIComponent(id)}`;
  const group = (id: string) => `/api/conversation-groups/${encodeURIComponent(id)}`;

  return {
    list: () => send(`/api/conversations?limit=${LIST_LIMIT}`),
    search: (query) => send(`/api/conversations/search?q=${encodeURIComponent(query)}`),
    get: async (id) => {
      const response = await fetcher(conversation(id));
      if (response.status === 404) return null;
      if (!response.ok) throw await refused(response);
      const thread = (await response.json()) as ConversationThreadContract;
      return {
        conversation: thread.conversation,
        turns: thread.turns.map((turn) => ({ ...turn, question_lang: langOf(turn.question), events: turn.events as AskEvent[] })),
      };
    },
    save: async () => {},
    update: (id, patch) => send(conversation(id), json("PATCH", patch)),
    remove: (id) => send(conversation(id), { method: "DELETE" }),
    groups: () => send("/api/conversation-groups", { method: "GET" }),
    createGroup: (name) => send("/api/conversation-groups", json("POST", { name })),
    renameGroup: (id, name) => send(group(id), json("PATCH", { name })),
    removeGroup: (id) => send(group(id), { method: "DELETE" }),
  };
}

export const httpConversations = createHttpConversations();
