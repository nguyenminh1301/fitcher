import { cleanup, configure, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { AuditSection } from "@/components/console/sections/AuditSection";
import { CostsSection } from "@/components/console/sections/CostsSection";
import { DatasetsSection } from "@/components/console/sections/DatasetsSection";
import { DocumentsSection } from "@/components/console/sections/DocumentsSection";
import { EvaluationReport, EvaluationSection } from "@/components/console/sections/EvaluationSection";
import { FeedbackSection } from "@/components/console/sections/FeedbackSection";
import { ReviewDetail, ReviewSection } from "@/components/console/sections/ReviewSection";
import { RunDetail, RunsSection } from "@/components/console/sections/RunsSection";
import { UsersSection } from "@/components/console/sections/UsersSection";
import { createMockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import { FEATURES, type Sources } from "@/lib/api/sources";
import { ChatProvider } from "@/lib/chat/ChatContext";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

vi.mock("@/components/chat/ChartView", () => ({ ChartView: () => null }));

configure({ asyncUtilTimeout: 4000 });

const CONSOLE: Partial<ConsoleFile> = {
  pack: { name: "shop", display_name: "Shop" },
  pack_roles: ["analyst"],
  identities: [{ user_id: "both", display_name: "Bo Both", roles: ["pack_reviewer", "admin"] }],
  conversations: [],
  review_items: [{ id: "i1", file: "glossary.yaml", name: "term_one", kind: "item", status: "draft", confidence: 0.9, body: "A definition." }],
  eval_reports: [{ id: "e1", ts: "2026-11-02T13:40:00Z", passed: true, threshold: 0.8, layers: {}, categories: {}, failed_cases: [] }],
  runs: [{ trace_id: "t1", ts: "2026-11-02T08:15:00Z", user_id: "ana", role: "analyst", question: "Totals", status: "succeeded", latency_ms: 10, cost_usd: 0 }],
  traces: { t1: [] },
};

// Each console surface, with the section that frames it.
const SURFACES: [string, string, ReactNode][] = [
  ["review list", "review", <ReviewSection key="s" />],
  ["review item", "review", <ReviewDetail key="s" id="i1" />],
  ["documents", "documents", <DocumentsSection key="s" />],
  ["datasets", "datasets", <DatasetsSection key="s" />],
  ["feedback", "feedback", <FeedbackSection key="s" />],
  ["evaluation", "evaluation", <EvaluationSection key="s" />],
  ["evaluation report", "evaluation", <EvaluationReport key="s" id="e1" />],
  ["runs", "runs", <RunsSection key="s" />],
  ["run trace", "runs", <RunDetail key="s" traceId="t1" />],
  ["audit", "audit", <AuditSection key="s" />],
  ["costs", "costs", <CostsSection key="s" />],
  ["users", "users", <UsersSection key="s" />],
];

function show(section: string, page: ReactNode, sources?: Partial<Sources>) {
  window.localStorage.setItem("fitcher.demo.identity", "both");
  render(
    <ThemeProvider>
      <I18nProvider initial="en">
        <ChatProvider api={createMockApi()} navigate={vi.fn()} activeId={null} sources={sources}>
          <ConsoleLayout section={section} navigate={vi.fn()} onChat={vi.fn()}>{page}</ConsoleLayout>
        </ChatProvider>
      </I18nProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url.endsWith("/console") ? new Response(JSON.stringify(CONSOLE)) : new Response(JSON.stringify({ suggestions: [], scenarios: [] }))));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Sample data badge in the console", () => {
  it.each(SURFACES)("marks the %s page while its feature runs on sample data", async (_name, section, page) => {
    show(section, page, Object.fromEntries(FEATURES.map((feature) => [feature, "mock"])) as Sources);

    expect(await screen.findByText("Sample data")).toBeTruthy();
  });

  it.each(SURFACES)("leaves the %s page unmarked once its feature uses the api", async (_name, section, page) => {
    // The page still loads through the sample api here; only the sources map says the features are real.
    show(section, page, Object.fromEntries(FEATURES.map((feature) => [feature, "http"])) as Sources);

    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText("Sample data")).toBeNull();
  });
});
