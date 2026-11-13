import { act, cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { AuditSection } from "@/components/console/sections/AuditSection";
import { CostsSection } from "@/components/console/sections/CostsSection";
import { EvaluationSection } from "@/components/console/sections/EvaluationSection";
import { RunDetail, RunsSection } from "@/components/console/sections/RunsSection";
import { UsersSection } from "@/components/console/sections/UsersSection";
import { createMockApi, type MockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import { ChatProvider } from "@/lib/chat/ChatContext";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

// ECharts needs a real browser; these tests check what surrounds the chart.
vi.mock("@/components/chat/ChartView", () => ({ ChartView: () => null }));

configure({ asyncUtilTimeout: 4000 });

const CONSOLE: Partial<ConsoleFile> = {
  pack: { name: "shop", display_name: "Shop" },
  pack_roles: ["analyst", "viewer"],
  identities: [
    { user_id: "adm", display_name: "Ada Admin", roles: ["admin", "analyst"] },
    { user_id: "rev", display_name: "Rae Reviewer", roles: ["pack_reviewer", "analyst"] },
  ],
  conversations: [],
  eval_reports: [
    {
      id: "e2", ts: "2026-11-02T13:40:00Z", passed: true, threshold: 0.8,
      layers: {
        intent: { passed: 0, failed: 0, not_scored: 10 },
        extraction: { passed: 9, failed: 1, not_scored: 0 },
        retrieval: { passed: 10, failed: 0, not_scored: 0 },
        execution: { passed: 17, failed: 3, not_scored: 2 },
      },
      categories: { two_period_compare: "4/5", top_n: "2/3" },
      failed_cases: [{ case_id: "case_one", category: "top_n", reason: "expected 10 rows, got 4" }],
    },
    {
      id: "e1", ts: "2026-10-30T09:00:00Z", passed: false, threshold: 0.8,
      layers: { execution: { passed: 10, failed: 10, not_scored: 0 } }, categories: {}, failed_cases: [],
    },
  ],
  runs: [
    { trace_id: "t1", ts: "2026-11-02T08:15:00Z", user_id: "ana", role: "analyst", question: "Totals by month", intent: "data_query", status: "succeeded", latency_ms: 6420, cost_usd: 0.0042 },
    { trace_id: "t2", ts: "2026-11-02T09:15:00Z", user_id: "bo", role: "viewer", question: "Refunds in 2025", intent: "data_query", status: "denied", latency_ms: 900, cost_usd: 0.0004 },
  ],
  traces: {
    t1: [
      { name: "extract", kind: "llm", status: "ok", ms: 1210, meta: ["fast", "412 + 96 tokens", "$0.0004"] },
      { name: "gate", kind: "access", status: "ok", ms: 2, meta: ["analyst", "ALLOW"] },
      { name: "explain (attempt 1)", kind: "sql", status: "err", ms: 41, sql: "SELECT x FROM marts.t", error: "Code: 47. Unknown identifier" },
    ],
  },
  audit: [
    { ts: "2026-11-02T08:15:04Z", trace_id: "t1", user_id: "ana", role: "analyst", decision: "ALLOW", dataset: "table_one", blocked_tables: [], reason: "allowed" },
    { ts: "2026-11-02T09:15:01Z", trace_id: "t2", user_id: "bo", role: "viewer", decision: "DENY", dataset: "table_two", blocked_tables: ["table_two"], reason: "not granted" },
  ],
  costs: [
    { day: "2026-11-01", alias: "fast", model: "model-small", tier: "fast", provider: "openai", calls: 10, cost_usd: 0.25 },
    { day: "2026-11-02", alias: "sql-gen", model: "model-large", tier: "sql-gen", provider: "openai", calls: 4, cost_usd: 1.5 },
  ],
  users: [
    { id: "adm", email: "adm@example.com", display_name: "Ada Admin", roles: ["admin", "analyst"], enabled: true },
    { id: "ana", email: "ana@example.com", display_name: "Ana Analyst", roles: ["analyst"], enabled: true },
  ],
};

let api: MockApi;
let navigate: Mock<(path: string, options?: { replace: boolean }) => void>;

function show(section: string, page: ReactNode, user = "adm") {
  window.localStorage.setItem("fitcher.demo.identity", user);
  render(
    <ThemeProvider>
      <I18nProvider initial="en">
        <ChatProvider api={api} navigate={vi.fn()} activeId={null}>
          <ConsoleLayout section={section} navigate={navigate} onChat={vi.fn()}>{page}</ConsoleLayout>
        </ChatProvider>
      </I18nProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url.endsWith("/console") ? new Response(JSON.stringify(CONSOLE)) : new Response(JSON.stringify({ suggestions: [], scenarios: [] }))));
  api = createMockApi();
  navigate = vi.fn();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("evaluation", () => {
  it("shows the latest report's per-layer rates against the 80% threshold", async () => {
    show("evaluation", <EvaluationSection />);

    expect(await screen.findByRole("img", { name: /Execution match 85% · Threshold 80%/ })).toBeTruthy();
    expect(screen.getByRole("img", { name: /Retrieval recall 100%/ })).toBeTruthy();
    expect(screen.getAllByText("Pack enabled").length).toBeGreaterThan(0);
    const intent = screen.getByText("Intent routing").closest(".fc-meter-row") as HTMLElement;
    expect(within(intent).getByText("Not scored yet")).toBeTruthy();
  });

  it("lists every required question category, the failed cases and earlier reports", async () => {
    show("evaluation", <EvaluationSection />);
    const required = await screen.findByRole("region", { name: "Required question set" });

    expect(within(required).getByText("Two-period comparison")).toBeTruthy();
    expect(within(required).getAllByText("Not scored yet").length).toBe(5);
    expect(screen.getByText("case_one")).toBeTruthy();
    expect(screen.getByText("expected 10 rows, got 4")).toBeTruthy();

    fireEvent.click(within(screen.getByRole("region", { name: "Reports" })).getAllByRole("button")[1]);
    expect(navigate).toHaveBeenCalledWith("/console/evaluation/e1");
  });

  it("labels Run evaluation as paid AI and asks before an admin starts it", async () => {
    const start = vi.spyOn(api.evaluation, "start");
    show("evaluation", <EvaluationSection />);

    fireEvent.click(await screen.findByRole("button", { name: /Run evaluation.*Uses paid AI/ }));
    expect(start).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(within(screen.getByRole("dialog", { name: "This uses paid AI" })).getByRole("button", { name: /Continue/ })));

    await waitFor(() => expect(start).toHaveBeenCalled());
  });

  it("does not let a reviewer run the evaluation set", async () => {
    show("evaluation", <EvaluationSection />, "rev");

    await screen.findAllByText("Pack enabled");
    expect(screen.queryByRole("button", { name: /Run evaluation/ })).toBeNull();
  });
});

describe("runs and trace", () => {
  it("filters runs by status and user and opens a run's trace", async () => {
    show("runs", <RunsSection />);
    await screen.findByText("Totals by month");

    fireEvent.click(screen.getByRole("radio", { name: "Denied" }));
    expect(screen.queryByText("Totals by month")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "All" }));
    fireEvent.change(screen.getByRole("textbox", { name: "User" }), { target: { value: "bo" } });
    expect(screen.queryByText("Totals by month")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Refunds in 2025" }));
    expect(navigate).toHaveBeenCalledWith("/console/runs/t2");
  });

  it("lists the trace's steps with durations, LLM calls by alias, SQL errors and the access decision", async () => {
    show("runs", <RunDetail traceId="t1" />);
    const timeline = await screen.findByRole("list", { name: "Trace" });

    expect(within(timeline).getByText("1.2 s")).toBeTruthy();
    expect(within(timeline).getByText("fast")).toBeTruthy();
    expect(within(timeline).getByText("$0.0004")).toBeTruthy();
    expect(within(timeline).getByText("Code: 47. Unknown identifier")).toBeTruthy();
    expect(within(timeline).getByText("ALLOW")).toBeTruthy();
    expect(screen.getByText("Estimate")).toBeTruthy();
  });

  it("says when a trace does not exist", async () => {
    show("runs", <RunDetail traceId="missing" />);

    expect(await screen.findByText("This item doesn't exist or was deleted.")).toBeTruthy();
  });
});

describe("audit", () => {
  it("lists allow and deny decisions with the blocked tables", async () => {
    show("audit", <AuditSection />);
    const row = (await screen.findByText("table_two", { selector: "td code" })).closest("tr") as HTMLElement;

    expect(within(row).getByText("Denied")).toBeTruthy();
    expect(screen.getByText("Allowed")).toBeTruthy();
  });
});

describe("costs", () => {
  it("labels every cost as an estimate", async () => {
    show("costs", <CostsSection />);

    expect(await screen.findByText("$1.75")).toBeTruthy();
    expect(screen.getAllByText("Estimate").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText(/Estimated from token counts/)).toBeTruthy();
  });
});

describe("users", () => {
  it("changes a user's roles and disables them after confirmation", async () => {
    show("users", <UsersSection />);
    const row = (await screen.findByText("Ana Analyst")).closest("tr") as HTMLElement;

    await act(async () => fireEvent.click(within(row).getByRole("button", { name: "viewer" })));
    await waitFor(() => expect(within(row).getByRole("button", { name: "viewer" }).getAttribute("aria-pressed")).toBe("true"));

    fireEvent.click(within(row).getByRole("button", { name: "Disable" }));
    await act(async () => fireEvent.click(within(screen.getByRole("alertdialog", { name: "Disable Ana Analyst?" })).getByRole("button", { name: "Disable" })));
    await waitFor(() => expect(within(row).getByText("Disabled")).toBeTruthy());
    expect((await api.users.list()).find((user) => user.id === "ana")).toMatchObject({ roles: ["analyst", "viewer"], enabled: false });
  });

  it("lists users for an admin who may not read the Datasets section", async () => {
    vi.spyOn(api.datasets, "list").mockRejectedValue(new Error("this console section needs the pack_reviewer role"));
    show("users", <UsersSection />);

    expect(await screen.findByText("Ana Analyst")).toBeTruthy();
  });

  it("does not let the signed-in admin change their own roles or disable themselves", async () => {
    show("users", <UsersSection />);
    const row = (await screen.findByText("Ada Admin", { selector: "b" })).closest("tr") as HTMLElement;

    expect(within(row).getByRole("button", { name: "analyst" }).hasAttribute("disabled")).toBe(true);
    expect(within(row).queryByRole("button", { name: "Disable" })).toBeNull();
  });

  it("offers only the pack's roles, which are the only roles the api changes", async () => {
    show("users", <UsersSection />);
    const row = (await screen.findByText("Ana Analyst")).closest("tr") as HTMLElement;

    expect(within(row).getAllByRole("button").map((button) => button.textContent)).toEqual(expect.arrayContaining(["analyst", "viewer"]));
    expect(within(row).queryByRole("button", { name: "admin" })).toBeNull();
    expect(within(row).queryByRole("button", { name: "pack_reviewer" })).toBeNull();
  });
});
