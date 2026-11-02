import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMockConversations } from "@/lib/api/mock/conversations";
import { EMPTY_CONSOLE, EMPTY_SCENARIOS, type SampleData } from "@/lib/api/mock/load";
import type { ConversationThread, Identity } from "@/lib/api/provisional";

const SEED: ConversationThread = {
  conversation: { id: "c1", title: "Doanh thu quý 1", pinned: false, group_id: null, updated_at: "2026-11-01T10:00:00Z" },
  turns: [{ turn: 1, revision: 1, question: "Doanh thu quý 1 so với năm ngoái?", question_lang: "vi", events: [] }],
};

function store(user = "u1") {
  const data: SampleData = { console: { ...EMPTY_CONSOLE, conversations: [SEED] }, scenarios: EMPTY_SCENARIOS, status: "ok" };
  const identity: Identity = { user_id: user, display_name: "Ana", roles: ["analyst"] };
  return createMockConversations(async () => data, async () => identity);
}

function thread(id: string, title: string): ConversationThread {
  return { conversation: { id, title, pinned: false, group_id: null, updated_at: new Date().toISOString() }, turns: [] };
}

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("demo conversations", () => {
  it("starts from the pack's sample conversations and survives a reload", async () => {
    await store().save(thread("c2", "Top brands"));

    const reloaded = store();
    expect((await reloaded.list()).map((item) => item.id)).toEqual(["c2", "c1"]);
  });

  it("renames, pins, groups and deletes", async () => {
    const conversations = store();
    const group = await conversations.createGroup("Quarterly");

    await conversations.update("c1", { title: "Q1 sales", pinned: true, group_id: group.id });
    let [item] = await conversations.list();
    expect(item).toMatchObject({ title: "Q1 sales", pinned: true, group_id: group.id });

    await conversations.removeGroup(group.id);
    [item] = await conversations.list();
    expect(item.group_id).toBeNull();

    await conversations.remove("c1");
    expect(await conversations.list()).toEqual([]);
  });

  it("searches titles and the user's questions, ignoring accents", async () => {
    expect((await store().search("nam ngoai")).map((item) => item.id)).toEqual(["c1"]);
    expect(await store().search("weather")).toEqual([]);
  });

  it("keeps each demo identity's conversations apart", async () => {
    await store("u1").save(thread("c2", "Mine"));

    expect((await store("u2").list()).map((item) => item.id)).toEqual(["c1"]);
  });

  it("works in memory when browser storage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const conversations = store();

    await conversations.save(thread("c2", "Kept in memory"));

    expect((await conversations.list()).map((item) => item.id)).toEqual(["c2", "c1"]);
  });
});
