import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { OverviewSection } from "@/components/console/sections/OverviewSection";
import { createMockApi, type MockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import { ChatProvider } from "@/lib/chat/ChatContext";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

const CONSOLE: Partial<ConsoleFile> = {
  pack: { name: "shop", display_name: "Shop" },
  conversations: [],
};

const hoursAgo = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();
const run = (id: string, status: string, hours: number) => ({
  trace_id: id, ts: hoursAgo(hours), user_id: "owner", role: "admin", question: `Question ${id}`, intent: "data", status, latency_ms: 4200, cost_usd: 0.01,
});

let api: MockApi;
let navigate: Mock<(path: string, options?: { replace: boolean }) => void>;

function show() {
  render(
    <ThemeProvider>
      <I18nProvider initial="en">
        <ChatProvider api={api} navigate={vi.fn()} activeId={null}>
          <ConsoleLayout section="overview" navigate={navigate} onChat={vi.fn()}><OverviewSection /></ConsoleLayout>
        </ChatProvider>
      </I18nProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) =>
    url.endsWith("/console") ? new Response(JSON.stringify(structuredClone(CONSOLE))) : new Response(JSON.stringify({ suggestions: [], scenarios: [] }))));
  api = createMockApi();
  navigate = vi.fn();
  vi.spyOn(api.runs, "list").mockResolvedValue([run("a", "succeeded", 2), run("b", "failed", 30), run("c", "succeeded", 24 * 20)]);
  vi.spyOn(api.costs, "list").mockResolvedValue([]);
  vi.spyOn(api.evaluation, "reports").mockResolvedValue([]);
  vi.spyOn(api.models, "providers").mockResolvedValue([{ id: "openai", name: "OpenAI", kind: "openai", base_url: null, key_set: true, key_last4: "1234", hosted: true, in_use: true }]);
  vi.spyOn(api.sources, "list").mockResolvedValue([]);
  vi.spyOn(api.sources, "drift").mockResolvedValue({ pack: null, changes: [] });
  vi.spyOn(api.owner, "status").mockResolvedValue({ password_set: false, signed_in: false, exposed: false });
  vi.spyOn(api.review, "items").mockResolvedValue([]);
  vi.spyOn(api.feedbackReview, "list").mockResolvedValue([]);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("overview", () => {
  it("counts the runs of the chosen period and the share that returned a result", async () => {
    show();
    const figures = await screen.findByRole("region", { name: "Figures for 7 days" });
    await waitFor(() => expect(within(figures).getByText("Runs").closest("a")?.textContent).toContain("2"));
    expect(within(figures).getByText("50%")).toBeTruthy();

    fireEvent.click(screen.getByRole("radio", { name: "24 hours" }));
    expect(within(screen.getByRole("region", { name: "Figures for 24 hours" })).getByText("100%")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Question a" })).toBeTruthy();
  });

  it("walks through Get started and points to the next step, and hides it on this browser", async () => {
    vi.spyOn(api.sources, "list").mockResolvedValue([]);
    show();

    const start = await screen.findByRole("region", { name: "Get started" });
    expect(within(start).getByText("3 of 5 done")).toBeTruthy();
    fireEvent.click(within(start).getByRole("button", { name: "Add a source" }));
    expect(navigate).toHaveBeenCalledWith("/console/sources");

    fireEvent.click(within(start).getByRole("button", { name: "Hide Get started on this browser" }));
    expect(screen.queryByRole("region", { name: "Get started" })).toBeNull();
    expect(window.localStorage.getItem("fitcher.overview.hideStart")).toBe("1");
  });

  it("lists only what needs a look, and warns when the address is open without a password", async () => {
    vi.spyOn(api.review, "items").mockResolvedValue([{ id: "i1", status: "draft" }, { id: "i2", status: "approved" }] as never);
    vi.spyOn(api.sources, "list").mockResolvedValue([{ id: "kho", kind: "mysql", selected_count: 5, last_sync: { status: "failed" } }] as never);
    vi.spyOn(api.owner, "status").mockResolvedValue({ password_set: false, signed_in: false, exposed: true });
    show();

    const attention = await screen.findByRole("region", { name: "Needs a look" });
    await waitFor(() => expect(within(attention).getAllByRole("link").map((link) => link.textContent)).toEqual(["1 item to review", "Source kho failed to sync"]));
    expect(screen.getByRole("alert").textContent).toContain("open to other machines");
    expect(within(screen.getByRole("navigation", { name: "Console" })).getByRole("link", { name: /Review/ }).textContent).toContain("1");
  });

  it("counts items approved without a person and questions that failed in the last day", async () => {
    vi.spyOn(api.review, "items").mockResolvedValue([{ id: "i1", status: "approved", reviewed: false }, { id: "i2", status: "approved" }] as never);
    vi.spyOn(api.runs, "list").mockResolvedValue([run("a", "failed", 2), run("b", "error", 5), run("c", "failed", 30)]);
    show();

    const attention = await screen.findByRole("region", { name: "Needs a look" });
    await waitFor(() => expect(within(attention).getAllByRole("link").map((link) => link.textContent))
      .toEqual(["1 item to review", "2 questions failed in the last 24 hours"]));
  });

  it("says there is nothing to look at", async () => {
    show();
    expect(await screen.findByText("Nothing needs a look.")).toBeTruthy();
  });
});
