import { act, cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConsoleLayout } from "@/components/console/ConsoleLayout";
import { ModelsSection } from "@/components/console/sections/ModelsSection";
import { createMockApi, type MockApi } from "@/lib/api/mock";
import type { ConsoleFile } from "@/lib/api/provisional";
import { ChatProvider } from "@/lib/chat/ChatContext";
import type { ModelTier, ModelTiers } from "@/lib/contracts";
import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

configure({ asyncUtilTimeout: 4000 });

const CONSOLE: Partial<ConsoleFile> = {
  pack: { name: "shop", display_name: "Shop" },
  pack_roles: ["analyst"],
  identities: [{ user_id: "adm", display_name: "Ada Admin", roles: ["admin", "analyst"] }],
  conversations: [],
};

function tier(name: string, alias: string, extra: Partial<ModelTier> = {}): ModelTier {
  return {
    tier: name, alias, provider: alias.split("-")[0], default_alias: alias, editable: name !== "embed", eligible: true,
    reason: "the latest eval report with it passed without regression", report_id: "r1", report_ts: "2026-11-04T08:00:00Z",
    options: [], ...extra,
  };
}

const TIERS: ModelTiers = {
  pack: "shop",
  tiers: [
    tier("sql-small", "openai-small", {
      options: [
        { alias: "openai-small", provider: "openai", eligible: true, reason: "passed", report_id: "r1" },
        { alias: "anthropic-small", provider: "anthropic", eligible: true, reason: "passed", report_id: "r2" },
        { alias: "gemini-small", provider: "gemini", eligible: false, reason: "no eval report ran sql-small with gemini-small" },
      ],
    }),
    tier("embed", "openai-embed"),
  ],
};

let api: MockApi;

function show() {
  window.localStorage.setItem("fitcher.demo.identity", "adm");
  render(
    <ThemeProvider>
      <I18nProvider initial="en">
        <ChatProvider api={api} navigate={vi.fn()} activeId={null} sources={{ auth: "mock", models: "http" }}>
          <ConsoleLayout section="models" navigate={vi.fn()} onChat={vi.fn()}><ModelsSection /></ConsoleLayout>
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
  api.models.list = vi.fn(async () => TIERS);
  api.models.set = vi.fn(async (name: string, alias: string) => tier(name, alias));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("models", () => {
  it("shows each tier's model and eligibility without a Sample data badge", async () => {
    show();
    const small = await screen.findByRole("region", { name: "Tier sql-small" });

    expect(within(small).getAllByText("openai-small").length).toBeGreaterThan(0);
    expect(within(small).getByText("Eligible")).toBeTruthy();
    expect(screen.queryByText("Sample data")).toBeNull();
  });

  it("disables an ineligible model and says why", async () => {
    show();
    const small = await screen.findByRole("region", { name: "Tier sql-small" });

    expect((within(small).getByRole("button", { name: "gemini-small" }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(small).getByText(/no eval report ran sql-small with gemini-small/)).toBeTruthy();
  });

  it("asks before mapping a tier to an eligible model", async () => {
    show();
    const small = await screen.findByRole("region", { name: "Tier sql-small" });

    fireEvent.click(within(small).getByRole("button", { name: "anthropic-small" }));
    expect(api.models.set).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Change model" })));

    await waitFor(() => expect(api.models.set).toHaveBeenCalledWith("sql-small", "anthropic-small"));
  });

  it("disables every choice while a change saves", async () => {
    let finish: (tier: ModelTier) => void = () => undefined;
    api.models.set = vi.fn(() => new Promise<ModelTier>((resolve) => { finish = resolve; }));
    show();
    const small = await screen.findByRole("region", { name: "Tier sql-small" });

    fireEvent.click(within(small).getByRole("button", { name: "anthropic-small" }));
    await act(async () => fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Change model" })));

    expect((within(small).getByRole("button", { name: "anthropic-small" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => finish(tier("sql-small", "anthropic-small")));
    await waitFor(() => expect((within(small).getByRole("button", { name: "anthropic-small" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("offers no change for the embedding tier", async () => {
    show();
    const embed = await screen.findByRole("region", { name: "Tier embed" });

    expect(within(embed).queryAllByRole("button")).toEqual([]);
    expect(within(embed).getByText(/full reindex/)).toBeTruthy();
  });
});
