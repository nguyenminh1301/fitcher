// The chat against the api (Phase 7): POST /api/ask streams the events of DECISIONS §6, parsed from the
// server-sent event stream. Stop aborts the request, which ends the run on the api, and the answer
// ends with a stopped notice. A request without a conversation id starts one; the api names it in the
// X-Conversation-Id header, which ``onConversation`` receives before the first event.

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
  return {
    async *ask(request, signal, onConversation) {
      let trace = "";
      const stopped = (): AskEvent => ({ event: "error", kind: "stopped", message: "stopped", sql: null, error: null, trace_id: trace });
      let response: Response;
      try {
        response = await fetcher("/api/ask", {
          method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(request), signal,
        });
      } catch (error) {
        if (!signal.aborted) throw error;
        yield stopped();
        return;
      }
      if (!response.ok || !response.body) throw new Error(await refusal(response));
      const started = response.headers.get("x-conversation-id");
      if (started) onConversation?.(started);
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
    // A hand-written pack keeps its suggested questions with its sample data; a pack built from a source has none,
    // so the api offers its first example questions (DECISIONS §11 step 0). The answers always come from the api.
    suggestions: async () => {
      const response = await fetcher("/api/sample/scenarios");
      const sample = response.ok ? ((await response.json()) as ScenarioFile).suggestions : [];
      if (sample.length) return sample;
      const generated = await fetcher("/api/pack/suggestions", { cache: "no-store" });
      return generated.ok ? ((await generated.json()) as { text: string; lang: string }[]) : [];
    },
  };
}

export const httpChat = createHttpChat();
