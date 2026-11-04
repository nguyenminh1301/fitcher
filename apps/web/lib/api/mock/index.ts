// The sample implementation of every feature. Data comes from the active pack's sample_data; changes
// (approvals, role changes, uploads) live in memory for the page's lifetime, and demo conversations in
// browser storage, so each feature behaves as it will once its api exists.

import { readStored, writeStored } from "@/lib/storage";

import type { FitcherApi } from "../client";
import type { DocumentRow, EvalReport, Identity, ReviewItem } from "../provisional";
import { createMockChat } from "./chat";
import { createMockConversations } from "./conversations";
import { sampleLoader, type SampleStatus } from "./load";

const IDENTITY_KEY = "fitcher.demo.identity";

export type MockApi = FitcherApi & { sampleStatus(): Promise<SampleStatus> };

function delay<T>(value: T, ms = 150): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

/** ``identity`` replaces the demo identities with the signed-in user once sign-in is real. */
export function createMockApi(options: { latencyMs?: number; identity?: () => Promise<Identity | null> } = {}): MockApi {
  const load = sampleLoader();
  const wait = <T>(value: T) => delay(value, options.latencyMs ?? 0);
  let current: Identity | null = null;

  async function identity(): Promise<Identity | null> {
    if (options.identity) return options.identity();
    if (current) return current;
    const { console } = await load();
    const stored = readStored(IDENTITY_KEY);
    current = console.identities.find((item) => item.user_id === stored) ?? console.identities[0] ?? null;
    return current;
  }

  function find<T extends { id: string }>(items: T[], id: string): T {
    const item = items.find((candidate) => candidate.id === id);
    if (!item) throw new Error(`no sample item ${id}`);
    return item;
  }

  return {
    sampleStatus: async () => (await load()).status,
    auth: {
      identities: async () => wait((await load()).console.identities),
      current: async () => wait(await identity()),
      switchTo: async (userId) => {
        const next = (await load()).console.identities.find((item) => item.user_id === userId);
        if (!next) throw new Error(`no demo identity ${userId}`);
        current = next;
        writeStored(IDENTITY_KEY, userId);
        return next;
      },
      pack: async () => {
        const { console } = await load();
        return { ...console.pack, roles: console.pack_roles };
      },
      signOut: async () => "/sign-in",
    },
    chat: createMockChat(load, identity),
    conversations: createMockConversations(load, identity),
    feedback: { send: async () => wait(undefined) },
    datasets: { list: async () => wait((await load()).console.datasets) },
    review: {
      items: async () => wait((await load()).console.review_items),
      update: async (id, patch) => {
        Object.assign(find((await load()).console.review_items, id), patch);
      },
      approve: async (id) => {
        find((await load()).console.review_items, id).status = "approved";
      },
      remove: async (id) => {
        const state = (await load()).console;
        state.review_items = state.review_items.filter((item) => item.id !== id);
      },
      testRun: async (id): Promise<ReviewItem> => delay(find((await load()).console.review_items, id), 900),
    },
    documents: {
      list: async () => wait((await load()).console.documents),
      upload: async (file, roles) => {
        const state = (await load()).console;
        const row: DocumentRow = {
          id: `doc-${Date.now()}`, name: file.name, size: file.size, status: "processing", roles,
          uploaded_at: new Date().toISOString(),
        };
        state.documents = [row, ...state.documents];
        setTimeout(() => (row.status = "indexed"), 2500);
        return row;
      },
      remove: async (id) => {
        const state = (await load()).console;
        state.documents = state.documents.filter((item) => item.id !== id);
      },
      setRoles: async (id, roles) => {
        find((await load()).console.documents, id).roles = roles;
      },
      draft: async () => delay(undefined, 1200),
    },
    feedbackReview: {
      list: async () => wait((await load()).console.feedback),
      propose: async (traceId) => {
        const row = (await load()).console.feedback.find((item) => item.trace_id === traceId);
        if (row) row.proposal = "proposed";
      },
    },
    evaluation: {
      reports: async () => wait((await load()).console.eval_reports),
      report: async (id) => wait((await load()).console.eval_reports.find((report) => report.id === id) ?? null),
      start: async (): Promise<EvalReport> => {
        const state = (await load()).console;
        const latest = state.eval_reports[0];
        const report = { ...latest, id: `eval-${Date.now()}`, ts: new Date().toISOString() };
        state.eval_reports = [report, ...state.eval_reports];
        return delay(report, 2500);
      },
    },
    runs: {
      list: async () => wait((await load()).console.runs),
      trace: async (traceId) => {
        const { console } = await load();
        const run = console.runs.find((item) => item.trace_id === traceId);
        return wait(run ? { run, items: console.traces[traceId] ?? [] } : null);
      },
    },
    audit: { list: async () => wait((await load()).console.audit) },
    costs: { list: async () => wait((await load()).console.costs) },
    users: {
      list: async () => wait((await load()).console.users),
      setRoles: async (id, roles) => {
        find((await load()).console.users, id).roles = roles;
      },
      setEnabled: async (id, enabled) => {
        find((await load()).console.users, id).enabled = enabled;
      },
    },
    // The Models page has no sample data: it reads the gateway catalog and eval reports from the api.
    models: {
      list: () => Promise.reject(new Error("The Models page needs the api; it has no sample data.")),
      set: () => Promise.reject(new Error("The Models page needs the api; it has no sample data.")),
    },
  };
}
