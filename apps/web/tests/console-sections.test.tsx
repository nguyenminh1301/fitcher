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

  it("moves an approved item from draft to approved", async () => {
    show("review", <ReviewDetail id="m1" />);
    const approve = await screen.findByRole("button", { name: "Approve" });
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

  it("test-runs a metric and shows the sample result", async () => {
    show("review", <ReviewDetail id="m1" />);

    fireEvent.click(await screen.findByRole("button", { name: "Test run" }));

    expect(await screen.findByText("Test run returned 2 rows")).toBeTruthy();
    expect(screen.getByText("2026-09")).toBeTruthy();
  });

  it("flags evidence that cites a deleted document", async () => {
    show("review", <ReviewDetail id="g1" />);

    expect(await screen.findByText(/Evidence cites a deleted document/)).toBeTruthy();
    expect(screen.getByText("Nothing to run")).toBeTruthy();
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
    expect(screen.queryByText("big.pdf", { selector: ".fc-doc-name" })).toBeNull();
  });

  it("shows an accepted file as processing, then indexed", async () => {
    show("documents", <DocumentsSection />);
    await screen.findByText("Handbook.pdf");

    await act(async () => fireEvent.change(document.querySelector("input[type=file]")!, { target: { files: [new File(["x"], "notes.md")] } }));

    const row = (await screen.findByText("notes.md", { selector: ".fc-doc-name" })).closest(".fc-doc") as HTMLElement;
    expect(within(row).getByText("Processing")).toBeTruthy();
    await waitFor(() => expect(within(row).getByText("Indexed")).toBeTruthy());
  });

  it("lets the reviewer choose which pack roles may see a document", async () => {
    show("documents", <DocumentsSection />);
    const row = (await screen.findByText("Handbook.pdf")).closest(".fc-doc") as HTMLElement;

    await act(async () => fireEvent.click(within(row).getByRole("button", { name: "viewer" })));

    await waitFor(() => expect(within(row).getByRole("button", { name: "viewer" }).getAttribute("aria-pressed")).toBe("true"));
    expect((await api.documents.list()).find((doc) => doc.id === "d1")?.roles).toEqual(["analyst", "viewer"]);
  });

  it("labels Draft pack items as paid AI and asks before drafting", async () => {
    const draft = vi.spyOn(api.documents, "draft");
    show("documents", <DocumentsSection />);
    const row = (await screen.findByText("Handbook.pdf")).closest(".fc-doc") as HTMLElement;

    fireEvent.click(within(row).getByRole("button", { name: /Draft pack items.*Uses paid AI/ }));
    const dialog = screen.getByRole("dialog", { name: "This uses paid AI" });
    expect(draft).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: /Continue/ })));

    await waitFor(() => expect(draft).toHaveBeenCalledWith("d1"));
  });

  it("shows a failed document's error", async () => {
    show("documents", <DocumentsSection />);

    expect(await screen.findByText("Merged header cells.")).toBeTruthy();
  });
});

describe("datasets", () => {
  it("lists the compiled datasets and opens one with its columns and readable roles", async () => {
    show("datasets", <DatasetsSection />);

    fireEvent.click(await screen.findByRole("button", { name: /table_one/ }));

    expect(await screen.findByText("Line amount")).toBeTruthy();
    expect(screen.getByText("analyst", { selector: ".fc-pill" })).toBeTruthy();
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
