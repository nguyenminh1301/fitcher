// Demo conversations per demo identity, kept in browser storage (in memory when storage is blocked) and
// seeded from the pack's sample conversations, so the sidebar works before the conversation api exists.

import { readStored, storageAvailable, writeStored } from "@/lib/storage";
import { fold } from "@/lib/text";

import type { FitcherApi } from "../client";
import type { ConversationGroup, ConversationThread } from "../conversations";
import type { Identity } from "../provisional";
import type { SampleData } from "./load";

type Saved = { threads: ConversationThread[]; groups: ConversationGroup[] };

const memory = new Map<string, Saved>();

export function createMockConversations(load: () => Promise<SampleData>, identity: () => Promise<Identity | null>): FitcherApi["conversations"] {
  async function key(): Promise<string> {
    return `fitcher.demo.conversations.${(await identity())?.user_id ?? "anonymous"}`;
  }

  async function read(): Promise<Saved> {
    const storageKey = await key();
    // Memory stands in for browser storage only where storage does not work.
    const stored = storageAvailable() ? readStored(storageKey) : null;
    if (stored) return JSON.parse(stored) as Saved;
    if (!storageAvailable() && memory.has(storageKey)) return memory.get(storageKey) as Saved;
    return { threads: structuredClone((await load()).console.conversations), groups: [] };
  }

  async function write(saved: Saved): Promise<void> {
    const storageKey = await key();
    memory.set(storageKey, saved);
    writeStored(storageKey, JSON.stringify(saved));
  }

  async function change(edit: (saved: Saved) => void): Promise<void> {
    const saved = await read();
    edit(saved);
    await write(saved);
  }

  const newest = (saved: Saved) =>
    saved.threads.map((thread) => thread.conversation).sort((a, b) => b.updated_at.localeCompare(a.updated_at));

  return {
    list: async () => newest(await read()),
    search: async (query) => {
      const wanted = fold(query);
      const saved = await read();
      const hits = saved.threads.filter(
        (thread) => fold(thread.conversation.title).includes(wanted) || thread.turns.some((turn) => fold(turn.question).includes(wanted)),
      );
      return hits.map((thread) => thread.conversation).sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    },
    get: async (id) => (await read()).threads.find((thread) => thread.conversation.id === id) ?? null,
    save: (thread) =>
      change((saved) => {
        saved.threads = [thread, ...saved.threads.filter((item) => item.conversation.id !== thread.conversation.id)];
      }),
    update: (id, patch) =>
      change((saved) => {
        const thread = saved.threads.find((item) => item.conversation.id === id);
        if (thread) Object.assign(thread.conversation, patch);
      }),
    remove: (id) =>
      change((saved) => {
        saved.threads = saved.threads.filter((item) => item.conversation.id !== id);
      }),
    groups: async () => (await read()).groups,
    createGroup: async (name) => {
      const group = { id: `g-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`, name };
      await change((saved) => saved.groups.push(group));
      return group;
    },
    renameGroup: (id, name) =>
      change((saved) => {
        const group = saved.groups.find((item) => item.id === id);
        if (group) group.name = name;
      }),
    removeGroup: (id) =>
      change((saved) => {
        saved.groups = saved.groups.filter((item) => item.id !== id);
        for (const thread of saved.threads) if (thread.conversation.group_id === id) thread.conversation.group_id = null;
      }),
  };
}
