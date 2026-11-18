import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InstantPack } from "@/components/setup/InstantPack";
import type { FitcherApi } from "@/lib/api/client";
import type { InstantJobView } from "@/lib/contracts";
import { I18nProvider } from "@/lib/i18n/react";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const STEPS = ["marts", "profile", "files", "draft", "approve", "compile", "activate"] as const;

function job(status: InstantJobView["status"], done: number, extra: Partial<InstantJobView> = {}): InstantJobView {
  return {
    id: "job1", source_id: "erp", tables: ["orders"], status, started_at: "2026-11-15T10:00:00Z", finished_at: null,
    failed_step: null, error: null, result: null,
    steps: STEPS.map((id, index) => ({ id, state: index < done ? "done" : index === done && status === "running" ? "running" : "pending" })),
    ...extra,
  };
}

function fakeSources(jobs: InstantJobView[], estimate = { prompt_tokens: 3080, datasets: 2, model_missing: null as string | null }) {
  return {
    syncs: vi.fn(async () => [{ id: 1, status: "succeeded" }]),
    instantEstimate: vi.fn(async () => estimate),
    instantStart: vi.fn(async () => ({ job: jobs[0] })),
    instantJob: vi.fn(async () => ({ job: jobs.length > 1 ? jobs.shift() as InstantJobView : jobs[0] })),
  } as unknown as FitcherApi["sources"];
}

function show(sources: FitcherApi["sources"], onAsk = vi.fn()) {
  render(<I18nProvider initial="en"><InstantPack sources={sources} sourceId="erp" tables={["orders"]} onAsk={onAsk} pollMs={10} /></I18nProvider>);
  return onAsk;
}

describe("instant pack", () => {
  it("shows the paid draft's size and starts only after the admin confirms it", async () => {
    const done = job("succeeded", 7, { result: { pack: "erp", datasets: 2, relationships: 0, skipped: [], dropped: [], slow: [], suggested_questions: ["Total sales?", "Top items?", "Monthly trend?"] } });
    const sources = fakeSources([job("running", 0), job("running", 4), done]);
    const onAsk = show(sources);

    expect(await screen.findByText(/about 3,080 prompt tokens/)).toBeTruthy();
    expect(screen.getByText(/the provider bills it unless the model is free or runs on this computer/)).toBeTruthy();
    expect(sources.instantStart).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Build the pack" }));

    expect(sources.instantStart).toHaveBeenCalledWith({ source_id: "erp", tables: ["orders"], confirm_billable: true });
    await userEvent.click(await screen.findByRole("button", { name: "Total sales?" }));
    expect(onAsk).toHaveBeenCalledWith("Total sales?");
    expect(screen.getAllByRole("listitem").length).toBeGreaterThanOrEqual(STEPS.length);
    expect(screen.queryByText(/^ui\./)).toBeNull();
  });

  it("says which model is missing instead of offering the paid call", async () => {
    show(fakeSources([job("running", 0)], { prompt_tokens: 3080, datasets: 2, model_missing: "no model is mapped to the sql-gen tier" }));

    expect(await screen.findByText(/no model is mapped to the sql-gen tier/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Build the pack" })).toBeNull();
  });

  it("names the step that failed and says the previous answers still work", async () => {
    const failed = job("failed", 3, { failed_step: "draft", error: "the provider refused the request" });
    failed.steps[3].state = "failed";
    const sources = fakeSources([job("running", 0), failed]);
    show(sources);

    await userEvent.click(await screen.findByRole("button", { name: "Build the pack" }));

    expect(await screen.findByText(/the provider refused the request/)).toBeTruthy();
    expect(screen.getByText(/Draft the descriptions and metrics failed/)).toBeTruthy();
    expect(screen.getAllByText("Waiting").length).toBe(3);
  });

  it("waits for the copy of the chosen tables before estimating", async () => {
    const sources = fakeSources([job("running", 0)]);
    let calls = 0;
    (sources.syncs as ReturnType<typeof vi.fn>).mockImplementation(async () => [{ id: 1, status: calls++ < 1 ? "running" : "succeeded" }]);
    show(sources);

    expect(await screen.findByText(/Copying the chosen tables/)).toBeTruthy();
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 50)); });
    expect(await screen.findByText(/about 3,080 prompt tokens/)).toBeTruthy();
  });
});
