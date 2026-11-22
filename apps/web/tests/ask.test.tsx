import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMockChat } from "@/lib/api/mock/chat";
import { createMockConversations } from "@/lib/api/mock/conversations";
import { EMPTY_CONSOLE, type SampleData } from "@/lib/api/mock/load";
import type { FitcherApi } from "@/lib/api/client";
import { AskRefused } from "@/lib/api/http/chat";
import type { Identity, Scenario } from "@/lib/api/provisional";
import { ChatProvider, useChat, type ChatState } from "@/lib/chat/ChatContext";

const SCENARIO: Scenario = {
  id: "top", lang: "en", match: { any: ["top"] }, allowed_roles: ["analyst"], kind: "answer", question: "top", sql: "SELECT 1",
  result: { columns: [{ name: "v", type: "number", role: "measure" }], rows: [[1]], row_count: 1 }, summary: "One.", warnings: [],
  deny_message: "No.", blocked: [],
};
const IDENTITY: Identity = { user_id: "ana", display_name: "Ana", roles: ["analyst"] };

function api(stepMs = 0, overrides: Partial<{ pack: FitcherApi["auth"]["pack"]; chat: FitcherApi["chat"] }> = {}): FitcherApi {
  const data: SampleData = { console: { ...EMPTY_CONSOLE,}, scenarios: { suggestions: [], scenarios: [SCENARIO] }, status: "ok" };
  const load = async () => data;
  const identity = async () => IDENTITY;
  return {
    auth: { current: identity, identities: async () => [IDENTITY], switchTo: identity, pack: overrides.pack ?? (async () => ({ name: "shop", display_name: "Shop", roles: ["analyst"] })) },
    chat: overrides.chat ?? createMockChat(load, identity, { stepMs }),
    conversations: createMockConversations(load, identity),
  } as unknown as FitcherApi;
}

let state: ChatState;
function Probe() {
  state = useChat();
  return null;
}

function setup(stepMs = 0, overrides: Parameters<typeof api>[1] = {}) {
  const navigate = vi.fn();
  render(
    <ChatProvider api={api(stepMs, overrides)} navigate={navigate} activeId={null}>
      <Probe />
    </ChatProvider>,
  );
  return { navigate };
}

beforeEach(() => window.localStorage.clear());
afterEach(cleanup);

describe("asking a question", () => {
  it("starts a conversation titled by the question, opens it and streams the answer into its turn", async () => {
    const { navigate } = setup();
    await waitFor(() => expect(state.loaded).toBe(true));
    const question = `top ${"x".repeat(100)}`;

    let id = "";
    await act(async () => {
      id = await state.ask(question);
    });

    expect(navigate).toHaveBeenCalledWith(id);
    await waitFor(() => expect(state.threads[id]?.turns[0].events.at(-1)?.event).toBe("done"));
    expect(state.conversations[0]).toMatchObject({ id, title: question.slice(0, 80) });
    expect(state.busy).toBeNull();
    expect((await state.api.conversations.get(id))?.turns[0].events.at(-1)?.event).toBe("done");
  });

  it("loads the identity and conversations when no pack is active yet", async () => {
    setup(0, { pack: async () => null });

    await waitFor(() => expect(state.loaded).toBe(true));
    expect(state.identity).toEqual(IDENTITY);
    expect(state.pack).toBeNull();
  });

  it("ends a question the api refused with its reason rather than a lost connection", async () => {
    const refusing = {
      async *ask() { throw new AskRefused(503, "no pack is active"); },
      suggestions: async () => [],
    } as unknown as FitcherApi["chat"];
    setup(0, { chat: refusing });
    await waitFor(() => expect(state.loaded).toBe(true));

    let id = "";
    await act(async () => {
      id = await state.ask("top");
    });

    await waitFor(() => expect(state.threads[id]?.turns[0].events.at(-1)).toMatchObject({ event: "error", kind: "refused", message: "no pack is active" }));
  });

  it("stops the running answer", async () => {
    setup(40);
    await waitFor(() => expect(state.loaded).toBe(true));

    let id = "";
    await act(async () => {
      id = await state.ask("top");
    });
    act(() => state.stop());

    await waitFor(() => expect(state.threads[id]?.turns[0].events.at(-1)).toMatchObject({ event: "error", kind: "stopped" }));
    expect(state.busy).toBeNull();
  });

  it("follows a question the api is still answering after the page was left, until its answer is stored", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const answering = { conversation: { id: "c1", title: "top", pinned: false, group_id: null, updated_at: "2026-11-20T08:00:00Z", pack: "shop" },
      turns: [{ turn: 1, revision: 1, question: "top", question_lang: "en", events: [] }], running: true };
    const answered = { ...answering, running: false, turns: [{ ...answering.turns[0], events: [{ event: "done" as const, trace_id: "t" }] }] };
    const get = vi.fn().mockResolvedValueOnce(answering).mockResolvedValueOnce(answering).mockResolvedValue(answered);
    const stop = vi.fn(async () => undefined);
    const base = api();
    const chat = { ...base.chat, stop };
    render(
      <ChatProvider api={{ ...base, chat, conversations: { ...base.conversations, get } } as FitcherApi} navigate={vi.fn()} activeId={null}>
        <Probe />
      </ChatProvider>,
    );
    await waitFor(() => expect(state.loaded).toBe(true));

    await act(async () => { await state.loadThread("c1"); });
    expect(state.threads.c1.running).toBe(true);
    act(() => state.stop("c1"));
    expect(stop).toHaveBeenCalledWith("c1");

    await act(async () => { await vi.advanceTimersByTimeAsync(4500); });
    await waitFor(() => expect(state.threads.c1.running).toBe(false));
    expect(state.threads.c1.turns[0].events).toEqual([{ event: "done", trace_id: "t" }]);
    vi.useRealTimers();
  });

  it("ignores a second question while one is running", async () => {
    setup(40);
    await waitFor(() => expect(state.loaded).toBe(true));
    let id = "";
    await act(async () => {
      id = await state.ask("top");
    });

    await act(async () => {
      await state.ask("top again", { conversationId: id });
    });

    expect(state.threads[id].turns).toHaveLength(1);
    // The first answer is still streaming; let it finish before the test environment is torn down.
    await waitFor(() => expect(state.busy).toBeNull());
  });

  it("editing a question replaces that turn and drops the turns after it", async () => {
    setup();
    await waitFor(() => expect(state.loaded).toBe(true));
    let id = "";
    await act(async () => {
      id = await state.ask("top one");
    });
    await waitFor(() => expect(state.busy).toBeNull());
    await act(async () => {
      await state.ask("top two", { conversationId: id });
    });
    await waitFor(() => expect(state.busy).toBeNull());

    await act(async () => {
      await state.ask("top edited", { conversationId: id, editOf: 1 });
    });
    await waitFor(() => expect(state.busy).toBeNull());

    expect(state.threads[id].turns.map((turn) => [turn.turn, turn.revision, turn.question])).toEqual([[1, 2, "top edited"]]);
  });
});


describe("asking through the api", () => {
  function apiChat(conversationId: string) {
    const requests: unknown[] = [];
    const base = api();
    const chat: FitcherApi["chat"] = {
      suggestions: async () => [],
      stop: async () => undefined,
      async *ask(request, _signal, onConversation) {
        requests.push(request);
        onConversation?.(conversationId);
        yield { event: "done", trace_id: "t" };
      },
    };
    return { requests, api: { ...base, chat } as FitcherApi };
  }

  function mount(value: FitcherApi) {
    const navigate = vi.fn();
    render(
      <ChatProvider api={value} navigate={navigate} activeId={null}>
        <Probe />
      </ChatProvider>,
    );
    return navigate;
  }

  it("starts a conversation without an id and moves it to the id the api gave it", async () => {
    const { requests, api: value } = apiChat("api-1");
    const navigate = mount(value);
    await waitFor(() => expect(state.loaded).toBe(true));

    await act(async () => {
      await state.ask("top widgets");
    });

    await waitFor(() => expect(state.threads["api-1"]?.turns[0].events.at(-1)?.event).toBe("done"));
    expect(requests[0]).toMatchObject({ question: "top widgets", conversation_id: null, edit_of_turn: null, retry_of_turn: null });
    expect(navigate).toHaveBeenLastCalledWith("api-1");
    expect(state.threads["api-1"].conversation.id).toBe("api-1");
    expect(Object.keys(state.threads)).toEqual(["api-1"]);
  });

  it("sends an edit or a retry with its turn and the conversation", async () => {
    const { requests, api: value } = apiChat("api-1");
    mount(value);
    await waitFor(() => expect(state.loaded).toBe(true));
    await act(async () => {
      await state.ask("top widgets");
    });
    await waitFor(() => expect(state.busy).toBeNull());

    await act(async () => {
      await state.ask("top gadgets", { conversationId: "api-1", editOf: 1 });
    });
    await waitFor(() => expect(state.busy).toBeNull());
    await act(async () => {
      await state.ask("", { conversationId: "api-1", retryOf: 1 });
    });

    expect(requests[1]).toMatchObject({ question: "top gadgets", conversation_id: "api-1", edit_of_turn: 1, retry_of_turn: null });
    expect(requests[2]).toMatchObject({ question: "top gadgets", conversation_id: "api-1", edit_of_turn: null, retry_of_turn: 1 });
    await waitFor(() => expect(state.busy).toBeNull());
  });
});
