import { act, cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { DatasetsSection } from "@/components/console/sections/DatasetsSection";
import { DocumentsSection } from "@/components/console/sections/DocumentsSection";
import { FeedbackSection } from "@/components/console/sections/FeedbackSection";
import { ReviewDetail, ReviewSection } from "@/components/console/sections/ReviewSection";
import { createMockApi, type MockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import type { Result } from "@/lib/contracts";
import { ChatProvider } from "@/lib/chat/ChatContext";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

const TEST_RESULT: Result = {
  columns: [{ name: "month", type: "string", role: "dimension" }, { name: "rate", type: "number", role: "measure", format: "ratio" }],
  rows: [["2026-08", 0.05], ["2026-09", 0.04]],
  row_count: 2,
};

const CONSOLE: Partial<ConsoleFile> = {
  pack: { name: "shop", display_name: "Shop" },
  pack_roles: ["analyst", "viewer"],
  identities: [
    { user_id: "rev", display_name: "Rae Reviewer", roles: ["pack_reviewer", "analyst"] },
    { user_id: "adm", display_name: "Ada Admin", roles: ["admin", "analyst"] },
  ],
  conversations: [],
  review_items: [
    { id: "m1", file: "metrics.yaml", name: "metric_one", kind: "item", status: "draft", confidence: 0.82, body: "Units returned over units sold.", formula: "sum(a) / sum(b)", evidence: { source: "Handbook.pdf, page 2", quote: "Measured in units." }, test_result: TEST_RESULT },
    { id: "g1", file: "glossary.yaml", name: "term_one", kind: "item", status: "approved", confidence: 0.95, body: "A plain definition.", evidence: { source: "Old guide.docx", deleted: true } },
    // The api sends a null formula for an item that has none.
    { id: "g2", file: "glossary.yaml", name: "term_two", kind: "item", status: "draft", confidence: 0.7, body: "Second definition.", formula: null },
    { id: "u1", file: "metrics.yaml", name: "metric_generated", kind: "item", status: "approved", reviewed: false, confidence: 0.5, body: "Drafted with the instant pack.", formula: "sum(c)" },
    { id: "p1", file: "examples.yaml", name: "Proposal one", kind: "proposal", status: "draft", confidence: 0.6, body: "Total for [MASKED_NAME] in 2025?", formula: "SELECT sum(x) FROM marts.t WHERE name = '[MASKED_NAME]'", evidence: { source: "Disliked chat" }, test_result: TEST_RESULT },
  ],
  documents: [
    { id: "d1", name: "Handbook.pdf", size: 1_200_000, status: "indexed", roles: ["analyst"], uploaded_at: "2026-10-28T10:00:00Z" },
    { id: "d2", name: "Targets.xlsx", size: 3_800_000, status: "failed", error: "Merged header cells.", roles: [], uploaded_at: "2026-10-30T10:00:00Z" },
  ],
  datasets: [
    { id: "table_one", description: "One row per line.", grain: "line", time_column: "day", readable_roles: ["analyst"], columns: [{ name: "day", type: "Date", role: "time", description: "Day of the line" }, { name: "amount", type: "Float64", role: "measure", description: "Line amount" }] },
  ],
  feedback: [
    { trace_id: "t1", ts: "2026-11-02T08:00:00Z", user_id: "ana", rating: "dislike", question: "Totals by month", note: "wrong year", run_status: "succeeded" },
    { trace_id: "t2", ts: "2026-11-02T09:00:00Z", user_id: "ana", rating: "like", question: "Totals by region", run_status: "succeeded" },
  ],
};

// Each test loads the providers and a section through the sample api; a full parallel run needs more than 1s.
configure({ asyncUtilTimeout: 4000 });

let api: MockApi;
let navigate: Mock<(path: string, options?: { replace: boolean }) => void>;

function show(section: string, page: ReactNode, user = "rev") {
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
    url.endsWith("/console") ? new Response(JSON.stringify(structuredClone(CONSOLE))) : new Response(JSON.stringify({ suggestions: [], scenarios: [] }))));
  api = createMockApi();
  navigate = vi.fn();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("review", () => {
  it("groups pack items by file and filters them by draft and approved", async () => {
    show("review", <ReviewSection />);
    await screen.findByText("metric_one");

    expect(screen.getByText("metrics.yaml")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Approved" }));
    expect(screen.queryByText("metric_one")).toBeNull();
    expect(screen.getByText("term_one")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /term_one/ }));
    expect(navigate).toHaveBeenCalledWith("/console/review/g1");
  });

  it("moves an approved item from draft to approved, once its formula is test-run", async () => {
    show("review", <ReviewDetail id="m1" />);
    const approve = await screen.findByRole("button", { name: "Approve" });
    expect(approve.hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Test run" }));
    await waitFor(() => expect(approve.hasAttribute("disabled")).toBe(false));
    await act(async () => fireEvent.click(approve));
    await screen.findByText("metric_one approved");
    cleanup();

    show("review", <ReviewSection />);
    await screen.findByText("metric_one");
    fireEvent.click(screen.getByRole("radio", { name: "Draft" }));
    expect(screen.queryByText("metric_one")).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Approved" }));
    expect(screen.getByText("metric_one")).toBeTruthy();
  });

  it("labels an item approved without a person as unreviewed until a reviewer confirms it", async () => {
    show("review", <ReviewSection />);
    const row = (await screen.findByText("metric_generated")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Unreviewed")).toBeTruthy();
    cleanup();

    show("review", <ReviewDetail id="u1" />);
    const confirm = await screen.findByRole("button", { name: "Confirm" });
    fireEvent.click(screen.getByRole("button", { name: "Test run" }));
    await waitFor(() => expect(confirm.hasAttribute("disabled")).toBe(false));
    await act(async () => fireEvent.click(confirm));
    await screen.findByText("metric_generated approved");
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
  });

  it("test-runs a metric and shows the sample result", async () => {
    show("review", <ReviewDetail id="m1" />);

    fireEvent.click(await screen.findByRole("button", { name: "Test run" }));

    expect(await screen.findByText("Test run returned 2 rows")).toBeTruthy();
    expect(screen.getByText("2026-09")).toBeTruthy();
  });

  it("edits only the text of an item whose formula is null", async () => {
    const update = vi.spyOn(api.review, "update");
    show("review", <ReviewDetail id="g2" />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(screen.queryByRole("textbox", { name: "Formula" })).toBeNull();
    fireEvent.change(screen.getByRole("textbox", { name: "Definition" }), { target: { value: "Edited." } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save" })));

    expect(update).toHaveBeenCalledWith("g2", { body: "Edited." });
  });

  it("flags evidence that cites a deleted document", async () => {
    show("review", <ReviewDetail id="g1" />);

    expect(await screen.findByText(/Evidence cites a deleted document/)).toBeTruthy();
    expect(screen.getByText(/checked against their evidence, not run/)).toBeTruthy();
  });

  it("approves a proposal only after its masked values are replaced and it is test-run", async () => {
    show("review", <ReviewDetail id="p1" />);
    const approve = await screen.findByRole("button", { name: "Approve" });
    const testRun = screen.getByRole("button", { name: "Test run" });
    expect(testRun.hasAttribute("disabled")).toBe(true);

    fireEvent.change(screen.getByRole("textbox", { name: "Replace [MASKED_NAME]" }), { target: { value: "North" } });
    expect(document.querySelector("pre code")?.textContent).toContain("name = 'North'");
    expect(approve.hasAttribute("disabled")).toBe(true);
    fireEvent.click(testRun);

    await waitFor(() => expect(approve.hasAttribute("disabled")).toBe(false));
  });

  it("saves the reviewer's question and SQL before test-running them, and asks for a new test-run after an edit", async () => {
    const update = vi.spyOn(api.review, "update");
    const testRun = vi.spyOn(api.review, "testRun");
    show("review", <ReviewDetail id="p1" />);
    const approve = await screen.findByRole("button", { name: "Approve" });

    fireEvent.change(screen.getByRole("textbox", { name: "Question" }), { target: { value: "Total for North in 2025?" } });
    fireEvent.change(screen.getByRole("textbox", { name: "SQL" }), { target: { value: "SELECT sum(x) AS total FROM marts.t WHERE name = 'North'" } });
    fireEvent.click(screen.getByRole("button", { name: "Test run" }));

    await waitFor(() => expect(approve.hasAttribute("disabled")).toBe(false));
    expect(update).toHaveBeenCalledWith("p1", { body: "Total for North in 2025?", formula: "SELECT sum(x) AS total FROM marts.t WHERE name = 'North'" });
    expect(update.mock.invocationCallOrder[0]).toBeLessThan(testRun.mock.invocationCallOrder[0]);

    fireEvent.change(screen.getByRole("textbox", { name: "SQL" }), { target: { value: "SELECT 1" } });
    expect(approve.hasAttribute("disabled")).toBe(true);
  });

  it("saves a confirmed spec with its masked filter value replaced", async () => {
    const update = vi.spyOn(api.review, "update");
    show("review", <ReviewDetail id="p1" />);
    const approve = await screen.findByRole("button", { name: "Approve" });

    fireEvent.click(screen.getByRole("checkbox", { name: "Use this spec when the same question is asked" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Metrics" }), { target: { value: "total" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Dataset" }), { target: { value: "t" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Filters" }), { target: { value: "name = [MASKED_NAME]" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Replace [MASKED_NAME]" }), { target: { value: "North" } });
    fireEvent.click(screen.getByRole("button", { name: "Test run" }));

    await waitFor(() => expect(approve.hasAttribute("disabled")).toBe(false));
    expect(update).toHaveBeenCalledWith("p1", expect.objectContaining({ spec: {
      metric_ids: ["total"], dataset: "t", dimensions: [], filters: [{ column: "name", op: "=", values: ["North"] }], top_n: null, rank_by: null,
    } }));
  });

  it("does not test-run a spec that does not parse", async () => {
    show("review", <ReviewDetail id="p1" />);
    await screen.findByRole("button", { name: "Approve" });
    fireEvent.change(screen.getByRole("textbox", { name: "Replace [MASKED_NAME]" }), { target: { value: "North" } });

    fireEvent.click(screen.getByRole("checkbox", { name: "Use this spec when the same question is asked" }));

    expect(screen.getByRole("alert").textContent).toContain("Check this part of the spec");
    expect(screen.getByRole("button", { name: "Test run" }).hasAttribute("disabled")).toBe(true);
  });
});

describe("documents", () => {
  it("rejects a file type outside PDF, DOCX, MD, TXT and XLSX, and a file over 20 MB", async () => {
    show("documents", <DocumentsSection />);
    await screen.findByText("Handbook.pdf");
    const input = document.querySelector<HTMLInputElement>("input[type=file]")!;

    fireEvent.change(input, { target: { files: [new File(["x"], "photo.png")] } });
    expect(await screen.findByText("photo.png isn't a supported file type.")).toBeTruthy();

    const big = new File(["x"], "big.pdf");
    Object.defineProperty(big, "size", { value: 21 * 1024 * 1024 });
    fireEvent.change(input, { target: { files: [big] } });
    expect(await screen.findByText("big.pdf is larger than 20 MB.")).toBeTruthy();
    expect(screen.queryByText("big.pdf", { selector: ".doc-name" })).toBeNull();
  });

  it("shows an accepted file as processing, then indexed", async () => {
    show("documents", <DocumentsSection />);
    await screen.findByText("Handbook.pdf");

    await act(async () => fireEvent.change(document.querySelector("input[type=file]")!, { target: { files: [new File(["x"], "notes.md")] } }));

    const row = (await screen.findByText("notes.md", { selector: ".doc-name" })).closest("tr") as HTMLElement;
    expect(within(row).getByText("Processing")).toBeTruthy();
    await waitFor(() => expect(within(row).getByText("Indexed")).toBeTruthy());
  });

  it("labels Draft pack items as paid AI and asks before drafting", async () => {
    const draft = vi.spyOn(api.documents, "draft");
    show("documents", <DocumentsSection />);
    const row = (await screen.findByText("Handbook.pdf")).closest("tr") as HTMLElement;

    const button = within(row).getByRole("button", { name: "Draft pack items" });
    expect(document.getElementById(button.getAttribute("aria-describedby") ?? "")?.textContent).toBe("Uses paid AI");
    fireEvent.click(button);
    const dialog = screen.getByRole("dialog", { name: "Draft pack items from Handbook.pdf?" });
    expect(within(dialog).getByText(/The provider bills each call/)).toBeTruthy();
    expect(draft).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Draft items" })));

    await waitFor(() => expect(draft).toHaveBeenCalledWith("d1"));
  });

  it("shows a failed document's error", async () => {
    show("documents", <DocumentsSection />);

    expect(await screen.findByText("Merged header cells.")).toBeTruthy();
  });

  it("turns documents on, and asks before turning them off while documents are stored", async () => {
    const settings = vi.spyOn(api.documents, "settings").mockResolvedValue({ enabled: false, documents: 2 });
    const setEnabled = vi.spyOn(api.documents, "setEnabled").mockImplementation(async (enabled) => ({ enabled, documents: 2 }));
    show("documents", <DocumentsSection />);

    expect(await screen.findByText(/Numbers always come from your data/)).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByRole("switch", { name: "Use company documents" })));
    expect(setEnabled).toHaveBeenLastCalledWith(true, false);
    await screen.findByText("Handbook.pdf");

    await act(async () => fireEvent.click(screen.getByRole("switch", { name: "Use company documents" })));
    const dialog = screen.getByRole("dialog", { name: "Turn documents off?" });
    expect(within(dialog).getByText("2 documents stay stored but are no longer searched.")).toBeTruthy();
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Turn documents off" })));
    expect(setEnabled).toHaveBeenLastCalledWith(false, true);
    settings.mockRestore();
    setEnabled.mockRestore();
  });
});

describe("datasets", () => {
  it("lists the compiled datasets and opens one with its columns, without roles", async () => {
    show("datasets", <DatasetsSection />);

    fireEvent.click(await screen.findByRole("button", { name: /table_one/ }));

    expect(await screen.findByText("Line amount")).toBeTruthy();
    expect(screen.queryByText("analyst", { selector: ".fc-pill" })).toBeNull();
  });
});

describe("feedback", () => {
  it("proposes an example from a disliked run", async () => {
    show("feedback", <FeedbackSection />);
    await screen.findByText("Totals by month");

    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Propose example" })));

    await waitFor(() => expect(screen.getAllByText("Proposed").length).toBeGreaterThan(0));
    expect((await api.feedbackReview.list()).find((row) => row.trace_id === "t1")?.proposal).toBe("proposed");
  });
});
