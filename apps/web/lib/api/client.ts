// The web app's whole view of the backend, one group per feature. Each feature has a sample
// implementation (lib/api/mock) and a real one (lib/api/http); lib/api/sources.ts picks per feature.

import type {
  AskRequest,
  ConversationPatch,
  DatasetView,
  DocumentList,
  DocumentSettings,
  DocumentView,
  DraftResult,
  AuditRow,
  CostRow,
  EvalReport,
  EvalRunStarted,
  FeedbackRow,
  FileLoad,
  InstantEstimate,
  InstantEstimateRequest,
  InstantJobReply,
  InstantRequest,
  FileUploadView,
  ProbeResult,
  ProposalResult,
  RunRow,
  TraceItem,
  FeedbackInput,
  ClassifierStatus,
  EmbeddingChange,
  EmbeddingView,
  ModelTiersView,
  ProviderCreate,
  ProviderModels,
  ProviderTestResult,
  ProviderUpdate,
  ProviderView,
  TierChange,
  TierView,
  ReviewItem,
  ReviewItemPatch,
  SetupStatus,
  OwnerStatus,
  SourceConnection,
  SourceCreate,
  SourceDetail,
  SourceDrift,
  SourcePatch,
  SourceView,
  SyncView,
  TableView,
  TablesChange,
} from "@/lib/contracts";

import type { Conversation, ConversationGroup, ConversationThread } from "./conversations";
import type { AskEvent } from "./events";
import type { Identity } from "./provisional";

export type { ConversationPatch } from "@/lib/contracts";

export interface FitcherApi {
  auth: {
    identities(): Promise<Identity[]>;
    current(): Promise<Identity | null>;
    switchTo(userId: string): Promise<Identity>;
    /** The active pack, or null while no pack is active (a new instance before its first pack is built). */
    pack(): Promise<{ name: string; display_name: string; roles: string[] } | null>;
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
    /** Whether company documents are on, and how many the active pack keeps. */
    settings(): Promise<DocumentSettings>;
    /** Turn documents on or off (admin); off while documents are kept is refused without ``confirm``. */
    setEnabled(enabled: boolean, confirm?: boolean): Promise<DocumentSettings>;
  };
  feedbackReview: {
    list(): Promise<FeedbackRow[]>;
    /** Propose an example from one run; the answer says why when the run is not eligible. */
    propose(traceId: string): Promise<ProposalResult>;
  };
  evaluation: {
    reports(): Promise<EvalReport[]>;
    report(id: string): Promise<EvalReport | null>;
    /** Start a run of the active pack's eval set in the background; it uses paid AI. */
    start(): Promise<EvalRunStarted>;
  };
  runs: {
    /** Runs newest first, 50 a page; ``from`` and ``to`` are ISO days and ``to`` is exclusive. */
    list(query?: { from?: string; to?: string; page?: number }): Promise<RunRow[]>;
    trace(traceId: string): Promise<{ run: RunRow; items: TraceItem[] } | null>;
  };
  audit: { list(): Promise<AuditRow[]> };
  costs: { list(): Promise<CostRow[]> };
  /** Model providers, the tier mapping, the embedding and the optional screening classifier (admin only). */
  models: {
    providers(): Promise<ProviderView[]>;
    addProvider(body: ProviderCreate): Promise<ProviderView>;
    changeProvider(id: string, body: ProviderUpdate): Promise<ProviderView>;
    removeProvider(id: string): Promise<void>;
    providerModels(id: string): Promise<ProviderModels>;
    /** Lists the provider's models, then asks one of them for a small structured reply (billed by a hosted provider). */
    testProvider(id: string, model?: string): Promise<ProviderTestResult>;
    tiers(): Promise<ModelTiersView>;
    /** Map a chat tier to any model of a configured provider. */
    setTier(tier: string, change: TierChange): Promise<TierView>;
    /** Change the embedding model; the api refuses it unless ``confirm_reindex`` is set. */
    setEmbedding(change: EmbeddingChange): Promise<EmbeddingView>;
    classifier(): Promise<ClassifierStatus>;
    setClassifier(enabled: boolean): Promise<ClassifierStatus>;
  };
  /** Data sources (DECISIONS §4, §15): an admin connects, tests, edits, deletes and syncs them. No call returns a password. */
  sources: {
    list(): Promise<SourceView[]>;
    /** Test a connection and list its tables with sizes and the proposed mode; nothing is saved. */
    test(body: SourceConnection): Promise<ProbeResult>;
    create(body: SourceCreate): Promise<SourceDetail>;
    update(id: string, body: SourcePatch): Promise<SourceDetail>;
    /** Delete a source after confirming its name; the api refuses while a mart reads it. */
    remove(id: string, confirm: string): Promise<void>;
    tables(id: string, refresh?: boolean): Promise<TableView[]>;
    changeTables(id: string, change: TablesChange): Promise<TableView[]>;
    sync(id: string): Promise<SyncView>;
    cancel(id: string): Promise<SyncView>;
    syncs(id: string): Promise<SyncView[]>;
    upload(file: File): Promise<FileUploadView>;
    loadFile(id: string, body: FileLoad): Promise<SourceDetail>;
    /** Columns added, removed or retyped since the source's instant pack was built; refresh reads the catalog again. */
    drift(id: string, refresh?: boolean): Promise<SourceDrift>;
    /** The draft's prompt size and whether a model can draft, before anything runs (DECISIONS §11 step 0). */
    instantEstimate(body: InstantEstimateRequest): Promise<InstantEstimate>;
    /** Build a pack from the chosen tables; the draft is a paid call, so ``confirm_billable`` must be set. */
    instantStart(body: InstantRequest): Promise<InstantJobReply>;
    instantJob(id: string): Promise<InstantJobReply>;
  };
  /** The optional owner password (DECISIONS §9): its status, signing in and out, setting and removing it. */
  owner: {
    status(): Promise<OwnerStatus>;
    /** Throws an OwnerSignInError when the password is wrong or too many attempts failed. */
    signIn(password: string): Promise<void>;
    signOut(): Promise<void>;
    /** Set the password, or change it with the current one; signs this browser in. */
    setPassword(newPassword: string, currentPassword?: string): Promise<void>;
    removePassword(currentPassword: string): Promise<void>;
  };
  /** First-run setup (DECISIONS §15); the changes need the admin role. */
  setup: {
    status(): Promise<SetupStatus>;
    skip(id: string): Promise<SetupStatus>;
    complete(): Promise<SetupStatus>;
  };
}

export type Feature = keyof FitcherApi;
