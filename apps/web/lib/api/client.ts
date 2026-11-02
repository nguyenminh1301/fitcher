// The web app's whole view of the backend, one group per feature. Each feature has a sample
// implementation (lib/api/mock) and a real one (lib/api/http); lib/api/sources.ts picks per feature.

import type {
  AskEvent,
  AskRequest,
  AuditRow,
  Conversation,
  ConversationGroup,
  ConversationThread,
  CostRow,
  DatasetView,
  DocumentRow,
  EvalReport,
  FeedbackInput,
  FeedbackRow,
  Identity,
  ReviewItem,
  RunRow,
  TraceItem,
  UserRow,
} from "./provisional";

export type ConversationPatch = Partial<Pick<Conversation, "title" | "pinned" | "group_id">>;

export interface FitcherApi {
  auth: {
    identities(): Promise<Identity[]>;
    current(): Promise<Identity | null>;
    switchTo(userId: string): Promise<Identity>;
    pack(): Promise<{ name: string; display_name: string; roles: string[] }>;
  };
  chat: {
    ask(request: AskRequest, signal: AbortSignal): AsyncIterable<AskEvent>;
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
    update(id: string, patch: Partial<Pick<ReviewItem, "body" | "formula">>): Promise<void>;
    approve(id: string): Promise<void>;
    remove(id: string): Promise<void>;
    testRun(id: string): Promise<ReviewItem>;
  };
  documents: {
    list(): Promise<DocumentRow[]>;
    upload(file: { name: string; size: number }, roles: string[]): Promise<DocumentRow>;
    remove(id: string): Promise<void>;
    setRoles(id: string, roles: string[]): Promise<void>;
    draft(id: string): Promise<void>;
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
}

export type Feature = keyof FitcherApi;
