import { describe, expect, it, vi } from "vitest";

import { createHttpConversations } from "@/lib/api/http/conversations";

const CONVERSATION = { id: "c1", title: "Doanh thu quý 1", pinned: false, group_id: null, updated_at: "2026-11-03T08:00:00Z" };
const T = { trace_id: "t".repeat(32) };

function client(body: unknown = [], status = 200) {
  const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
    void init;
    return status === 204 ? new Response(null, { status }) : Response.json(body, { status });
  });
  return { fetcher, conversations: createHttpConversations(fetcher) };
}

const call = (fetcher: ReturnType<typeof client>["fetcher"], index = 0) => {
  const [url, init] = fetcher.mock.calls[index];
  return { url: String(url), method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body as string) : undefined };
};

describe("http conversations", () => {
  it("lists and searches the user's conversations", async () => {
    const { fetcher, conversations } = client([CONVERSATION]);

    expect(await conversations.list()).toEqual([CONVERSATION]);
    expect(await conversations.search("doanh thu")).toEqual([CONVERSATION]);

    expect(call(fetcher, 0).url).toBe("/api/conversations?limit=200");
    expect(call(fetcher, 1).url).toBe("/api/conversations/search?q=doanh%20thu");
  });

  it("reads a thread, giving each question its language", async () => {
    const turn = { turn: 1, revision: 2, question: "Doanh thu quý 1 năm 2025", events: [{ ...T, event: "done" }] };
    const { fetcher, conversations } = client({ conversation: CONVERSATION, turns: [turn] });

    const thread = await conversations.get("c 1");

    expect(call(fetcher).url).toBe("/api/conversations/c%201");
    expect(thread).toEqual({ conversation: CONVERSATION, turns: [{ ...turn, question_lang: "vi" }] });
  });

  it("returns no thread for a conversation the api does not know", async () => {
    const { conversations } = client({ detail: "conversation not found" }, 404);

    expect(await conversations.get("gone")).toBeNull();
  });

  it("changes, deletes and groups conversations with the api's methods", async () => {
    const { fetcher, conversations } = client({ id: "g1", name: "Sales" });

    await conversations.update("c1", { pinned: true, group_id: null });
    await conversations.remove("c1");
    expect(await conversations.createGroup("Sales")).toEqual({ id: "g1", name: "Sales" });
    await conversations.renameGroup("g1", "Sales 2025");
    await conversations.removeGroup("g1");
    await conversations.groups();

    expect([0, 1, 2, 3, 4, 5].map((index) => call(fetcher, index))).toEqual([
      { url: "/api/conversations/c1", method: "PATCH", body: { pinned: true, group_id: null } },
      { url: "/api/conversations/c1", method: "DELETE", body: undefined },
      { url: "/api/conversation-groups", method: "POST", body: { name: "Sales" } },
      { url: "/api/conversation-groups/g1", method: "PATCH", body: { name: "Sales 2025" } },
      { url: "/api/conversation-groups/g1", method: "DELETE", body: undefined },
      { url: "/api/conversation-groups", method: "GET", body: undefined },
    ]);
  });

  it("leaves storing turns to the api", async () => {
    const { fetcher, conversations } = client();

    await conversations.save({ conversation: CONVERSATION, turns: [] });

    expect(fetcher).not.toHaveBeenCalled();
  });

  it("says why the api refused a change", async () => {
    const { conversations } = client({ detail: "group not found" }, 404);

    await expect(conversations.update("c1", { group_id: "theirs" })).rejects.toThrow("404: group not found");
  });
});
