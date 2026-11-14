// The web app's whole view of the backend, one group per feature. Each feature has a sample
// implementation (lib/api/mock) and a real one (lib/api/http); lib/api/sources.ts picks per feature.

import type {
  AskRequest,
  ConversationPatch,
  DatasetView,
  DocumentList,
  DocumentView,
  DraftResult,
  AuditRow,
  CostRow,
  EvalReport,
  EvalRunStarted,
  FeedbackRow,
  ProposalResult,
  RunRow,
  TraceItem,
  NewUser,
  UserRow,
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
  SetupModeChange,
  SetupStatus,
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
    pack(): Promise<{ name: string; display_name: string; roles: string[] }>;
    /** Sign in with a local account; throws a SignInError when refused. */
    signIn(email: string, password: string): Promise<void>;
    /** Whether the sign-in page offers the OpenID Connect provider. */
    oidcEnabled(): Promise<boolean>;
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
    list(): Promise<RunRow[]>;
    trace(traceId: string): Promise<{ run: RunRow; items: TraceItem[] } | null>;
  };
  audit: { list(): Promise<AuditRow[]> };
  costs: { list(): Promise<CostRow[]> };
  users: {
    list(): Promise<UserRow[]>;
    setRoles(id: string, roles: string[]): Promise<void>;
    setEnabled(id: string, enabled: boolean): Promise<void>;
    create(user: NewUser): Promise<UserRow>;
    resetPassword(id: string, password: string): Promise<void>;
  };
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
  /** First-run setup (DECISIONS §15); the changes need the admin role. */
  setup: {
    status(): Promise<SetupStatus>;
    /** Choose who uses the instance; moving to team mode without an admin needs the first admin. */
    setMode(mode: SetupModeChange["mode"], admin?: NonNullable<SetupModeChange["admin"]>): Promise<SetupStatus>;
    skip(id: string): Promise<SetupStatus>;
    complete(): Promise<SetupStatus>;
  };
}

export type Feature = keyof FitcherApi;
