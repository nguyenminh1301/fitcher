import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssistantTurn } from "@/components/chat/AssistantTurn";
import type { AskEvent } from "@/lib/api/events";
import type { Turn } from "@/lib/api/conversations";
import type { Result } from "@/lib/contracts";
import { I18nProvider, useI18n } from "@/lib/i18n/react";

const T = "trace-1";
const status = (node: string, attempt?: number): AskEvent => ({ event: "status", node, phase: "end", trace_id: T, attempt: attempt ?? null });
const RESULT: Result = { columns: [{ name: "region", type: "string", role: "dimension" }, { name: "sales", type: "number", role: "measure" }], rows: [["West", 10]], row_count: 1 };
const ANSWER: AskEvent[] = [
  status("extract"), status("generate_sql"), { event: "sql", sql: "SELECT region, sum(x) AS sales FROM marts.t GROUP BY region", attempt: 1, trace_id: T },
  status("execute"), { event: "result", result: RESULT, trace_id: T },
  { event: "chart_spec", spec: { type: "table", x: "region", y: ["sales"], allowed_types: ["bar", "table"] }, trace_id: T },
  { event: "summary", text: "The West led with **10**.", lang: "en", warnings: ["Q1 2026 is only partly covered by the data"], trace_id: T },
  { event: "done", trace_id: T },
];
const turn = (events: AskEvent[]): Turn => ({ turn: 1, revision: 1, question: "Sales by region", question_lang: "en", events });

function Switch() {
  const { setLocale } = useI18n();
  return <button onClick={() => setLocale("vi")}>vi</button>;
}

function show(events: AskEvent[], props: Partial<Parameters<typeof AssistantTurn>[0]> = {}) {
  const handlers = { onStop: vi.fn(), onRetry: vi.fn(), onFollowUp: vi.fn(), onFeedback: vi.fn() };
  render(
    <I18nProvider>
      <Switch />
      <AssistantTurn turn={turn(events)} streaming={false} {...handlers} {...props} />
    </I18nProvider>,
  );
  return handlers;
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("answer", () => {
  it("shows live steps while streaming and a Stop button", () => {
    const { onStop } = show(ANSWER.slice(0, 3), { streaming: true });

    expect(screen.getByText("Writing SQL")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalled();
  });

  it("names the repair attempt", () => {
    show([status("generate_sql"), status("generate_sql", 2)], { streaming: true });

    expect(screen.getByText("Repairing SQL (attempt 2 of 3)")).toBeTruthy();
  });

  it("collapses the steps into How I got this once done, with summary, warning, chart, table and SQL", () => {
    show(ANSWER);

    expect(screen.getByRole("button", { name: /How I got this/ }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByText("10", { selector: "b" })).toBeTruthy();
    expect(screen.getByText("Q1 2026 is only partly covered by the data")).toBeTruthy();
    expect(screen.getByRole("radiogroup", { name: "Chart type" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "SQL" })).toBeTruthy();
  });

  it("keeps the summary in its own language when the interface language changes", () => {
    show(ANSWER);

    fireEvent.click(screen.getByRole("button", { name: "vi" }));

    const summary = screen.getByText(/The West led with/);
    expect(summary.closest("[lang]")?.getAttribute("lang")).toBe("en");
    expect(screen.getByRole("button", { name: /Cách tôi tìm ra kết quả/ })).toBeTruthy();
  });

  it("explains a denial calmly: what was blocked and that nothing was queried", () => {
    show([status("gate"), { event: "deny", message: "Your role can't read this dataset.", role: "marketing", blocked: ["blocked_dataset"], lang: "en", trace_id: T }, { event: "done", trace_id: T }]);

    const notice = screen.getByRole("status");
    expect(within(notice).getByText("blocked_dataset")).toBeTruthy();
    expect(within(notice).getByText(/Nothing was queried/)).toBeTruthy();
    expect(notice.className).not.toContain("danger");
  });

  it("shows the last SQL and database error after a failure, with no result", () => {
    show([status("generate_sql"), { event: "error", kind: "failed", message: "failed", sql: "SELECT warehouse_id", error: "Code: 47. Unknown identifier", trace_id: T }]);

    expect(screen.getByText("Code: 47. Unknown identifier")).toBeTruthy();
    expect(document.querySelector("pre code")?.textContent).toBe("SELECT warehouse_id");
    expect(screen.queryByRole("radiogroup", { name: "Chart type" })).toBeNull();
  });

  it("sends a clarifying option as a follow-up question", () => {
    const { onFollowUp } = show([{ event: "clarify", question: "Which measure?", options: [{ id: "a", label: "Net sales" }, { id: "b", label: "Orders" }], lang: "en", trace_id: T }, { event: "done", trace_id: T }]);

    fireEvent.click(screen.getByRole("button", { name: "Net sales" }));

    expect(onFollowUp).toHaveBeenCalledWith("Net sales");
  });

  it("says the run was stopped", () => {
    show([status("extract"), { event: "error", kind: "stopped", message: "stopped", sql: null, error: null, trace_id: T }]);

    expect(screen.getByText("Stopped")).toBeTruthy();
  });

  it("asks for an optional note on dislike and sends it with the run's trace", async () => {
    const { onFeedback } = show(ANSWER);

    fireEvent.click(screen.getByRole("button", { name: "Not helpful" }));
    fireEvent.change(screen.getByRole("textbox", { name: /What went wrong/ }), { target: { value: "wrong year" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Send feedback" })));

    expect(onFeedback).toHaveBeenCalledWith({ trace_id: T, rating: "dislike", note: "wrong year" });
  });

  it("retries the answer", () => {
    const { onRetry } = show(ANSWER);

    fireEvent.click(screen.getByRole("button", { name: /Retry/ }));

    expect(onRetry).toHaveBeenCalled();
  });
});
