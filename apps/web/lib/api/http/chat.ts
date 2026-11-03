// The chat against the api (Phase 7): POST /api/ask streams the events of DECISIONS §6, parsed from the
// server-sent event stream. Stop aborts the request, which ends the run on the api, and the answer
// ends with a stopped notice.
//
// Conversations are still kept in the browser (sample data) and carry the browser's own ids, which the
// api does not know. A chat's first question starts an api conversation; its X-Conversation-Id is kept
// for this page so the chat's follow-ups continue it. The conversation endpoints replace this mapping.

import { parseStream } from "@/lib/sse/parseStream";
import type { StreamEvent } from "@/lib/contracts";

import type { FitcherApi } from "../client";
import type { AskEvent } from "../events";
import type { ScenarioFile } from "../provisional";

/** Why the api did not start an answer, from its JSON error body. */
async function refusal(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown; error?: unknown };
    const reason = typeof body.detail === "string" ? body.detail : typeof body.error === "string" ? body.error : "";
    return `The api answered ${response.status}${reason ? `: ${reason}` : ""}`;
  } catch {
    return `The api answered ${response.status}`;
  }
}

export function createHttpChat(fetcher: typeof fetch = (...args) => fetch(...args)): FitcherApi["chat"] {
  // The browser's conversation id -> the api's.
  const apiConversations = new Map<string, string>();
  return {
    async *ask(request, signal) {
      let trace = "";
      const stopped = (): AskEvent => ({ event: "error", kind: "stopped", message: "stopped", sql: null, error: null, trace_id: trace });
      const local = request.conversation_id ?? null;
      const body = { ...request, conversation_id: local ? (apiConversations.get(local) ?? null) : null };
      let response: Response;
      try {
        response = await fetcher("/api/ask", {
          method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal,
        });
      } catch (error) {
        if (!signal.aborted) throw error;
        yield stopped();
        return;
      }
      if (!response.ok || !response.body) throw new Error(await refusal(response));
      const started = response.headers.get("x-conversation-id");
      if (local && started) apiConversations.set(local, started);
      try {
        for await (const frame of parseStream(response.body)) {
          const event = JSON.parse(frame.data) as StreamEvent;
          trace = event.trace_id;
          yield event;
          if (event.event === "done" || event.event === "error") return;
        }
      } catch (error) {
        if (!signal.aborted) throw error;
      }
      if (signal.aborted) {
        yield stopped();
        return;
      }
      throw new Error("The answer stream ended before the answer was complete.");
    },
    // The pack's suggested questions are pack content kept with its sample data; the answers come from the api.
    suggestions: async () => {
      const response = await fetcher("/api/sample/scenarios");
      return response.ok ? ((await response.json()) as ScenarioFile).suggestions : [];
    },
  };
}

export const httpChat = createHttpChat();
