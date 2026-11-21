// The sample implementation of every feature. Data comes from the active pack's sample_data; changes
// (approvals, role changes, uploads) live in memory for the page's lifetime, and demo conversations in
// browser storage, so each feature behaves as it will once its api exists.

import { readStored, writeStored } from "@/lib/storage";

import type { FitcherApi } from "../client";
import type { DocumentView, EvalRunStarted, ReviewItem } from "@/lib/contracts";

import type { Identity, SampleDocument } from "../provisional";
import { createMockChat } from "./chat";
import { createMockConversations } from "./conversations";
import { sampleLoader, type SampleStatus } from "./load";

const IDENTITY_KEY = "fitcher.demo.identity";

export type MockApi = FitcherApi & { sampleStatus(): Promise<SampleStatus> };

/** A sample document as the api would list it; only the api knows its type, chunks and uploader. */
function documentView(row: SampleDocument): DocumentView {
  return { media_type: "", chunk_count: 0, blocked_chunks: 0, uploaded_by: "sample", ...row };
}

function delay<T>(value: T, ms = 150): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

/** ``identity`` replaces the demo identities with the signed-in user once sign-in is real. */
export function createMockApi(options: { latencyMs?: number; identity?: () => Promise<Identity | null> } = {}): MockApi {
  const load = sampleLoader();
  const wait = <T>(value: T) => delay(value, options.latencyMs ?? 0);
  let current: Identity | null = null;
  let documentsEnabled = true;

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
      // The sample data has one pack, so choosing a source keeps it.
      choosePack: async () => {
        const { console } = await load();
        return { ...console.pack, roles: console.pack_roles };
      },
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
        const approved = find((await load()).console.review_items, id);
        approved.status = "approved";
        if (approved.reviewed === false) approved.reviewed = true;
      },
      remove: async (id) => {
        const state = (await load()).console;
        state.review_items = state.review_items.filter((item) => item.id !== id);
      },
      testRun: async (id): Promise<ReviewItem> => delay(find((await load()).console.review_items, id), 900),
    },
    documents: {
      list: async () => wait({ compiling: false, documents: (await load()).console.documents.map(documentView) }),
      upload: async (file, roles) => {
        const state = (await load()).console;
        const row: SampleDocument = {
          id: `doc-${Date.now()}`, name: file.name, size: file.size, status: "processing", roles,
          uploaded_at: new Date().toISOString(),
        };
        state.documents = [row, ...state.documents];
        setTimeout(() => (row.status = "indexed"), 2500);
        return documentView(row);
      },
      remove: async (id) => {
        const state = (await load()).console;
        state.documents = state.documents.filter((item) => item.id !== id);
      },
      setRoles: async (id, roles) => {
        find((await load()).console.documents, id).roles = roles;
      },
      draft: async () => delay({ added: [], updated: [], skipped_approved: [] }, 1200),
      settings: async () => wait({ enabled: documentsEnabled, documents: (await load()).console.documents.length }),
      setEnabled: async (enabled) => {
        documentsEnabled = enabled;
        return { enabled, documents: (await load()).console.documents.length };
      },
    },
    feedbackReview: {
      list: async () => wait((await load()).console.feedback),
      propose: async (traceId) => {
        const row = (await load()).console.feedback.find((item) => item.trace_id === traceId);
        if (row) row.proposal = "proposed";
        return { proposed: !!row, proposal_id: row ? `p-${traceId}` : null, question: row?.question ?? null,
          reason: row ? null : "run not found" };
      },
    },
    evaluation: {
      reports: async () => wait((await load()).console.eval_reports),
      report: async (id) => wait((await load()).console.eval_reports.find((report) => report.id === id) ?? null),
      start: async (): Promise<EvalRunStarted> => {
        const state = (await load()).console;
        const latest = state.eval_reports[0];
        const report = { ...latest, id: `eval-${Date.now()}`, ts: new Date().toISOString() };
        state.eval_reports = [report, ...state.eval_reports];
        return delay({ pack: state.pack.name, running: true }, 2500);
      },
    },
    runs: {
      list: async (query) => wait((query?.page ?? 1) > 1 ? [] : (await load()).console.runs),
      trace: async (traceId) => {
        const { console } = await load();
        const run = console.runs.find((item) => item.trace_id === traceId);
        return wait(run ? { run, items: console.traces[traceId] ?? [] } : null);
      },
    },
    audit: { list: async () => wait((await load()).console.audit), screening: async () => wait([]) },
    costs: { list: async () => wait((await load()).console.costs) },
    // The Models page has no sample data: providers, keys and tiers live in the instance's app state.
    models: Object.fromEntries([
      "providers", "addProvider", "changeProvider", "removeProvider", "providerModels", "testProvider", "tiers", "setTier",
      "catalog", "setMode", "setEmbedding", "classifier", "setClassifier", "changeClassifier",
      "startClassifierDownload", "classifierDownload", "cancelClassifierDownload",
    ].map((name) => [name, () => Promise.reject(new Error("The Models page needs the api; it has no sample data."))])) as unknown as FitcherApi["models"],
    sources: Object.fromEntries([
      "list", "test", "create", "update", "remove", "tables", "changeTables", "sync", "cancel", "syncs", "upload", "loadFile",
      "drift", "instantEstimate", "instantStart", "instantJob",
    ].map((name) => [name, () => Promise.reject(new Error("The Sources page needs the api; it has no sample data."))])) as unknown as FitcherApi["sources"],
    // The demo has no owner password, so it never asks to sign in.
    owner: {
      status: async () => ({ password_set: false, signed_in: false, exposed: false }),
      limits: async () => ({ concurrent_questions: 2 }),
      setLimits: () => Promise.reject(new Error("The limits need the api; they have no sample data.")),
      signIn: () => Promise.reject(new Error("The owner password needs the api; it has no sample data.")),
      signOut: async () => undefined,
      setPassword: () => Promise.reject(new Error("The owner password needs the api; it has no sample data.")),
      removePassword: () => Promise.reject(new Error("The owner password needs the api; it has no sample data.")),
    },
    // The demo is an instance that was set up already, so it never redirects to the setup.
    setup: {
      status: async () => ({
        steps: [{ id: "models", state: "done" }, { id: "data", state: "done" }], complete: true,
      }),
      skip: () => Promise.reject(new Error("The setup needs the api; it has no sample data.")),
      complete: () => Promise.reject(new Error("The setup needs the api; it has no sample data.")),
    },
  };
}
