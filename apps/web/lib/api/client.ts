// The web app's whole view of the backend, one group per feature. Each feature has a sample
// implementation (lib/api/mock) and a real one (lib/api/http); lib/api/sources.ts picks per feature.

import type {
  AskRequest,
  ConversationPatch,
  DatasetView,
  DocumentList,
  DocumentView,
  DraftResult,
  FeedbackInput,
  ModelTier,
  ModelTiers,
  ReviewItem,
  ReviewItemPatch,
} from "@/lib/contracts";

import type { Conversation, ConversationGroup, ConversationThread } from "./conversations";
import type { AskEvent } from "./events";
import type {
  AuditRow,
  CostRow,
  EvalReport,
  FeedbackRow,
  Identity,
  RunRow,
  TraceItem,
  UserRow,
} from "./provisional";

export type { ConversationPatch } from "@/lib/contracts";

export interface FitcherApi {
  auth: {
    identities(): Promise<Identity[]>;
    current(): Promise<Identity | null>;
    switchTo(userId: string): Promise<Identity>;
    pack(): Promise<{ name: string; display_name: string; roles: string[] }>;
    /** End the session; the address to open next. */
    signOut(): Promise<string>;
  };
  chat: {
    /** Stream an answer; ``onConversation`` learns the id the api gave a conversation the request started. */
    ask(request: AskRequest, signal: AbortSignal, onConversation?: (conversationId: string) => void): AsyncIterable<AskEvent>;
    suggestions(): Promise<{ text: string; lang: string }[]>;
  };
  conversations: {
    list(): Promise<Conversation[]>;
    search(query: string): Promise<Conversation[]>;
    get(id: string): Promise<ConversationThread | null>;
    save(thread: ConversationThread): Promise<void>;
    update(id: string, patch: ConversationPatch): Promise<void>;
    remove(id: string): Promise<void>;
    groups(): Promise<ConversationGroup[]>;
    createGroup(name: string): Promise<ConversationGroup>;
    renameGroup(id: string, name: string): Promise<void>;
    removeGroup(id: string): Promise<void>;
  };
  feedback: { send(input: FeedbackInput): Promise<void> };
  datasets: { list(): Promise<DatasetView[]> };
  review: {
    items(): Promise<ReviewItem[]>;
    /** Edit an item's text or formula; it returns to draft until approved again. */
    update(id: string, patch: ReviewItemPatch): Promise<void>;
    /** Approve an item; one with a formula is approved only after a clean test-run. */
    approve(id: string): Promise<void>;
    remove(id: string): Promise<void>;
    testRun(id: string): Promise<ReviewItem>;
  };
  documents: {
    /** The pack's documents, and whether it compiles, which blocks uploads and deletes. */
    list(): Promise<DocumentList>;
    upload(file: File, roles: string[]): Promise<DocumentView>;
    remove(id: string): Promise<void>;
    setRoles(id: string, roles: string[]): Promise<void>;
    /** Draft pack items from one indexed document; it uses paid AI. */
    draft(id: string): Promise<DraftResult>;
  };
  feedbackReview: {
    list(): Promise<FeedbackRow[]>;
    propose(traceId: string): Promise<void>;
  };
  evaluation: {
    reports(): Promise<EvalReport[]>;
    report(id: string): Promise<EvalReport | null>;
    start(): Promise<EvalReport>;
  };
  runs: {
    list(): Promise<RunRow[]>;
    trace(traceId: string): Promise<{ run: RunRow; items: TraceItem[] } | null>;
  };
  audit: { list(): Promise<AuditRow[]> };
  costs: { list(): Promise<CostRow[]> };
  users: {
    list(): Promise<UserRow[]>;
    setRoles(id: string, roles: string[]): Promise<void>;
    setEnabled(id: string, enabled: boolean): Promise<void>;
  };
  models: {
    list(): Promise<ModelTiers>;
    /** Map a chat tier to an eligible alias; the api refuses embed and any ineligible alias. */
    set(tier: string, alias: string): Promise<ModelTier>;
  };
}

export type Feature = keyof FitcherApi;
